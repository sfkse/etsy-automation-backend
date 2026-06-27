"""
Phase 6.0 — Variant Strategy data contracts.

ListingVariant  : one complete, internally-consistent listing proposal (title + tags + description).
VariantBundle   : the 3 variants produced for a single product in one generation run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ListingVariant:
    """One complete, internally-consistent listing proposal."""

    variant_id: str              # "A", "B", "C"
    strategy_label: str          # e.g. "Conservative niche", "Differentiated", "Gift-focused"
    strategy_rationale: str      # 1-2 sentences shown in the approval UI
    title: str                   # 137-140 chars
    tags: list[str]              # exactly 13
    description: str             # 150-220 words
    estimated_ctr_signal: str    # "high" | "medium" | "low" | "unknown"

    def to_dict(self) -> dict:
        return {
            "id": self.variant_id,
            "strategy_label": self.strategy_label,
            "strategy_rationale": self.strategy_rationale,
            "title": self.title,
            "tags": self.tags,
            "description": self.description,
            "estimated_ctr_signal": self.estimated_ctr_signal,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ListingVariant":
        return cls(
            variant_id=d["id"],
            strategy_label=d.get("strategy_label", ""),
            strategy_rationale=d.get("strategy_rationale", ""),
            title=d.get("title", ""),
            tags=d.get("tags", []),
            description=d.get("description", ""),
            estimated_ctr_signal=d.get("estimated_ctr_signal", "unknown"),
        )


@dataclass
class VariantBundle:
    """The 3 variants generated for a single product in one run."""

    product_sku: str
    variants: list[ListingVariant]   # always 3, ordered A / B / C
    research_snapshot_id: str        # which research snapshot was used
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "product_sku": self.product_sku,
            "variants": [v.to_dict() for v in self.variants],
            "research_snapshot_id": self.research_snapshot_id,
            "generated_at": self.generated_at.isoformat(),
        }
