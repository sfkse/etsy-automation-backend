"""Tests for OpportunityScorer's `price_alignment` sub-score.

The sub-score used to give full marks when target_retail (landed x 4) fell
inside the top-20's p25..p75, else penalise |target - median| symmetrically.

Both halves misread the market. The band check rewarded *dispersion*: handmade
jewelry price spreads are enormous, so almost any target sits between p25 and
p75. On the REX-936 analysis, 8 of 11 keywords scored a perfect 1.0 while every
one of their medians sat 13-47% BELOW the target — the three that were penalised
were simply the ones with tight bands. And the symmetric fallback marked down a
market pricing well ABOVE our cost basis, which is the best possible finding.

It now scores where the median sits between break-even and the target multiple.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.db.models import KeywordCandidate, SourcingAnalysis
from src.sourcing.opportunity_scorer import OpportunityScorer


# REX-936: $6.60 premium + $7.42 shipping = $14.02 landed → $56.08 target.
_LANDED_CENTS = 1402
_TARGET_CENTS = int(_LANDED_CENTS * OpportunityScorer.RETAIL_MULTIPLIER)


def _top20(prices_cents: list[int]) -> list:
    rows = []
    for i, price in enumerate(prices_cents):
        row = MagicMock()
        row.price_cents = price
        row.shop_age_years = 5.0
        row.shop_id = f"shop-{i}"
        row.keyword_total_results = 10_000
        row.eh_sales_recent = 0
        row.eh_sales_total = 0
        rows.append(row)
    return rows


def _price_score(prices_cents: list[int], target: int = _TARGET_CENTS) -> float:
    scorer = OpportunityScorer(MagicMock())
    row = scorer._score_single(
        SourcingAnalysis(id=1),
        KeywordCandidate(id=1, keyword="k", tier="niche"),
        _top20(prices_cents),
        target,
    )
    return row.score_price_alignment


def test_market_at_the_target_multiple_scores_full():
    """Median == landed x 4 is exactly the price we want to charge."""
    assert _price_score([_TARGET_CENTS] * 10) == 1.0


def test_richer_market_is_not_punished_for_being_rich():
    """The regression: a market pricing far above our cost basis is the best
    possible finding, not a misalignment."""
    rich = _price_score([20_000] * 10)  # $200 median vs a $56.08 target
    assert rich == 1.0
    # ...and never below a market priced at the bare target.
    assert rich >= _price_score([_TARGET_CENTS] * 10)


def test_market_below_breakeven_scores_zero():
    """Under 1.5x landed cost, Etsy's cut leaves nothing."""
    breakeven = _LANDED_CENTS * OpportunityScorer.BREAKEVEN_MULTIPLIER
    assert _price_score([int(breakeven)] * 10) == 0.0
    assert _price_score([500] * 10) == 0.0


def test_score_rises_monotonically_with_market_price():
    """Direction is the whole point: richer market, better score."""
    medians = [2000, 3000, 4000, 5000, 6000, 10_000]
    scores = [_price_score([m] * 10) for m in medians]
    assert scores == sorted(scores)


def test_wide_spread_no_longer_buys_a_free_pass():
    """`baptism gift cross necklace`: $37.49 median inside a $27-$113 band.

    The old band check scored this 1.0. The typical competitor charges $37 while
    we need $56, which is a squeeze, not a perfect fit.
    """
    prices = [2701, 2900, 3200, 3749, 3800, 4500, 8000, 11_324]
    score = _price_score(prices)
    assert 0.3 < score < 0.7


def test_tight_cheap_market_is_penalised_but_not_annihilated():
    """`gold cross birthstone necklace`: $29.41 median, tight $24-$45 band.

    Scored 0.09 before — near-zero for a market still selling at 2.1x landed
    cost. It should read as squeezed, not as worthless.
    """
    prices = [2459, 2600, 2941, 3100, 3400, 4519]
    score = _price_score(prices)
    assert 0.15 < score < 0.45


def test_missing_supplier_cost_is_unknown_not_perfect():
    """target_retail == 0 would otherwise score every market a flat 1.0."""
    assert _price_score([5000] * 10, target=0) == 0.5


def test_too_few_prices_is_unknown():
    assert _price_score([5000, 5100], target=_TARGET_CENTS) == 0.5
