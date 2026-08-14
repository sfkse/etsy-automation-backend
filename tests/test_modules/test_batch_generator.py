"""
Tests for BatchTitleTagGenerator — the single-call title+tag generator for all
3 variants. Fixtures below were validated against the real validate_title /
validate_tags rules so the "happy path" genuinely passes validation.

asyncio_mode = "auto" (see pyproject.toml) → async tests need no decorator.
"""
from __future__ import annotations

import json
from copy import copy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.modules.content.batch_generator import (
    BatchGenerationError,
    BatchTitleTagGenerator,
)
from src.modules.llm.angles import (
    ANGLE_CONSERVATIVE,
    ANGLE_DIFFERENTIATED,
    ANGLE_GIFT_FOCUSED,
)

# ── Valid fixtures (verified against validators) ──────────────────────────────

TITLE_A = "Dainty Cross Necklace for Women, Minimalist Gold Pendant Necklace, Layering Chain Jewelry, Religious Faith Charm Accessory"
TITLE_B = "Sideways Cross Choker Necklace, Tiny Silver Faith Charm Chain, Everyday Layering Pendant Necklace, Baptism Confirmation Keepsake"
TITLE_C = "Cross Necklace Present for Mom, Christian Faith Pendant Necklace, Birthday Idea Chain Jewelry for Daughter Her Grandma Wife Sister"

TAGS_A = [
    "cross pendant", "faith jewelry", "dainty necklace", "religious gift",
    "christian charm", "gold necklace", "layered chain", "minimalist gift",
    "gift for her", "baptism gift", "confirmation gift", "tiny cross",
    "everyday jewelry",
]
# Distinct from A and C — used for the clean happy path (no overlap warning).
TAGS_B = [
    "sideways cross", "silver charm", "choker necklace", "baptism keepsake",
    "tiny pendant", "faith symbol", "communion gift", "delicate chain",
    "boho jewelry", "unisex necklace", "spiritual gift", "modern cross",
    "everyday charm",
]
TAGS_C = [
    "gift for mom", "gift for her", "birthday present", "gift for daughter",
    "christian gift", "faith necklace", "cross jewelry", "present for wife",
    "grandma gift", "sister gift", "religious charm", "holiday gift",
    "stocking stuffer",
]
# Deliberately ~69% overlap with TAGS_A (valid tags, but too similar) —
# used only for the soft cross-variant-overlap warning test.
TAGS_B_OVERLAP = [
    "sideways cross", "silver faith", "baptism keepsake", "confirmation gift",
    "christian charm", "layered chain", "dainty necklace", "choker necklace",
    "faith jewelry", "religious gift", "tiny cross", "everyday jewelry",
    "minimalist gift",
]


def _angles():
    """Three real angles, copied and lettered A/B/C like the orchestrator does."""
    base = [copy(ANGLE_CONSERVATIVE), copy(ANGLE_DIFFERENTIATED), copy(ANGLE_GIFT_FOCUSED)]
    for letter, angle in zip(("A", "B", "C"), base):
        angle.variant_letter = letter
    return base


def _product():
    product = MagicMock()
    product.target_keyword = "cross necklace"
    product.sku = "TEST-001"
    return product


def _generator(response: str) -> BatchTitleTagGenerator:
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=response)

    research_ctx = MagicMock()
    research_ctx.has_data = False
    research = MagicMock()
    research.build_for_product.return_value = research_ctx

    return BatchTitleTagGenerator(llm_client=llm, research_builder=research)


def _payload(tags_b=TAGS_B) -> str:
    return json.dumps({
        "variant_a": {"title": TITLE_A, "tags": TAGS_A},
        "variant_b": {"title": TITLE_B, "tags": tags_b},
        "variant_c": {"title": TITLE_C, "tags": TAGS_C},
    })


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_success_returns_three_variants():
    gen = _generator(_payload())
    result = await gen.generate_all(_product(), _angles())

    assert set(result.keys()) == {"A", "B", "C"}
    assert result["A"]["title"] == TITLE_A
    assert result["B"]["tags"] == TAGS_B
    assert all(len(result[k]["tags"]) == 13 for k in ("A", "B", "C"))


async def test_strips_markdown_fence():
    gen = _generator("```json\n" + _payload() + "\n```")
    result = await gen.generate_all(_product(), _angles())
    assert result["C"]["title"] == TITLE_C


async def test_malformed_json_raises():
    gen = _generator("not json {")
    with pytest.raises(BatchGenerationError):
        await gen.generate_all(_product(), _angles())


async def test_one_variant_fails_validation_raises():
    # Variant B ships only 12 tags → validate_tags fails → whole batch rejected.
    bad = json.dumps({
        "variant_a": {"title": TITLE_A, "tags": TAGS_A},
        "variant_b": {"title": TITLE_B, "tags": TAGS_B[:12]},
        "variant_c": {"title": TITLE_C, "tags": TAGS_C},
    })
    gen = _generator(bad)
    with pytest.raises(BatchGenerationError):
        await gen.generate_all(_product(), _angles())


async def test_missing_variant_key_raises():
    incomplete = json.dumps({
        "variant_a": {"title": TITLE_A, "tags": TAGS_A},
        "variant_b": {"title": TITLE_B, "tags": TAGS_B},
        # variant_c missing
    })
    gen = _generator(incomplete)
    with pytest.raises(BatchGenerationError):
        await gen.generate_all(_product(), _angles())


async def test_high_tag_overlap_warns_but_returns():
    # A and B share ~69% of tags — all valid, so it must still return, only warn.
    # structlog writes to stdout (not the stdlib `caplog`), so patch the module
    # logger to observe the warning deterministically.
    gen = _generator(_payload(tags_b=TAGS_B_OVERLAP))
    with patch("src.modules.content.batch_generator._log") as mock_log:
        result = await gen.generate_all(_product(), _angles())

    assert set(result.keys()) == {"A", "B", "C"}
    warned = [c.args[0] for c in mock_log.warning.call_args_list]
    assert "batch_variant_high_overlap" in warned
