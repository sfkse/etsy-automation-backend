"""Route tests for background per-slot regeneration + status polling.

Mounts only the products (input) router on a bare FastAPI app and overrides the
DB session so we sidestep the main app's lifespan. The background worker is
patched to a no-op so the test never hits real image generation — we assert the
route dispatches the job (marks it running) and that the status endpoint reflects
the running → done transition.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.dependencies import get_session
from src.db.models import Product
from src.modules.images import regen_jobs
from src.web.routes import input as input_routes

SKU = "TAKI-REGEN-TEST"
SLOT = "mannequin-1"


def _make_session() -> MagicMock:
    session = MagicMock()
    product = Product(id=1, sku=SKU, carrier_pillar="cross")

    def query_side(model):
        q = MagicMock()
        if model is Product:
            q.filter_by.return_value.first.return_value = product
        else:  # ProductImage
            q.filter_by.return_value.all.return_value = []
        return q

    session.query.side_effect = query_side
    return session


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(input_routes.router)
    app.dependency_overrides[get_session] = lambda: _make_session()
    return TestClient(app)


def test_regenerate_dispatches_and_status_reflects_running_then_done():
    regen_jobs.clear(SKU, SLOT)
    client = _client()

    # Patch the background worker so no real generation runs; the route still
    # marks the slot running before dispatching.
    with patch.object(input_routes, "_regenerate_bg", new=AsyncMock()):
        r = client.post(
            f"/products/{SKU}/images/regenerate",
            data={"slot": SLOT, "workflow": "gemini", "instructions": "", "palette": ""},
        )
    assert r.status_code == 200
    assert r.json() == {"status": "started", "slot": SLOT, "workflow": "gemini"}
    assert regen_jobs.is_running(SKU, SLOT) is True

    # Status endpoint reports the slot as running.
    s = client.get(f"/products/{SKU}/images/status").json()
    assert s["any_running"] is True
    assert s["slots"][SLOT]["running"] is True

    # Simulate the worker finishing, then the status flips to not-running.
    regen_jobs.mark_done(SKU, SLOT)
    s2 = client.get(f"/products/{SKU}/images/status").json()
    assert s2["any_running"] is False
    assert s2["slots"][SLOT]["running"] is False

    regen_jobs.clear(SKU, SLOT)


def test_regenerate_rejects_double_dispatch():
    regen_jobs.clear(SKU, SLOT)
    client = _client()
    with patch.object(input_routes, "_regenerate_bg", new=AsyncMock()):
        first = client.post(
            f"/products/{SKU}/images/regenerate",
            data={"slot": SLOT, "workflow": "gemini"},
        )
        assert first.status_code == 200
        # already running → second dispatch is rejected
        second = client.post(
            f"/products/{SKU}/images/regenerate",
            data={"slot": SLOT, "workflow": "gemini"},
        )
    assert second.status_code == 409

    regen_jobs.clear(SKU, SLOT)
