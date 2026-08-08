"""Tests for compute_preflight (WS4 — settings preflight for the build gate).

Uses a MagicMock session that dispatches by model, mirroring the pattern in
test_payload_builder / test_approval_payload_preview, so no real DB is needed.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.db.models import PricingStrategy, ShopSettings, VariationPreset
from src.web.routes.settings import compute_preflight

# Sentinel "row exists" — compute_preflight only checks for presence (not None).
_EXISTS = object()


def _make_session(*, settings, pricing=_EXISTS, preset=_EXISTS) -> MagicMock:
    session = MagicMock()

    def query_side(model):
        q = MagicMock()
        if model is ShopSettings:
            q.filter_by.return_value.first.return_value = settings
        elif model is PricingStrategy:
            q.first.return_value = pricing
        elif model is VariationPreset:
            q.first.return_value = preset
        else:
            q.filter_by.return_value.first.return_value = None
            q.first.return_value = None
        return q

    session.query.side_effect = query_side
    return session


def test_ready_when_partner_and_shipping_set():
    session = _make_session(
        settings=ShopSettings(id=1, production_partner_id="pp_42", default_shipping_profile_id="ship_1")
    )
    result = compute_preflight(session)
    assert result["ready"] is True
    assert result["missing"] == []


def test_missing_shipping_profile_only():
    session = _make_session(
        settings=ShopSettings(id=1, production_partner_id="pp_42", default_shipping_profile_id=None)
    )
    result = compute_preflight(session)
    keys = {m["key"] for m in result["missing"]}
    assert result["ready"] is False
    assert "default_shipping_profile_id" in keys
    assert "production_partner_id" not in keys


def test_blank_strings_count_as_missing():
    session = _make_session(
        settings=ShopSettings(id=1, production_partner_id="  ", default_shipping_profile_id="")
    )
    keys = {m["key"] for m in compute_preflight(session)["missing"]}
    assert {"production_partner_id", "default_shipping_profile_id"} <= keys


def test_defensive_seed_checks_trip_when_rows_absent():
    session = _make_session(settings=None, pricing=None, preset=None)
    result = compute_preflight(session)
    keys = {m["key"] for m in result["missing"]}
    assert {
        "shop_settings",
        "production_partner_id",
        "default_shipping_profile_id",
        "pricing_strategy",
        "variation_presets",
    } <= keys
    assert result["ready"] is False


def test_each_missing_entry_names_a_settings_tab():
    result = compute_preflight(_make_session(settings=None, pricing=None, preset=None))
    assert all(m.get("tab") and m.get("why") for m in result["missing"])
