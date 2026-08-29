"""Tests for input handling in POST /sourcing/suggest-keywords.

Covers the metadata overlay the Chrome extension posts alongside the product
image. Rexven is a client-rendered, auth-gated SPA, so the extension reads the
live page and hands over title/category/cost/badges directly; supplying those
must NOT divert the request into ``scrape_rexven_product``, whose httpx fetch
cannot see that page.

Mounts only the sourcing router on a bare FastAPI app, sidestepping the main
app's lifespan — same pattern as ``test_quick_scrape.py``.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.dependencies import get_session
from src.db.models import SourcingAnalysis
from src.web.routes import sourcing as sourcing_routes


@pytest.fixture
def captured():
    """Collects the SourcingAnalysis rows the route persists."""
    return []


@pytest.fixture
def client(captured):
    app = FastAPI()
    app.include_router(sourcing_routes.router)

    session = MagicMock()
    session.add.side_effect = lambda obj: (
        captured.append(obj) if isinstance(obj, SourcingAnalysis) else None
    )
    app.dependency_overrides[get_session] = lambda: session

    with TestClient(app) as c:
        yield c


def _no_candidates():
    """Stub Layer A — these tests are about row construction, not the vision LLM."""
    suggester = MagicMock()
    suggester.run.return_value = []
    return suggester


def test_metadata_overlay_populates_row_without_scraping(client, captured):
    """An image + metadata must fill the rexven_* columns and skip the scraper."""
    with (
        patch.object(sourcing_routes, "save_uploaded_image", return_value="/tmp/p.jpg"),
        patch.object(sourcing_routes, "scrape_rexven_product") as scrape,
        patch.object(
            sourcing_routes, "VisionKeywordSuggester", return_value=_no_candidates()
        ),
    ):
        resp = client.post(
            "/sourcing/suggest-keywords",
            files={"image": ("p.jpg", b"\xff\xd8\xff", "image/jpeg")},
            data={
                "rexven_url": "https://rexven.com/product-details/123",
                "rexven_sku": "REX-9",
                "image_url": "https://cdn.rexven.com/p.jpg",
                "rexven_title": "Gümüş Kolye",
                "rexven_category": "necklace",
                "rexven_cost_cents": "738",
                "rexven_premium_cost_cents": "615",
                "rexven_satisa_uygun": "true",
                "rexven_yeni": "false",
            },
        )

    assert resp.status_code == 200, resp.text
    # The whole point: the browser already read the page.
    scrape.assert_not_called()

    row = captured[0]
    assert row.image_path == "/tmp/p.jpg"
    assert row.rexven_url == "https://rexven.com/product-details/123"
    assert row.rexven_sku == "REX-9"
    assert row.image_url == "https://cdn.rexven.com/p.jpg"
    assert row.rexven_title_tr == "Gümüş Kolye"
    assert row.rexven_category == "necklace"
    assert row.rexven_cost_usd_cents == 738
    assert row.rexven_premium_cost_usd_cents == 615
    assert row.rexven_has_satisa_uygun_badge is True
    assert row.rexven_has_yeni_badge is False


def test_rexven_url_alone_still_scrapes(client, captured):
    """The URL-only path (non-extension callers) is unchanged."""
    scraped = {
        "image_url": "https://cdn.rexven.com/scraped.jpg",
        "title_tr": "Kolye",
        "title_en": None,
        "cost_cents": 900,
        "premium_cost_cents": 800,
        "category": "jewelry",
        "satisa_uygun": True,
        "yeni": False,
    }
    with (
        patch.object(sourcing_routes, "scrape_rexven_product", return_value=scraped) as scrape,
        patch.object(sourcing_routes, "download_remote_image", return_value="/tmp/s.jpg"),
        patch.object(
            sourcing_routes, "VisionKeywordSuggester", return_value=_no_candidates()
        ),
    ):
        resp = client.post(
            "/sourcing/suggest-keywords",
            data={"rexven_url": "https://rexven.com/product-details/123"},
        )

    assert resp.status_code == 200, resp.text
    scrape.assert_called_once_with("https://rexven.com/product-details/123")

    row = captured[0]
    assert row.image_path == "/tmp/s.jpg"
    assert row.rexven_title_tr == "Kolye"
    assert row.rexven_cost_usd_cents == 900
    assert row.rexven_has_satisa_uygun_badge is True


def test_overlay_overrides_scraped_values(client, captured):
    """When both exist the browser's reading wins — it saw the rendered page."""
    scraped = {
        "image_url": "https://cdn.rexven.com/scraped.jpg",
        "title_tr": "Wrong Title",
        "title_en": None,
        "cost_cents": 100,
        "premium_cost_cents": None,
        "category": "jewelry",
        "satisa_uygun": False,
        "yeni": False,
    }
    with (
        patch.object(sourcing_routes, "scrape_rexven_product", return_value=scraped),
        patch.object(sourcing_routes, "download_remote_image", return_value="/tmp/s.jpg"),
        patch.object(
            sourcing_routes, "VisionKeywordSuggester", return_value=_no_candidates()
        ),
    ):
        resp = client.post(
            "/sourcing/suggest-keywords",
            data={
                "rexven_url": "https://rexven.com/product-details/123",
                "rexven_title": "Gümüş Kolye",
                "rexven_cost_cents": "738",
            },
        )

    assert resp.status_code == 200, resp.text
    row = captured[0]
    assert row.rexven_title_tr == "Gümüş Kolye"
    assert row.rexven_cost_usd_cents == 738
    # Untouched by the overlay, so the scraped value survives.
    assert row.rexven_category == "jewelry"


