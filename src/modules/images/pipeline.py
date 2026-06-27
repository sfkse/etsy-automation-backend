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

from PIL import Image
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.models import Product, ProductImage, ProductStatus
from src.modules.images.alt_text import generate_alt_text
from src.modules.images.base import ImageGenerationRequest, ImageGenerationResult
from src.modules.images.factory import ImageWorkflowFactory
from src.modules.images.preprocessing import preprocess_and_save
from src.modules.sheets.sync import upsert_product_row
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Lifestyle prompt templates ────────────────────────────────────────────────

LIFESTYLE_PROMPTS = [
    "Woman wearing the necklace, soft natural lighting, neutral background",
    "Necklace on marble surface flat lay, minimalist styling",
    "Hand opening gift box containing necklace, lifestyle",
    "Macro detail shot of necklace pendant",
    "Young woman in cafe wearing necklace, candid lifestyle",
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
    """Resize image to TARGET_SIZE (2000×2000) with white background fill."""
    img = img.convert("RGBA")
    canvas = Image.new("RGBA", TARGET_SIZE, (255, 255, 255, 255))
    img.thumbnail(TARGET_SIZE, Image.LANCZOS)
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
      2. Generate lifestyle images
      3. Save files + DB records
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
    preprocessed_path = preprocess_and_save(
        image_path=primary_path,
        sku=sku,
        images_dir=settings.IMAGES_DIR,
    )
    logger.info("preprocessing_done", sku=sku, path=str(preprocessed_path))

    # ── 2. Generate lifestyle images ──────────────────────────────────────────
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

    # ── 4. Advance status ─────────────────────────────────────────────────────
    product.status = ProductStatus.AWAITING_APPROVAL.value
    session.commit()
    upsert_product_row(product, settings)
    logger.info("image_pipeline_done", sku=sku, total_cost=total_cost)
