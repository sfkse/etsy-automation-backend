"""Tests for GET /approval/{sku}/payload-preview (PR 2).

Uses a minimal FastAPI app that mounts only the approval router — avoids the
main app's lifespan (scheduler + shop-defaults seed) which depends on env vars.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.dependencies import get_session
from src.db.models import (
    DefaultAttributes,
    MaterialType,
    PersonalizationTemplate,
    Product,
    RenewalOption,
    ShopSettings,
    VariationPreset,
    VariationRow,
)
from src.web.routes import approval as approval_routes


def _shop_settings() -> ShopSettings:
    return ShopSettings(
        id=1,
        production_partner_id="pp_42",
        renewal_option=RenewalOption.AUTOMATIC.value,
        default_quantity=999,
        feature_listing_default=False,
        default_shipping_profile_id="ship_1",
    )


def _defaults() -> DefaultAttributes:
    return DefaultAttributes(
        category="necklace",
        style="Minimalist",
        theme="Love & Friendship",
        holiday_default="Christmas",
        sustainability="Made with Recycled Metals",
        chain_style="Cable Chain",
        adjustable=True,
        convertible=True,
        default_occasion="Birthday",
        default_recipients=["Her"],
    )


def _preset() -> VariationPreset:
    return VariationPreset(
        id=1,
        name="necklace_brass_multi_birthstone",
        category="necklace",
        material_type=MaterialType.BRASS.value,
        finishes=["Gold", "Silver"],
        lengths_inches=[],
        multi_count_label="Birthstone",
        multi_count_range=[1, 2, 3],
        has_length_variation=False,
    )


def _pers() -> PersonalizationTemplate:
    return PersonalizationTemplate(
        id=1,
        name="birthstone_initial_single",
        instruction_text="Please Provide: birthstone + initial",
        example_text="For example: May, E",
        reference_note="See photo.",
        max_characters=0,
        is_optional=False,
    )


def _rows() -> list[VariationRow]:
    return [
        VariationRow(
            product_id=1, finish="Gold", length_inches=None, multi_count=n,
            price_cents=3000 + n * 500, sku_suffix=f"GO-N{n}", is_loss_leader=False,
        )
        for n in (1, 2, 3)
    ]


def _product() -> Product:
    return Product(
        id=1,
        sku="TAKI-0042",
        carrier_pillar="birthstone",
        final_title="Test Title",
        final_tags=["a", "b", "c"],
        final_description="Body copy.",
        variation_preset_id=1,
        personalization_template_id=1,
        material_type=MaterialType.BRASS.value,
        generated_variants=[
            {
                "id": "A",
                "title": "Variant A Title",
                "tags": ["x", "y"],
                "description": "Variant A description.",
                "strategy_label": "Conservative",
                "strategy_rationale": "",
                "estimated_ctr_signal": "medium",
            }
        ],
    )


def _make_session(
    *,
    product: Product | None,
    settings: ShopSettings | None = None,
) -> MagicMock:
    """Dispatch queries by model — mirrors test_payload_builder pattern."""
    session = MagicMock()
    settings = settings if settings is not None else _shop_settings()

    def query_side(model):
        q = MagicMock()
        if model is Product:
            q.filter_by.return_value.first.return_value = product
        elif model is ShopSettings:
            q.filter_by.return_value.first.return_value = settings
        elif model is VariationPreset:
            q.get.return_value = _preset()
        elif model is DefaultAttributes:
            q.filter_by.return_value.first.return_value = _defaults()
        elif model is PersonalizationTemplate:
            q.get.return_value = _pers()
        elif model is VariationRow:
            q.filter_by.return_value.order_by.return_value.all.return_value = _rows()
        else:
            q.filter_by.return_value.first.return_value = None
        return q

    session.query.side_effect = query_side
    return session


@pytest.fixture
def client_and_session():
    """Minimal app with just the approval router mounted — no lifespan."""
    app = FastAPI()
    app.include_router(approval_routes.router)

    session = _make_session(product=_product())
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as client:
        yield client, session

    app.dependency_overrides.clear()


def test_payload_preview_returns_200_with_expected_shape(client_and_session):
    client, _session = client_and_session
    resp = client.get("/approval/TAKI-0042/payload-preview", params={"variant_id": "A"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Variant A Title"
    assert body["tags"] == ["x", "y"]
    assert "inventory" in body and "products" in body["inventory"]
    assert len(body["inventory"]["products"]) == 3
    assert body["is_personalizable"] is True


def test_payload_preview_includes_production_partner_when_settings_set(client_and_session):
    client, _session = client_and_session
    body = client.get(
        "/approval/TAKI-0042/payload-preview", params={"variant_id": "A"}
    ).json()

    assert body["production_partner_ids"] == ["pp_42"]
    assert body["should_auto_renew"] is True


def test_payload_preview_falls_back_to_final_fields_without_variant_id():
    app = FastAPI()
    app.include_router(approval_routes.router)
    session = _make_session(product=_product())
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as client:
        body = client.get("/approval/TAKI-0042/payload-preview").json()

    assert body["title"] == "Test Title"
    assert body["tags"] == ["a", "b", "c"]
    app.dependency_overrides.clear()


def test_payload_preview_returns_404_for_missing_product():
    app = FastAPI()
    app.include_router(approval_routes.router)
    session = _make_session(product=None)
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as client:
        resp = client.get("/approval/UNKNOWN/payload-preview")

    assert resp.status_code == 404
    assert resp.json() == {"error": "not found"}
    app.dependency_overrides.clear()
