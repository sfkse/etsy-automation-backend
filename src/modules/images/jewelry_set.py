"""
9-image jewelry set (PR 4).

Assembles the "3 mannequin + 3 concept + 3 chart" image set that matches
the training production standard. Mannequin/concept shots reuse the
existing ``AbstractImageGenerator`` implementations via
``ImageWorkflowFactory``; the six AI calls run concurrently under
``asyncio.gather``. Charts are deterministic Pillow output produced by
``chart_generators``.

Chart selection:
- Size chart: always included.
- Birthstone chart: included when the product has a stone_shape *or* when
  the linked personalization template's ``type_signature`` contains
  ``has_birthstone``.
- Care instructions chart: always included.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PIL import Image
from sqlalchemy.orm import Session

from src.db.models import PersonalizationTemplate, Product, VariationPreset
from src.modules.images.base import ImageGenerationRequest, ImageGenerationResult
from src.modules.images.chart_generators import (
    BirthstoneChartGenerator,
    CareInstructionsChartGenerator,
    SizeChartGenerator,
)
from src.modules.images.factory import ImageWorkflowFactory

if TYPE_CHECKING:  # pragma: no cover
    from src.config.settings import Settings


# ── Prompt templates ─────────────────────────────────────────────────────────

_MANNEQUIN_PROMPTS = [
    "Front-facing portrait of a woman wearing the necklace, soft natural window light, plain neutral background, professional jewelry catalog photography",
    "Three-quarter angle of a woman wearing the necklace, soft studio lighting, subtle beige background, editorial lifestyle photography",
    "Close-up bust shot focused on the necklace against skin, gentle rim lighting, blurred neutral background, high detail",
]

_CONCEPT_PROMPTS = [
    "The necklace displayed on textured marble surface, minimalist flat lay, soft daylight from top-left, styled with a small linen ribbon",
    "The necklace inside an opened branded gift box on a light wooden surface, warm ambient lighting, cozy gifting atmosphere",
    "Macro detail shot of the necklace pendant with soft bokeh background, showcasing craftsmanship and finish",
]

_STYLE_HINT = "professional jewelry photography, soft natural lighting, high quality, sharp focus"


# ── Data ────────────────────────────────────────────────────────────────────


@dataclass
class ChartResult:
    """A rendered chart image and its persisted file path."""

    image: Image.Image
    file_path: str
    kind: str  # "size" | "birthstone" | "care"


@dataclass
class JewelryImageSet:
    """The full 9-image set (10 slots — gift box is optional)."""

    mannequin_shots: list[ImageGenerationResult] = field(default_factory=list)
    concept_shots: list[ImageGenerationResult] = field(default_factory=list)
    size_chart: Optional[ChartResult] = None
    birthstone_chart: Optional[ChartResult] = None
    care_instructions_chart: Optional[ChartResult] = None
    gift_box_shot: Optional[ImageGenerationResult] = None


# ── Chart selection ─────────────────────────────────────────────────────────


def _wants_birthstone_chart(
    product: Product,
    personalization: Optional[PersonalizationTemplate],
) -> bool:
    if getattr(product, "stone_shape", None):
        return True
    if personalization and isinstance(personalization.type_signature, dict):
        if personalization.type_signature.get("has_birthstone"):
            return True
    return False


def _resolve_lengths(preset: Optional[VariationPreset]) -> list[int]:
    if preset and preset.lengths_inches:
        return [int(x) for x in preset.lengths_inches]
    return [14, 16, 18, 20, 22, 24]


# ── Main entry ──────────────────────────────────────────────────────────────


async def generate_jewelry_set(
    product: Product,
    workflow: str,
    session: Session,
    settings: "Settings",
    reference_image: Image.Image,
    output_dir: str | Path,
) -> JewelryImageSet:
    """Produce the full 9-image set for ``product`` and persist charts.

    Mannequin + concept shots are returned in-memory (the caller decides
    how to name and persist them alongside DB rows). Charts are written to
    disk under ``output_dir/charts/`` because they are deterministic
    static PNGs.
    """
    output_dir = Path(output_dir)
    generator = ImageWorkflowFactory.get(workflow, settings)

    def _request(prompt: str) -> ImageGenerationRequest:
        return ImageGenerationRequest(
            reference_image=reference_image,
            prompt=prompt,
            style_hint=_STYLE_HINT,
            num_outputs=1,
        )

    # ── Kick off all 6 AI calls concurrently ──────────────────────────────
    ai_tasks = [
        asyncio.create_task(generator.generate(_request(p)))
        for p in (*_MANNEQUIN_PROMPTS, *_CONCEPT_PROMPTS)
    ]
    ai_results: list[list[ImageGenerationResult] | BaseException] = await asyncio.gather(
        *ai_tasks, return_exceptions=True
    )

    def _first_or_none(item) -> Optional[ImageGenerationResult]:
        if isinstance(item, BaseException):
            return None
        return item[0] if item else None

    mannequin_shots = [
        r for r in (_first_or_none(x) for x in ai_results[:3]) if r is not None
    ]
    concept_shots = [
        r for r in (_first_or_none(x) for x in ai_results[3:6]) if r is not None
    ]

    # ── Charts (deterministic, sync) ──────────────────────────────────────
    charts_dir = output_dir / "charts"

    preset = (
        session.query(VariationPreset)
        .filter_by(id=product.variation_preset_id)
        .first()
        if product.variation_preset_id
        else None
    )
    personalization = (
        session.query(PersonalizationTemplate)
        .filter_by(id=product.personalization_template_id)
        .first()
        if product.personalization_template_id
        else None
    )

    size_gen = SizeChartGenerator(_resolve_lengths(preset))
    size_img = size_gen.render()
    size_path = size_gen.save(charts_dir)
    size_chart = ChartResult(image=size_img, file_path=size_path, kind="size")

    birthstone_chart: Optional[ChartResult] = None
    if _wants_birthstone_chart(product, personalization):
        bs_gen = BirthstoneChartGenerator()
        birthstone_chart = ChartResult(
            image=bs_gen.render(),
            file_path=bs_gen.save(charts_dir),
            kind="birthstone",
        )

    care_gen = CareInstructionsChartGenerator()
    care_chart = ChartResult(
        image=care_gen.render(),
        file_path=care_gen.save(charts_dir),
        kind="care",
    )

    return JewelryImageSet(
        mannequin_shots=mannequin_shots,
        concept_shots=concept_shots,
        size_chart=size_chart,
        birthstone_chart=birthstone_chart,
        care_instructions_chart=care_chart,
    )


__all__ = [
    "JewelryImageSet",
    "ChartResult",
    "generate_jewelry_set",
]
