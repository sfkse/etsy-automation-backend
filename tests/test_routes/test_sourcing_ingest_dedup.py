"""Tests for the per-keyword dedup in POST /sourcing/{id}/ingest-and-score.

`competitor_listings.listing_id` used to be UNIQUE while `keyword_searched` was
a scalar on the same row, so the table could not represent one Etsy listing
ranking for two keywords. The ingest deduped on `filter_by(listing_id=...)`
unscoped — across every analysis and all history — and skipped the card without
recording the new keyword.

The first keyword to see a listing therefore owned it permanently. Any later
keyword whose Etsy results overlapped an already-scraped one retained almost
nothing, fell under `OpportunityScorer.MIN_LISTINGS_TO_SCORE` in `_fetch_top20`,
and was dropped as `scorer_skip_insufficient_data` — which hits specific
long-tail keywords hardest, since their results overlap the generic terms
already in the table.

JSONB rules out a real SQLite session (see tests/test_db/), so the store below
models just enough of the composite-key semantics to exercise the decision.

Mounts only the sourcing router on a bare FastAPI app — same pattern as
``test_sourcing_inputs.py``.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.dependencies import get_session
from src.db.models import CompetitorListing, SourcingAnalysis
from src.web.routes import sourcing as sourcing_routes


class _Query:
    """Attribute-matching stand-in for a SQLAlchemy query over one model."""

    def __init__(self, rows):
        self._rows = rows

    def filter_by(self, **criteria):
        return _Query(
            [
                r
                for r in self._rows
                if all(getattr(r, k, None) == v for k, v in criteria.items())
            ]
        )

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _Store:
    """Minimal session: routes queries by model, records adds."""

    def __init__(self, analysis: SourcingAnalysis):
        self.analysis = analysis
        self.listings: list[CompetitorListing] = []

    def query(self, model):
        if model is SourcingAnalysis:
            return _Query([self.analysis])
        if model is CompetitorListing:
            return _Query(self.listings)
        return _Query([])

    def add(self, obj):
        if isinstance(obj, CompetitorListing):
            self.listings.append(obj)

    def commit(self):
        pass

    def for_keyword(self, keyword: str) -> list[CompetitorListing]:
        """What `OpportunityScorer._fetch_top20(keyword)` would see."""
        return [l for l in self.listings if l.keyword_searched == keyword]


@pytest.fixture
def store():
    return _Store(SourcingAnalysis(id=1))


@pytest.fixture
def client(store):
    app = FastAPI()
    app.include_router(sourcing_routes.router)
    app.dependency_overrides[get_session] = lambda: store
    with TestClient(app) as c:
        yield c


def _cards(keyword: str, listing_ids: list[str]) -> list[dict]:
    return [
        {
            "listing_id": lid,
            "keyword": keyword,
            "rank": i + 1,
            "title": f"Listing {lid}",
            "price_cents": 6900,
            "shop_id": f"shop-{lid}",
        }
        for i, lid in enumerate(listing_ids)
    ]


def _ingest(client, keyword: str, listing_ids: list[str]):
    # The background task is Layer B+C; these tests are about what got stored.
    with patch.object(sourcing_routes, "_run_layer_b_and_c"):
        resp = client.post(
            "/sourcing/1/ingest-and-score",
            json={"cards": _cards(keyword, listing_ids)},
        )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_overlapping_keywords_each_keep_their_own_top20(client, store):
    """The regression: two keywords returning the SAME 20 listings.

    Under the old listing_id-only dedup the second keyword stored 0 rows and was
    dropped from scoring entirely.
    """
    listing_ids = [str(1000 + i) for i in range(20)]

    _ingest(client, "gold cross pendant", listing_ids)
    _ingest(client, "birthstone cross necklace", listing_ids)

    assert len(store.for_keyword("gold cross pendant")) == 20
    assert len(store.for_keyword("birthstone cross necklace")) == 20

    # Same images, two keywords — 40 rows over 20 distinct listings.
    assert len(store.listings) == 40
    assert len({l.listing_id for l in store.listings}) == 20


def test_second_keyword_clears_the_scoring_floor(client, store):
    """A fully-overlapping niche keyword must still be scoreable."""
    from src.sourcing.opportunity_scorer import OpportunityScorer

    listing_ids = [str(2000 + i) for i in range(20)]
    _ingest(client, "dainty religious jewelry", listing_ids)
    _ingest(client, "personalized birthstone cross", listing_ids)

    found = len(store.for_keyword("personalized birthstone cross"))
    assert found >= OpportunityScorer.MIN_LISTINGS_TO_SCORE


def test_same_listing_and_keyword_is_not_duplicated(client, store):
    """Re-ingesting the same batch must not create a second row per pair."""
    listing_ids = ["3001", "3002", "3003"]

    first = _ingest(client, "layering cross necklace", listing_ids)
    second = _ingest(client, "layering cross necklace", listing_ids)

    assert first["cards_ingested"] == 3
    assert second["cards_ingested"] == 0
    assert len(store.listings) == 3


def test_duplicate_pair_within_one_batch_is_collapsed(client, store):
    """Etsy can surface the same listing twice in one result page."""
    with patch.object(sourcing_routes, "_run_layer_b_and_c"):
        resp = client.post(
            "/sourcing/1/ingest-and-score",
            json={"cards": _cards("cross necklace", ["4001", "4001", "4002"])},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["cards_ingested"] == 2
    assert len(store.listings) == 2


def test_card_without_a_keyword_is_skipped(client, store):
    """A keyword-less row is unreachable by _fetch_top20, so it is not stored."""
    with patch.object(sourcing_routes, "_run_layer_b_and_c"):
        resp = client.post(
            "/sourcing/1/ingest-and-score",
            json={
                "cards": [
                    {"listing_id": "5001", "keyword": "", "rank": 1},
                    {"listing_id": "5002", "rank": 2},
                    {"listing_id": "5003", "keyword": "cross necklace", "rank": 3},
                ]
            },
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["cards_ingested"] == 1
    assert [l.listing_id for l in store.listings] == ["5003"]


def test_keyword_is_stored_trimmed_to_match_the_dedup_key(client, store):
    """Stray whitespace must not create a keyword no later lookup can match."""
    with patch.object(sourcing_routes, "_run_layer_b_and_c"):
        client.post(
            "/sourcing/1/ingest-and-score",
            json={"cards": [{"listing_id": "6001", "keyword": "  cross necklace  "}]},
        )

    assert store.listings[0].keyword_searched == "cross necklace"
    assert len(store.for_keyword("cross necklace")) == 1
