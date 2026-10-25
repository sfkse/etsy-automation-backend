"""Tests for the real-publish flow (POST /approval/{sku}/publish) and the
queue's batch (?skus=) filter.

Uses a minimal FastAPI app that mounts only the approval router — avoids the
main app's lifespan (scheduler + shop-defaults seed). The session is a MagicMock
that returns a single hand-built Product; approve_variant mutates that same
instance, so assertions inspect it directly after the request. The actual
Etsy publish runs as a background task (_run_real_publish_bg) — tests
monkeypatch it out so no real network/DB call happens.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from src.db.dependencies import get_session
from src.db.models import Product, ProductStatus
from src.web.routes import approval as approval_routes
from src.web.routes import etsy as etsy_routes


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


def _connected_token_manager() -> MagicMock:
    tm = MagicMock()
    tm.is_connected.return_value = True
    return tm


def test_radio_selected_publish_approves_and_schedules_real_publish(monkeypatch):
    """Main submit button posts the radio-selected `variant_id` — approves
    that variant's content and schedules the real Etsy publish pipeline."""
    product = _product()
    client, _session = _client(product)

    monkeypatch.setattr(etsy_routes, "_get_token_manager", _connected_token_manager)
    monkeypatch.setattr(etsy_routes, "_publish_running", False)
    scheduled: dict = {}
    monkeypatch.setattr(
        approval_routes, "_run_real_publish_bg",
        lambda sku: scheduled.setdefault("sku", sku),
    )

    resp = client.post(
        "/approval/TAKI-0042/publish",
        data={"variant_id": "A"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/products/TAKI-0042?publishing=1"
    assert scheduled["sku"] == "TAKI-0042"

    # approve_variant ran synchronously — status is approved, not published,
    # since the real Etsy call hasn't happened yet (it's in the background).
    assert product.status == ProductStatus.APPROVED.value
    assert product.final_title == "Title A"
    assert product.final_tags == ["a"]
    assert product.selected_variant_id == "A"


def test_publish_only_best_uses_first_variant_ids_entry(monkeypatch):
    """"Publish Only Best" sends a single `variant_ids` entry (no `variant_id`)."""
    product = _product()
    client, _session = _client(product)

    monkeypatch.setattr(etsy_routes, "_get_token_manager", _connected_token_manager)
    monkeypatch.setattr(etsy_routes, "_publish_running", False)
    scheduled: dict = {}
    monkeypatch.setattr(
        approval_routes, "_run_real_publish_bg",
        lambda sku: scheduled.setdefault("sku", sku),
    )

    resp = client.post(
        "/approval/TAKI-0042/publish",
        data={"variant_ids": ["B"]},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/products/TAKI-0042?publishing=1"
    assert scheduled["sku"] == "TAKI-0042"
    assert product.status == ProductStatus.APPROVED.value
    assert product.final_title == "Title B"


def test_publish_with_no_valid_variant_bounces_back(monkeypatch):
    product = _product()
    client, _session = _client(product)

    monkeypatch.setattr(etsy_routes, "_get_token_manager", _connected_token_manager)
    monkeypatch.setattr(etsy_routes, "_publish_running", False)
    scheduled: dict = {}
    monkeypatch.setattr(
        approval_routes, "_run_real_publish_bg",
        lambda sku: scheduled.setdefault("sku", sku),
    )

    resp = client.post(
        "/approval/TAKI-0042/publish",
        data={"variant_ids": ["Z"]},  # not a real variant id
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/approval/TAKI-0042?error=invalid_variant"
    assert product.status == ProductStatus.AWAITING_APPROVAL.value
    assert scheduled == {}


def test_publish_when_not_connected_bounces_back_without_scheduling(monkeypatch):
    product = _product()
    client, _session = _client(product)

    disconnected_tm = MagicMock()
    disconnected_tm.is_connected.return_value = False
    monkeypatch.setattr(etsy_routes, "_get_token_manager", lambda: disconnected_tm)
    scheduled: dict = {}
    monkeypatch.setattr(
        approval_routes, "_run_real_publish_bg",
        lambda sku: scheduled.setdefault("sku", sku),
    )

    resp = client.post(
        "/approval/TAKI-0042/publish",
        data={"variant_id": "A"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/approval/TAKI-0042?error=not_connected"
    # approve_variant already ran (content is saved either way); only the
    # network call is blocked.
    assert product.status == ProductStatus.APPROVED.value
    assert scheduled == {}


def test_publish_while_another_run_in_progress_bounces_back(monkeypatch):
    product = _product()
    client, _session = _client(product)

    monkeypatch.setattr(etsy_routes, "_get_token_manager", _connected_token_manager)
    monkeypatch.setattr(etsy_routes, "_publish_running", True)
    scheduled: dict = {}
    monkeypatch.setattr(
        approval_routes, "_run_real_publish_bg",
        lambda sku: scheduled.setdefault("sku", sku),
    )

    resp = client.post(
        "/approval/TAKI-0042/publish",
        data={"variant_id": "A"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/approval/TAKI-0042?error=publish_in_progress"
    assert scheduled == {}


# ── Queue: batch (?skus=) filter ──────────────────────────────────────────────


def _queue_client(monkeypatch) -> tuple[TestClient, dict]:
    """Client for GET /approval that records what the route asked the service
    for. The queue's real work is the query it builds, so the service call and
    the template render are both stubbed out.
    """
    captured: dict = {}

    def fake_queue(session, sort="newest", status_filter="pending", skus=None):
        captured["sort"] = sort
        captured["status_filter"] = status_filter
        captured["skus"] = skus
        return []

    monkeypatch.setattr(approval_routes, "get_approval_queue", fake_queue)
    monkeypatch.setattr(
        approval_routes,
        "_tmpl",
        lambda name, request, context, **kw: HTMLResponse(""),
    )

    client, _session = _client(None)
    return client, captured


def test_queue_skus_filter_scopes_to_batch_and_defaults_to_all(monkeypatch):
    client, captured = _queue_client(monkeypatch)

    assert client.get("/approval?skus=TAKI-0003,TAKI-0004").status_code == 200

    assert captured["skus"] == ["TAKI-0003", "TAKI-0004"]
    # A batch mixes awaiting-approval and already-approved rows, so the usual
    # "pending" default would hide half of what was just built.
    assert captured["status_filter"] == "all"


def test_queue_skus_filter_ignores_blanks_and_whitespace(monkeypatch):
    client, captured = _queue_client(monkeypatch)

    assert client.get("/approval?skus=TAKI-0003,,%20TAKI-0004%20,").status_code == 200

    assert captured["skus"] == ["TAKI-0003", "TAKI-0004"]


def test_queue_without_skus_still_defaults_to_pending(monkeypatch):
    client, captured = _queue_client(monkeypatch)

    assert client.get("/approval").status_code == 200

    assert captured["skus"] == []
    assert captured["status_filter"] == "pending"


def test_queue_explicit_status_wins_over_skus_default(monkeypatch):
    client, captured = _queue_client(monkeypatch)

    assert client.get("/approval?skus=TAKI-0003&status=pending").status_code == 200

    assert captured["skus"] == ["TAKI-0003"]
    assert captured["status_filter"] == "pending"


def test_variants_json_mirror_is_gone():
    """The extension no longer reviews inline — the web app owns review, and the
    JSON mirror that existed only to feed the side panel is retired."""
    client, _session = _client(_product())

    assert client.get("/approval/TAKI-0042/variants").status_code == 404
