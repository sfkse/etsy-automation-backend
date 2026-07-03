"""
Phase 4 — Rank Prediction (Layer C)

Estimates where a new Rexven product would rank in Etsy search results for a
given keyword, based on empirical data from visually similar listings already
in the competitor_listings table.

Algorithm:
  1. Filter similar listings to those that ranked for the target keyword.
  2. Take their average rank + average shop age.
  3. Apply a shop-age penalty: every year below the competitor average adds
     ~3 rank positions (new shops rank lower due to Etsy's trust algorithm).

The "3 positions per year" constant is a starting heuristic. Calibrate it
once you have post-launch data by fitting:
  actual_rank ~ empirical_avg_rank + shop_age_penalty_coeff * shop_age_gap
"""
from __future__ import annotations

import statistics

from src.db.models import CompetitorListing

# Etsy shows 48 listings per search results page
_ETSY_PAGE_SIZE = 48

# Initial heuristic: each year of shop age below competitor avg costs this many positions.
# Back-test and update once you have real ranking data.
_SHOP_AGE_PENALTY_PER_YEAR = 3.0


def predict_rank(
    similar_listings: list[tuple[CompetitorListing, float]],
    target_keyword: str,
    your_shop_age_years: float = 0.0,
    your_shop_total_sales: int = 0,
) -> dict:
    """
    Predict estimated rank for the target keyword.

    Returns:
        {
          "estimated_rank": int | None,
          "estimated_page": int | None,
          "confidence": float,        # 0.0–1.0
          "support_count": int,       # similar listings ranking for this keyword
          "reasoning": str,
        }
    """
    # Filter to listings that actually ranked for this keyword
    keyword_specific = [
        (l, sim) for l, sim in similar_listings
        if l.keyword_searched == target_keyword
    ]

    if not keyword_specific:
        return {
            "estimated_rank": None,
            "estimated_page": None,
            "confidence": 0.0,
            "support_count": 0,
            "reasoning": (
                f"No visually similar listings have been observed ranking for "
                f"'{target_keyword}'. This may be new territory for this product type."
            ),
        }

    ranks = [l.rank_in_search for l, _ in keyword_specific if l.rank_in_search]
    if not ranks:
        return {
            "estimated_rank": None,
            "estimated_page": None,
            "confidence": 0.0,
            "support_count": len(keyword_specific),
            "reasoning": "Similar listings exist for this keyword but lack rank data.",
        }

    avg_rank = statistics.mean(ranks)

    shop_ages = [l.shop_age_years for l, _ in keyword_specific if l.shop_age_years]
    avg_shop_age = statistics.mean(shop_ages) if shop_ages else 5.0

    shop_age_gap = max(0.0, avg_shop_age - your_shop_age_years)
    shop_penalty = shop_age_gap * _SHOP_AGE_PENALTY_PER_YEAR

    estimated_rank = max(1, int(avg_rank + shop_penalty))
    estimated_page = (estimated_rank - 1) // _ETSY_PAGE_SIZE + 1

    # Confidence scales linearly up to 5 support listings
    confidence = min(1.0, len(keyword_specific) / 5.0)

    reasoning = (
        f"{len(keyword_specific)} visually similar listings rank for '{target_keyword}'. "
        f"Their avg rank is {avg_rank:.1f} with avg shop age {avg_shop_age:.1f}yr. "
        f"Adjusted for your shop age ({your_shop_age_years:.1f}yr, "
        f"+{shop_penalty:.0f} position penalty), "
        f"estimated rank is ~{estimated_rank} (page {estimated_page})."
    )

    return {
        "estimated_rank": estimated_rank,
        "estimated_page": estimated_page,
        "confidence": round(confidence, 2),
        "support_count": len(keyword_specific),
        "reasoning": reasoning,
    }
