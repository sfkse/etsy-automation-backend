"""Integration test for the jewelry_9 branch of run_image_pipeline (PR 4).

Stubs ``generate_jewelry_set`` so no image generators run. Asserts that
9 ProductImage rows are created with ranks 1..9 and correct
``workflow_source`` metadata.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from src.db.models import ProductImage, ShopSettings
from src.modules.images.base import ImageGenerationResult
from src.modules.images.jewelry_set import ChartResult, JewelryImageSet
from src.modules.images.pipeline import run_image_pipeline


def _ai_result() -> ImageGenerationResult:
    return ImageGenerationResult(
        image=Image.new("RGB", (600, 600), (180, 160, 140)),
        model_name="mock",
        cost_estimate=0.0,
    )


def _chart(path: str, kind: str) -> ChartResult:
    return ChartResult(
        image=Image.new("RGB", (2000, 2000), (255, 255, 255)),
        file_path=path,
        kind=kind,
    )


@pytest.mark.asyncio
async def test_jewelry_9_pipeline_persists_nine_ranked_images(tmp_path):
    product = MagicMock()
    product.id = 42
    product.sku = "TAKI-0042"
    product.image_workflow_used = "flux"

    real_image = ProductImage(
        id=1, product_id=42, file_path=str(tmp_path / "real.png"), rank=1, is_real=True
    )
    Image.new("RGB", (800, 800), (255, 255, 255)).save(real_image.file_path)

    shop = ShopSettings(id=1, image_workflow_mode="jewelry_9")

    session = MagicMock()

    def query_side(model):
        q = MagicMock()
        if model is ProductImage:
            q.filter_by.return_value.order_by.return_value.all.return_value = [real_image]
        elif model is ShopSettings:
            q.filter_by.return_value.first.return_value = shop
        else:
            q.filter_by.return_value.first.return_value = None
        return q

    session.query.side_effect = query_side

    added_rows: list[ProductImage] = []
    session.add.side_effect = added_rows.append

    settings = MagicMock()
    settings.IMAGES_DIR = str(tmp_path)
    settings.DEFAULT_IMAGE_WORKFLOW = "flux"

    fake_set = JewelryImageSet(
        mannequin_shots=[_ai_result() for _ in range(3)],
        concept_shots=[_ai_result() for _ in range(3)],
        size_chart=_chart(str(tmp_path / "size.png"), "size"),
        birthstone_chart=_chart(str(tmp_path / "birthstone.png"), "birthstone"),
        care_instructions_chart=_chart(str(tmp_path / "care.png"), "care"),
    )

    with patch(
        "src.modules.images.pipeline.preprocess_and_save",
        return_value=real_image.file_path,
    ), patch(
        "src.modules.images.pipeline.generate_jewelry_set",
        new=AsyncMock(return_value=fake_set),
    ), patch(
        "src.modules.images.pipeline.generate_alt_text", return_value="alt"
    ), patch(
        "src.modules.images.pipeline.upsert_product_row"
    ), patch(
        "src.modules.images.pipeline.auto_crop_cover_photo"
    ):
        await run_image_pipeline(product=product, session=session, settings=settings)

    ranks = [row.rank for row in added_rows]
    assert ranks == [1, 2, 3, 4, 5, 6, 7, 8, 9], f"unexpected ranks: {ranks}"

    workflow_sources = [row.workflow_source for row in added_rows]
    assert workflow_sources[:6] == ["flux"] * 6
    assert workflow_sources[6:] == ["chart:size", "chart:birthstone", "chart:care"]

    assert added_rows[0].is_selected is True
    assert all(row.is_selected is False for row in added_rows[1:])
