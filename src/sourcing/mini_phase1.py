"""
Phase 4 — Etsy search-HTML parsing helpers

Parses the ``__NEXT_DATA__`` JSON embedded in Etsy search pages into listing-card
dicts. These pure helpers are shared by ``/research/quick-scrape`` (Title Helper).

NOTE: server-side scraping of Etsy from a datacenter IP is reliably bot-blocked,
so the sourcing pipeline (Layer B) no longer scrapes here — it scores competitor
listings collected in a real browser by the Chrome extension and ingested via
``/sourcing/{id}/ingest-and-score``. Only the parsing helpers below remain, used
by the lightweight quick-scrape path.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog

_log = structlog.get_logger(__name__)

_ETSY_SEARCH_URL = "https://www.etsy.com/search"
_LISTINGS_PER_KEYWORD = 20

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


# ── Module-level pure helpers ─────────────────────────────────────────────────
# Shared by web/routes/research.py's /research/quick-scrape endpoint (PR 5).
# Do not depend on ORM or session.


def parse_next_data(html: str, *, keyword: str | None = None) -> list[dict]:
    """
    Extract listing cards from Etsy's embedded ``__NEXT_DATA__`` JSON.
    Returns a list of raw card dicts; empty list if parse fails. Falls
    back to href-pattern scraping when the JSON blob is missing.

    ``keyword`` is used only for log context.
    """
    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        _log.warning("mini_phase1_no_next_data", keyword=keyword)
        return _fallback_parse_html(html)

    try:
        data: dict = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        _log.warning("mini_phase1_json_parse_failed", keyword=keyword, error=str(e))
        return []

    return _extract_cards_from_next_data(data)


def _extract_cards_from_next_data(data: dict) -> list[dict]:
    paths = [
        ["props", "pageProps", "results"],
        ["props", "pageProps", "initialData", "results"],
        ["props", "pageProps", "initialProps", "results"],
    ]
    for path in paths:
        node: Any = data
        for key in path:
            if isinstance(node, dict):
                node = node.get(key)
            else:
                node = None
                break
        if isinstance(node, list) and node:
            return node

    return _deep_search_listings(data)


def _deep_search_listings(obj: Any, depth: int = 0) -> list[dict]:
    if depth > 8:
        return []
    if isinstance(obj, list) and len(obj) >= 5:
        if obj and isinstance(obj[0], dict):
            first = obj[0]
            if any(k in first for k in ("listing_id", "listingId", "id", "url")):
                return obj
    if isinstance(obj, dict):
        for value in obj.values():
            result = _deep_search_listings(value, depth + 1)
            if result:
                return result
    return []


def _fallback_parse_html(html: str) -> list[dict]:
    """Extract listing IDs from href patterns as a last-resort fallback."""
    pattern = re.compile(
        r'href=["\']https://www\.etsy\.com/listing/(\d{8,12})/([^"\'?\s]+)'
    )
    seen: set[str] = set()
    cards: list[dict] = []
    for m in pattern.finditer(html):
        listing_id = m.group(1)
        slug = m.group(2)
        if listing_id in seen:
            continue
        seen.add(listing_id)
        cards.append(
            {
                "listing_id": listing_id,
                "url": f"https://www.etsy.com/listing/{listing_id}/{slug}",
                "title": slug.replace("-", " "),
            }
        )
    return cards[:_LISTINGS_PER_KEYWORD]


def card_to_listing_dict(card: dict, keyword: str, rank: int) -> dict | None:
    """
    Convert a raw Etsy ``__NEXT_DATA__`` card dict to a plain dict shaped
    like the ``CompetitorListing`` columns. Returns ``None`` for cards we
    can't identify. Callers add ORM-only fields (``imported_at``,
    ``sourcing_analysis_id``) themselves.
    """
    listing_id = str(
        card.get("listing_id") or card.get("listingId") or card.get("id") or ""
    ).strip()
    if not listing_id:
        return None

    url = card.get("url") or f"https://www.etsy.com/listing/{listing_id}"

    price_cents: int | None = None
    raw_price = card.get("price") or card.get("price_cents") or card.get("listingPrice")
    if raw_price:
        if isinstance(raw_price, dict):
            amount = raw_price.get("amount") or raw_price.get("value", 0)
            divisor = raw_price.get("divisor", 100)
            try:
                price_cents = int(float(amount) / divisor * 100)
            except (ValueError, TypeError, ZeroDivisionError):
                pass
        else:
            try:
                price_cents = int(float(str(raw_price).replace(",", ".")))
            except (ValueError, TypeError):
                pass

    shop_name = (
        card.get("shop_name")
        or card.get("shopName")
        or (card.get("shop") or {}).get("name")
        or ""
    )
    shop_id = str(
        card.get("shop_id")
        or card.get("shopId")
        or (card.get("shop") or {}).get("shop_id")
        or ""
    )

    total_results = card.get("keyword_total_results") or card.get("numFound")

    return {
        "listing_id": listing_id,
        "url": url,
        "keyword_searched": keyword,
        "rank_in_search": rank,
        "title": card.get("title") or card.get("listingTitle") or "",
        "image_url": (
            card.get("image_url")
            or card.get("imageUrl")
            or card.get("main_image")
            or ""
        ),
        "shop_name": shop_name or None,
        "shop_id": shop_id or None,
        "price_cents": price_cents,
        "is_bestseller": bool(card.get("is_bestseller") or card.get("isBestseller")),
        "is_star_seller": bool(card.get("is_star_seller") or card.get("isStarSeller")),
        "keyword_total_results": total_results,
    }


__all__ = [
    "parse_next_data",
    "card_to_listing_dict",
]
