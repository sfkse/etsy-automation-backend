"""
Phase 6.7 — VariantBundleOrchestrator

Entry point for Phase 7 (Human Approval UI). Coordinates TitleGenerator,
TagGenerator, DescriptionGenerator, and InternalLinker to produce a
VariantBundle containing 3 internally-consistent ListingVariants.

Within each variant, the pipeline is serialized (title → tags → description → links)
because each step uses the previous step's output for internal consistency.
Across the 3 variants, generation is parallelised via asyncio.gather.
"""
from __future__ import annotations

import asyncio
from copy import copy
from datetime import datetime

import structlog

from src.db.models import Product
from src.modules.content.description_generator import DescriptionGenerator
from src.modules.content.internal_linker import InternalLinker
from src.modules.content.tag_generator import TagGenerator
from src.modules.content.title_generator import TitleGenerator
from src.modules.llm.angles import (
    ANGLE_CONSERVATIVE,
    ANGLE_DIFFERENTIATED,
    ANGLE_GIFT_FOCUSED,
    ANGLE_HOLIDAY,
    ANGLE_MOTHERS_DAY,
    ANGLE_PREMIUM,
    ANGLE_VALENTINES,
    VariantAngle,
)
from src.modules.llm.variants import ListingVariant, VariantBundle
from src.modules.research.context_builder import ResearchContextBuilder

_log = structlog.get_logger(__name__)


class VariantBundleOrchestrator:
    """Compose the 3 final ListingVariants for a product."""

    def __init__(
        self,
        title_gen: TitleGenerator,
        tag_gen: TagGenerator,
        desc_gen: DescriptionGenerator,
        internal_linker: InternalLinker,
        research_builder: ResearchContextBuilder,
    ) -> None:
        self.title = title_gen
        self.tag = tag_gen
        self.desc = desc_gen
        self.linker = internal_linker
        self.research = research_builder

    async def generate_bundle(self, product: Product) -> VariantBundle:
        """Generate all 3 variants in parallel where possible."""
        angles = self._select_angles_for_niche(product)

        # Parallelise across variants; within each variant we serialise
        variant_tasks = [
            self._generate_one_variant(product, angle) for angle in angles
        ]
        variants = list(await asyncio.gather(*variant_tasks))

        snapshot_id = self.research.current_snapshot_id(product.carrier_pillar)
        return VariantBundle(
            product_sku=product.sku,
            variants=variants,
            research_snapshot_id=snapshot_id,
            generated_at=datetime.utcnow(),
        )

    async def _generate_one_variant(
        self, product: Product, angle: VariantAngle
    ) -> ListingVariant:
        _log.info("variant_generation_start", sku=product.sku, angle=angle.label)

        # 1. Title — anchors the variant
        title = await self.title.generate_for_angle(product, angle)

        # 2. Tags — complement the title
        tags = await self.tag.generate_for_angle(product, angle, paired_title=title)

        # 3. Description — echoes title + tags for internal consistency
        description = await self.desc.generate_for_angle(
            product, angle, paired_title=title, paired_tags=tags
        )

        # 4. Internal links appended to description
        description = await self.linker.insert_links(description, product)

        # 5. CTR signal heuristic
        ctr = self._estimate_ctr_signal(title, tags, angle, product)

        _log.info("variant_generation_done", sku=product.sku, angle=angle.label, ctr=ctr)

        return ListingVariant(
            variant_id=angle.variant_letter,
            strategy_label=angle.label,
            strategy_rationale=self._build_rationale(angle, product),
            title=title,
            tags=tags,
            description=description,
            estimated_ctr_signal=ctr,
        )

    def _select_angles_for_niche(self, product: Product) -> list[VariantAngle]:
        """
        Pick the 3 most relevant angles for this niche.
        Default: [Conservative, Differentiated, Gift-focused]
        Swaps applied based on season and material.
        """
        # Work with copies so we can mutate variant_letter without affecting the singletons
        base = [copy(ANGLE_CONSERVATIVE), copy(ANGLE_DIFFERENTIATED), copy(ANGLE_GIFT_FOCUSED)]

        # Season-aware swap for slot C (index 2)
        today = datetime.utcnow()
        if today.month in (10, 11, 12):
            base[2] = copy(ANGLE_HOLIDAY)
        elif today.month == 2:
            base[2] = copy(ANGLE_VALENTINES)
        elif today.month in (4, 5):
            base[2] = copy(ANGLE_MOTHERS_DAY)

        # Material-aware swap for slot A (index 0)
        material = (product.material or "").lower()
        if "solid gold" in material or "14k" in material:
            base[0] = copy(ANGLE_PREMIUM)

        # Assign variant letters A / B / C
        for letter, angle in zip(("A", "B", "C"), base):
            angle.variant_letter = letter

        return base

    def _estimate_ctr_signal(
        self,
        title: str,
        tags: list[str],
        angle: VariantAngle,
        product: Product,
    ) -> str:
        """
        Cheap heuristic — not an ML model.
        Compares variant against bestseller patterns from research.
        """
        research = self.research.build_for_carrier_pillar(product.carrier_pillar)
        if not research.has_data:
            return "unknown"

        # How many top structural pattern keywords appear in the title?
        top_patterns = research.structural_patterns[:10]
        pattern_phrases = [
            word
            for p in top_patterns
            for word in p.get("pattern", "").lower().split()
            if len(word) > 3
        ]
        title_lower = title.lower()
        hits = sum(1 for phrase in pattern_phrases if phrase in title_lower)

        if hits >= 3:
            return "high"
        if hits >= 1:
            return "medium"
        return "low"

    @staticmethod
    def _build_rationale(angle: VariantAngle, product: Product) -> str:
        """1-2 sentence human-readable explanation shown in the approval UI."""
        return f"{angle.label}: {angle.short_rationale}"
