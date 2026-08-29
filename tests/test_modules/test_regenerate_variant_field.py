"""
Tests for per-field, per-variant content regeneration.

asyncio_mode = "auto" (see pyproject.toml) → async tests need no decorator.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.modules.content.regenerate import (
    RegenerationError,
    regenerate_variant_field,
)
from src.modules.llm.angles import ANGLE_CONSERVATIVE, angle_for_label

TITLE = (
    "Dainty Cross Necklace for Women, Minimalist Gold Pendant Necklace, "
    "Layering Chain Jewelry, Religious Faith Charm Accessory"
)
NEW_TITLE = (
    "Sterling Silver Cross Pendant Necklace, Tiny Faith Charm Chain, "
    "Dainty Religious Jewelry, Everyday Layering Accessory Gift"
)
# Shares no verbatim phrase with TAGS, so a regen to this title should leave the
# existing tag set completely alone.
CLEAN_TITLE = (
    "Ankh Key of Life Pendant Necklace, Egyptian Protection Symbol Chain, "
    "Ancient Talisman Jewelry, Spiritual Everyday Layering Piece"
)
TAGS = [
    "Cross Pendant", "Faith Jewelry", "Dainty Necklace", "Religious Gift",
    "Christian Charm", "Gold Necklace", "Layered Chain", "Minimalist Gift",
    "Gifts for Mom", "Baptism Gift", "Confirmation Gift", "Tiny Cross",
    "Everyday Jewelry",
]


def _variant(**overrides) -> dict:
    variant = {
        "id": "A",
        "strategy_label": ANGLE_CONSERVATIVE.label,
        "strategy_rationale": "…",
        "title": TITLE,
        "tags": list(TAGS),
        "description": "An existing description echoing the old title.",
        "estimated_ctr_signal": "medium",
    }
    variant.update(overrides)
    return variant


def _product() -> MagicMock:
    product = MagicMock()
    product.sku = "TAKI-0001"
    product.carrier_pillar = "cross"
    product.shape = None
    product.target_keyword = "cross necklace"
    return product


def _orchestrator(
    new_title: str = NEW_TITLE,
    new_tags: list[str] | None = None,
    new_description: str = "A freshly written description.",
    pool_candidates: list[str] | None = None,
) -> MagicMock:
    orch = MagicMock()
    orch.title.generate_for_angle = AsyncMock(return_value=new_title)
    orch.tag.generate_for_angle = AsyncMock(return_value=new_tags or list(TAGS))
    orch.tag.pool.get_candidates.return_value = pool_candidates or [
        "Spiritual Charm", "Believer Jewelry", "Devotion Pendant", "Grace Charm",
    ]
    orch.desc.generate_for_angle = AsyncMock(return_value=new_description)
    orch.linker.insert_links = AsyncMock(side_effect=lambda d, p: d + "\n\n[links]")
    orch._estimate_ctr_signal.return_value = "high"
    return orch


# ── Angle recovery ────────────────────────────────────────────────────────────


class TestAngleRecovery:
    def test_label_round_trips_to_its_angle(self) -> None:
        angle = angle_for_label(ANGLE_CONSERVATIVE.label, variant_letter="B")
        assert angle is not None
        assert angle.label == ANGLE_CONSERVATIVE.label
        assert angle.variant_letter == "B"

    def test_lookup_does_not_mutate_the_singleton(self) -> None:
        angle_for_label(ANGLE_CONSERVATIVE.label, variant_letter="C")
        assert ANGLE_CONSERVATIVE.variant_letter == "A"

    def test_unknown_label_returns_none(self) -> None:
        assert angle_for_label("Hybrid (user composed)", "HYBRID") is None

    async def test_hybrid_variant_cannot_be_regenerated(self) -> None:
        variant = _variant(id="HYBRID", strategy_label="Hybrid (user composed)")
        with pytest.raises(RegenerationError, match="no strategic angle"):
            await regenerate_variant_field(
                _product(), variant, "title", _orchestrator()
            )


# ── Field dispatch ────────────────────────────────────────────────────────────


class TestFieldDispatch:
    async def test_unknown_field_rejected(self) -> None:
        with pytest.raises(RegenerationError, match="cannot be regenerated"):
            await regenerate_variant_field(
                _product(), _variant(), "price", _orchestrator()
            )

    async def test_tags_regen_pairs_against_current_title(self) -> None:
        orch = _orchestrator()
        await regenerate_variant_field(_product(), _variant(), "tags", orch)
        _, kwargs = orch.tag.generate_for_angle.call_args
        assert kwargs["paired_title"] == TITLE

    async def test_tags_regen_makes_exactly_one_call(self) -> None:
        orch = _orchestrator()
        await regenerate_variant_field(_product(), _variant(), "tags", orch)
        assert orch.tag.generate_for_angle.await_count == 1
        assert orch.title.generate_for_angle.await_count == 0
        assert orch.desc.generate_for_angle.await_count == 0

    async def test_description_regen_pairs_against_current_title_and_tags(self) -> None:
        orch = _orchestrator()
        await regenerate_variant_field(_product(), _variant(), "description", orch)
        _, kwargs = orch.desc.generate_for_angle.call_args
        assert kwargs["paired_title"] == TITLE
        assert kwargs["paired_tags"] == TAGS

    async def test_description_regen_reinserts_internal_links(self) -> None:
        orch = _orchestrator()
        result = await regenerate_variant_field(
            _product(), _variant(), "description", orch
        )
        assert orch.linker.insert_links.await_count == 1
        assert result["updates"]["description"].endswith("[links]")

    async def test_description_regen_leaves_title_and_tags_alone(self) -> None:
        result = await regenerate_variant_field(
            _product(), _variant(), "description", _orchestrator()
        )
        assert set(result["updates"]) == {"description"}


# ── Title regen coherence ─────────────────────────────────────────────────────


class TestTitleRegenCoherence:
    async def test_tags_duplicating_the_new_title_are_replaced(self) -> None:
        # The new title contains "Faith Charm" and "Layering Accessory"; the
        # stored tags include "Faith Jewelry" (fine) and "Tiny Cross" (fine),
        # but "Cross Pendant" now appears verbatim in the new title.
        new_title = "Cross Pendant Necklace for Her, " + NEW_TITLE
        result = await regenerate_variant_field(
            _product(), _variant(), "title", _orchestrator(new_title=new_title)
        )
        assert "Cross Pendant" not in result["updates"]["tags"]

    async def test_tag_count_is_preserved_after_backfill(self) -> None:
        new_title = "Cross Pendant Necklace for Her, " + NEW_TITLE
        result = await regenerate_variant_field(
            _product(), _variant(), "title", _orchestrator(new_title=new_title)
        )
        assert len(result["updates"]["tags"]) == len(TAGS)

    async def test_title_regen_costs_no_extra_llm_call(self) -> None:
        orch = _orchestrator(new_title="Cross Pendant Necklace for Her, " + NEW_TITLE)
        await regenerate_variant_field(_product(), _variant(), "title", orch)
        assert orch.title.generate_for_angle.await_count == 1
        assert orch.tag.generate_for_angle.await_count == 0
        assert orch.desc.generate_for_angle.await_count == 0

    async def test_clean_new_title_leaves_tags_untouched(self) -> None:
        result = await regenerate_variant_field(
            _product(), _variant(), "title", _orchestrator(new_title=CLEAN_TITLE)
        )
        assert "tags" not in result["updates"]

    async def test_stale_description_is_reported(self) -> None:
        result = await regenerate_variant_field(
            _product(), _variant(), "title", _orchestrator()
        )
        assert any("Description still echoes" in n for n in result["notes"])

    async def test_no_stale_note_when_there_is_no_description(self) -> None:
        result = await regenerate_variant_field(
            _product(), _variant(description=""), "title", _orchestrator()
        )
        assert not any("Description still echoes" in n for n in result["notes"])


# ── Derived fields ────────────────────────────────────────────────────────────


class TestDerivedFields:
    async def test_ctr_recomputed_when_title_changes(self) -> None:
        result = await regenerate_variant_field(
            _product(), _variant(), "title", _orchestrator()
        )
        assert result["updates"]["estimated_ctr_signal"] == "high"

    async def test_ctr_recomputed_when_tags_change(self) -> None:
        result = await regenerate_variant_field(
            _product(), _variant(), "tags", _orchestrator()
        )
        assert result["updates"]["estimated_ctr_signal"] == "high"

    async def test_ctr_untouched_when_only_description_changes(self) -> None:
        result = await regenerate_variant_field(
            _product(), _variant(), "description", _orchestrator()
        )
        assert "estimated_ctr_signal" not in result["updates"]

    async def test_ctr_is_computed_from_the_new_values(self) -> None:
        orch = _orchestrator()
        await regenerate_variant_field(_product(), _variant(), "title", orch)
        args, _ = orch._estimate_ctr_signal.call_args
        assert args[0] == NEW_TITLE


# ── Description scaffold (regression) ─────────────────────────────────────────
# The LLM writes only the unique intro; the 8 operational sections (How to Order,
# Materials, Finish, Packaging, Gift Note, Best Gifts For, Have a Question) come
# from DescriptionEngine, applied by the listings pipeline AFTER generation.
# Regeneration originally skipped it, replacing a full description with a bare
# intro paragraph and silently deleting everything the buyer actually reads.

SCAFFOLDED = """A one-of-a-kind ankh pendant, written fresh for this variant.

