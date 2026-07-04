"""Tests for POST /settings/shop-sections/sync (PR 7).

Verifies that local ``ShopSection`` rows with ``etsy_section_id IS NULL`` get
pushed to Etsy via ``EtsyClient.create_shop_section`` and the returned id is
persisted back. Re-running is idempotent because the filter excludes rows that
already have an id; per-row exceptions do not abort the batch.

Follows the MagicMock pattern from ``test_payload_builder.py``: a minimal
FastAPI app mounts only the settings router (avoids main app's lifespan) and
``get_session`` is dependency-overridden. ``_get_etsy_client`` is
monkey-patched at its usage site inside the sync route.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.dependencies import get_session
from src.db.models import ShopSection
from src.web.routes import settings as settings_routes


def _make_session(unsynced_rows: list[ShopSection]) -> MagicMock:
    """MagicMock session where ShopSection.query yields ``unsynced_rows``.

    The route calls: session.query(ShopSection).filter(...).order_by(...).all()
    """
    session = MagicMock()
    query = MagicMock()
    query.filter.return_value.order_by.return_value.all.return_value = unsynced_rows
    session.query.return_value = query
    return session


@pytest.fixture
def app_with_mocks(monkeypatch):
    """Yield (client, session, etsy_client, rows_getter). Caller populates rows."""
    app = FastAPI()
    app.include_router(settings_routes.router)

    state: dict = {"rows": [], "etsy_client": None}

    def _session_dep():
        return state["session"]

    app.dependency_overrides[get_session] = _session_dep

    def _install(rows: list[ShopSection], etsy_client: MagicMock) -> None:
        state["rows"] = rows
        state["session"] = _make_session(rows)
        state["etsy_client"] = etsy_client
        monkeypatch.setattr(
            "src.web.routes.etsy._get_etsy_client",
            lambda: etsy_client,
        )

    with TestClient(app) as client:
        yield client, _install, state

    app.dependency_overrides.clear()


def test_sync_pushes_unsynced_rows_and_persists_returned_ids(app_with_mocks):
    client, install, state = app_with_mocks

    rows = [
        ShopSection(id=1, name="Cross Necklace", carrier_pillar="cross", display_order=1),
        ShopSection(id=2, name="Name Necklace", carrier_pillar="name", display_order=2),
    ]
    etsy = MagicMock()
    etsy.create_shop_section = AsyncMock(
        side_effect=[
            {"shop_section_id": 111, "title": "Cross Necklace"},
            {"shop_section_id": 222, "title": "Name Necklace"},
        ]
    )
    install(rows, etsy)

    resp = client.post("/settings/shop-sections/sync")

    assert resp.status_code == 200
    body = resp.json()
    assert body["errors"] == []
    assert body["created"] == [
        {"name": "Cross Necklace", "etsy_section_id": "111"},
        {"name": "Name Necklace", "etsy_section_id": "222"},
    ]
    assert etsy.create_shop_section.await_count == 2
    etsy.create_shop_section.assert_any_await("Cross Necklace")
    etsy.create_shop_section.assert_any_await("Name Necklace")
    assert rows[0].etsy_section_id == "111"
    assert rows[1].etsy_section_id == "222"
    state["session"].commit.assert_called_once()


def test_sync_is_idempotent_when_all_rows_already_synced(app_with_mocks):
    client, install, state = app_with_mocks

    etsy = MagicMock()
    etsy.create_shop_section = AsyncMock()
    install([], etsy)

    resp = client.post("/settings/shop-sections/sync")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"created": [], "errors": []}
    etsy.create_shop_section.assert_not_awaited()
    state["session"].commit.assert_called_once()


def test_sync_isolates_per_row_errors(app_with_mocks):
    client, install, state = app_with_mocks

    rows = [
        ShopSection(id=1, name="Cross Necklace", carrier_pillar="cross", display_order=1),
        ShopSection(id=2, name="Name Necklace", carrier_pillar="name", display_order=2),
    ]
    etsy = MagicMock()
    etsy.create_shop_section = AsyncMock(
        side_effect=[
            RuntimeError("etsy 500"),
            {"shop_section_id": 222},
        ]
    )
    install(rows, etsy)

    resp = client.post("/settings/shop-sections/sync")

    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] == [{"name": "Name Necklace", "etsy_section_id": "222"}]
    assert body["errors"] == [{"name": "Cross Necklace", "error": "etsy 500"}]
    assert rows[0].etsy_section_id is None
    assert rows[1].etsy_section_id == "222"
    state["session"].commit.assert_called_once()
