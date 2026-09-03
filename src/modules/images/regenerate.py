"""Per-slot image regeneration & multi-backend comparison.

Supports the "7 AI photos, mix backends" workflow:
  - regenerate a single slot (mannequin-1..4 / concept-1..3) with any backend,
    replacing that photo in place;
  - generate candidates for one slot across several backends for side-by-side
    comparison (candidates are NOT committed to the slot);
  - promote a chosen candidate to become the slot's committed photo.

Slot identity is stable and derived from the deterministic filename the
pipeline already uses: ``{sku.lower()}-{slot}.jpg`` (e.g. ``taki-0001-mannequin-1.jpg``).
No DB migration is required.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.models import Product, ProductImage
from src.modules.images.alt_text import generate_alt_text
from src.modules.images.base import ImageGenerationRequest
from src.modules.images.factory import ImageWorkflowFactory
from src.modules.images.jewelry_set import (
    Palette,
    build_concept_prompts,
    build_mannequin_prompts,
    build_style_hint,
    resolve_palette,
)
from src.modules.images.pipeline import _save_ai_shot
from src.modules.images.preprocessing import preprocess_and_save
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ── Slot registry ────────────────────────────────────────────────────────────
# Slot identity is palette-independent (a stable list of 7 slots); only the
# prompt *text* varies with the chosen palette. Rank/cover mirror the jewelry_9
# pipeline: mannequin-1..4 = rank 1..4 (mannequin-1 is the cover),
# concept-1..3 = rank 5..7.
SLOT_ORDER: list[str] = [
    "mannequin-1", "mannequin-2", "mannequin-3", "mannequin-4",
    "concept-1", "concept-2", "concept-3",
]


def build_slots(p: Palette) -> dict[str, tuple[str, int, bool]]:
    """slot -> (prompt, rank, is_cover) for the given palette."""
    slots: dict[str, tuple[str, int, bool]] = {}
    mannequin_prompts = build_mannequin_prompts(p)
    for i, prompt in enumerate(mannequin_prompts, start=1):
        slots[f"mannequin-{i}"] = (prompt, i, i == 1)
    for i, prompt in enumerate(build_concept_prompts(p), start=1):
        slots[f"concept-{i}"] = (prompt, len(mannequin_prompts) + i, False)
    return slots


def valid_slot(slot: str) -> bool:
    return slot in SLOT_ORDER


@dataclass
class SlotCandidate:
    workflow: str
    model_name: str
    url: str | None
    success: bool
    elapsed_seconds: float
    cost_estimate: float
    error: str | None = None


# ── Shared helpers ───────────────────────────────────────────────────────────


def _reference_image(product: Product, session: Session, settings: Settings) -> Image.Image:
    """Preprocessed (background-removed) reference photo for AI generation."""
    real = (
        session.query(ProductImage)
        .filter_by(product_id=product.id, is_real=True)
        .order_by(ProductImage.rank)
        .all()
    )
    if not real:
        raise ValueError(f"No real images found for {product.sku}")
    preprocessed_path = preprocess_and_save(
        image_path=real[0].file_path,
        sku=product.sku,
        images_dir=settings.IMAGES_DIR,
    )
    return Image.open(preprocessed_path).convert("RGBA")


def _ai_dir(product: Product, settings: Settings) -> Path:
    return Path(settings.IMAGES_DIR) / product.sku / "ai_generated"


def _slot_path(product: Product, settings: Settings, slot: str) -> Path:
    return _ai_dir(product, settings) / f"{product.sku.lower()}-{slot}.jpg"


def _to_url(settings: Settings, path: Path | str) -> str:
    rel = str(path).split("data/images/")[-1]
    # also handle absolute IMAGES_DIR paths
    images_root = str(Path(settings.IMAGES_DIR)).split("data/images/")[-1]
    if images_root and rel.startswith(images_root):
        rel = rel[len(images_root):].lstrip("/")
    return "/images/" + rel.lstrip("/")


def _request(reference: Image.Image, prompt: str, style_hint: str) -> ImageGenerationRequest:
    return ImageGenerationRequest(
        reference_image=reference,
        prompt=prompt,
        style_hint=style_hint,
        num_outputs=1,
    )


def _effective_prompt(base: str, instructions: str | None) -> str:
    """Append user art direction to the slot's built-in prompt (empty = unchanged)."""
    instructions = (instructions or "").strip()
    if not instructions:
        return base
    return f"{base}\n\nAdditional art direction: {instructions}"


# ── Regenerate a single slot in place ────────────────────────────────────────


