"""
Phase 4 — Opportunity Scorer (Layer B)

Computes 5 sub-scores and an aggregate opportunity_score for each keyword
candidate, based on the top-20 competitor listings already in the DB.

Sub-scores (all 0.0–1.0):
  new_shop_share   – fraction of top-20 with shop_age < 2yr  (weight 0.30)
  price_alignment  – Rexven cost × 4 fits the top-20 price band (weight 0.25)
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

    # Rexven-to-retail multiplier (Etsy price ÷ Rexven cost).
    # Use 4.0 as conservative baseline (Etsy fees + ads eat margin).
    RETAIL_MULTIPLIER = 4.0

    def __init__(self, session: Session):
        self.session = session

    def score_analysis(self, analysis: SourcingAnalysis) -> list[KeywordScore]:
        """
        Compute scores for all candidates of an analysis. Persists results.
        Returns ranked list of KeywordScore rows (rank 1 = best opportunity).
        """
        analysis.status = SourcingStatus.LAYER_B_RUNNING.value
        self.session.commit()

        rexven_cost = (
            analysis.rexven_premium_cost_usd_cents
            or analysis.rexven_cost_usd_cents
            or 0
        )
        target_retail_cents = int(rexven_cost * self.RETAIL_MULTIPLIER)

        scores: list[KeywordScore] = []
        for candidate in analysis.candidates:
            top20 = self._fetch_top20(candidate.keyword)
            if len(top20) < 5:
                _log.info(
                    "scorer_skip_insufficient_data",
                    keyword=candidate.keyword,
                    count=len(top20),
                )
                continue

            score_row = self._score_single(analysis, candidate, top20, target_retail_cents)
            scores.append(score_row)

        scores.sort(key=lambda s: (s.opportunity_score or 0), reverse=True)
        for i, score in enumerate(scores, start=1):
            score.rank_in_recommendation = i

        self.session.add_all(scores)
        analysis.layer_b_completed = True
        self.session.commit()

        _log.info(
            "opportunity_scorer_complete",
            analysis_id=analysis.id,
            scored=len(scores),
        )
        return scores

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
    ) -> KeywordScore:
        n = len(top20)

        # Sub-score 1: new shop share
        new_shops = sum(1 for l in top20 if (l.shop_age_years or 99) < 2)
        score_new_shop_share = new_shops / n

        # Sub-score 2: price alignment
        prices = [l.price_cents for l in top20 if l.price_cents and l.price_cents > 0]
        if len(prices) >= 5:
            p25 = statistics.quantiles(prices, n=4)[0]
            p75 = statistics.quantiles(prices, n=4)[2]
            if p25 <= target_retail_cents <= p75:
                score_price_alignment = 1.0
            else:
                median_price = statistics.median(prices)
                if median_price > 0:
                    distance = abs(target_retail_cents - median_price) / median_price
                    score_price_alignment = max(0.0, 1.0 - min(distance, 1.0))
                else:
                    score_price_alignment = 0.5
        else:
            score_price_alignment = 0.5  # insufficient data

        # Sub-score 3: market activity
        with_sales = sum(1 for l in top20 if (l.eh_sales_recent or 0) >= 1)
        score_activity = with_sales / n

        # Sub-score 4: competition (inverted log of total search results)
        total_results = (
            next((l.keyword_total_results for l in top20 if l.keyword_total_results), None)
            or 1
        )
        log_results = math.log10(max(total_results, 1))
        score_competition = max(0.0, 1.0 - log_results / 6.0)  # [0,6] → [1.0,0.0]

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
