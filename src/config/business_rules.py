"""
All hard business rules as constants.
Single source of truth — never duplicate these in other modules.
No logic here; only data declarations.
"""

# ─── Title ────────────────────────────────────────────────────────────────────
# The training guide's golden rule (§2) is 137-140 chars: "Her zaman 137-140
# karakter aralığında ol". This was briefly relaxed to 120 on the theory that
# LLMs could not hit a 4-char window — but the real cause of the misses was the
# substring bug below, which rejected every "Birthstone" title and forced the
# retry path into its unvalidated fallback. With that fixed and the deterministic
# padding pass in title_generator.py::_pad_to_band, the guide's band is
# reachable, so it is restored here.
TITLE_MIN_LENGTH: int = 137
TITLE_MAX_LENGTH: int = 140
TITLE_FIRST_NICHE_CHARS: int = 60  # first 60 chars = niche description zone
TITLE_SEPARATOR: str = ", "        # comma-space, never pipe

# Approved padding phrases. Appended by _pad_to_band to lift a short title into
# the 137-140 band; also quoted in the retry prompt so the model and the padder
# draw from one vocabulary. The padder picks the best-fitting phrase rather than
# walking this list in order, so the spread of lengths (5-25 chars) is what lets
# it close an arbitrary gap without overshooting TITLE_MAX_LENGTH.
TITLE_PADDING_PHRASES: list[str] = [
    "Charm",
    "Gift Idea",
    "for Women",
    "Boho Charm",
    "Jewelry Gift",
    "Dainty Charm",
    "Gift for Her",
    "Chic Gift Idea",
    "Charm Accessory",
    "Jewelry Present",
    "Layering Necklace",
    "Everyday Necklace",
    "Boho Chic Jewelry",
    "Minimalist Jewelry",
    "Handmade Charm Gift",
    "Dainty Layering Charm",
    "Minimalist Everyday Charm",
]

# ─── Forbidden title keywords ─────────────────────────────────────────────────
FORBIDDEN_TITLE_KEYWORDS: list[str] = [
    "Stone",         # use "CZ" or "Pave"
    "Mother's Day Gift",  # use "Gifts for Mom"
    "Diamond",       # for brass/plated products
    "Floral",        # only for actual visual flowers, never letter-flowers
]

# Compounds that legitimately contain a forbidden keyword. "Birthstone" is a
# carrier pillar (CARRIER_PILLARS below) — matching it as banned "Stone" made
# every birthstone title invalid. These spans are removed before the scan.
FORBIDDEN_TITLE_KEYWORD_EXCEPTIONS: list[str] = [
    "Birthstone",
    "Moonstone",
    "Gemstone",
    "Stonewashed",
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

# Guide §3: "Büyük tekleri AZALT" — broad tags blow up ad spend without a
# matching lift, so at most 1-2 of the 13 slots may be broad, and 8+ must be
# long-tail (multi-word) niche phrases.
TAG_MAX_BROAD: int = 2
TAG_MIN_NICHE: int = 8

# Broad ("büyük tek") terms. Gift occasions and bare material/style words are
# high-volume and generic — they compete with the whole marketplace. Matched
# case-insensitively against the full tag phrase, not as substrings, so
# "gift for daughter" is broad while "ankh necklace" is not.
BROAD_TAG_TERMS: frozenset[str] = frozenset({
    # Gift occasions / recipients
    "gifts for mom", "gift for mom", "gift for her", "gifts for her",
    "gift for him", "gifts for him", "birthday gift", "christmas gift",
    "gift for daughter", "gifts for daughter", "bridesmaid gift",
    "gift for wife", "gift for girlfriend", "anniversary gift",
    "valentines gift", "graduation gift", "holiday gift",
    # Generic shop qualifiers
    "handmade jewelry", "handmade gift", "personalized", "custom",
    "customized", "jewelry", "necklace",
    # Bare material / style words (fine inside a phrase, wasteful alone)
    "gold", "silver", "sterling silver", "925 silver", "14k gold",
    "14k gold plated", "gold plated", "dainty", "minimalist", "boho",
})

# The subset of broad terms that must stay OUT of a title's first 60 characters
# (guide §2: "Burada büyük tekler değil, niş tanımlama olmalı"). Deliberately
# excludes materials — the same §2 karat rule *requires* "925 Sterling Silver"
# in the title, and the structural formula opens with [Malzeme].
NICHE_ZONE_FORBIDDEN_TERMS: frozenset[str] = frozenset({
    "gifts for mom", "gift for mom", "gift for her", "gifts for her",
    "gift for him", "gifts for him", "birthday gift", "christmas gift",
    "gift for daughter", "gifts for daughter", "bridesmaid gift",
    "gift for wife", "gift for girlfriend", "anniversary gift",
    "valentines gift", "graduation gift", "holiday gift",
})

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

# Guide §14: three variants exist to cast three different keyword nets. Past this
# Jaccard overlap (≈7 of 13 shared tags) they compete with each other instead.
VARIANT_MAX_TAG_OVERLAP: float = 0.5

# ─── Material coherence ───────────────────────────────────────────────────────
# Guide §15: one material story per listing. A "Sterling Silver" title carrying
# "14K Gold Plated" tags sends Etsy contradictory attribute signals and reads as
# careless to buyers. Keys are the claim families; values are the phrases that
# assert them (matched case-insensitively as whole phrases).
MATERIAL_CLAIM_TERMS: dict[str, frozenset[str]] = {
    "silver": frozenset({
        "sterling silver", "925 silver", "925 sterling silver", "silver",
    }),
    "gold": frozenset({
        "gold plated", "14k gold plated", "14k gold", "18k gold", "gold ankh",
        "solid gold", "gold",
    }),
}
