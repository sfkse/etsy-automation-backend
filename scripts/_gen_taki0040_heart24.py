"""TAKI-0040: regenerate all 7 AI shots from the new, cleaner single-item
reference photo (heart + "24" charm necklace), replacing the old 3-up
"24/05/45" flat lay used previously.

Goes through the normal production path -- regenerate_slot() from
src/modules/images/regenerate.py, the same function the web UI's per-slot
"Regenerate" button calls -- using the real Gemini backend. The ProductImage
row with is_real=True was already repointed to
originals/heart-24-clean-ref.jpg before running this.

Carries an explicit digit-disambiguation instruction on every slot: an
earlier attempt via a different backend consistently misread the script-style
"4" charm as "1" (rendering "21" instead of "24"), so this spells it out.
"""
import asyncio
import sys

sys.path.insert(0, "/app")

from src.config.settings import Settings
from src.db.session import SessionLocal
from src.db.models import Product
from src.modules.images.regenerate import regenerate_slot, SLOT_ORDER

DIGIT_INSTRUCTION = (
    "THE NUMBER ON THE PENDANT IS TWENTY-FOUR, WRITTEN AS THE TWO DIGITS 2 "
    "AND 4 (TWO-FOUR). It is NOT twenty-one, NOT 21, and the second digit is "
    "NOT a 1. The second charm is the numeral FOUR (4) in a cursive script "
    "style: it has a small closed loop/triangle near its base and a short "
    "flag or hook at the top -- this is the distinctive shape of a script "
    "'4', completely different from a plain '1'. Render the second digit as "
    "a 4, full stop."
)


async def main() -> None:
    settings = Settings()
    session = SessionLocal()
    try:
        product = session.query(Product).filter_by(sku="TAKI-0040").first()
        assert product is not None, "TAKI-0040 not found"

        for slot in SLOT_ORDER:
            print(f"--- regenerating {slot} ---", flush=True)
            await regenerate_slot(
                product,
                session,
                settings,
                slot,
                workflow="gemini",
                instructions=DIGIT_INSTRUCTION,
                palette="soft_blush_neutral",
            )
            print(f"SAVED {slot}", flush=True)
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
