"""TAKI-0040: retry the 4 slots that still rendered "21" instead of "24"
after the first regeneration pass (_gen_taki0040_heart24.py).

mannequin-1/2/3 came out correct on the first Gemini pass; mannequin-4 and
all 3 concept slots did not. Re-running just those 4 through the same
regenerate_slot() production path, same digit-disambiguation instruction --
plain retry, since the first pass showed Gemini can get it right.
"""
import asyncio
import sys

sys.path.insert(0, "/app")

from src.config.settings import Settings
from src.db.session import SessionLocal
from src.db.models import Product
from src.modules.images.regenerate import regenerate_slot

DIGIT_INSTRUCTION = (
    "THE NUMBER ON THE PENDANT IS TWENTY-FOUR, WRITTEN AS THE TWO DIGITS 2 "
    "AND 4 (TWO-FOUR). It is NOT twenty-one, NOT 21, and the second digit is "
    "NOT a 1. The second charm is the numeral FOUR (4) in a cursive script "
    "style: it has a small closed loop/triangle near its base and a short "
    "flag or hook at the top -- this is the distinctive shape of a script "
    "'4', completely different from a plain '1'. Render the second digit as "
    "a 4, full stop."
)

RETRY_SLOTS = ["mannequin-4", "concept-1", "concept-2", "concept-3"]


async def main() -> None:
    settings = Settings()
    session = SessionLocal()
    try:
        product = session.query(Product).filter_by(sku="TAKI-0040").first()
        assert product is not None, "TAKI-0040 not found"

        for slot in RETRY_SLOTS:
            print(f"--- retrying {slot} ---", flush=True)
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
