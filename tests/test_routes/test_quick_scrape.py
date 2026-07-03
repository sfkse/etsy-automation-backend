"""Tests for POST /research/quick-scrape (PR 5).

Mounts only the research router on a bare FastAPI app so we sidestep the
main app's lifespan (scheduler + seed) and env-var requirements.
Follows the same pattern as ``test_settings_ui.py``.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from src.web.routes import research as research_routes


def _next_data_html(cards: list[dict]) -> str:
    payload = {"props": {"pageProps": {"results": cards}}}
    return (
        "<html><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        "</body></html>"
    )


def _mock_response(html: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.text = html
    resp.status_code = status_code
    return resp


@pytest.fixture
def client():
    app = FastAPI()
    templates = Jinja2Templates(directory="src/web/templates")
    research_routes.set_templates(templates)
    app.include_router(research_routes.router)
    with TestClient(app) as c:
        yield c


def _mock_httpx(html: str, status_code: int = 200):
    """Patch ``httpx.AsyncClient`` so ``async with ... as client: client.get(...)``
    returns our fixture response."""
    ctx_manager = MagicMock()
    ctx_manager.__aenter__ = AsyncMock(
        return_value=MagicMock(get=AsyncMock(return_value=_mock_response(html, status_code)))
    )
    ctx_manager.__aexit__ = AsyncMock(return_value=None)
    return patch(
        "src.web.routes.research.httpx.AsyncClient",
        return_value=ctx_manager,
    )


def test_quick_scrape_returns_parsed_listings(client):
    cards = [
        {
            "listing_id": str(1000 + i),
            "title": f"Result {i}",
            "url": f"https://etsy.com/listing/{1000 + i}",
            "shop_name": "Shop",
            "is_star_seller": i % 2 == 0,
        }
        for i in range(5)
    ]
    with _mock_httpx(_next_data_html(cards)):
        resp = client.post("/research/quick-scrape", json={"keyword": "necklace"})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["listings"]) == 5
    assert body["listings"][0]["listing_id"] == "1000"
    assert body["listings"][0]["keyword_searched"] == "necklace"
    assert body["listings"][0]["rank_in_search"] == 1


def test_quick_scrape_honours_limit(client):
    cards = [
        {"listing_id": str(i), "title": f"r{i}"} for i in range(25)
    ]
    with _mock_httpx(_next_data_html(cards)):
        resp = client.post(
            "/research/quick-scrape",
            json={"keyword": "necklace", "limit": 5},
        )
    assert resp.status_code == 200
    assert len(resp.json()["listings"]) == 5


def test_quick_scrape_rejects_empty_keyword(client):
    resp = client.post("/research/quick-scrape", json={"keyword": "   "})
    assert resp.status_code == 422


def test_quick_scrape_returns_502_on_upstream_error(client):
    with _mock_httpx("", status_code=503):
        resp = client.post("/research/quick-scrape", json={"keyword": "necklace"})
    assert resp.status_code == 502
