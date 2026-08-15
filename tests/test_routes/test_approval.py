"""Tests for the multi-listing publish flow (POST /approval/{sku}/publish).

Uses a minimal FastAPI app that mounts only the approval router — avoids the
main app's lifespan (scheduler + shop-defaults seed). The session is a MagicMock
that returns a single hand-built Product; publish_variants mutates that same
instance, so assertions inspect it directly after the request.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.dependencies import get_session
from src.db.models import Product, ProductStatus
from src.web.routes import approval as approval_routes


def _product() -> Product:
    return Product(
        id=1,
        sku="TAKI-0042",
        carrier_pillar="birthstone",
        status=ProductStatus.AWAITING_APPROVAL.value,
        published_variant_ids=[],
        etsy_urls={},
        generated_variants=[
            {"id": "A", "title": "Title A", "tags": ["a"], "description": "Desc A."},
            {"id": "B", "title": "Title B", "tags": ["b"], "description": "Desc B."},
            {"id": "C", "title": "Title C", "tags": ["c"], "description": "Desc C."},
        ],
    )


def _make_session(product: Product | None) -> MagicMock:
    session = MagicMock()

    def query_side(model):
        q = MagicMock()
        if model is Product:
            q.filter_by.return_value.first.return_value = product
        else:
            q.filter_by.return_value.first.return_value = None
        return q

    session.query.side_effect = query_side
    return session


def _client(product: Product | None):
    app = FastAPI()
    app.include_router(approval_routes.router)
    session = _make_session(product)
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app), session


def test_multi_variant_publish():
    product = _product()
    client, _session = _client(product)

    resp = client.post(
        "/approval/TAKI-0042/publish",
        data={"variant_ids": ["A", "B", "C"]},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/approval/TAKI-0042/copy-paste-helper"

    assert product.published_variant_ids == ["A", "B", "C"]
    assert product.status == ProductStatus.PUBLISHED.value
    assert product.is_multi_published is True
    # final_* mirrors the FIRST published variant for downstream consumers.
    assert product.final_title == "Title A"
    assert product.final_tags == ["a"]
    assert product.selected_variant_id == "A"


def test_single_variant_publish():
    product = _product()
    client, _session = _client(product)

    resp = client.post(
        "/approval/TAKI-0042/publish",
        data={"variant_ids": ["B"]},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/approval/TAKI-0042/copy-paste-helper"

    assert product.published_variant_ids == ["B"]
    assert product.status == ProductStatus.PUBLISHED.value
    assert product.is_multi_published is False
    assert product.final_title == "Title B"


def test_publish_with_no_valid_variants_bounces_back():
    product = _product()
    client, _session = _client(product)

    resp = client.post(
        "/approval/TAKI-0042/publish",
        data={"variant_ids": ["Z"]},  # not a real variant id
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/approval/TAKI-0042"
    assert product.published_variant_ids == []
    assert product.status == ProductStatus.AWAITING_APPROVAL.value
