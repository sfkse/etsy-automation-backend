"""
9-image jewelry set (PR 4).

Assembles the "3 mannequin + 3 concept + 3 chart" image set that matches
the training production standard. Mannequin/concept shots reuse the
existing ``AbstractImageGenerator`` implementations via
``ImageWorkflowFactory``; the six AI calls run under ``asyncio.gather`` but are
bounded by a concurrency semaphore (``IMAGE_GEN_CONCURRENCY``, default 2) so they
don't burst the image provider's rate limit. Charts are deterministic Pillow
output produced by ``chart_generators``.

Prompt guardrails (Christmas 1 training — ``docs/Christmas1.txt``):
- Every mannequin shot crops the model's head out of frame ("Mankenin kafası
  falan gözükmemesi lazım"). A face by hand holding the product near it is fine,
  but bust/torso shots must not show the face — it distracts from the product.
- ``build_style_hint`` enforces small/dainty product proportions matching the
  reference photo, so the model doesn't exaggerate product size (a well-known
  1-star review pattern for dainty jewelry).

Chart selection:
- Size chart: always included.
- Birthstone chart: included when the product has a stone_shape *or* when
  the linked personalization template's ``type_signature`` contains
  ``has_birthstone``.
- Care instructions chart: always included.
"""

from __future__ import annotations

import asyncio
import os
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
# lighting temperature and prop tones are unified. The active palette is chosen
# per generation (shop default via ShopSettings.image_palette, or a per-image
# override at regeneration) and resolved through ``resolve_palette`` —
# ``DEFAULT_PALETTE`` is the fallback.


@dataclass(frozen=True)
class Palette:
    name: str
    background: str  # background colours/surfaces
    lighting: str  # light temperature/quality
    props: str  # prop colours/materials
    anchor: str  # short directive folded into every prompt's style hint


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
    "dusty_rose_ivory": Palette(
        name="Dusty rose & ivory",
        background=(
            "soft muted pastel backgrounds in dusty rose and warm ivory tones "
        ),
        lighting="soft studio side-lighting with a subtle warm ambient glow",
        props="dusty-rose silk and warm-ivory ceramic props",
        anchor=(
            "consistent dusty-rose-and-ivory palette, muted pastel dusty rose and "
            "warm ivory tones, soft studio side-lighting with warm ambient glow, "
            "cinematic depth of field with soft bokeh, ultra-realistic detail, "
            "minimalist commercial colour grading"
        ),
    ),
}

# The fallback palette used when no shop-level / per-image palette is chosen.
DEFAULT_PALETTE = "soft_blush_neutral"


def resolve_palette(key: str | None) -> Palette:
    """Return the ``Palette`` for ``key``, falling back to ``DEFAULT_PALETTE``.

    Unknown / missing keys never raise — they resolve to the default so a stale
    setting can't break generation.
    """
    return PALETTES.get(key or DEFAULT_PALETTE, PALETTES[DEFAULT_PALETTE])


def palette_choices() -> list[tuple[str, str]]:
    """(key, human-name) pairs for populating a palette selector in the UI."""
    return [(key, pal.name) for key, pal in PALETTES.items()]


# ── Prompt templates ─────────────────────────────────────────────────────────
# Compositions stay distinct; backgrounds/lighting/props reference the chosen
# palette so the six shots colour-match each other. The palette is resolved per
# generation (see ``generate_jewelry_set``) rather than baked in at import, so
# it can be picked from the frontend.


def build_mannequin_prompts(p: Palette) -> list[str]:
    return [
        # M1 — intimate macro, hand present, shot from the front (COVER — pendant centered & hero)
        f"Tight close-up of a woman gently holding the necklace pendant between her thumb and "
        f"forefinger near her collarbone, camera moved in close so the pendant sits in the "
        f"centre of the frame and clearly commands the composition, pendant tack-sharp with "
        f"the chain visible resting on the skin, shallow depth of field, natural manicured "
        f"nails, real un-retouched skin with visible pores and fine texture, gentle "
        f"{p.lighting}, {p.background}, candid intimate tactile moment, shot on 85mm lens, "
        f"subtle film grain, balanced centred framing with no large empty areas, "
        f"face NOT visible in frame, cropped at chin at most",
        # M2 — side / three-quarter profile angle, product is the hero and stays tack-sharp
        f"Side three-quarter angle of the necklace worn on a woman's neck and collarbone, "
        f"the pendant and chain tack-sharp and the clear focal point of the frame, filling a "
        f"generous portion of the composition, skin and a plain soft cream neckline falling "
        f"gently out of focus so nothing competes with the jewelry, natural {p.lighting}, "
        f"blurred {p.background}, natural skin texture, shot on 85mm lens, gentle film grain, "
        f"head turned so the face is NOT visible, cropped above the jaw",
        # M3 — straight-on frontal extreme macro of the pendant in the hollow of the throat
        f"Straight-on frontal extreme macro of the pendant resting in the hollow of the "
        f"throat against bare skin, no hands, ultra-shallow depth of field with the chain "
        f"falling softly out of focus, {p.lighting} raking across the skin to reveal fine "
        f"natural texture and the metal's finish, blurred {p.background}, editorial jewelry "
        f"detail, shot on 100mm macro lens, "
        f"face and eyes NOT visible, only the throat and upper chest in frame",
    ]


