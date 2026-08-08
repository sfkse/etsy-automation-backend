"""
All hard business rules as constants.
Single source of truth — never duplicate these in other modules.
No logic here; only data declarations.
"""

# ─── Title ────────────────────────────────────────────────────────────────────
# Etsy's hard cap is 140 chars. The min is our own SEO floor — keeping it in the
# 120–140 band still uses ~86% of available characters (well above the ~100-char
# average of top-ranked Etsy titles) while giving the LLM a realistic target it
# can hit without char-counting acrobatics. Previous value of 137 produced a
# 4-char window that LLMs missed on nearly every generation, forcing the retry
# path and often falling back to invalid titles that surfaced as approval
# violations. See title_generator.py::_retry_with_relaxation.
TITLE_MIN_LENGTH: int = 120
TITLE_MAX_LENGTH: int = 140
TITLE_FIRST_NICHE_CHARS: int = 60  # first 60 chars = niche description zone
TITLE_SEPARATOR: str = ", "        # comma-space, never pipe

# ─── Forbidden title keywords ─────────────────────────────────────────────────
FORBIDDEN_TITLE_KEYWORDS: list[str] = [
    "Stone",         # use "CZ" or "Pave"
    "Mother's Day Gift",  # use "Gifts for Mom"
    "Diamond",       # for brass/plated products
    "Floral",        # only for actual visual flowers, never letter-flowers
]

# Words that must not appear alone (must be accompanied by qualifier)
PENDANT_MUST_BE: str = "Pendant Necklace"  # "Pendant" alone is forbidden
SOLID_GOLD_PLATED_CONFLICT: list[str] = ["Solid Gold", "Gold Plated"]  # both forbidden in same title

# No repeated words in title
TITLE_NO_DUPLICATE_WORDS: bool = True

# ─── Tags ─────────────────────────────────────────────────────────────────────
TAG_COUNT: int = 13
TAG_MAX_LENGTH: int = 20

# Distribution per variant angle
# Kept within the training doc's 8-9 niche / 2-3 medium / 1-2 mainstream band —
# mainstream tags disproportionately inflate ad spend without a matching lift.
TAG_DISTRIBUTION: dict[str, dict[str, int]] = {
    "A": {"mainstream": 2, "medium": 3, "niche": 8},   # Conservative niche
    "B": {"mainstream": 1, "medium": 3, "niche": 9},   # Differentiated
    "C": {"mainstream": 1, "medium": 4, "niche": 8},   # Gift-focused
}

FORBIDDEN_TAG_PHRASES: list[str] = [
    "Mother's Day Gift",  # use "Gifts for Mom"
]

# ─── Description ──────────────────────────────────────────────────────────────
DESCRIPTION_MIN_WORDS: int = 150
DESCRIPTION_MAX_WORDS: int = 220
DESCRIPTION_MAX_SIMILARITY: float = 0.85   # cosine similarity vs corpus (sentence-transformers)
DESCRIPTION_MIN_ORIGINALITY_PCT: int = 96  # ≥ 96% originality

CLICHE_DESCRIPTION_PHRASES: list[str] = [
    "Discover the beauty of",
    "Elevate your style",
    "Perfect for any occasion",
    "Add a touch of elegance",
    "Make a statement",
    "A timeless piece",
    "Crafted with care",
    "The perfect gift",
    "You deserve",
    "Treat yourself",
]

# ─── Images ───────────────────────────────────────────────────────────────────
MIN_IMAGES_PER_LISTING: int = 8
MAX_REAL_IMAGES_REQUIRED: int = 3  # Etsy AI policy: at least 3 real photos

# ─── Listing quantity ─────────────────────────────────────────────────────────
QUANTITY_CONFIDENT: int = 999
QUANTITY_TEST_MIN: int = 10
QUANTITY_TEST_MAX: int = 300
QUANTITY_FORBIDDEN: int = 1  # kills algorithm

# ─── Renewal schedule (Turkey time, UTC+3) ────────────────────────────────────
RENEW_HOURS_TR: list[int] = [17, 21, 2, 5]

# ─── Carrier pillars ──────────────────────────────────────────────────────────
CARRIER_PILLARS: list[str] = [
    "cross",
    "name",
    "birthstone",
    "birth_flower",
    "pet",
    "pendant",
]

# ─── Variants ─────────────────────────────────────────────────────────────────
VARIANT_COUNT: int = 3
VARIANT_IDS: list[str] = ["A", "B", "C"]
