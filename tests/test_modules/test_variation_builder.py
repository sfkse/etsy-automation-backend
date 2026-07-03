"""
Tests for the VariationMatrixBuilder (Section C).

Uses MagicMock sessions — no live DB, matching the project convention
(JSONB rules out SQLite in-memory).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.db.models import MaterialType, PricingStrategy, VariationPreset
from src.modules.listings.variation_builder import (
    VariationMatrixBuilder,
    variation_display_label,
)


def _pricing() -> PricingStrategy:
    return PricingStrategy(
        id=1,
        base_multiplier=4.0,
        finish_offsets_pct={"Gold": 0.0, "Silver": -3.0, "Rose": -5.0},
        length_base_inches=16,
        length_price_per_extra_inch_pct=2.5,
        loss_leader_enabled=True,
        loss_leader_finish="Rose",
        loss_leader_length=12,
        loss_leader_margin_pct=15.0,
        multi_count_extra_pct=12.0,
    )


def _preset_silver() -> VariationPreset:
    return VariationPreset(
        id=1,
        name="necklace_silver_standard",
        category="necklace",
        material_type=MaterialType.SILVER_925.value,
        finishes=["Gold", "Silver", "Rose"],
        lengths_inches=[12, 14, 16, 18, 20, 22, 24],
        multi_count_label=None,
        multi_count_range=None,
        has_length_variation=True,
    )


def _preset_brass() -> VariationPreset:
    return VariationPreset(
        id=2,
        name="necklace_brass_standard",
        category="necklace",
        material_type=MaterialType.BRASS.value,
        finishes=["Gold", "Silver"],
        lengths_inches=[],
        multi_count_label=None,
        multi_count_range=None,
        has_length_variation=False,
    )


def _preset_multi() -> VariationPreset:
    return VariationPreset(
        id=3,
        name="necklace_brass_multi_birthstone",
        category="necklace",
        material_type=MaterialType.BRASS.value,
        finishes=["Gold", "Silver"],
        lengths_inches=[],
        multi_count_label="Birthstone",
        multi_count_range=[1, 2, 3],
        has_length_variation=False,
    )


def _session_for(preset: VariationPreset) -> MagicMock:
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = preset
    # PricingStrategy is fetched via .query().first()
    def _query_side(model):
        q = MagicMock()
        if model is VariationPreset:
            q.filter_by.return_value.first.return_value = preset
        elif model is PricingStrategy:
            q.first.return_value = _pricing()
        return q

    session.query.side_effect = _query_side
    return session


def test_silver_standard_yields_21_cells():
    builder = VariationMatrixBuilder(_session_for(_preset_silver()))
    cells = builder.build("necklace_silver_standard", rexven_cost_cents=750)
    assert len(cells) == 21  # 3 finishes × 7 lengths


def test_brass_standard_yields_2_cells():
    builder = VariationMatrixBuilder(_session_for(_preset_brass()))
    cells = builder.build("necklace_brass_standard", rexven_cost_cents=750)
    assert len(cells) == 2
    assert {c.finish for c in cells} == {"Gold", "Silver"}
    assert all(c.length is None for c in cells)


def test_multi_birthstone_yields_finishes_times_counts():
    builder = VariationMatrixBuilder(_session_for(_preset_multi()))
    cells = builder.build("necklace_brass_multi_birthstone", rexven_cost_cents=750)
    assert len(cells) == 2 * 3   # 2 finishes × 3 counts
    counts = {c.multi_count for c in cells}
    assert counts == {1, 2, 3}


def test_loss_leader_cell_is_flagged_and_cheapest_in_column():
    builder = VariationMatrixBuilder(_session_for(_preset_silver()))
    cells = builder.build("necklace_silver_standard", rexven_cost_cents=750)

    loss_leaders = [c for c in cells if c.is_loss_leader]
    assert len(loss_leaders) == 1
    ll = loss_leaders[0]
    assert ll.finish == "Rose"
    assert ll.length == 12
    # 15% margin on $7.50 cost → 862 cents
    assert ll.price_cents == int(750 * 1.15)

    # The loss-leader should be strictly cheaper than the Rose × 16" cell
    rose_16 = next(c for c in cells if c.finish == "Rose" and c.length == 16)
    assert ll.price_cents < rose_16.price_cents


def test_sku_suffix_format():
    builder = VariationMatrixBuilder(_session_for(_preset_multi()))
    cells = builder.build("necklace_brass_multi_birthstone", rexven_cost_cents=1000)
    # Suffix like "GO-N2" for Gold × 2 multicount, no length
    gold_n2 = next(c for c in cells if c.finish == "Gold" and c.multi_count == 2)
    assert gold_n2.sku_suffix == "GO-N2"


def test_display_label_composition():
    preset = _preset_multi()
    builder = VariationMatrixBuilder(_session_for(preset))
    cells = builder.build("necklace_brass_multi_birthstone", rexven_cost_cents=1000)
    cell = next(c for c in cells if c.finish == "Gold" and c.multi_count == 2)
    label = variation_display_label(cell, preset)
    assert "Gold" in label
    assert "2" in label
    assert "Birthstone" in label


def test_missing_preset_raises():
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    builder = VariationMatrixBuilder(session)
    with pytest.raises(ValueError):
        builder.build("does_not_exist", rexven_cost_cents=750)
