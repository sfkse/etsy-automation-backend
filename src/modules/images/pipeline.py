"""
Production image pipeline (Step 5.8).

Orchestrates:
  1. Background removal on the primary real photo
  2. AI generation of 5 lifestyle images via the selected workflow
  3. Saving images with SEO filenames
  4. Updating the DB ProductImage records
  5. Alt-text assignment

Rule (Section 1.11): at least 3 real Reksven photos must remain in the final set.
AI images supplement — they never replace real ones.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.models import Product, ProductImage, ProductStatus, ShopSettings
from src.modules.images.alt_text import generate_alt_text
from src.modules.images.base import ImageGenerationRequest, ImageGenerationResult
from src.modules.images.cover_crop import auto_crop_cover_photo
from src.modules.images.factory import ImageWorkflowFactory
from src.modules.images.jewelry_set import (
    DEFAULT_PALETTE,
    ChartResult,
    JewelryImageSet,
    generate_jewelry_set,
)
from src.modules.images.preprocessing import preprocess_and_save
from src.modules.sheets.sync import upsert_product_row
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Lifestyle prompt templates ────────────────────────────────────────────────

LIFESTYLE_PROMPTS = [
    "Woman wearing the necklace, soft natural lighting, neutral background, "
    "no face visible, cropped at neck or shoulders, product is small and delicate "
    "— do NOT exaggerate its size, realistic dainty jewelry proportions",
    "Necklace on marble surface flat lay, minimalist styling",
    "Hand opening gift box containing necklace, lifestyle",
    "Macro detail shot of necklace pendant",
    "Young woman in cafe wearing necklace, candid lifestyle, "
    "no face visible, cropped at neck or shoulders, product is small and delicate "
    "— do NOT exaggerate its size, realistic dainty jewelry proportions",
]

STYLE_HINT = "professional jewelry photography, soft natural lighting, high quality"

TARGET_SIZE = (2000, 2000)


def _seo_filename(sku: str, index: int, product: Product) -> str:
    """
    Build kebab-case SEO filename.
    e.g. taki-0001-gold-plated-cross-necklace-lifestyle-1.jpg
    """
    parts = [sku.lower()]
    for field in (product.color, product.material, product.carrier_pillar):
        if field:
            parts.append(re.sub(r"[^a-z0-9]+", "-", field.lower()).strip("-"))
    parts += ["lifestyle", str(index)]
    return "-".join(filter(None, parts)) + ".jpg"


def _resize_to_target(img: Image.Image) -> Image.Image:
    """Scale image up/down to fill TARGET_SIZE (2000×2000), preserving aspect.

    Uses ``ImageOps.contain`` which *upscales* as well as downscales (unlike
    ``Image.thumbnail`` which only shrinks) — so the native 1024×1024 model
    output fills the full 2000×2000 frame instead of floating in white padding.
    Any non-square output is letterboxed onto a white canvas.
    """
    img = img.convert("RGBA")
    canvas = Image.new("RGBA", TARGET_SIZE, (255, 255, 255, 255))
    img = ImageOps.contain(img, TARGET_SIZE, Image.LANCZOS)
    offset = ((TARGET_SIZE[0] - img.width) // 2, (TARGET_SIZE[1] - img.height) // 2)
    canvas.paste(img, offset, img)
    return canvas.convert("RGB")


async def run_image_pipeline(
    product: Product,
    session: Session,
    settings: Settings,
) -> None:
    """
    Full image pipeline for a product.

    Steps:
      1. Preprocess (background removal)
      2. Dispatch on ``ShopSettings.image_workflow_mode``:
           - ``jewelry_9`` → 3 mannequin + 3 concept + 3 chart set
           - otherwise    → legacy 5-lifestyle loop
      3. Save files + DB records with rank ordering
      4. Assign alt text
    """
    sku = product.sku
    workflow_name = product.image_workflow_used or settings.DEFAULT_IMAGE_WORKFLOW
    logger.info("image_pipeline_start", sku=sku, workflow=workflow_name)

    # ── 1. Preprocess primary real image ──────────────────────────────────────
    real_images = (
        session.query(ProductImage)
        .filter_by(product_id=product.id, is_real=True)
        .order_by(ProductImage.rank)
        .all()
    )

    if not real_images:
        raise ValueError(f"No real images found for product {sku}")

    primary_path = real_images[0].file_path
    # Off the event loop: rembg inference is seconds of blocking CPU work (plus a
    # one-time model load), and running it inline froze uvicorn hard enough that
    # the compose healthcheck stopped getting answered mid-build.
    preprocessed_path = await asyncio.to_thread(
        preprocess_and_save,
        image_path=primary_path,
        sku=sku,
        images_dir=settings.IMAGES_DIR,
    )
    logger.info("preprocessing_done", sku=sku, path=str(preprocessed_path))

    shop_settings = session.query(ShopSettings).filter_by(id=1).first()
    mode = getattr(shop_settings, "image_workflow_mode", None) or "jewelry_9"
    palette = getattr(shop_settings, "image_palette", None) or DEFAULT_PALETTE

    if mode == "jewelry_9":
        await _run_jewelry_9_pipeline(
            product=product,
            session=session,
            settings=settings,
            workflow_name=workflow_name,
            preprocessed_path=preprocessed_path,
            real_images=real_images,
            palette=palette,
        )
        product.status = ProductStatus.AWAITING_APPROVAL.value
        session.commit()
        upsert_product_row(product, settings)
        logger.info("image_pipeline_done", sku=sku, mode=mode)
        return

    await _run_legacy_pipeline(
        product=product,
        session=session,
        settings=settings,
        workflow_name=workflow_name,
        preprocessed_path=preprocessed_path,
        real_images=real_images,
    )


async def _run_legacy_pipeline(
    product: Product,
    session: Session,
    settings: Settings,
    workflow_name: str,
    preprocessed_path,
    real_images: list[ProductImage],
) -> None:
    """The original 5-lifestyle pipeline, extracted verbatim for the
    ``image_workflow_mode="legacy"`` branch."""
    sku = product.sku

    reference_image = Image.open(preprocessed_path).convert("RGBA")
    generator = ImageWorkflowFactory.get(workflow_name, settings)

    ai_dir = Path(settings.IMAGES_DIR) / sku / "ai_generated"
    ai_dir.mkdir(parents=True, exist_ok=True)

    next_rank = max((img.rank for img in real_images), default=0) + 1
    total_cost = 0.0

    for idx, prompt_text in enumerate(LIFESTYLE_PROMPTS, start=1):
        request = ImageGenerationRequest(
            reference_image=reference_image,
            prompt=prompt_text,
            style_hint=STYLE_HINT,
            num_outputs=1,
        )
        try:
            results: list[ImageGenerationResult] = await generator.generate(request)
        except Exception:
            logger.exception("image_generation_failed", sku=sku, prompt_idx=idx)
            continue

        for result in results:
            filename = _seo_filename(sku, idx, product)
            output_path = ai_dir / filename

            final_img = _resize_to_target(result.image)
            final_img.save(output_path, format="JPEG", quality=92)

            db_image = ProductImage(
                product_id=product.id,
                file_path=str(output_path),
                rank=next_rank,
                is_real=False,
                workflow_source=workflow_name,
                is_selected=False,
            )
            session.add(db_image)
            session.flush()  # get db_image.id before alt text

            db_image.alt_text = generate_alt_text(product, db_image)
            total_cost += result.cost_estimate
            next_rank += 1

    # ── 3. Assign alt text to real images ─────────────────────────────────────
    for img in real_images:
        if not img.alt_text:
            img.alt_text = generate_alt_text(product, img)

    # ── 3. Assign alt text to real images ─────────────────────────────────────
    for img in real_images:
        if not img.alt_text:
            img.alt_text = generate_alt_text(product, img)

    # ── 4. Advance status ─────────────────────────────────────────────────────
    product.status = ProductStatus.AWAITING_APPROVAL.value
    session.commit()
    upsert_product_row(product, settings)
    logger.info("image_pipeline_done", sku=sku, total_cost=total_cost)


# ── Jewelry-9 (3 mannequin + 3 concept + 3 chart) ───────────────────────────


def _save_ai_shot(
    result: ImageGenerationResult,
    output_path: Path,
    apply_cover_crop: bool = False,
) -> Path:
    """Resize AI output to 2000x2000 and (optionally) auto-crop as cover."""
    final = _resize_to_target(result.image)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final.save(output_path, format="JPEG", quality=92)
    if apply_cover_crop:
        auto_crop_cover_photo(output_path, output_path, target_size=TARGET_SIZE)
    return output_path


async def _run_jewelry_9_pipeline(
    product: Product,
    session: Session,
    settings: Settings,
    workflow_name: str,
    preprocessed_path,
    real_images: list[ProductImage],
    palette: str | None = None,
) -> None:
    """The 9-image jewelry set pipeline (PR 4).

    Rank ordering (as specified in OPERATIONAL_INTEGRATION_FOLLOWUP.md):
      1        cover photo (best mannequin, auto-cropped)
      2..3     other mannequin shots
      4..6     concept shots
      7        size chart
      8        birthstone chart (only if warranted)
      9        care instructions chart
    """
    sku = product.sku
    reference_image = Image.open(preprocessed_path).convert("RGBA")
    ai_dir = Path(settings.IMAGES_DIR) / sku / "ai_generated"

    jset: JewelryImageSet = await generate_jewelry_set(
        product=product,
        workflow=workflow_name,
        session=session,
        settings=settings,
        reference_image=reference_image,
        output_dir=ai_dir,
        palette=palette,
    )

    next_rank = 1

    def _persist_ai(
        result: ImageGenerationResult,
        kind: str,
        idx: int,
        is_cover: bool,
    ) -> None:
        nonlocal next_rank
        filename = f"{sku.lower()}-{kind}-{idx}.jpg"
        path = ai_dir / filename
        _save_ai_shot(result, path, apply_cover_crop=is_cover)
        # Upsert by filename so re-running the pipeline replaces a slot's photo
        # in place instead of appending a duplicate row.
        db_image = (
            session.query(ProductImage)
            .filter_by(product_id=product.id, is_real=False)
            .filter(ProductImage.file_path.like(f"%{filename}"))
            .first()
        )
        if db_image is None:
            db_image = ProductImage(
                product_id=product.id,
                file_path=str(path),
                is_real=False,
            )
            session.add(db_image)
        db_image.file_path = str(path)
        db_image.rank = next_rank
        db_image.workflow_source = workflow_name
        db_image.palette_used = palette
        db_image.is_selected = is_cover
        session.flush()
        db_image.alt_text = generate_alt_text(product, db_image)
        next_rank += 1

    for i, shot in enumerate(jset.mannequin_shots, start=1):
        _persist_ai(shot, "mannequin", i, is_cover=(i == 1))

    for i, shot in enumerate(jset.concept_shots, start=1):
        _persist_ai(shot, "concept", i, is_cover=False)

    def _persist_chart(chart: Optional[ChartResult]) -> None:
        nonlocal next_rank
        if chart is None:
            return
        chart_name = str(chart.file_path).rsplit("/", 1)[-1]
        db_image = (
            session.query(ProductImage)
            .filter_by(product_id=product.id, is_real=False)
            .filter(ProductImage.file_path.like(f"%{chart_name}"))
            .first()
        )
        if db_image is None:
            db_image = ProductImage(
                product_id=product.id,
                file_path=chart.file_path,
                is_real=False,
            )
            session.add(db_image)
        db_image.file_path = chart.file_path
        db_image.rank = next_rank
        db_image.workflow_source = f"chart:{chart.kind}"
        db_image.is_selected = False
        session.flush()
        db_image.alt_text = generate_alt_text(product, db_image)
        next_rank += 1

    _persist_chart(jset.size_chart)
    _persist_chart(jset.birthstone_chart)
    _persist_chart(jset.care_instructions_chart)

    # ── Alt text for real images (preserved from legacy behaviour) ────────
    for img in real_images:
        if not img.alt_text:
            img.alt_text = generate_alt_text(product, img)
