"""Tests for the per-build deep-dive wait budget.

Competitor deep-dives run serially in the extension — Phase 2 owns one queue and
one scrape window — so in a multi-keyword batch the Nth keyword's dive only
starts once N-1 have finished. Each build waits for its *own* keyword's dive, so
a flat budget would expire on every build past the first before its dive had even
begun, and it would generate content with no competitor tag pool.

The extension sizes `deepdive_wait_s` by queue position; the backend clamps it.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from src.modules.listings import orchestrator
from src.modules.listings.orchestrator import (
    _DEEPDIVE_WAIT_CAP_S,
    _DEEPDIVE_WAIT_DEFAULT_S,
    ListingBuildRequest,
    _await_deepdive_grounding,
)


def _req(**kw) -> ListingBuildRequest:
    base = dict(rexven_sku="REX-936", carrier_pillar="cross")
    base.update(kw)
    return ListingBuildRequest(**base)


def test_wait_budget_defaults_to_none_on_the_request():
    """Absent means "use the backend default", not zero."""
    assert _req().deepdive_wait_s is None


def test_request_carries_a_position_sized_budget():
    assert _req(deepdive_wait_s=1800).deepdive_wait_s == 1800


@pytest.mark.parametrize(
    "supplied,expected",
    [
        (None, _DEEPDIVE_WAIT_DEFAULT_S),          # single dive — unchanged
        (1200, 1200),                              # 2nd in queue
        (3000, 3000),                              # 5th in queue
        (_DEEPDIVE_WAIT_CAP_S + 6000, _DEEPDIVE_WAIT_CAP_S),  # clamped
    ],
)
def test_effective_budget_is_clamped(supplied, expected):
    """Mirrors the expression in run_listing_content_pipeline."""
    effective = min(supplied or _DEEPDIVE_WAIT_DEFAULT_S, _DEEPDIVE_WAIT_CAP_S)
    assert effective == expected


def test_cap_covers_a_realistic_batch():
    """Six keywords at ~8 min a dive must fit under the cap, or the last build
    would give up before its dive ran."""
    assert 6 * 600 <= _DEEPDIVE_WAIT_CAP_S


def test_unknown_score_returns_immediately(monkeypatch):
    """No KeywordScore → nothing to wait for; must not burn the budget."""

    class _Session:
        def query(self, *_a, **_kw):
            return self

        def filter_by(self, **_kw):
            return self

        def first(self):
            return None

    started = time.monotonic()
    asyncio.run(_await_deepdive_grounding(_Session(), 999, timeout_s=3600))
    assert time.monotonic() - started < 1.0


def test_wait_is_bounded_by_its_budget(monkeypatch):
    """On timeout the build proceeds with existing grounding rather than hanging."""
    score = type("S", (), {"keyword": "gold cross birthstone necklace"})()

    class _Session:
        def query(self, model):
            self._model = model
            return self

        def filter_by(self, **_kw):
            return self

        def first(self):
            # KeywordScore lookup resolves; KeywordResearch never refreshes.
            return score if getattr(self._model, "__name__", "") == "KeywordScore" else None

        def rollback(self):
            pass

    slept: list[float] = []

    async def _fake_sleep(s):
        slept.append(s)
        # Advance fast; the real loop would wait poll_interval_s each turn.
        if len(slept) > 10:
            raise TimeoutError("loop did not terminate")

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    # timeout_s=0 means the deadline is already past — one pass, then give up.
    asyncio.run(_await_deepdive_grounding(_Session(), 1, timeout_s=0))
    assert slept == []
