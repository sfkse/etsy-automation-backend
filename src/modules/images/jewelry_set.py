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


# ── Shop colour palette ──────────────────────────────────────────────────────
# A single shared palette is applied to every generated photo so the whole set
# (and the shop) reads as one cohesive brand instead of a grab-bag of
# backgrounds. Each shot keeps its own *composition*; only the colour scheme,
# lighting temperature and prop tones are unified. Switch the whole look by
# changing ACTIVE_PALETTE — no other edits needed.


@dataclass(frozen=True)
class Palette:
    name: str
    background: str      # background colours/surfaces
    lighting: str        # light temperature/quality
    props: str           # prop colours/materials
    anchor: str          # short directive folded into every prompt's style hint


PALETTES: dict[str, Palette] = {
    "warm_ivory_gold": Palette(
        name="Warm ivory & gold",
        background="soft ivory and cream backgrounds",
        lighting="warm golden natural lighting",
        props="beige linen and light-wood props",
        anchor=(
            "consistent warm ivory-and-gold colour palette, soft ivory and cream "
            "tones, warm golden lighting, cohesive editorial colour grading"
        ),
    ),
    "cool_minimal_white": Palette(
        name="Cool minimal white",
        background="bright white and soft-grey backgrounds",
        lighting="bright neutral daylight",
        props="minimal matte-ceramic and glass props",
        anchor=(
            "consistent cool minimal white palette, bright white and soft-grey "
            "tones, neutral daylight, clean airy cohesive colour grading"
        ),
    ),
    "soft_blush_neutral": Palette(
        name="Soft blush & neutral",
        background="muted blush-pink and warm-taupe backgrounds",
        lighting="soft diffused light with gentle shadows",
        props="silk and pastel props",
        anchor=(
            "consistent soft blush-and-neutral palette, muted blush-pink and warm "
            "taupe tones, soft diffused light, romantic cohesive colour grading"
        ),
    ),
    "warm_earthy_stone": Palette(
        name="Warm earthy stone",
        background="sand, terracotta and travertine backgrounds",
        lighting="warm directional sunlight",
        props="natural stone and dried-botanical props",
        anchor=(
            "consistent warm earthy stone palette, sand, terracotta and travertine "
            "tones, warm directional sunlight, organic cohesive colour grading"
        ),
    ),
}

ACTIVE_PALETTE = "warm_ivory_gold"
_P = PALETTES[ACTIVE_PALETTE]


# ── Prompt templates ─────────────────────────────────────────────────────────
# Compositions stay distinct; backgrounds/lighting/props reference the shared
# palette so the six shots colour-match each other.

_MANNEQUIN_PROMPTS = [
    f"Close-up of a woman gently holding the necklace pendant between her thumb and "
    f"forefinger near her collarbone, pendant sharp and centered against softly blurred "
    f"skin, shallow depth of field, natural manicured nails, gentle {_P.lighting}, "
    f"{_P.background}, intimate tactile editorial close-up",
    f"Three-quarter angle of a woman wearing the necklace, {_P.lighting}, "
    f"{_P.background}, editorial lifestyle photography",
    f"Close-up bust shot focused on the necklace against skin, gentle {_P.lighting}, "
    f"blurred {_P.background}, high detail",
]

_CONCEPT_PROMPTS = [
    f"The necklace displayed as a minimalist flat lay on {_P.background}, "
    f"{_P.lighting} from top-left, styled with {_P.props}",
    f"The necklace inside an opened branded gift box, {_P.lighting}, "
    f"cozy gifting atmosphere with {_P.background} and {_P.props}",
    f"Macro detail shot of the necklace pendant with {_P.background} in soft bokeh, "
    f"{_P.lighting}, showcasing craftsmanship and finish",
]

_STYLE_HINT = (
    f"professional jewelry photography, {_P.anchor}, high quality, sharp focus"
)


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
    include_charts: bool = False,
) -> JewelryImageSet:
    """Produce the 6 AI photos (3 mannequin + 3 concept) for ``product``.

    Mannequin + concept shots are returned in-memory (the caller decides
    how to name and persist them alongside DB rows).

    Charts (size / birthstone / care) are only generated when
    ``include_charts=True``; by default they are skipped so the set is the
    6 AI photos only — remaining listing images (e.g. Rexven size/care
    instructions) are added manually. Chart generation is retained for
    callers that still want the deterministic PNGs.
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

    # ── Charts (deterministic, sync) — skipped unless explicitly requested ─
    if not include_charts:
        return JewelryImageSet(
            mannequin_shots=mannequin_shots,
            concept_shots=concept_shots,
        )

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