**How to Order**
1. Choose your preferred finish — Gold, Silver, or Rose Gold.

**Materials**
925 Sterling Silver with optional Gold/Rose Gold Plating

**Packaging & Shipping**
Every order ships in a branded gift box.

**Best Gifts For**
Mothers, wives, daughters.

**Have a Question?**
Message us anytime."""


def _scaffold_session(preset=None):
    if preset is None:
        preset = MagicMock()
        preset.category = "necklace"
    session = MagicMock()
    session.get.return_value = preset
    return session


async def test_description_regen_reapplies_the_scaffold(monkeypatch):
    product = _product()
    product.variation_preset_id = 7
    product.personalization_template_id = None

    engine = MagicMock()
    engine.fill.return_value = "INTRO\n\n**How to Order**\n…rebuilt scaffold…"
    monkeypatch.setattr(
        "src.modules.listings.description_engine.DescriptionEngine",
        MagicMock(return_value=engine),
    )

    result = await regenerate_variant_field(
        product,
        _variant(description=SCAFFOLDED),
        "description",
        _orchestrator(),
        session=_scaffold_session(),
    )

    assert engine.fill.called
    assert "How to Order" in result["updates"]["description"]


async def test_scaffold_receives_the_regenerated_intro_as_llm_intro(monkeypatch):
    product = _product()
    product.variation_preset_id = 7
    product.personalization_template_id = None

    engine = MagicMock()
    engine.fill.return_value = "wrapped"
    monkeypatch.setattr(
        "src.modules.listings.description_engine.DescriptionEngine",
        MagicMock(return_value=engine),
    )

    await regenerate_variant_field(
        product, _variant(), "description", _orchestrator(), session=_scaffold_session()
    )

    # The intro handed to the scaffold is the fresh text *with* internal links.
    assert engine.fill.call_args.kwargs["llm_intro"].endswith("[links]")


async def test_no_preset_means_no_scaffold_and_a_warning(monkeypatch):
    product = _product()
    product.variation_preset_id = None

    result = await regenerate_variant_field(
        product,
        _variant(description=SCAFFOLDED),
        "description",
        _orchestrator(),
        session=MagicMock(),
    )

    # Nothing to rebuild from, but the user is told the sections are gone.
    assert any("operational sections" in n for n in result["notes"])


async def test_unscaffolded_product_gets_no_spurious_warning():
    product = _product()
    product.variation_preset_id = None

    result = await regenerate_variant_field(
        product,
        _variant(description="Just a plain description with no sections."),
        "description",
        _orchestrator(),
        session=MagicMock(),
    )

    assert not any("operational sections" in n for n in result["notes"])


async def test_missing_session_falls_back_to_intro_only():
    product = _product()
    product.variation_preset_id = 7

    result = await regenerate_variant_field(
        product, _variant(), "description", _orchestrator(), session=None
    )

    assert result["updates"]["description"].endswith("[links]")
