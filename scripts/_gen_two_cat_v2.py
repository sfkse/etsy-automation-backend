"""Retry #2: TAKI-0023 two-cat version, matching the user's reference composition.

The first attempt (_gen_two_cat.py) kept mannequin-2's worn-on-neck framing and
just dropped the third cat, but the user says it doesn't match how a real
2-cat pendant should look: cats sitting pressed together (touching at the
hip), shown in a hand-holding-the-pendant pose near the collarbone, per a
reference photo they shared (scripts/refs/pose_reference.webp).

This calls the Gemini client directly (not through ImageWorkflowFactory) so it
can pass TWO reference images in one request:
  1. TAKI-0023's own real product photo — for OUR cutout linework style, chain
     style, engraving font and gold tone (keeps this shot consistent with the
     rest of the product's photo set).
  2. The user's reference photo — for the hand-holding pose and the cats'
     pressed-together arrangement.
Saved as a sibling file; does not touch the committed slot or DB.
"""
import asyncio
import io
import sys
from pathlib import Path

from PIL import Image
from sqlalchemy.orm import Session

sys.path.insert(0, "/app")

from src.config.settings import Settings
from src.db.session import SessionLocal
from src.db.models import Product, ProductImage
from src.modules.images.jewelry_set import DAINTY_SCALE, CLOSE_FRAMING, PALETTES
from src.modules.images.pipeline import _save_ai_shot
from src.modules.images.base import ImageGenerationResult
from src.modules.images.preprocessing import preprocess_and_save

REF_POSE_PATH = Path("/app/scripts/refs/pose_reference.webp")


async def main() -> None:
    from google import genai
    from google.genai import types

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
        product_ref = Image.open(preprocessed_path).convert("RGBA")
        pose_ref = Image.open(REF_POSE_PATH).convert("RGB")

        pal = PALETTES["soft_blush_neutral"]

        prompt = (
            "You are given two reference images. Reference A is our own product "
            "photo: a personalized gold necklace with a three-cat cutout pendant "
            '(cats named "Maggie", "Billy", "Penny"). Reference B is a composition '
            "example from a similar necklace (different product, different cat "
            "shapes, different names — use it ONLY for pose and layout, not for "
            "the cat artwork itself).\n\n"
            "Generate a new photo of OUR necklace from Reference A, but as a "
            "TWO-cat version instead of three, composed like Reference B:\n"
            "- Tight close-up of a woman gently holding the necklace pendant "
            "between her thumb and forefinger near her collarbone, camera close "
            "in so the pendant is centred and tack-sharp, matching Reference B's "
            "hand grip and framing.\n"
            "- The pendant shows exactly TWO cats — reuse Reference A's exact cat "
            "silhouette style, cutout linework, sitting pose (viewed from "
            'behind) and engraved cursive font, with "Maggie" engraved on the '
            'left cat and "Billy" engraved on the right cat; drop the third cat '
            '("Penny") entirely.\n'
            "- Like Reference B, the two cats sit pressed together, touching at "
            "the body/hip in the middle, each tail curling outward on its own "
            "outer side, front paws visible at the bottom — not spaced apart.\n"
            "- Keep OUR polished warm yellow gold metal tone and chain style from "
            "Reference A, not Reference B's chain.\n"
            f"- Background and lighting: {pal.background}, {pal.lighting}, soft "
            "blurred neutral clothing fabric behind the hand, consistent with "
            "our shop's photography style.\n"
            "- Real un-retouched skin with visible pores and fine texture, "
            "natural manicured nails, shot on 85mm lens, subtle film grain, face "
            "NOT visible in frame, cropped at chin at most.\n"
            f"- {DAINTY_SCALE}\n"
            f"- {CLOSE_FRAMING}"
        )

        client = genai.Client(api_key=settings.GEMINI_API_KEY)

        def _to_part(img: Image.Image) -> "types.Part":
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png")

        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-3-pro-image",
            contents=[
                _to_part(product_ref),
                _to_part(pose_ref),
                prompt,
            ],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
                image_config=types.ImageConfig(aspect_ratio="1:1"),
            ),
        )

        result_image = None
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                result_image = Image.open(io.BytesIO(part.inline_data.data))
                break
        assert result_image is not None, "Gemini returned no image"

        gen_result = ImageGenerationResult(
            image=result_image, model_name="gemini-3-pro-image", cost_estimate=0.039
        )
        out_path = (
            Path(settings.IMAGES_DIR)
            / product.sku
            / "ai_generated"
            / f"{product.sku.lower()}-mannequin-2-two-cats.jpg"
        )
        _save_ai_shot(gen_result, out_path, apply_cover_crop=False)
        print(f"SAVED {out_path}")
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