def build_concept_prompts(p: Palette) -> list[str]:
    return [
        f"The necklace displayed as a minimalist flat lay on {p.background}, "
        f"{p.lighting} from top-left, styled with {p.props}",
        f"The necklace inside an opened branded gift box, {p.lighting}, "
        f"cozy gifting atmosphere with {p.background} and {p.props}",
        f"Macro detail shot of the necklace pendant with {p.background} in soft bokeh, "
        f"{p.lighting}, showcasing craftsmanship and finish",
    ]


def build_style_hint(p: Palette) -> str:
    return (
        f"professional jewelry photography, {p.anchor}, high quality, sharp focus, "
        f"authentic real-world photograph with natural imperfections and genuine skin "
        f"texture, soft natural light falloff, NOT an over-smoothed plastic CGI render, "
        f"no waxy skin, no artificial glossy over-processing, "
        f"product is small and delicate — do NOT exaggerate its size, realistic dainty "
        f"jewelry proportions matching the reference photo."
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
    palette: str | None = None,
) -> JewelryImageSet:
    """Produce the 6 AI photos (3 mannequin + 3 concept) for ``product``.

    Mannequin + concept shots are returned in-memory (the caller decides
    how to name and persist them alongside DB rows).

    ``palette`` selects the shared colour scheme (see ``PALETTES``); unknown or
    ``None`` values fall back to ``DEFAULT_PALETTE``.

    Charts (size / birthstone / care) are only generated when
    ``include_charts=True``; by default they are skipped so the set is the
    6 AI photos only — remaining listing images (e.g. Rexven size/care
    instructions) are added manually. Chart generation is retained for
    callers that still want the deterministic PNGs.
    """
    output_dir = Path(output_dir)
    generator = ImageWorkflowFactory.get(workflow, settings)

    pal = resolve_palette(palette)
    mannequin_prompts = build_mannequin_prompts(pal)
    concept_prompts = build_concept_prompts(pal)
    style_hint = build_style_hint(pal)

    def _request(prompt: str) -> ImageGenerationRequest:
        return ImageGenerationRequest(
            reference_image=reference_image,
            prompt=prompt,
            style_hint=style_hint,
            num_outputs=1,
        )

    # ── Kick off the 6 AI calls, bounded by a concurrency limit ────────────
    # Firing all 6 at once bursts the image provider's rate limit (e.g. Gemini
    # returns 429 Too Many Requests). A small semaphore staggers them into waves.
    # Tune with IMAGE_GEN_CONCURRENCY in .env (1 = fully sequential, safest).
    max_concurrency = max(1, int(os.getenv("IMAGE_GEN_CONCURRENCY", "2")))
    sem = asyncio.Semaphore(max_concurrency)

    async def _bounded_generate(prompt: str) -> list[ImageGenerationResult]:
        async with sem:
            return await generator.generate(_request(prompt))

    ai_tasks = [
        asyncio.create_task(_bounded_generate(p))
        for p in (*mannequin_prompts, *concept_prompts)
    ]
    ai_results: list[list[ImageGenerationResult] | BaseException] = (
        await asyncio.gather(*ai_tasks, return_exceptions=True)
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
        session.query(VariationPreset).filter_by(id=product.variation_preset_id).first()
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
    "Palette",
    "PALETTES",
    "DEFAULT_PALETTE",
    "resolve_palette",
    "palette_choices",
    "build_mannequin_prompts",
    "build_concept_prompts",
    "build_style_hint",
]
