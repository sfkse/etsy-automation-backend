"""
Universal-keyword injection for tag generation.

The 9 Christmas-2 SEO staples must always appear in the candidate list handed to
the LLM, marked with a [universal] suffix, regardless of the candidate path
(volume-bucket vs fallback) — but they remain candidates, never forced picks.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.modules.content.tag_generator import TagGenerator

UNIVERSALS = [
    "Custom", "Personalized", "Gold", "14K Gold", "14K Gold Plated",
    "925 Silver", "Sterling Silver", "Dainty", "Minimalist",
]


def _generator() -> TagGenerator:
    pool = MagicMock()
    pool.get_universal_keywords.return_value = list(UNIVERSALS)
    return TagGenerator(
        llm_client=MagicMock(),
        keyword_pool=pool,
        research_builder=MagicMock(),
    )


def test_prepend_universals_adds_all_nine_marked():
    gen = _generator()
    existing = [{"tag": "cross necklace", "volume": None, "bucket": "pool"}]
    result = gen._prepend_universals(existing)

    universal_tags = [c["tag"] for c in result if c["bucket"] == "universal"]
    assert universal_tags == UNIVERSALS
    # the pre-existing candidate is preserved after the universals
    assert result[-1]["tag"] == "cross necklace"


def test_prepend_universals_dedupes_existing_marks_universal():
    gen = _generator()
    # "Gold" already present as a plain pool candidate — must not duplicate
    existing = [{"tag": "gold", "volume": None, "bucket": "pool"}]
    result = gen._prepend_universals(existing)

    gold_entries = [c for c in result if c["tag"].lower() == "gold"]
    assert len(gold_entries) == 1
    assert gold_entries[0]["bucket"] == "universal"


def test_format_candidates_renders_universal_suffix():
    gen = _generator()
    formatted = gen._format_candidates(gen._prepend_universals([]))
    for kw in UNIVERSALS:
        assert f"- {kw} [universal]" in formatted


def test_no_universals_seeded_leaves_candidates_untouched():
    gen = _generator()
    gen.pool.get_universal_keywords.return_value = []
    existing = [{"tag": "cross necklace", "volume": None, "bucket": "pool"}]
    assert gen._prepend_universals(existing) == existing
