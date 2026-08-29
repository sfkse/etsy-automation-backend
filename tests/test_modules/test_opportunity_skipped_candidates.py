"""Tests for OpportunityScorer reporting the candidates it could not score.

A keyword with too little competitor data used to disappear with only a log
line, so "the vision model never suggested it" and "it was suggested but had no
data" looked identical from the outside. That mattered because the drop is not
random: specific long-tail keywords are exactly the ones least likely to have
been scraped, so the recommendations skewed generic without saying so.

`score_analysis` now records them on the analysis (and on the scorer) with the
reason, which the API surfaces as `unscored_candidates` and the popup renders
with a "Run Phase 1" button.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.db.models import KeywordCandidate, KeywordTier, SourcingAnalysis
from src.sourcing.opportunity_scorer import OpportunityScorer


def _candidate(keyword: str, tier: str = KeywordTier.NICHE.value) -> KeywordCandidate:
    return KeywordCandidate(id=hash(keyword) % 10_000, keyword=keyword, tier=tier)


def _analysis(candidates: list[KeywordCandidate]) -> SourcingAnalysis:
    analysis = SourcingAnalysis(
        id=1, rexven_premium_cost_usd_cents=660, rexven_shipping_cents=742
    )
    analysis.candidates = candidates
    return analysis


def _scorer_with_top20(by_keyword: dict[str, list]) -> OpportunityScorer:
    """Scorer whose `_fetch_top20` is driven by a keyword→listings mapping."""
    scorer = OpportunityScorer(MagicMock())
    scorer._fetch_top20 = lambda kw: by_keyword.get(kw, [])  # type: ignore[method-assign]
    return scorer


def _listings(n: int) -> list:
    """`n` listings with just the columns the sub-scores read."""
    rows = []
    for i in range(n):
        row = MagicMock()
        row.shop_age_years = 5.0
        row.price_cents = 6900
        row.shop_id = f"shop-{i}"
        row.keyword_total_results = 12_000
        row.eh_sales_recent = 1
        row.eh_sales_total = 10
        rows.append(row)
    return rows


def test_starved_candidate_is_reported_not_dropped():
    starved = _candidate("personalized birthstone cross")
    analysis = _analysis([_candidate("gold cross pendant"), starved])
    scorer = _scorer_with_top20({"gold cross pendant": _listings(20)})

    scores = scorer.score_analysis(analysis)

    assert [s.keyword for s in scores] == ["gold cross pendant"]
    assert len(scorer.skipped_candidates) == 1
    reported = scorer.skipped_candidates[0]
    assert reported["keyword"] == "personalized birthstone cross"
    assert reported["reason"] == "insufficient_data"
    assert reported["listings_found"] == 0
    assert reported["listings_required"] == OpportunityScorer.MIN_LISTINGS_TO_SCORE
    # Persisted for the poll endpoint to serve.
    assert analysis.unscored_candidates == scorer.skipped_candidates


def test_partial_data_below_the_floor_reports_what_it_found():
    analysis = _analysis([_candidate("dainty religious jewelry")])
    scorer = _scorer_with_top20({"dainty religious jewelry": _listings(3)})

    scores = scorer.score_analysis(analysis)

    assert scores == []
    assert scorer.skipped_candidates[0]["listings_found"] == 3


def test_broad_tier_is_excluded_without_being_reported():
    """Broad keywords are deliberately out of scope, not starved of data —
    offering a Phase 1 run for them would be a pointless scrape."""
    analysis = _analysis(
        [
            _candidate("gold cross pendant"),
            _candidate("gifts for her", tier=KeywordTier.BROAD.value),
        ]
    )
    scorer = _scorer_with_top20(
        {"gold cross pendant": _listings(20), "gifts for her": _listings(20)}
    )

    scores = scorer.score_analysis(analysis)

    assert [s.keyword for s in scores] == ["gold cross pendant"]
    assert scorer.skipped_candidates == []


def test_no_skips_leaves_the_column_null():
    """`or None` keeps a clean analysis out of the "needs data" UI entirely."""
    analysis = _analysis([_candidate("gold cross pendant")])
    scorer = _scorer_with_top20({"gold cross pendant": _listings(20)})

    scorer.score_analysis(analysis)

    assert analysis.unscored_candidates is None
