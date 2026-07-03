"""
Phase 4 — Mini-Phase-1 Runner (Layer B)

Programmatically scrapes Etsy's public search HTML to get the top-20 listings
for a keyword. Uses a 7-day cache against the existing competitor_listings table
to avoid redundant scraping.

Unlike the Chrome extension (which uses a logged-in browser), this scraper hits
Etsy's public search endpoint. It parses the __NEXT_DATA__ JSON embedded in every
Etsy search page, which contains all the listing cards without requiring JS execution.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from typing import Any

import httpx
import structlog
from sqlalchemy.orm import Session

from src.db.models import CompetitorListing, SourcingAnalysis

_log = structlog.get_logger(__name__)

_ETSY_SEARCH_URL = "https://www.etsy.com/search"
_LISTINGS_PER_KEYWORD = 20
_CACHE_DAYS = 7
_REQUEST_DELAY_S = 2.5  # polite delay between requests

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


class MiniPhase1Runner:
    """
    Programmatic Phase 1 scraper with reduced depth (top 20 vs. 60).

    Cache-first: if we scraped this keyword in the last 7 days, reuse existing
    competitor_listings rows. Only hits Etsy when data is stale or absent.
    """

    def __init__(self, session: Session):
        self.session = session

    def run(
        self,
        analysis: SourcingAnalysis,
        keywords: list[str],
    ) -> dict[str, list[CompetitorListing]]:
        """
        Ensure top-20 listings exist for each keyword.
        Returns dict: keyword -> list[CompetitorListing].
        """
        results: dict[str, list[CompetitorListing]] = {}

        for i, keyword in enumerate(keywords):
            cached = self._lookup_cache(keyword)
            if cached:
                _log.info("mini_phase1_cache_hit", keyword=keyword, count=len(cached))
                results[keyword] = cached
                continue

            _log.info("mini_phase1_scraping", keyword=keyword)
            if i > 0:
                time.sleep(_REQUEST_DELAY_S)

            try:
                listings = self._scrape_keyword(keyword, analysis)
                results[keyword] = listings
            except Exception as e:
                _log.warning("mini_phase1_scrape_failed", keyword=keyword, error=str(e))
                results[keyword] = []

        return results

    def _lookup_cache(self, keyword: str) -> list[CompetitorListing]:
        """Return cached listings if scraped within CACHE_DAYS, else empty list."""
        cutoff = datetime.utcnow() - timedelta(days=_CACHE_DAYS)
        rows = (
            self.session.query(CompetitorListing)
            .filter(
                CompetitorListing.keyword_searched == keyword,
                CompetitorListing.imported_at >= cutoff,
            )
            .order_by(CompetitorListing.rank_in_search.asc().nullslast())
            .limit(_LISTINGS_PER_KEYWORD)
            .all()
        )
        return rows if len(rows) >= 5 else []

    def _scrape_keyword(
        self,
        keyword: str,
        analysis: SourcingAnalysis,
    ) -> list[CompetitorListing]:
        """Scrape Etsy search page and persist top-20 listings."""
        params = {
            "q": keyword,
            "explicit": "1",
            "ref": "pagination",
        }

        with httpx.Client(
            headers=_HEADERS,
            follow_redirects=True,
            timeout=30,
        ) as client:
            resp = client.get(_ETSY_SEARCH_URL, params=params)
            resp.raise_for_status()

        cards = parse_next_data(resp.text, keyword=keyword)
        if not cards:
            _log.warning("mini_phase1_no_cards", keyword=keyword)
            return []

        listings = []
        for rank, card in enumerate(cards[:_LISTINGS_PER_KEYWORD], start=1):
            data = card_to_listing_dict(card, keyword, rank)
            if not data:
                continue
            existing = (
                self.session.query(CompetitorListing)
                .filter_by(listing_id=data["listing_id"])
                .first()
            )
            if existing:
                listings.append(existing)
                continue

            listing = CompetitorListing(
                **data,
                scraped_for_sourcing=True,
                sourcing_analysis_id=analysis.id,
                imported_at=datetime.utcnow(),
            )
            self.session.add(listing)
            listings.append(listing)

        self.session.commit()
        _log.info("mini_phase1_scraped", keyword=keyword, count=len(listings))
        return listings

# ── Module-level pure helpers ─────────────────────────────────────────────────
# Shared by MiniPhase1Runner and web/routes/research.py's /research/quick-scrape
# endpoint (PR 5). Do not depend on ORM or session.


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
        cards.append({
            "listing_id": listing_id,
            "url": f"https://www.etsy.com/listing/{listing_id}/{slug}",
            "title": slug.replace("-", " "),
        })
    return cards[:_LISTINGS_PER_KEYWORD]


def card_to_listing_dict(card: dict, keyword: str, rank: int) -> dict | None:
    """
    Convert a raw Etsy ``__NEXT_DATA__`` card dict to a plain dict shaped
    like the ``CompetitorListing`` columns. Returns ``None`` for cards we
    can't identify. Callers add ORM-only fields (``imported_at``,
    ``sourcing_analysis_id``) themselves.
    """
    listing_id = str(
        card.get("listing_id")
        or card.get("listingId")
        or card.get("id")
        or ""
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
    "MiniPhase1Runner",
    "parse_next_data",
    "card_to_listing_dict",
]
