"""Per-slot short video clip generation (image-to-video).

Animates a slot's committed AI photo into a short ``.mp4`` clip via a video
backend (Higgsfield DoP). Mirrors ``modules.images.regenerate``: slot identity
comes from the deterministic filename the image pipeline already uses, so the
clip lives beside the photo and no DB migration is needed — the presence of the
``.mp4`` on disk *is* the "this slot has a clip" state.

The source image must be reachable by the video provider over the public
internet, so a ``PUBLIC_BASE_URL`` (the externally-visible origin of this app,
e.g. a tunnel or deployed domain) is required — Higgsfield fetches the photo by
URL and cannot reach ``localhost``.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.models import Product
# Reuse the image-side slot helpers so the two stay in lock-step.
from src.modules.images.regenerate import (
    SLOT_ORDER,
    _ai_dir,
    _slot_path,
    _to_url,
    valid_slot,
)
from src.modules.video.factory import VideoWorkflowFactory
from src.utils.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "DEFAULT_MOTION_PROMPT",
    "default_motion_prompt_for_slot",
    "generate_slot_video",
    "video_path",
    "SLOT_ORDER",
]

# Fallback for a slot that isn't in SLOT_MOTION_PROMPTS (shouldn't happen for a
# valid slot, but keeps _effective_motion_prompt total).
DEFAULT_MOTION_PROMPT = (
    "Subtle cinematic motion: a slow, smooth push-in with soft light gently "
    "shifting across the jewelry and a faint sparkle on the metal and stones. "
    "Keep the product sharp, centered and unchanged; no warping, no extra objects."
)

# Each slot's motion prompt mirrors what's actually in that shot (see
# build_mannequin_prompts / build_concept_prompts in jewelry_set.py) rather than
# one generic "push-in" applied to every pose — a hand holding a pendant should
# not animate the same way as an overhead flat lay.
SLOT_MOTION_PROMPTS: dict[str, str] = {
    # M1 — intimate macro, hand holding the pendant near the collarbone (cover)
    "mannequin-1": (
        "Subtle cinematic motion: the hand holding the pendant stays still while "
        "the camera does a slow, soft push-in toward the pendant, light shifting "
        "gently across the metal for a faint sparkle on the stones. Keep the "
        "pendant sharp, centered and unchanged; no warping, no extra objects, no "
        "new hand movement, face stays out of frame."
    ),
    # M2 — side three-quarter profile, worn on the neck/collarbone
    "mannequin-2": (
        "Subtle cinematic motion: a slow, smooth camera drift around the "
        "collarbone profile, soft light sweeping gently across the pendant and "
        "chain to catch a faint sparkle on the metal. Keep the jewelry sharp and "
        "unchanged; no warping, no extra objects, face stays out of frame."
    ),
    # M3 — straight-on frontal macro, pendant in the hollow of the throat
    "mannequin-3": (
        "Subtle cinematic motion: a gentle, breathing-like rise and fall of the "
        "chest, warm light slowly raking across the skin and pendant to catch a "
        "faint sparkle on the metal. Keep the pendant sharp, centered and "
        "unchanged; no warping, no extra objects, face stays out of frame."
    ),
    # M4 — both hands lifting the chain off the skin to show drape/length
    "mannequin-4": (
        "Subtle cinematic motion: the fingertips hold their grip while the "
        "chain sways with a soft, natural pendulum motion, light shifting gently "
        "across the links for a faint sparkle. Keep the jewelry sharp and "
        "unchanged; no warping, no extra objects, no new hand movement."
    ),
    # C1 — overhead flat lay, chain gathered into a teardrop shape
    "concept-1": (
        "Subtle cinematic motion: a slow overhead camera drift across the "
        "flat-laid necklace, soft light sweeping over the chain and pendant to "
        "reveal a faint sparkle on the metal. Keep the product sharp, centered "
        "and unchanged; no warping, no extra objects, nothing shifting on the "
        "surface."
    ),
    # C2 — resting on the surface edge with a fabric drape, three-quarter angle
    "concept-2": (
        "Subtle cinematic motion: a slow, smooth push-in toward the pendant "
        "while the draped fabric behind it sways ever so slightly, soft light "
        "shifting gently across the metal for a faint sparkle. Keep the product "
        "sharp and unchanged; no warping, no extra objects."
    ),
    # C3 — macro pendant detail on the surface, background dissolved to bokeh
    "concept-3": (
        "Subtle cinematic motion: a slow push-in on the macro pendant detail "
        "while the background bokeh softly breathes, light shifting gently "
        "across the metal finish for a faint sparkle. Keep the pendant sharp, "
        "centered and unchanged; no warping, no extra objects."
    ),
}


def default_motion_prompt_for_slot(slot: str) -> str:
    """The motion prompt that matches this slot's actual pose/composition."""
    return SLOT_MOTION_PROMPTS.get(slot, DEFAULT_MOTION_PROMPT)


def video_path(product: Product, settings: Settings, slot: str) -> Path:
    """On-disk path of a slot's clip (served at ``/images/...``)."""
    return _ai_dir(product, settings) / "videos" / f"{product.sku.lower()}-{slot}.mp4"


def _effective_motion_prompt(user_prompt: str | None, slot: str) -> str:
    """The field is pre-filled with this slot's default, so 'override or append'
    is just whatever the user left in it; fall back to the slot's own default
    (not a generic one) only if it is empty."""
    user_prompt = (user_prompt or "").strip()
    return user_prompt or default_motion_prompt_for_slot(slot)


def _public_image_url(settings: Settings, image_path: Path) -> str:
    base = (settings.PUBLIC_BASE_URL or "").strip().rstrip("/")
    if not base:
        raise ValueError(
            "PUBLIC_BASE_URL is not set. The video provider fetches the source "
            "photo by URL and cannot reach localhost — set PUBLIC_BASE_URL in "
            ".env to this app's public origin (e.g. an ngrok/tunnel or deployed "
            "domain)."
        )
    return base + _to_url(settings, image_path)


async def generate_slot_video(
    product: Product,
    session: Session,
    settings: Settings,
    slot: str,
    prompt: str | None = None,
    duration: int | None = None,
    workflow: str = "dop",
) -> Path:
    """Generate a short clip from ``slot``'s committed photo and save it to disk.

    Returns the path of the written ``.mp4``. Raises if the slot has no photo yet
    or the provider fails.
    """
    if not valid_slot(slot):
        raise ValueError(f"Unknown slot {slot!r}. Valid: {SLOT_ORDER}")

    source = _slot_path(product, settings, slot)
    if not source.exists():
        raise FileNotFoundError(
            f"Slot {slot} has no image to animate yet — generate the photo first."
        )

    image_url = _public_image_url(settings, source)
    generator = VideoWorkflowFactory.get(workflow, settings)

    from src.modules.video.base import VideoGenerationRequest

    result = await generator.generate(
        VideoGenerationRequest(
            image_url=image_url,
            prompt=_effective_motion_prompt(prompt, slot),
            duration=duration,
        )
    )

    out = video_path(product, settings, slot)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(result.video_bytes)

    logger.info("slot_video_generated", sku=product.sku, slot=slot, workflow=workflow)
    return out
