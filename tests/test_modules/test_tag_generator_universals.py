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


# ── Tag count floor (regression) ──────────────────────────────────────────────
# normalize_tags drops tags that duplicate the paired title. Backfill originally
# drew only from the pillar keyword pool — which is empty for every pillar in a
# stock DB — so the drops were never replaced and listings shipped with 10 tags.
# Etsy gives 13 slots and the guide treats all 13 as mandatory, so the count must
# never fall short regardless of how bare the pool is.

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.config.business_rules import TAG_COUNT
from src.modules.content.tag_generator import TagGenerator
from src.modules.llm.angles import ANGLE_CONSERVATIVE

_FLOOR_TITLE = (
    "Birthstone Ankh Pendant Necklace, Sterling Silver Egyptian Cross Chain "
    "Necklace, Key of Life Jewelry Gift for Women"
)
# Three of these appear verbatim in the title above.
_FLOOR_TAGS = [
    "gift for her", "birthstone ankh", "minimalist necklace", "handmade gift",
    "dainty necklace", "personalized", "necklace for woman", "birthday gift",
    "pendant necklace", "layering necklace", "protection jewelry",
    "religious jewelry", "key of life",
]


def _floor_generator(pool_candidates, universals):
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=", ".join(_FLOOR_TAGS))
    pool = MagicMock()
    pool.get_candidates.return_value = pool_candidates
    pool.get_universal_keywords.return_value = universals
    research = MagicMock()
    ctx = MagicMock()
    ctx.has_data = False
    research.build_for_product.return_value = ctx
    return TagGenerator(llm, pool, research)


def _floor_product():
    product = MagicMock()
    product.carrier_pillar = "birthstone"
    product.shape = None
    return product


def _run_floor(pool_candidates, universals):
    gen = _floor_generator(pool_candidates, universals)
    return asyncio.run(
        gen.generate_for_angle(_floor_product(), ANGLE_CONSERVATIVE, _FLOOR_TITLE)
    )


def test_empty_pool_still_yields_13_tags():
    assert len(_run_floor([], [])) == TAG_COUNT


def test_universals_are_used_when_pillar_pool_is_empty():
    tags = _run_floor([], ["Handmade Charm", "Gift Idea Box", "Boho Amulet"])
    assert len(tags) == TAG_COUNT
    assert "Handmade Charm" in tags


def test_pillar_pool_replaces_the_dropped_tags():
    tags = _run_floor(["Egyptian Talisman", "Ra Symbol Charm", "Ancient Amulet"], [])
    assert len(tags) == TAG_COUNT
    assert "Egyptian Talisman" in tags
    # Genuinely replaced, not merely restored.
    assert "Birthstone Ankh" not in tags


def test_dropped_tags_are_restored_only_as_a_last_resort():
    tags = _run_floor([], [])
    assert len(tags) == TAG_COUNT
    # With nothing to replace them, the title-duplicates come back rather than
    # leaving slots empty.
    restored = {t.lower() for t in tags} & {"birthstone ankh", "pendant necklace", "key of life"}
    assert restored


def test_no_duplicates_after_backfill():
    tags = _run_floor(["Egyptian Talisman"], ["Handmade Charm"])
    lowered = [t.lower() for t in tags]
    assert len(lowered) == len(set(lowered))
