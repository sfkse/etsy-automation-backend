"""Scoring an analysis twice must refresh its keyword scores, not duplicate them.

Every POST /sourcing/{id}/ingest-and-score queues Layer B again, so the
"Run Phase 1 for this keyword → re-ingest → re-score" loop re-scores the whole
analysis. `score_analysis` used to construct a fresh KeywordScore every time,
leaving two rows per keyword — previously masked by the poll endpoint's top-5
cut, and now fully visible since it returns every scored keyword.

Preserving the row also keeps `Product.selected_keyword_score_id` pointing at a
live score rather than a superseded one.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.db.models import KeywordCandidate, KeywordScore, SourcingAnalysis
from src.sourcing.opportunity_scorer import OpportunityScorer


def _listings(n: int, price_cents: int = 5000) -> list:
    rows = []
    for i in range(n):
        row = MagicMock()
        row.price_cents = price_cents
        row.shop_age_years = 5.0
        row.shop_id = f"shop-{i}"
        row.keyword_total_results = 10_000
        row.eh_sales_recent = 1
        row.eh_sales_total = 5
        rows.append(row)
    return rows


class _Session:
    """Session whose add_all appends to the analysis's score collection,
    mimicking the relationship backref a real flush would populate."""

    def __init__(self, analysis: SourcingAnalysis):
        self._analysis = analysis

    def add_all(self, objs):
        for o in objs:
            if isinstance(o, KeywordScore) and o not in self._analysis.scores:
                self._analysis.scores.append(o)

    def commit(self):
        pass


def _analysis() -> SourcingAnalysis:
    a = SourcingAnalysis(
        id=1, rexven_premium_cost_usd_cents=660, rexven_shipping_cents=742
    )
    a.candidates = [
        KeywordCandidate(id=1, keyword="gold cross pendant", tier="niche"),
        KeywordCandidate(id=2, keyword="baptism gift cross necklace", tier="niche"),
    ]
    a.scores = []
    return a


def _scorer(analysis, top20):
    scorer = OpportunityScorer(_Session(analysis))
    scorer._fetch_top20 = lambda kw: top20  # type: ignore[method-assign]
    return scorer


def test_second_score_updates_instead_of_duplicating():
    analysis = _analysis()
    _scorer(analysis, _listings(20)).score_analysis(analysis)
    assert len(analysis.scores) == 2

    _scorer(analysis, _listings(20)).score_analysis(analysis)

    assert len(analysis.scores) == 2
    assert sorted(s.keyword for s in analysis.scores) == [
        "baptism gift cross necklace",
        "gold cross pendant",
    ]


def test_rescore_preserves_row_identity():
    """`Product.selected_keyword_score_id` must keep resolving after a re-score."""
    analysis = _analysis()
    _scorer(analysis, _listings(20)).score_analysis(analysis)
    for i, s in enumerate(analysis.scores, start=100):
        s.id = i  # stand in for the ids a flush would assign
    before = {s.keyword: s.id for s in analysis.scores}

    _scorer(analysis, _listings(20)).score_analysis(analysis)

    assert {s.keyword: s.id for s in analysis.scores} == before


def test_rescore_picks_up_new_market_data():
    """A re-score after more listings arrive must actually move the numbers."""
    analysis = _analysis()
    _scorer(analysis, _listings(20, price_cents=2000)).score_analysis(analysis)
    cheap = {s.keyword: s.score_price_alignment for s in analysis.scores}

    _scorer(analysis, _listings(20, price_cents=9000)).score_analysis(analysis)
    rich = {s.keyword: s.score_price_alignment for s in analysis.scores}

    assert all(rich[k] > cheap[k] for k in cheap)
