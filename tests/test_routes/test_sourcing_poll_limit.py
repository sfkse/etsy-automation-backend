"""GET /sourcing/{id} must return every scored keyword, not just the top 5.

The response was hard-capped at `scores[:5]`. On the REX-936 analysis that
discarded 6 of 11 scored keywords — including all three birthstone keywords, at
ranks 7, 10 and 11, for a product whose defining feature is its birthstone. The
cap read as a display detail but was the main reason the product's own
differentiating keywords never reached the user.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.dependencies import get_session
from src.db.models import KeywordScore, SourcingAnalysis
from src.web.routes import sourcing as sourcing_routes


def _analysis(n_scores: int) -> SourcingAnalysis:
    analysis = SourcingAnalysis(id=1, status="completed")
    analysis.candidates = []
    analysis.scores = [
        KeywordScore(
            id=i,
            analysis_id=1,
            keyword=f"keyword {i}",
            opportunity_score=0.5,
            rank_in_recommendation=i,
        )
        for i in range(1, n_scores + 1)
    ]
    return analysis


@pytest.fixture
def client():
    analysis = _analysis(11)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = analysis

    app = FastAPI()
    app.include_router(sourcing_routes.router)
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c


def test_all_scored_keywords_are_returned(client):
    body = client.get("/sourcing/1").json()
    assert len(body["recommended_keywords"]) == 11


def test_results_stay_in_rank_order(client):
    body = client.get("/sourcing/1").json()
    ranks = [k["rank"] for k in body["recommended_keywords"]]
    assert ranks == sorted(ranks)


def test_limit_truncates_explicitly(client):
    body = client.get("/sourcing/1", params={"limit": 3}).json()
    assert [k["keyword"] for k in body["recommended_keywords"]] == [
        "keyword 1",
        "keyword 2",
        "keyword 3",
    ]


def test_nonpositive_limit_is_ignored(client):
    body = client.get("/sourcing/1", params={"limit": 0}).json()
    assert len(body["recommended_keywords"]) == 11
