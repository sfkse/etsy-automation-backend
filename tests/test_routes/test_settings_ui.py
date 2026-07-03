"""Tests for the /settings tabbed HTML editor (PR 3).

Mounts only the settings router on a bare FastAPI app so we sidestep the main
app's lifespan (scheduler + seed) and its env-var requirements. Templates are
wired manually via ``settings_routes.set_templates``.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from src.db.dependencies import get_session
from src.db.models import (
    DefaultAttributes,
    DescriptionTemplate,
    PersonalizationTemplate,
    PricingStrategy,
    ShopSection,
    ShopSettings,
    VariationPreset,
)
from src.web.routes import settings as settings_routes


def _empty_chain() -> MagicMock:
    """A MagicMock whose ``.filter_by().order_by().all()`` chain returns []."""
    q = MagicMock()
    q.all.return_value = []
    q.order_by.return_value.all.return_value = []
    q.filter_by.return_value.order_by.return_value.all.return_value = []
    q.filter_by.return_value.all.return_value = []
    return q


def _make_session() -> MagicMock:
    session = MagicMock()
    shop = ShopSettings(
        id=1,
        renewal_option="automatic",
        default_quantity=999,
        feature_listing_default=False,
        omit_karat_in_title=False,
        return_policy_days=30,
        active_pillars=["cross", "birthstone"],
        default_shipping_profile_id="ship_1",
    )
    pricing = PricingStrategy(
        id=1,
        base_multiplier=3.0,
        finish_offsets_pct={"Gold": 0, "Silver": -5, "Rose Gold": 10},
        length_base_inches=18,
        length_price_per_extra_inch_pct=3.0,
        loss_leader_enabled=False,
        multi_count_extra_pct=12.0,
    )

    def query_side(model):
        q = _empty_chain()
        if model is ShopSettings:
            q.filter_by.return_value.first.return_value = shop
        elif model is PricingStrategy:
            q.filter_by.return_value.first.return_value = pricing
        elif model in (
            DescriptionTemplate,
            DefaultAttributes,
            VariationPreset,
            PersonalizationTemplate,
            ShopSection,
        ):
            q.all.return_value = []
            q.order_by.return_value.all.return_value = []
        else:
            q.filter_by.return_value.first.return_value = None
        return q

    session.query.side_effect = query_side
    return session


@pytest.fixture
def client():
    app = FastAPI()
    templates = Jinja2Templates(directory="src/web/templates")
    settings_routes.set_templates(templates)
    app.include_router(settings_routes.router)

    session = _make_session()
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


def test_settings_index_renders_all_eight_tabs(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    html = resp.text
    assert "nav-tabs" in html
    for label in [
        "Production Partner",
        "Description Templates",
        "Default Attributes",
        "Variation Presets",
        "Pricing Strategy",
        "Personalization",
        "Operations",
        "Shop Sections",
    ]:
        assert label in html, f"missing tab label {label!r} in /settings response"


def test_settings_index_includes_static_scripts(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "/static/settings.js" in resp.text
    assert "/static/settings_pricing_preview.js" in resp.text


def test_operations_round_trip_saves_via_json(client):
    resp = client.post(
        "/settings/operations",
        json={
            "renewal_option": "manual",
            "default_quantity": 111,
            "feature_listing_default": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["renewal_option"] == "manual"
    assert body["default_quantity"] == 111
    assert body["feature_listing_default"] is True
