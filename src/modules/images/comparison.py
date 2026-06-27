"""
Comparison workflow (Step 5.7).
Runs the same prompt through all 3 workflows for side-by-side evaluation.
Results saved to {images_dir}/{sku}/comparison/{workflow_name}.png
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
from src.modules.images.base import ImageGenerationRequest
from src.modules.images.factory import ImageWorkflowFactory
from src.utils.logger import get_logger

logger = get_logger(__name__)

COMPARISON_PROMPT = "Woman wearing the necklace, soft natural lighting, neutral background"
COMPARISON_STYLE = "professional jewelry photography, soft natural lighting"


@dataclass
class ComparisonResult:
    workflow_name: str
    file_path: str
    elapsed_seconds: float
    cost_estimate: float
    success: bool
    error: str | None = None


async def run_comparison(
    product: Product,
    session: Session,
    settings: Settings,
) -> list[ComparisonResult]:
    """
    Generate one image per workflow using the same prompt.
    Saves images and returns comparison results (not yet persisted to DB).
    """
    sku = product.sku
    real_images = (
        session.query(ProductImage)
        .filter_by(product_id=product.id, is_real=True)
        .order_by(ProductImage.rank)
        .all()
    )
    if not real_images:
        raise ValueError(f"No real images found for {sku}")

    from src.modules.images.preprocessing import preprocess_and_save

    preprocessed_path = preprocess_and_save(
        image_path=real_images[0].file_path,
        sku=sku,
        images_dir=settings.IMAGES_DIR,
    )
    reference_image = Image.open(preprocessed_path).convert("RGBA")

    comp_dir = Path(settings.IMAGES_DIR) / sku / "comparison"
    comp_dir.mkdir(parents=True, exist_ok=True)

    all_workflows = ImageWorkflowFactory.available_workflows()
    results: list[ComparisonResult] = []

    async def _run_one(workflow_name: str) -> ComparisonResult:
        output_path = comp_dir / f"{workflow_name}.png"
        t0 = time.perf_counter()
        try:
            generator = ImageWorkflowFactory.get(workflow_name, settings)
            request = ImageGenerationRequest(
                reference_image=reference_image,
                prompt=COMPARISON_PROMPT,
                style_hint=COMPARISON_STYLE,
                num_outputs=1,
            )
            gen_results = await generator.generate(request)
            elapsed = time.perf_counter() - t0
            if gen_results:
                gen_results[0].image.save(output_path, format="PNG")
                return ComparisonResult(
                    workflow_name=workflow_name,
                    file_path=str(output_path),
                    elapsed_seconds=round(elapsed, 2),
                    cost_estimate=gen_results[0].cost_estimate,
                    success=True,
                )
            return ComparisonResult(
                workflow_name=workflow_name,
                file_path=str(output_path),
                elapsed_seconds=round(elapsed, 2),
                cost_estimate=0.0,
                success=False,
                error="No images returned",
            )
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            logger.exception("comparison_failed", workflow=workflow_name, sku=sku)
            return ComparisonResult(
                workflow_name=workflow_name,
                file_path=str(output_path),
                elapsed_seconds=round(elapsed, 2),
                cost_estimate=0.0,
                success=False,
                error=str(exc),
            )

    results = await asyncio.gather(*[_run_one(w) for w in all_workflows])
    return list(results)
