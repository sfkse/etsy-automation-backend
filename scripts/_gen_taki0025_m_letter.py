"""TAKI-0025: regenerate the 7 AI shots with letter "M" and a silver/gold mix.

The committed photos are all letter "H" in rose gold (from the real reference
photo). The user wants the SAME 7 slots overwritten in place (slot count must
stay at 7) with:
  - the engraved letter changed from H to M
  - the metal finish alternated between polished silver and polished gold
    across the 7 slots, instead of the original rose gold

This can't go through the normal single-reference `regenerate_slot()` path
(web UI / src/modules/images/regenerate.py) because that only accepts ONE
reference image, and getting the M glyph's exact heart-letter shape right
needs a second reference: the user supplied a real silver "M" pendant in the
same heart-letter house style (scripts/refs/taki0025_m_silver_ref.png).

So this calls the Gemini client directly (same pattern as
_gen_two_cat_v2.py) with TWO reference images per shot:
  1. TAKI-0025's own preprocessed product photo — for cutout linework style,
     chain style, bail shape and the slot's pose/composition anchor.
  2. The user's reference photo — for the exact "M" heart-letter glyph shape
     and (for silver slots) the metal tone.

Overwrites the committed slot files/DB rows in place (mirrors
regenerate_slot's DB bookkeeping), keeping rank/cover and the existing
soft_blush_neutral palette untouched — only letter + metal change.
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
from src.modules.images.alt_text import generate_alt_text
from src.modules.images.jewelry_set import build_style_hint, resolve_palette
from src.modules.images.regenerate import build_slots, SLOT_ORDER
from src.modules.images.pipeline import _save_ai_shot
from src.modules.images.base import ImageGenerationResult

REF_M_PATH = Path("/app/scripts/refs/taki0025_m_silver_ref.png")
PALETTE_KEY = "soft_blush_neutral"

# Alternate silver/gold across the 7 slots (4 silver, 3 gold).
METAL_BY_SLOT = {
    "mannequin-1": "silver",
    "mannequin-2": "gold",
    "mannequin-3": "silver",
    "mannequin-4": "gold",
    "concept-1": "silver",
    "concept-2": "gold",
    "concept-3": "silver",
}

METAL_INSTRUCTION = {
    "silver": (
        "Render the pendant AND the chain in a polished silver (bright white "
        "metal) finish, matching Reference B's silver tone exactly — not rose "
        "gold, not yellow gold."
    ),
    "gold": (
        "Render the pendant AND the chain in a polished warm yellow gold "
        "finish — not rose gold, not silver."
    ),
}

LETTER_INSTRUCTION = (
    'Change the engraved pendant letter from "H" to "M". Reference B shows a '
    'real pendant in our exact heart-letter house style with the letter "M" — '
    "copy that M glyph's exact shape (the heart forms the first stroke of the "
    "letter, same cursive proportions) in place of Reference A's H. Keep "
    "every other design element from Reference A unchanged: the cutout "
    "linework style, the bail/loop where the chain attaches, the chain link "
    "style, and the overall necklace proportions."
)


async def main() -> None:
    from google import genai
    from google.genai import types

    settings = Settings()
    session: Session = SessionLocal()
    try:
        product = session.query(Product).filter_by(sku="TAKI-0025").first()
        assert product is not None, "TAKI-0025 not found"

        preprocessed_path = (
            Path(settings.IMAGES_DIR) / product.sku / "preprocessed" / "bg_removed.png"
        )
        assert preprocessed_path.exists(), f"missing {preprocessed_path}"
        product_ref = Image.open(preprocessed_path).convert("RGBA")
        m_ref = Image.open(REF_M_PATH).convert("RGB")

        pal = resolve_palette(PALETTE_KEY)
        slots = build_slots(pal)
        client = genai.Client(api_key=settings.GEMINI_API_KEY)

        def _to_part(img: Image.Image) -> "types.Part":
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png")

        ai_dir = Path(settings.IMAGES_DIR) / product.sku / "ai_generated"

        for slot in SLOT_ORDER:
            base_prompt, rank, is_cover = slots[slot]
            metal = METAL_BY_SLOT[slot]
            style_hint = build_style_hint(pal, still_life=slot.startswith("concept"))

            extra = f"{LETTER_INSTRUCTION} {METAL_INSTRUCTION[metal]}"
            full_prompt = (
                "You are given two reference images. Reference A is our own "
                "product photo: a personalized necklace with a heart-letter "
                'cutout pendant, currently engraved with "H" in rose gold. '
                "Reference B is a real pendant in the same heart-letter house "
                'style, engraved with "M" in silver — use it ONLY for the M '
                "letter shape (and, where instructed below, the metal tone), "
                "not for its pose or background.\n\n"
                f"{base_prompt}\n\n"
                f"Additional art direction: {extra}\n\n"
                f"Style: {style_hint}"
            )

            print(f"--- generating {slot} ({metal}) ---", flush=True)
            response = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-3-pro-image",
                contents=[
                    _to_part(product_ref),
                    _to_part(m_ref),
                    full_prompt,
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
            if result_image is None:
                print(f"!!! {slot}: Gemini returned no image, skipping", flush=True)
                continue

            gen_result = ImageGenerationResult(
                image=result_image, model_name="gemini-3-pro-image", cost_estimate=0.039
            )
            path = ai_dir / f"{product.sku.lower()}-{slot}.jpg"
            _save_ai_shot(gen_result, path, apply_cover_crop=is_cover)

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
            row.workflow_source = "gemini"
            row.regen_instructions = extra
            row.palette_used = PALETTE_KEY
            session.flush()
            row.alt_text = generate_alt_text(product, row)
            session.commit()
            print(f"SAVED {path}", flush=True)
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
