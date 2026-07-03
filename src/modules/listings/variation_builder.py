"""
Variation Matrix Builder (Section C of OPERATIONAL_INTEGRATION.md).

Turns a VariationPreset + Rexven cost into a list of concrete
VariationCells (finish x length x multi_count) with computed prices,
loss-leader flag, and SKU suffix.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from src.db.models import PricingStrategy, VariationPreset


@dataclass
class VariationCell:
    """One cell in the Finish x Length x MultiCount matrix."""

    finish: str
    length: Optional[int]
    multi_count: Optional[int]
    price_cents: int
    sku_suffix: str
    is_loss_leader: bool = False


class VariationMatrixBuilder:
    """Builds a variation matrix from a preset + Rexven cost."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def build(
        self,
        preset_name: str,
        rexven_cost_cents: int,
        override_base_price_cents: Optional[int] = None,
    ) -> list[VariationCell]:
        preset = (
            self.session.query(VariationPreset)
            .filter_by(name=preset_name)
            .first()
        )
        if preset is None:
            raise ValueError(f"Unknown variation preset: {preset_name!r}")

        pricing = self.session.query(PricingStrategy).first()
        if pricing is None:
            raise RuntimeError(
                "PricingStrategy row missing. Run seed_shop_defaults first."
            )

        base_price_cents = (
            override_base_price_cents
            if override_base_price_cents is not None
            else int(rexven_cost_cents * (pricing.base_multiplier or 4.0))
        )

        length_dim: list[Optional[int]] = list(preset.lengths_inches or []) or [None]
        multi_dim: list[Optional[int]] = list(preset.multi_count_range or []) or [None]
        finishes: list[str] = list(preset.finishes or [])

        cells: list[VariationCell] = []
        for finish in finishes:
            for length in length_dim:
                for multi_count in multi_dim:
                    price = self._compute_price(
                        base_price_cents, finish, length, multi_count, pricing
                    )

                    is_loss_leader = bool(
                        pricing.loss_leader_enabled
                        and finish == pricing.loss_leader_finish
                        and length == pricing.loss_leader_length
                    )
                    if is_loss_leader:
                        margin = (pricing.loss_leader_margin_pct or 0.0) / 100.0
                        price = int(rexven_cost_cents * (1.0 + margin))

                    cells.append(VariationCell(
                        finish=finish,
                        length=length,
                        multi_count=multi_count,
                        price_cents=price,
                        sku_suffix=self._build_sku_suffix(finish, length, multi_count),
                        is_loss_leader=is_loss_leader,
                    ))

        return cells

    def _compute_price(
        self,
        base_cents: int,
        finish: str,
        length: Optional[int],
        multi_count: Optional[int],
        pricing: PricingStrategy,
    ) -> int:
        price = float(base_cents)

        offsets = pricing.finish_offsets_pct or {}
        finish_off = float(offsets.get(finish, 0.0)) / 100.0
        price *= (1.0 + finish_off)

        if length is not None:
            base_inches = pricing.length_base_inches or 16
            per_inch_pct = pricing.length_price_per_extra_inch_pct or 0.0
            extra = length - base_inches
            price *= (1.0 + extra * per_inch_pct / 100.0)

        if multi_count is not None and multi_count > 1:
            per_extra_pct = pricing.multi_count_extra_pct or 12.0
            price *= (1.0 + (multi_count - 1) * per_extra_pct / 100.0)

        return int(price)

    @staticmethod
    def _build_sku_suffix(
        finish: str,
        length: Optional[int],
        multi_count: Optional[int],
    ) -> str:
        parts = [finish[:2].upper()]
        if length is not None:
            parts.append(f"L{length}")
        if multi_count is not None:
            parts.append(f"N{multi_count}")
        return "-".join(parts)


def variation_display_label(cell: VariationCell, preset: VariationPreset) -> str:
    """
    Build the label shown to buyers, per the training:
    - Single finish + length: "Gold / 16 inch"
    - Multi-count: "Gold - 2 Birthstone"
    - Multi-count + length: "Gold - 2 Birthstone / 16 inch"
    """
    parts = [cell.finish]
    if cell.multi_count is not None:
        parts.append(f"- {cell.multi_count} {preset.multi_count_label or ''}".rstrip())
    label_left = " ".join(parts)

    if cell.length is not None:
        return f"{label_left} / {cell.length} inch"
    return label_left
