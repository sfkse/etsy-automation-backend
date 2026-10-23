"""One-off: generate a two-cat version of TAKI-0023's mannequin-2 shot.

The product's pendant is a 3-cat personalized charm (Maggie / Billy / Penny).
This renders the same mannequin-2 composition with only two cats (Maggie,
Billy) on the pendant instead of three, keeping pose/chain/lighting/gold tone
identical. Saved as a sibling file; does not touch the committed slot or DB.
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
from src.modules.images.jewelry_set import build_mannequin_prompts, build_style_hint, resolve_palette
from src.modules.images.pipeline import _save_ai_shot
from src.modules.images.preprocessing import preprocess_and_save


async def main() -> None:
    settings = Settings()
    session: Session = SessionLocal()
    try:
        product = session.query(Product).filter_by(sku="TAKI-0023").first()
        assert product is not None, "TAKI-0023 not found"

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
        prompt = build_mannequin_prompts(pal)[1]  # mannequin-2
        style_hint = build_style_hint(pal)

        # The shared style_hint ends with a hard "never simplify, merge, or omit
        # any part of the design" fidelity lock (aimed at stopping the model from
        # dropping cutout detail). It is appended *after* the prompt text in the
        # final request (see gemini_generator.full_prompt), so it's the last thing
        # the model reads — it was silently overriding the two-cat instruction
        # below and the model kept drawing all three cats. Swap in a variant that
        # explicitly carves out the cat-count change as the one deliberate edit.
        fidelity_lock = (
            "Reproduce the pendant's exact shape and structure from the reference photo as well — "
            "every cutout, line, and the loop or bail the chain passes through must "
            "match precisely; never simplify, merge, or omit any part of the design."
        )
        fidelity_exception = (
            "Reproduce each individual cat's exact shape, cutout linework, pose and "
            "engraved script font from the reference photo precisely, and keep the "
            "same bail/loop style where the chain attaches. The ONE deliberate "
            "structural change in this photo is the total cat count: the reference "
            "has three cats, this photo must show exactly TWO cats, not three — "
            "that is an intentional edit, not an omission to avoid."
        )
        assert fidelity_lock in style_hint
        style_hint = style_hint.replace(fidelity_lock, fidelity_exception)

        two_cat_direction = (
            "The reference photo shows a three-cat personalized pendant (three cat "
            "silhouettes side by side, each with a name engraved on its body: "
            '"Maggie", "Billy", "Penny"). Render the pendant with EXACTLY TWO cats, '
            'not three — keep the leftmost two cats exactly as in the reference '
            '("Maggie" on the left cat, "Billy" on the middle cat) and fully remove '
            'the third cat ("Penny"), including its jump ring attachment point if '
            "it has a separate one. Count the cats in the final image before "
            "finishing: there must be two, not three. The chain connects cleanly "
            "to just the two remaining cats; same style, scale, cutout linework "
            "and polished gold finish as the reference. Nothing else about the "
            "composition, pose, lighting or chain changes."
        )
        prompt = f"{prompt}\n\nAdditional art direction: {two_cat_direction}"

        generator = ImageWorkflowFactory.get("gemini", settings)
        results = await generator.generate(
            ImageGenerationRequest(
                reference_image=reference, prompt=prompt, style_hint=style_hint, num_outputs=1
            )
        )
        assert results, "Gemini returned no image"

        out_path = (
            Path(settings.IMAGES_DIR) / product.sku / "ai_generated" / f"{product.sku.lower()}-mannequin-2-two-cats.jpg"
        )
        _save_ai_shot(results[0], out_path, apply_cover_crop=False)
        print(f"SAVED {out_path}")
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
