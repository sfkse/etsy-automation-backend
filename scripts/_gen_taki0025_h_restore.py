"""TAKI-0025: restore letter "H" on all 7 AI shots, keeping a silver/gold mix.

The previous script (_gen_taki0025_m_letter.py) overwrote all 7 committed
slots with letter "M". The user wants H back (the real product photo's
actual letter), but still wants some of the 7 in silver and some in gold
instead of all plain rose gold — same alternating split as before.

Unlike the M run, this does NOT need a second reference image: the product's
own real photo (originals/heart-initial.jpg -> preprocessed/bg_removed.png)
already shows the correct "H" glyph, so it's both the shape reference and the
letter reference. That means this can go through the normal **production**
single-reference path — `regenerate_slot()` from
src/modules/images/regenerate.py, the same function the web UI's per-slot
"Regenerate" button calls — instead of a custom multi-image Gemini script.
Only `instructions` (metal-tone override) is passed per slot; no palette
change, so the existing soft_blush_neutral background/lighting is kept.
"""
import asyncio
import sys

sys.path.insert(0, "/app")

from src.config.settings import Settings
from src.db.session import SessionLocal
from src.db.models import Product
from src.modules.images.regenerate import regenerate_slot, SLOT_ORDER

# Same alternating split used for the M run (4 silver, 3 gold).
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
        "metal) finish — not rose gold, not yellow gold."
    ),
    "gold": (
        "Render the pendant AND the chain in a polished warm yellow gold "
        "finish — not rose gold, not silver."
    ),
}


async def main() -> None:
    settings = Settings()
    session = SessionLocal()
    try:
        product = session.query(Product).filter_by(sku="TAKI-0025").first()
        assert product is not None, "TAKI-0025 not found"

        for slot in SLOT_ORDER:
            metal = METAL_BY_SLOT[slot]
            print(f"--- regenerating {slot} ({metal}, letter H) ---", flush=True)
            await regenerate_slot(
                product,
                session,
                settings,
                slot,
                workflow="gemini",
                instructions=METAL_INSTRUCTION[metal],
                palette="soft_blush_neutral",
            )
            print(f"SAVED {slot}", flush=True)
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
