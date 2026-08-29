"""
Phase 4 — Opportunity Scorer (Layer B)

Computes 5 sub-scores and an aggregate opportunity_score for each keyword
candidate, based on the top-20 competitor listings already in the DB.

Sub-scores (all 0.0–1.0):
  new_shop_share   – fraction of top-20 with shop_age < 2yr  (weight 0.30)
  price_alignment  – where the top-20 median price sits between break-even and
                     landed cost × RETAIL_MULTIPLIER          (weight 0.25)
  activity         – share of top-20 with eh_sales_recent ≥ 1  (weight 0.25)
  competition      – inverted log of keyword_total_results      (weight 0.10)
  diversity        – anti-dominance: 1 - max single-shop share  (weight 0.10)
"""
from __future__ import annotations

import math
import statistics
from collections import Counter
from datetime import datetime

import structlog
from sqlalchemy.orm import Session

from src.db.models import (
    CompetitorListing,
    KeywordCandidate,
    KeywordScore,
    KeywordTier,
    SourcingAnalysis,
    SourcingStatus,
)

_log = structlog.get_logger(__name__)


class OpportunityScorer:
    """Layer B — score keyword candidates against empirical top-20 market data."""

    WEIGHTS = {
        "new_shop_share": 0.30,
        "price_alignment": 0.25,
        "activity": 0.25,
        "competition": 0.10,
        "diversity": 0.10,
    }

    # Rexven-to-retail multiplier (Etsy price ÷ Rexven landed cost) we aim for.
    # 4.0 is a conservative target, not a hard requirement — Etsy fees + ads eat
    # margin, but a market pricing below it is squeezed, not unsellable.
    RETAIL_MULTIPLIER = 4.0

    # Below this multiple of landed cost, Etsy's cut (transaction + payment +
    # listing + ads, ~15-20% of revenue) leaves nothing worth having. This is the
    # zero point of `price_alignment`; RETAIL_MULTIPLIER is where it saturates.
    BREAKEVEN_MULTIPLIER = 1.5

    def __init__(self, session: Session):
        self.session = session
        # Populated by score_analysis: candidates that had too little competitor
        # data to score. Also persisted to analysis.unscored_candidates.
        self.skipped_candidates: list[dict] = []

    @staticmethod
    def _cost_basis_cents(analysis: SourcingAnalysis) -> int:
        """The supplier cost this keyword's target retail price is derived from.

        Must agree with what ListingBuilder actually prices off
        (`orchestrator.py` — landed cost, i.e. product + shipping), or the
        scorer validates a price that never goes live. Shipping is near-flat
        while product cost varies several-fold, so ignoring it understated the
        target by +48% on a $15.40 silver item and +112% on a $6.60 brass one.

        The premium tier is preferred because that is the tier the extension
        picks in `pickRexvenPrices`, and the two must use the same basis.

        Rows captured before `rexven_shipping_cents` existed have it NULL and
        keep the old product-only behaviour, so historical scores stay
        self-consistent instead of shifting under a re-score.
        """
        product = (
            analysis.rexven_premium_cost_usd_cents
            or analysis.rexven_cost_usd_cents
            or 0
        )
        return product + (analysis.rexven_shipping_cents or 0)

    # Minimum competitor listings before a keyword can be scored. Below this the
    # sub-scores are quantized too coarsely to mean anything (one listing moves
    # `activity` by 20+ points).
    MIN_LISTINGS_TO_SCORE = 5

    def score_analysis(self, analysis: SourcingAnalysis) -> list[KeywordScore]:
        """
        Compute scores for all candidates of an analysis. Persists results.
        Returns ranked list of KeywordScore rows (rank 1 = best opportunity).

        Candidates that could not be scored are recorded on
        ``self.skipped_candidates`` rather than only logged — a keyword dropped
        for want of competitor data is a keyword the user should be offered a
        "Run Phase 1" button for, not one that silently disappears from the
        recommendations.
        """
        analysis.status = SourcingStatus.LAYER_B_RUNNING.value
        self.session.commit()

        target_retail_cents = int(
            self._cost_basis_cents(analysis) * self.RETAIL_MULTIPLIER
        )

        # Scoring an analysis is idempotent: a keyword already scored for it is
        # refreshed, not duplicated. Reachable in normal use — every
        # /ingest-and-score post queues Layer B again, so a follow-up Phase 1 run
        # for a single keyword used to re-score the whole analysis and leave two
        # rows per keyword.
        existing_by_keyword = {s.keyword: s for s in analysis.scores}

        scores: list[KeywordScore] = []
        skipped: list[dict] = []
        for candidate in analysis.candidates:
            # Broad-tier keywords are "competition giants — context only" (Layer A).
            # They score well on market structure but are the wrong target for a
            # specific product, so they're excluded from the recommendation ranking.
            if candidate.tier == KeywordTier.BROAD.value:
                _log.info("scorer_skip_broad_tier", keyword=candidate.keyword)
                # Deliberately excluded, not missing data — kept out of the
                # skipped list so the UI doesn't invite a pointless Phase 1 run.
                continue

            top20 = self._fetch_top20(candidate.keyword)
            if len(top20) < self.MIN_LISTINGS_TO_SCORE:
                _log.info(
                    "scorer_skip_insufficient_data",
                    keyword=candidate.keyword,
                    count=len(top20),
                )
                skipped.append(
                    {
                        "keyword": candidate.keyword,
                        "tier": candidate.tier,
                        "reason": "insufficient_data",
                        "listings_found": len(top20),
                        "listings_required": self.MIN_LISTINGS_TO_SCORE,
                    }
                )
                continue

            score_row = self._score_single(
                analysis,
                candidate,
                top20,
                target_retail_cents,
                existing_by_keyword.get(candidate.keyword),
            )
            scores.append(score_row)

        scores.sort(key=lambda s: (s.opportunity_score or 0), reverse=True)
        for i, score in enumerate(scores, start=1):
            score.rank_in_recommendation = i

        self.session.add_all(scores)
        analysis.layer_b_completed = True
        analysis.unscored_candidates = skipped or None
        self.session.commit()

        self.skipped_candidates = skipped
        _log.info(
            "opportunity_scorer_complete",
            analysis_id=analysis.id,
            scored=len(scores),
            skipped=len(skipped),
        )
        return scores

    # Tier-B activity threshold: a bestseller badge alone (25) or a
    # popular-now + star-seller combo (25) clears it; weak signals don't.
    ACTIVITY_SIGNAL_THRESHOLD = 20.0

    @classmethod
    def _is_active(cls, listing: CompetitorListing) -> bool:
        """True when a listing shows evidence of recent sales.

        Tier A (EHunt present): recent sales >= 1 — identical to the original
        behavior. Tier B (no EHunt): the listing's persisted sales_signal_score
        (computed at ingest from on-page proxies) must clear the threshold;
        computed on the fly for legacy rows ingested before scoring-at-ingest.
        """
        if listing.eh_sales_recent is not None or listing.eh_sales_total is not None:
            return (listing.eh_sales_recent or 0) >= 1

        signal = listing.sales_signal_score
        if signal is None:
            from src.modules.research.scoring import compute_sales_signal_score

            signal = compute_sales_signal_score(listing)
        return signal >= cls.ACTIVITY_SIGNAL_THRESHOLD

    def _fetch_top20(self, keyword: str) -> list[CompetitorListing]:
        return (
            self.session.query(CompetitorListing)
            .filter(CompetitorListing.keyword_searched == keyword)
            .order_by(CompetitorListing.rank_in_search.asc().nullslast())
            .limit(20)
            .all()
        )

    def _score_single(
        self,
        analysis: SourcingAnalysis,
        candidate: KeywordCandidate,
        top20: list[CompetitorListing],
        target_retail_cents: int,
        existing: "KeywordScore | None" = None,
    ) -> KeywordScore:
        n = len(top20)

        # Sub-score 1: new shop share
        new_shops = sum(1 for l in top20 if (l.shop_age_years or 99) < 2)
        score_new_shop_share = new_shops / n

        # Sub-score 2: price headroom — how much margin the market's typical
        # price leaves over our landed cost.
        #
        # This was two-sided: full marks when target_retail_cents landed inside
        # the top-20's p25..p75, otherwise a penalty on |target - median|. Both
        # halves were wrong.
        #
        # The band check rewarded *dispersion*, not affordability. Handmade
        # jewelry spreads are enormous (one real keyword ran $27 to $213), so
        # almost any target falls between p25 and p75: on analysis #10, 8 of 11
        # keywords scored a perfect 1.0 while every one of their medians sat
        # 13-47% BELOW the target. The three that were penalised were simply the
        # ones with tight bands. A 25%-weight sub-score was pinned at 1.0 for
        # most keywords and effectively measured price noise.
        #
        # The distance fallback was symmetric, so a market pricing well ABOVE our
        # cost basis — the best possible finding, since the multiplier is a
        # target we want to beat — was marked down exactly like one pricing below
        # it.
        #
        # Now: score where the market's median sits between break-even and the
        # target multiple, saturating at the top. Monotonic in the right
        # direction (richer market = better) and reads as "how far from
        # break-even toward our target does the typical competitor price get us".
        # Median, not mean, so the long tail of outliers that used to game the
        # band can't move it.
        #
        # A missing supplier cost gives target_retail_cents == 0, which would
        # score every market a flat 1.0 here — a confident positive signal drawn
        # from no data at all. Treat it as unknown, same as too few prices.
        prices = [l.price_cents for l in top20 if l.price_cents and l.price_cents > 0]
        if target_retail_cents <= 0:
            score_price_alignment = 0.5  # no supplier cost — unknown, not bad
        elif len(prices) >= 5:
            median_price = statistics.median(prices)
            # target is landed x RETAIL_MULTIPLIER, so scaling it by the ratio of
            # the multipliers recovers landed x BREAKEVEN_MULTIPLIER without
            # needing the cost basis passed down again.
            breakeven_cents = target_retail_cents * (
                self.BREAKEVEN_MULTIPLIER / self.RETAIL_MULTIPLIER
            )
            span = target_retail_cents - breakeven_cents
            if span > 0:
                score_price_alignment = max(
                    0.0, min(1.0, (median_price - breakeven_cents) / span)
                )
            else:
                score_price_alignment = 0.5
        else:
            score_price_alignment = 0.5  # insufficient data

        # Sub-score 3: market activity.
        # EHunt data (Tier A) is ground truth; when a listing has no EHunt
        # numbers we fall back to its sales_signal_score, whose Tier-B branch
        # scores on-page proxies (badges, views, cart, reviews). Without this
        # fallback, a missing EHunt install silently zeroed out 25% of the
        # opportunity score for every keyword.
        with_sales = sum(1 for l in top20 if self._is_active(l))
        score_activity = with_sales / n

        # Sub-score 4: competition (inverted log of total search results).
        # When NO listing carries the total-results count, competition is unknown
        # — treat it as neutral (0.5) rather than defaulting to 1 result, which
        # would score competition = 1.0 (max) and make a data-less keyword look
        # like a zero-competition goldmine.
        total_results = next(
            (l.keyword_total_results for l in top20 if l.keyword_total_results), None
        )
        if total_results:
            log_results = math.log10(max(total_results, 1))
            score_competition = max(0.0, 1.0 - log_results / 6.0)  # [0,6] → [1.0,0.0]
        else:
            score_competition = 0.5  # unknown competition

        # Sub-score 5: diversity (anti-single-shop dominance)
        shop_counts = Counter(l.shop_id for l in top20 if l.shop_id)
        max_share = max(shop_counts.values()) / n if shop_counts else 0.0
        score_diversity = 1.0 - max_share

        opportunity_score = (
            self.WEIGHTS["new_shop_share"] * score_new_shop_share
            + self.WEIGHTS["price_alignment"] * score_price_alignment
            + self.WEIGHTS["activity"] * score_activity
            + self.WEIGHTS["competition"] * score_competition
            + self.WEIGHTS["diversity"] * score_diversity
        )

        avg_price = int(statistics.mean(prices)) if prices else 0
        ages = [l.shop_age_years for l in top20 if l.shop_age_years]
        avg_shop_age = statistics.mean(ages) if ages else 0.0

        # Updated in place when this analysis has been scored before, so a
        # re-score (the "Run Phase 1" → re-ingest → Layer B loop) refreshes the
        # existing row instead of inserting a rival copy of the same keyword.
        # Preserving the id also keeps `Product.selected_keyword_score_id`
        # pointing at a live row.
        if existing is not None:
            existing.score_new_shop_share = round(score_new_shop_share, 4)
            existing.score_price_alignment = round(score_price_alignment, 4)
            existing.score_activity = round(score_activity, 4)
            existing.score_competition = round(score_competition, 4)
            existing.score_diversity = round(score_diversity, 4)
            existing.opportunity_score = round(opportunity_score, 4)
            existing.top20_avg_price_cents = avg_price
            existing.top20_avg_shop_age = round(avg_shop_age, 2)
            existing.top20_keyword_total_results = total_results
            existing.top20_unique_shops = len(shop_counts)
            existing.top20_with_recent_sales = with_sales
            return existing

        return KeywordScore(
            analysis_id=analysis.id,
            candidate_id=candidate.id,
            keyword=candidate.keyword,
            score_new_shop_share=round(score_new_shop_share, 4),
            score_price_alignment=round(score_price_alignment, 4),
            score_activity=round(score_activity, 4),
            score_competition=round(score_competition, 4),
            score_diversity=round(score_diversity, 4),
            opportunity_score=round(opportunity_score, 4),
            top20_avg_price_cents=avg_price,
            top20_avg_shop_age=round(avg_shop_age, 2),
            top20_keyword_total_results=total_results,
            top20_unique_shops=len(shop_counts),
            top20_with_recent_sales=with_sales,
        )