def test_no_image_anywhere_is_422(client):
    """Unchanged guard: an analysis without an image is rejected."""
    with (
        patch.object(sourcing_routes, "scrape_rexven_product", return_value={}),
        patch.object(
            sourcing_routes, "VisionKeywordSuggester", return_value=_no_candidates()
        ),
    ):
        resp = client.post(
            "/sourcing/suggest-keywords",
            data={"rexven_url": "https://rexven.com/product-details/123"},
        )

    assert resp.status_code == 422
    assert "product image path" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Structural capture (options / spec block / raw payload)
# ---------------------------------------------------------------------------


def test_structural_capture_is_normalized_onto_the_row(client, captured):
    """Options + description arrive as form fields and land normalized.

    The extension posts these as JSON strings because multipart carries no
    nested structure; Turkish-label mapping is the server's job so the rules
    live in one place.
    """
    options = (
        '[{"name": "Renk", "selected": "Gold", "values": null},'
        ' {"name": "Materyal", "selected": "Pirin\\u00e7 (Brass)", "values": null},'
        ' {"name": "Sipari\\u015f yeri", "selected": "Yurt D\\u0131\\u015f\\u0131", "values": null}]'
    )
    description = (
        "<p><strong>Malzeme:</strong><span> Pirinç (Brass)</span></p>"
        "<p><strong>Renk:</strong><span> Gold Renk Seçeneği Mevcuttur..</span></p>"
        "<p><strong>Tarz:</strong><span> Minimalist</span></p>"
    )

    with (
        patch.object(sourcing_routes, "save_uploaded_image", return_value="/tmp/p.jpg"),
        patch.object(sourcing_routes, "scrape_rexven_product") as scrape,
        patch.object(
            sourcing_routes, "VisionKeywordSuggester", return_value=_no_candidates()
        ),
    ):
        resp = client.post(
            "/sourcing/suggest-keywords",
            files={"image": ("p.jpg", b"\xff\xd8\xff", "image/jpeg")},
            data={
                "rexven_sku": "REX-922",
                "rexven_cost_cents": "738",
                "rexven_shipping_cents": "830",
                "rexven_options": options,
                "rexven_description_html": description,
                "rexven_context": '{"currency": "USD", "orderLocation": "Yurt D\\u0131\\u015f\\u0131"}',
                "rexven_raw_payload": '{"sku": "REX-922"}',
            },
        )

    assert resp.status_code == 200, resp.text
    scrape.assert_not_called()

    row = captured[0]
    assert row.rexven_shipping_cents == 830
    assert row.rexven_raw_payload == {"sku": "REX-922"}

    by_key = {o["key"]: o for o in row.rexven_options}
    assert by_key["material"]["selected"] == "Pirinç (Brass)"
    # A single-value domain recovered from prose — not "unknown".
    assert by_key["finish"]["values"] == ["Gold"]
    # 'Sipariş yeri' is not a product dimension, but must survive.
    assert any(o["name"] == "Sipariş yeri" and o["key"] is None for o in row.rexven_options)

    assert row.rexven_attributes["material_type"] == "brass"
    assert row.rexven_attributes["style"] == "Minimalist"
    assert row.rexven_attributes["capture_context"]["currency"] == "USD"


def test_malformed_structural_json_does_not_lose_the_capture(client, captured):
    """A bad options blob must not cost us the image, prices and title.

    Those are what block the pipeline; the structural fields are enrichment.
    """
    with (
        patch.object(sourcing_routes, "save_uploaded_image", return_value="/tmp/p.jpg"),
        patch.object(
            sourcing_routes, "VisionKeywordSuggester", return_value=_no_candidates()
        ),
    ):
        resp = client.post(
            "/sourcing/suggest-keywords",
            files={"image": ("p.jpg", b"\xff\xd8\xff", "image/jpeg")},
            data={
                "rexven_title": "Güneş Kolye",
                "rexven_cost_cents": "738",
                "rexven_options": "{not json at all",
            },
        )

    assert resp.status_code == 200, resp.text
    row = captured[0]
    assert row.rexven_title_tr == "Güneş Kolye"
    assert row.rexven_cost_usd_cents == 738
    assert row.rexven_options is None


def test_shipping_is_optional_and_absent_stays_none(client, captured):
    """Pre-existing callers omit shipping; the column must stay NULL, not 0.

    OpportunityScorer keys its old-vs-new cost basis off exactly this.
    """
    with (
        patch.object(sourcing_routes, "save_uploaded_image", return_value="/tmp/p.jpg"),
        patch.object(
            sourcing_routes, "VisionKeywordSuggester", return_value=_no_candidates()
        ),
    ):
        resp = client.post(
            "/sourcing/suggest-keywords",
            files={"image": ("p.jpg", b"\xff\xd8\xff", "image/jpeg")},
            data={"rexven_cost_cents": "738"},
        )

    assert resp.status_code == 200, resp.text
    assert captured[0].rexven_shipping_cents is None
