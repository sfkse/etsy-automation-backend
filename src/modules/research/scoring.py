"""
Sales Signal Scorer (Step 3.3)

Computes a 0-100 score for each CompetitorListing combining all available
sales signals. EHunt data (Tier A) is ground truth; Tier B falls back to
proxy heuristics when EHunt is absent.
"""
from __future__ import annotations

import re


def compute_sales_signal_score(listing) -> float:
    """
    Returns 0-100. Higher = stronger evidence the listing is actively selling.

    Tier A: EHunt data present — uses eh_sales_recent + eh_sales_total +
            eh_shop_weekly_sales as ground truth. Etsy badges add a small bonus.
    Tier B: EHunt absent — proxy heuristics (badges, views, cart, reviews).
    """
    if listing.eh_sales_recent is not None or listing.eh_sales_total is not None:
        return _tier_a(listing)
    return _tier_b(listing)


def _tier_a(listing) -> float:
    score = 0.0

    if listing.eh_sales_recent is not None:
        r = listing.eh_sales_recent
        if r >= 100:
            score += 50
        elif r >= 50:
            score += 40
        elif r >= 20:
            score += 30
        elif r >= 10:
            score += 20
        elif r >= 5:
            score += 10
        elif r >= 1:
            score += 5

    if listing.eh_sales_total is not None:
        t = listing.eh_sales_total
        if t >= 5000:
            score += 20
        elif t >= 1000:
            score += 15
        elif t >= 500:
            score += 10
        elif t >= 100:
            score += 5

    if listing.eh_shop_weekly_sales is not None:
        w = listing.eh_shop_weekly_sales
        if w >= 500:
            score += 15
        elif w >= 100:
            score += 10
        elif w >= 20:
            score += 5

    if listing.is_bestseller:
        score += 10
    if listing.is_popular_now:
        score += 5

    return min(100.0, score)


def _tier_b(listing) -> float:
    score = 0.0

    if listing.is_bestseller:
        score += 25
    if listing.is_popular_now:
        score += 15
    if listing.is_star_seller:
        score += 10

    views = _parse_views_count(listing.views_24h_count)
    if views is not None:
        score += min(25.0, views / 4.0)

    if listing.cart_count:
        score += min(15.0, listing.cart_count / 5.0)

    if listing.review_count:
        score += min(10.0, listing.review_count / 200.0)

    return min(100.0, score)


def _parse_views_count(value: str | None) -> int | None:
    """Parse "20+", "150", None → int or None."""
    if value is None:
        return None
    cleaned = re.sub(r"[^\d]", "", str(value))
    if not cleaned:
        return None
    return int(cleaned)
