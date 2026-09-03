"""
9-image jewelry set (PR 4).

Assembles the "4 mannequin + 3 concept + 3 chart" image set that matches
the training production standard. Mannequin/concept shots reuse the
existing ``AbstractImageGenerator`` implementations via
``ImageWorkflowFactory``; the seven AI calls run under ``asyncio.gather`` but are
bounded by a concurrency semaphore (``IMAGE_GEN_CONCURRENCY``, default 2) so they
don't burst the image provider's rate limit. Charts are deterministic Pillow
output produced by ``chart_generators``.

Prompt guardrails (Christmas 1 training — ``docs/Christmas1.txt``):
- Every mannequin shot crops the model's head out of frame ("Mankenin kafası
  falan gözükmemesi lazım"). A face by hand holding the product near it is fine,
  but bust/torso shots must not show the face — it distracts from the product.
- ``DAINTY_SCALE`` is folded into every prompt *and* ``build_style_hint`` so the
  model doesn't exaggerate product size (a well-known 1-star review pattern for
  dainty jewelry). Framing directions are phrased as camera moves rather than as
  "fills the frame", which the model otherwise satisfies by inflating the piece.
- Concept shots are deliberately sparse: one surface, one fabric, one light, and
  generous empty space (``CONCEPT_SIMPLICITY``). Styled sets with several props
  bury a small pendant, so each palette carries exactly ONE ``surface`` and ONE
  ``textile``, and the three shots differ by composition, not by prop count.
  Still-lifes use ``DAINTY_SCALE_STILL_LIFE``, which anchors scale to an object
  rather than to a body part that isn't in frame.

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
    background: str  # background colours/surfaces (mannequin shots)
    lighting: str  # light temperature/quality
    surface: str  # THE one staging surface for concept still-lifes
    textile: str  # THE one soft fabric allowed in a concept frame
    anchor: str  # short directive folded into every prompt's style hint


PALETTES: dict[str, Palette] = {
    "warm_ivory_gold": Palette(
        name="Warm ivory & gold",
        background="soft ivory and cream backgrounds",
        lighting="warm golden natural lighting",
        surface="a pale limestone slab",
        textile="soft ivory linen",
        anchor=(
            "consistent warm ivory-and-gold colour palette, soft ivory and cream "
            "tones, warm golden lighting, cohesive editorial colour grading"
        ),
    ),
    "cool_minimal_white": Palette(
        name="Cool minimal white",
        background="bright white and soft-grey backgrounds",
        lighting="bright neutral daylight",
        surface="a smooth matte-white ceramic tile",
        textile="crisp white cotton",
        anchor=(
            "consistent cool minimal white palette, bright white and soft-grey "
            "tones, neutral daylight, clean airy cohesive colour grading"
        ),
    ),
    "soft_blush_neutral": Palette(
        name="Soft blush & neutral",
        background="muted blush-pink and warm-taupe backgrounds",
        lighting="soft diffused light with gentle shadows",
        surface="a warm taupe plaster surface",
        textile="soft blush-pink silk",
        anchor=(
            "consistent soft blush-and-neutral palette, muted blush-pink and warm "
            "taupe tones, soft diffused light, romantic cohesive colour grading"
        ),
    ),
    "warm_earthy_stone": Palette(
        name="Warm earthy stone",
        background="sand, terracotta and travertine backgrounds",
        lighting="warm directional sunlight",
        surface="a raw travertine stone slab",
        textile="soft cream gauze fabric",
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
        surface="a warm ivory plaster surface",
        textile="dusty-rose silk",
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
# palette so the seven shots colour-match each other. The palette is resolved per
# generation (see ``generate_jewelry_set``) rather than baked in at import, so
# it can be picked from the frontend.


# Two independent axes that must NOT be merged into one instruction:
#
#   * ``DAINTY_SCALE``  — how big the piece is *relative to the body/surface*.
#   * ``CLOSE_FRAMING`` — how big it is *in the frame*, i.e. camera distance.
#
# Collapsing them backfires in both directions. A single "make it prominent"
# rule is satisfied by inflating the jewelry into a chunky statement piece (a
# well-known 1-star review trigger); a single "keep it tiny" rule is satisfied by
# backing the camera off until the pendant is an unreadable speck. Stating them
# separately gets a dainty piece shot close. Scale is anchored to something
# actually in shot so the model has a measurable reference, not an adjective.
DAINTY_SCALE = (
    "the necklace keeps its true delicate proportions against the body — the pendant "
    "is no wider than the model's thumbnail, a fine lightweight minimalist piece and "
    "never a thick chunky statement version, sized exactly as in the reference photo "
    "relative to the skin and fingers around it; the chain is slender but crisply "
    "rendered with clearly defined links — fine yet unmistakably present, never "
    "thinned to a faint hairline scratch that disappears against the skin"
)

# Same rule, anchored to an object rather than a body part — concept shots are
# still-lifes with nobody in frame, so "no wider than the model's thumbnail"
# would reference a hand the prompt explicitly bans.
DAINTY_SCALE_STILL_LIFE = (
    "the necklace keeps its true delicate proportions — the pendant is no wider than "
    "a shirt button, a fine lightweight minimalist piece and never a thick chunky "
    "statement version, sized exactly as in the reference photo relative to the "
    "surface it rests on; the chain is slender but crisply rendered with clearly "
    "defined links — fine yet unmistakably present, never thinned to a faint "
    "hairline scratch"
)

# The camera half of the pair. Pushes the lens in hard so the small piece still
# reads clearly, without licensing the model to scale the jewelry up to get there.
CLOSE_FRAMING = (
    "framed tight and shot from very close — the camera is right up at the piece so "
    "the pendant is large and unmistakable within the frame and its shape, detail and "
    "metal finish read clearly at a glance, never small or lost in the composition; "
    "get there by closing the camera distance and cropping in, while the jewelry "
    "itself stays true to its small real-world size"
)

# Concept shots are simple still-lifes, not styled sets. The reference look is one
# surface + one fabric + one light with generous negative space; anything more
# reads as clutter and pulls attention off a small, dainty product. The scenes
# differ by *composition* (overhead / three-quarter / macro), never by prop count.
CONCEPT_SIMPLICITY = (
    "simple minimal still-life composition: at most two elements besides the "
    "product — one surface and one fabric. No gift box, no packaging, no ribbons, "
    "no flowers or petals, no scattered props, no other jewelry, no text or logos, "
    "no hands or people in frame. Calm, uncluttered, generous empty space"
)


def build_mannequin_prompts(p: Palette) -> list[str]:
    return [
        # M1 — intimate macro, hand present, shot from the front (COVER — pendant centered & hero)
        f"Tight close-up of a woman gently holding the necklace pendant between her thumb and "
        f"forefinger near her collarbone, camera moved in very close so the pendant sits in "
        f"the centre of the frame, pendant tack-sharp with "
        f"the chain visible resting on the skin, shallow depth of field, natural manicured "
        f"nails, real un-retouched skin with visible pores and fine texture, gentle "
        f"{p.lighting}, {p.background}, candid intimate tactile moment, shot on 85mm lens, "
        f"subtle film grain, balanced centred framing, "
        f"the pendant small enough to sit comfortably within her fingertips, "
        f"{DAINTY_SCALE}, {CLOSE_FRAMING}, "
        f"face NOT visible in frame, cropped at chin at most",
        # M2 — side / three-quarter profile angle, product is the hero and stays tack-sharp
        f"Side three-quarter angle of the necklace worn on a woman's neck and collarbone, "
        f"the pendant and chain tack-sharp and the clear focal point of the frame, "
        f"skin and a plain soft cream neckline falling "
        f"gently out of focus so nothing competes with the jewelry, natural {p.lighting}, "
        f"blurred {p.background}, natural skin texture, shot on 85mm lens, gentle film grain, "
        f"{DAINTY_SCALE}, {CLOSE_FRAMING}, "
        f"head turned so the face is NOT visible, cropped above the jaw",
        # M3 — straight-on frontal extreme macro of the pendant in the hollow of the throat
        f"Straight-on frontal extreme macro of the pendant resting in the hollow of the "
        f"throat against bare skin, no hands, ultra-shallow depth of field with the chain "
        f"falling softly out of focus, {p.lighting} raking across the skin to reveal fine "
        f"natural texture and the metal's finish, blurred {p.background}, editorial jewelry "
        f"detail, shot on 100mm macro lens, "
        f"the pendant small enough to nestle inside the hollow of the throat, "
        f"{DAINTY_SCALE}, {CLOSE_FRAMING}, "
        f"face and eyes NOT visible, only the throat and upper chest in frame",
        # M4 — both hands lifting the chain off the skin (shows drape + length)
        f"Close-up of a woman lifting the necklace chain gently away from her skin "
        f"with her fingertips — the index finger and thumb of one hand pinching the "
        f"chain near one collarbone while the index finger of the other hand lightly "
        f"hooks the chain at the centre of the neckline, so the full curve of the "
        f"chain and the pendant are held up and clearly presented to camera, chain "
        f"and pendant tack-sharp in the middle of the frame, natural "
        f"manicured nails, real un-retouched skin with visible pores and fine "
        f"texture, soft cream blazer over bare skin, {p.lighting}, {p.background}, "
        f"warm inviting 'try it on' product-demo moment, shot on 85mm lens, subtle "
        f"film grain, the chain delicate but every link crisp and clearly visible "
        f"where she pinches it between her fingertips, {DAINTY_SCALE}, {CLOSE_FRAMING}, "
        f"frame cropped just below the nose so the eyes are NOT visible",
    ]


def build_concept_prompts(p: Palette) -> list[str]:
    return [
        # C1 — overhead flat lay, chain coiled to sit inside a SQUARE frame.
        # "Wide"/"edge to edge" phrasing here previously read as a landscape
        # scene and the model answered with 16:9; the ratio is pinned on the
        # request now, so the wording must describe a square composition too.
        f"The necklace laid flat on {p.surface} in a square composition, the "
        f"chain curling in a loose natural coil so the whole piece sits well "
        f"inside a square frame, shot from directly overhead, {p.lighting}, the "
        f"pendant and chain reading clearly against the empty surface around "
        f"them, {CONCEPT_SIMPLICITY}, {DAINTY_SCALE_STILL_LIFE}",
        # C2 — stone slab + a single fabric drape (the reference-photo look)
        f"The necklace resting on the edge of {p.surface}, a single length of "
        f"{p.textile} draped softly behind and to one side of it, {p.lighting} "
        f"from the left casting one soft natural shadow, shot from a high "
        f"three-quarter angle, {CONCEPT_SIMPLICITY}, {DAINTY_SCALE_STILL_LIFE}",
        # C3 — pendant macro, background dissolved to bokeh, nothing staged
        f"Macro detail of the necklace pendant resting on {p.surface}, camera moved "
        f"in close so the pendant sits at the centre of the frame, shallow depth of "
        f"field with the background falling into soft bokeh, {p.lighting}, showing "
        f"the metal finish and craftsmanship, {CONCEPT_SIMPLICITY}, "
        f"{DAINTY_SCALE_STILL_LIFE}, {CLOSE_FRAMING}",
    ]


def build_style_hint(p: Palette, still_life: bool = False) -> str:
    """Shared style hint. ``still_life=True`` for the concept shots.

    The mannequin wording asks for genuine skin texture, which in a flat-lay
    prompt actively invites a hand into frame — working against
    ``CONCEPT_SIMPLICITY``. Still-lifes get surface/shadow realism instead.
    """
    if still_life:
        realism = (
            "authentic real-world product photograph with natural surface texture "
            "and one soft natural shadow"
        )
        scale = DAINTY_SCALE_STILL_LIFE
    else:
        realism = (
            "authentic real-world photograph with natural imperfections and genuine "
            "skin texture, no waxy skin"
        )
        scale = DAINTY_SCALE

    return (
        f"professional jewelry photography, {p.anchor}, high quality, sharp focus, "
        f"{realism}, soft natural light falloff, NOT an over-smoothed plastic CGI "
        f"render, no artificial glossy over-processing, "
        f"minimalist delicate everyday jewelry, understated rather than "
        f"statement or bold, {scale}. "
        f"Match the reference photo's proportions exactly — neither bulked up into a "
        f"chunkier piece nor thinned out until it barely registers."
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
    """Produce the 7 AI photos (4 mannequin + 3 concept) for ``product``.

    Mannequin + concept shots are returned in-memory (the caller decides
    how to name and persist them alongside DB rows).

    ``palette`` selects the shared colour scheme (see ``PALETTES``); unknown or
    ``None`` values fall back to ``DEFAULT_PALETTE``.

    Charts (size / birthstone / care) are only generated when
    ``include_charts=True``; by default they are skipped so the set is the
    7 AI photos only — remaining listing images (e.g. Rexven size/care
    instructions) are added manually. Chart generation is retained for
    callers that still want the deterministic PNGs.
    """
    output_dir = Path(output_dir)
    generator = ImageWorkflowFactory.get(workflow, settings)

    pal = resolve_palette(palette)
    mannequin_prompts = build_mannequin_prompts(pal)
    concept_prompts = build_concept_prompts(pal)
    mannequin_hint = build_style_hint(pal)
    concept_hint = build_style_hint(pal, still_life=True)

    def _request(prompt: str, style_hint: str) -> ImageGenerationRequest:
        return ImageGenerationRequest(
            reference_image=reference_image,
            prompt=prompt,
            style_hint=style_hint,
            num_outputs=1,
        )

    # ── Kick off the 7 AI calls, bounded by a concurrency limit ────────────
    # Firing all 7 at once bursts the image provider's rate limit (e.g. Gemini
    # returns 429 Too Many Requests). A small semaphore staggers them into waves.
    # Tune with IMAGE_GEN_CONCURRENCY in .env (1 = fully sequential, safest).
    max_concurrency = max(1, int(os.getenv("IMAGE_GEN_CONCURRENCY", "2")))
    sem = asyncio.Semaphore(max_concurrency)

    async def _bounded_generate(
        prompt: str, style_hint: str
    ) -> list[ImageGenerationResult]:
        async with sem:
            return await generator.generate(_request(prompt, style_hint))

    ai_tasks = [
        asyncio.create_task(_bounded_generate(prompt, hint))
        for prompt, hint in (
            *((p, mannequin_hint) for p in mannequin_prompts),
            *((p, concept_hint) for p in concept_prompts),
        )
    ]
    ai_results: list[list[ImageGenerationResult] | BaseException] = (
        await asyncio.gather(*ai_tasks, return_exceptions=True)
    )

    def _first_or_none(item) -> Optional[ImageGenerationResult]:
        if isinstance(item, BaseException):
            return None
        return item[0] if item else None

    # Split on the actual prompt counts, not literals — the two prompt builders
    # stay the single source of truth for how many shots of each kind exist.
    n_mannequin = len(mannequin_prompts)
    mannequin_shots = [
        r for r in (_first_or_none(x) for x in ai_results[:n_mannequin]) if r is not None
    ]
    concept_shots = [
        r for r in (_first_or_none(x) for x in ai_results[n_mannequin:]) if r is not None
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
