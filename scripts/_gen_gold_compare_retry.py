"""Retry of the TAKI-0020 gold/silver comparison concept shot.

The first attempt (_gen_gold_preview.py) flattened the witch-on-broom cutout
into a simplified blob and garbled the engraved name when asked to draw two
pendants in one frame. This retry drops the teardrop drape (extra geometry
per chain) for a simpler straight-hang layout and spells out pendant-fidelity
requirements for BOTH copies explicitly, the way jewelry_set.build_style_hint
already does for a single pendant.
"""
import asyncio
import sys
from pathlib import Path

from PIL import Image
from sqlalchemy.orm import Session

sys.path.insert(0, "/app")

from src.config.settings import Settings
from src.db.session import SessionLocal
from src.db.models import Product, ProductImage
from src.modules.images.base import ImageGenerationRequest
from src.modules.images.factory import ImageWorkflowFactory
from src.modules.images.jewelry_set import (
    CONCEPT_SIMPLICITY,
    DAINTY_SCALE_STILL_LIFE,
    build_style_hint,
    resolve_palette,
)
from src.modules.images.pipeline import _save_ai_shot
from src.modules.images.preprocessing import preprocess_and_save


async def main() -> None:
    settings = Settings()
    session: Session = SessionLocal()
    try:
        product = session.query(Product).filter_by(sku="TAKI-0020").first()
        assert product is not None, "TAKI-0020 not found"

        real = (
            session.query(ProductImage)
            .filter_by(product_id=product.id, is_real=True)
            .order_by(ProductImage.rank)
            .all()
        )
        preprocessed_path = preprocess_and_save(
            image_path=real[0].file_path, sku=product.sku, images_dir=settings.IMAGES_DIR
        )
        reference = Image.open(preprocessed_path).convert("RGBA")

        pal = resolve_palette("soft_blush_neutral")
        concept_hint = build_style_hint(pal, still_life=True)

        compare_prompt = (
            f"Two necklaces laid flat side by side on {pal.surface}, each chain "
            f"hanging in a simple relaxed curve with its pendant resting at the "
            f"bottom, the two pieces far enough apart that neither chain overlaps "
            f"or touches the other. The necklace on the left is in polished warm "
            f"yellow gold (14k/18k gold-tone metal); the necklace on the right is "
            f"in the original brushed sterling silver tone. Both pendants are the "
            f"exact same witch-flying-on-a-broom charm as the reference photo, "
            f"reproduced identically on both sides — the pointed witch hat, the "
            f"flowing cape silhouette, the two visible legs, and the broom "
            f"trailing behind must all be fully intact and clearly readable on "
            f"BOTH pendants, with the name \"Elizabeth\" engraved in the same "
            f"cursive script clearly legible on BOTH pendants. Never simplify, "
            f"merge, flatten, or omit any part of the cutout silhouette on either "
            f"pendant — only the metal colour differs between the two. Shot from "
            f"directly overhead, {pal.lighting}, nothing else on the surface, "
            f"{CONCEPT_SIMPLICITY}, {DAINTY_SCALE_STILL_LIFE}"
        )

        generator = ImageWorkflowFactory.get("gemini", settings)
        results = await generator.generate(
            ImageGenerationRequest(
                reference_image=reference, prompt=compare_prompt, style_hint=concept_hint, num_outputs=1
            )
        )
        assert results, "Gemini returned no image"

        out_path = (
            Path(settings.IMAGES_DIR)
            / product.sku
            / "ai_generated"
            / f"{product.sku.lower()}-concept-4-gold-silver-compare.jpg"
        )
        _save_ai_shot(results[0], out_path, apply_cover_crop=False)
        print(f"SAVED {out_path}")
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
