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

__all__ = ["DEFAULT_MOTION_PROMPT", "generate_slot_video", "video_path", "SLOT_ORDER"]

DEFAULT_MOTION_PROMPT = (
    "Subtle cinematic motion: a slow, smooth push-in with soft light gently "
    "shifting across the jewelry and a faint sparkle on the metal and stones. "
    "Keep the product sharp, centered and unchanged; no warping, no extra objects."
)


def video_path(product: Product, settings: Settings, slot: str) -> Path:
    """On-disk path of a slot's clip (served at ``/images/...``)."""
    return _ai_dir(product, settings) / "videos" / f"{product.sku.lower()}-{slot}.mp4"


def _effective_motion_prompt(user_prompt: str | None) -> str:
    """The field is pre-filled with the default, so 'override or append' is just
    whatever the user left in it; fall back to the default only if it is empty."""
    user_prompt = (user_prompt or "").strip()
    return user_prompt or DEFAULT_MOTION_PROMPT


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
            prompt=_effective_motion_prompt(prompt),
            duration=duration,
        )
    )

    out = video_path(product, settings, slot)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(result.video_bytes)

    logger.info("slot_video_generated", sku=product.sku, slot=slot, workflow=workflow)
    return out
