"""Unit tests for the module-level parse helpers extracted in PR 5.

These helpers are shared by ``MiniPhase1Runner`` (sourcing pipeline) and
the ``/research/quick-scrape`` endpoint that powers the Chrome extension's
Title Helper tab. Both call sites must handle Etsy's __NEXT_DATA__ blob
plus the href-based fallback.
"""
from __future__ import annotations

import json

from src.sourcing.mini_phase1 import card_to_listing_dict, parse_next_data


def _next_data_html(cards: list[dict]) -> str:
    payload = {"props": {"pageProps": {"results": cards}}}
    return (
        "<html><body>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        "</body></html>"
    )


def test_parse_next_data_returns_cards_from_json_blob():
    cards = [
        {"listing_id": "111", "title": "First", "url": "https://etsy.com/listing/111/first"},
        {"listing_id": "222", "title": "Second", "url": "https://etsy.com/listing/222/second"},
        {"listing_id": "333", "title": "Third", "url": "https://etsy.com/listing/333/third"},
    ]
    parsed = parse_next_data(_next_data_html(cards), keyword="test")
    assert len(parsed) == 3
    assert parsed[0]["listing_id"] == "111"


def test_parse_next_data_falls_back_to_href_scraping():
    html = """
    <a href="https://www.etsy.com/listing/12345678/my-necklace"></a>
    <a href="https://www.etsy.com/listing/98765432/another-piece"></a>
    <a href="https://www.etsy.com/listing/12345678/my-necklace"></a>
    """
    parsed = parse_next_data(html, keyword="fallback")
    assert len(parsed) == 2
    assert {c["listing_id"] for c in parsed} == {"12345678", "98765432"}


def test_parse_next_data_returns_empty_on_bad_json():
    html = '<script id="__NEXT_DATA__">{not valid json}</script>'
    assert parse_next_data(html, keyword="bad") == []


def test_card_to_listing_dict_normalises_camel_case_keys():
    card = {
        "listingId": "42",
        "listingTitle": "Camel Case Necklace",
        "imageUrl": "https://img/42.jpg",
        "shopName": "TestShop",
        "shopId": "9",
        "isStarSeller": True,
        "isBestseller": False,
        "listingPrice": {"amount": 2500, "divisor": 100},
    }
    row = card_to_listing_dict(card, keyword="necklace", rank=1)
    assert row is not None
    assert row["listing_id"] == "42"
    assert row["title"] == "Camel Case Necklace"
    assert row["image_url"] == "https://img/42.jpg"
    assert row["shop_name"] == "TestShop"
    assert row["shop_id"] == "9"
    assert row["is_star_seller"] is True
    assert row["is_bestseller"] is False
    assert row["price_cents"] == 2500
    assert row["rank_in_search"] == 1
    assert row["keyword_searched"] == "necklace"


def test_card_to_listing_dict_returns_none_without_id():
    assert card_to_listing_dict({"title": "no id"}, "kw", 1) is None
