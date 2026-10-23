"""One-off: generate gold-tone versions of TAKI-0020's remaining AI shots.

Ad-hoc script, not part of the app. Reuses the real pipeline building blocks
(preprocessing, prompts, style hint, Gemini generator, save/crop) so the output
matches production quality, but writes to sibling files instead of overwriting
committed slots or touching the DB. Companion to the earlier mannequin-1-gold
run: does mannequin-2/3/4 + concept-1/2/3 in gold, plus one extra concept shot
showing the gold and silver versions side by side.
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
    build_concept_prompts,
    build_mannequin_prompts,
    build_style_hint,
    resolve_palette,
)
from src.modules.images.pipeline import _save_ai_shot
from src.modules.images.preprocessing import preprocess_and_save

GOLD_DIRECTION = (
    "Render the necklace chain and pendant in polished warm yellow gold "
    "(14k/18k gold-tone metal) instead of silver — a rich warm yellow-gold "
    "hue with bright highlights, the same warm polished gold finish used "
    "consistently across this shop's other gold-tone product photos, not "
    "a pale or rose-tinted gold. Only the metal colour changes; the "
    "pendant's exact shape, cutout silhouette, engraved name text, chain "
    "style and proportions must stay identical to the reference photo."
)


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
        mannequin_prompts = build_mannequin_prompts(pal)
        concept_prompts = build_concept_prompts(pal)
        mannequin_hint = build_style_hint(pal)
        concept_hint = build_style_hint(pal, still_life=True)

        compare_prompt = (
            f"Two identical necklaces laid flat side by side on {pal.surface}, each "
            f"draped into the same simple teardrop shape as the reference piece — the "
            f"necklace on the left rendered in polished warm yellow gold (14k/18k "
            f"gold-tone metal) and the necklace on the right rendered in the original "
            f"brushed sterling silver tone, both pendants and chains otherwise "
            f"identical in shape, cutout silhouette, engraved name text and size to "
            f"the reference photo, so the two metal finishes sit next to each other "
            f"for direct comparison, nothing else on the surface, shot from directly "
            f"overhead, {pal.lighting}, {CONCEPT_SIMPLICITY}, {DAINTY_SCALE_STILL_LIFE}"
        )

        jobs = [
            ("mannequin-2", f"{mannequin_prompts[1]}\n\nAdditional art direction: {GOLD_DIRECTION}", mannequin_hint, False),
            ("mannequin-3", f"{mannequin_prompts[2]}\n\nAdditional art direction: {GOLD_DIRECTION}", mannequin_hint, False),
            ("mannequin-4", f"{mannequin_prompts[3]}\n\nAdditional art direction: {GOLD_DIRECTION}", mannequin_hint, False),
            ("concept-1", f"{concept_prompts[0]}\n\nAdditional art direction: {GOLD_DIRECTION}", concept_hint, False),
            ("concept-2", f"{concept_prompts[1]}\n\nAdditional art direction: {GOLD_DIRECTION}", concept_hint, False),
            ("concept-3", f"{concept_prompts[2]}\n\nAdditional art direction: {GOLD_DIRECTION}", concept_hint, False),
            ("concept-4-gold-silver-compare", compare_prompt, concept_hint, False),
        ]

        generator = ImageWorkflowFactory.get("gemini", settings)
        sem = asyncio.Semaphore(2)

        async def run_job(slot: str, prompt: str, style_hint: str, is_cover: bool) -> None:
            async with sem:
                results = await generator.generate(
                    ImageGenerationRequest(
                        reference_image=reference, prompt=prompt, style_hint=style_hint, num_outputs=1
                    )
                )
                if not results:
                    print(f"FAILED {slot}: no image returned")
                    return
                if slot == "concept-4-gold-silver-compare":
                    filename = f"{product.sku.lower()}-concept-4-gold-silver-compare.jpg"
                else:
                    filename = f"{product.sku.lower()}-{slot}-gold.jpg"
                out_path = Path(settings.IMAGES_DIR) / product.sku / "ai_generated" / filename
                _save_ai_shot(results[0], out_path, apply_cover_crop=is_cover)
                print(f"SAVED {out_path}")

        await asyncio.gather(*[run_job(*j) for j in jobs])
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