async def regenerate_slot(
    product: Product,
    session: Session,
    settings: Settings,
    slot: str,
    workflow: str,
    instructions: str | None = None,
    palette: str | None = None,
) -> ProductImage:
    """Regenerate ``slot`` with ``workflow`` and overwrite that photo in place.

    Updates the existing ProductImage row (or creates it if missing), keeping
    the slot's canonical rank / cover status. ``instructions`` (optional) are
    appended to the slot's built-in prompt as extra art direction and persisted
    on the row so the page can pre-fill them. ``palette`` (optional) overrides
    the colour scheme for this slot and is likewise persisted. Returns the
    persisted row.
    """
    if not valid_slot(slot):
        raise ValueError(f"Unknown slot {slot!r}. Valid: {SLOT_ORDER}")

    pal = resolve_palette(palette)
    style_hint = build_style_hint(pal, still_life=slot.startswith("concept"))
    prompt, rank, is_cover = build_slots(pal)[slot]
    reference = _reference_image(product, session, settings)
    generator = ImageWorkflowFactory.get(workflow, settings)

    results = await generator.generate(
        _request(reference, _effective_prompt(prompt, instructions), style_hint)
    )
    if not results:
        raise RuntimeError(f"{workflow} returned no image for slot {slot}")

    path = _slot_path(product, settings, slot)
    _save_ai_shot(results[0], path, apply_cover_crop=is_cover)

    row = (
        session.query(ProductImage)
        .filter_by(product_id=product.id, is_real=False)
        .filter(ProductImage.file_path.like(f"%{path.name}"))
        .first()
    )
    if row is None:
        row = ProductImage(
            product_id=product.id,
            file_path=str(path),
            rank=rank,
            is_real=False,
            is_selected=is_cover,
        )
        session.add(row)
    row.file_path = str(path)
    row.workflow_source = workflow
    row.regen_instructions = (instructions or "").strip() or None
    row.palette_used = (palette or "").strip() or None
    session.flush()
    row.alt_text = generate_alt_text(product, row)
    session.commit()

    logger.info("slot_regenerated", sku=product.sku, slot=slot, workflow=workflow)
    return row


# ── Multi-backend candidates for one slot (side-by-side compare) ─────────────


async def generate_slot_candidates(
    product: Product,
    session: Session,
    settings: Settings,
    slot: str,
    workflows: list[str] | None = None,
    instructions: str | None = None,
    palette: str | None = None,
) -> list[SlotCandidate]:
    """Generate ``slot`` with each backend and save as (uncommitted) candidates.

    Candidates land under ``ai_generated/candidates/{slot}__{workflow}.jpg`` so
    the user can compare them side by side before promoting one. ``instructions``
    (optional) are appended to the slot's built-in prompt for every candidate.
    ``palette`` (optional) overrides the colour scheme for the candidates.
    """
    if not valid_slot(slot):
        raise ValueError(f"Unknown slot {slot!r}. Valid: {SLOT_ORDER}")

    workflows = workflows or ImageWorkflowFactory.available_workflows()
    pal = resolve_palette(palette)
    style_hint = build_style_hint(pal, still_life=slot.startswith("concept"))
    prompt, _rank, is_cover = build_slots(pal)[slot]
    prompt = _effective_prompt(prompt, instructions)
    reference = _reference_image(product, session, settings)
    cand_dir = _ai_dir(product, settings) / "candidates"

    async def _one(workflow: str) -> SlotCandidate:
        t0 = time.perf_counter()
        try:
            generator = ImageWorkflowFactory.get(workflow, settings)
            results = await generator.generate(_request(reference, prompt, style_hint))
            elapsed = round(time.perf_counter() - t0, 2)
            if not results:
                return SlotCandidate(workflow, workflow, None, False, elapsed, 0.0, "No image returned")
            out = cand_dir / f"{slot}__{workflow}.jpg"
            _save_ai_shot(results[0], out, apply_cover_crop=is_cover)
            return SlotCandidate(
                workflow=workflow,
                model_name=results[0].model_name,
                url=_to_url(settings, out),
                success=True,
                elapsed_seconds=elapsed,
                cost_estimate=results[0].cost_estimate,
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = round(time.perf_counter() - t0, 2)
            logger.exception("slot_candidate_failed", sku=product.sku, slot=slot, workflow=workflow)
            return SlotCandidate(workflow, workflow, None, False, elapsed, 0.0, str(exc))

    return list(await asyncio.gather(*[_one(w) for w in workflows]))


def select_candidate(
    product: Product,
    session: Session,
    settings: Settings,
    slot: str,
    workflow: str,
    instructions: str | None = None,
    palette: str | None = None,
) -> ProductImage:
    """Promote a previously-generated candidate to the committed slot photo."""
    if not valid_slot(slot):
        raise ValueError(f"Unknown slot {slot!r}. Valid: {SLOT_ORDER}")

    # rank / cover status are palette-independent; resolve with the default.
    _prompt, rank, is_cover = build_slots(resolve_palette(None))[slot]
    cand = _ai_dir(product, settings) / "candidates" / f"{slot}__{workflow}.jpg"
    if not cand.exists():
        raise FileNotFoundError(f"No candidate for slot {slot} / {workflow}")

    dest = _slot_path(product, settings, slot)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Re-encode from the candidate so the committed file is independent of it.
    Image.open(cand).convert("RGB").save(dest, format="JPEG", quality=92)

    row = (
        session.query(ProductImage)
        .filter_by(product_id=product.id, is_real=False)
        .filter(ProductImage.file_path.like(f"%{dest.name}"))
        .first()
    )
    if row is None:
        row = ProductImage(
            product_id=product.id,
            file_path=str(dest),
            rank=rank,
            is_real=False,
            is_selected=is_cover,
        )
        session.add(row)
    row.file_path = str(dest)
    row.workflow_source = workflow
    if instructions is not None:
        row.regen_instructions = instructions.strip() or None
    if palette is not None:
        row.palette_used = palette.strip() or None
    session.flush()
    row.alt_text = generate_alt_text(product, row)
    session.commit()

    logger.info("slot_candidate_selected", sku=product.sku, slot=slot, workflow=workflow)
    return row


__all__ = [
    "SLOT_ORDER",
    "build_slots",
    "SlotCandidate",
    "valid_slot",
    "regenerate_slot",
    "generate_slot_candidates",
    "select_candidate",
]
