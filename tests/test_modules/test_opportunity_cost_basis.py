"""
Tests for OpportunityScorer's supplier cost basis.

The scorer derives a target retail price (cost x 4) and grades each keyword's
top-20 price band against it — `price_alignment`, 25% of the opportunity score.
That basis must match what ListingBuilder actually prices off, which is the
LANDED cost (product + shipping, `orchestrator.py`). It previously used the
product price alone, so the scorer validated a price that never went live.

The gap is not a rounding error: shipping is near-flat (~$7.42) while product
cost varies several-fold, so it is worst exactly where the catalogue is densest.
"""
from src.db.models import SourcingAnalysis
from src.sourcing.opportunity_scorer import OpportunityScorer


def _analysis(**kwargs) -> SourcingAnalysis:
    return SourcingAnalysis(**kwargs)


def test_landed_cost_is_the_basis():
    """REX-271: $15.40 premium + $7.42 shipping = $22.82 landed."""
    row = _analysis(
        rexven_premium_cost_usd_cents=1540,
        rexven_cost_usd_cents=1722,
        rexven_shipping_cents=742,
    )
    assert OpportunityScorer._cost_basis_cents(row) == 2282


def test_silver_target_retail_matches_the_builder():
    """Scorer and builder must agree: 4 x landed = $91.28, not 4 x $15.40."""
    row = _analysis(
        rexven_premium_cost_usd_cents=1540, rexven_shipping_cents=742
    )
    target = OpportunityScorer._cost_basis_cents(row) * OpportunityScorer.RETAIL_MULTIPLIER
    assert int(target) == 9128


def test_brass_is_where_the_old_basis_was_worst():
    """REX-922: $6.60 product, $7.42 shipping — shipping EXCEEDS the product.

    Old basis gave $26.40, actual listing price $56.08: a 112% understatement.
    """
    row = _analysis(rexven_premium_cost_usd_cents=660, rexven_shipping_cents=742)

    old_basis = 660 * OpportunityScorer.RETAIL_MULTIPLIER
    new_basis = OpportunityScorer._cost_basis_cents(row) * OpportunityScorer.RETAIL_MULTIPLIER

    assert int(old_basis) == 2640
    assert int(new_basis) == 5608
    assert new_basis > old_basis * 2


def test_rows_without_shipping_keep_the_old_behaviour():
    """Analyses captured before the migration must not shift under a re-score.

    Their shipping is NULL, so they stay self-consistent with the score they
    were originally given rather than silently moving.
    """
    row = _analysis(rexven_premium_cost_usd_cents=1540, rexven_shipping_cents=None)
    assert OpportunityScorer._cost_basis_cents(row) == 1540


def test_falls_back_to_base_tier_when_premium_absent():
    row = _analysis(
        rexven_premium_cost_usd_cents=None,
        rexven_cost_usd_cents=1722,
        rexven_shipping_cents=830,
    )
    assert OpportunityScorer._cost_basis_cents(row) == 2552


def test_no_cost_at_all_is_zero_not_an_error():
    """A missing cost is handled downstream as 'unknown, not bad'."""
    assert OpportunityScorer._cost_basis_cents(_analysis()) == 0
