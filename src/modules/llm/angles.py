"""
Phase 6.0 / 6.2 / 6.3 / 6.4 — VariantAngle value objects.

Each angle encodes ALL per-component guidance:
  - prompt_instructions      → used by TitleGenerator
  - tag_distribution         → used by TagGenerator (volume-aware bucket ratios)
  - tag_instructions         → used by TagGenerator
  - description_voice        → used by DescriptionGenerator
  - description_instructions → used by DescriptionGenerator
  - short_rationale          → shown in the approval UI

The orchestrator (Step 6.7) picks the 3 most relevant angles for each niche
and tags them with variant_letter "A" / "B" / "C".
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VariantAngle:
    label: str
    prompt_instructions: str        # title angle guidance
    keyword_bias: str               # "competitor_common" | "underused" | "gift_phrases" | "premium" | "seasonal"
    description_voice: str          # tone / persona for description
    description_instructions: str   # angle-specific description guidance
    tag_distribution: dict          # {"mainstream": int, "medium": int, "niche": int} — must sum to 13
    tag_instructions: str           # angle-specific tag guidance
    short_rationale: str            # 1 sentence shown in approval UI
    variant_letter: str = field(default="A")


# ── The 3 default angles ──────────────────────────────────────────────────────

ANGLE_CONSERVATIVE = VariantAngle(
    label="Conservative niche",
    prompt_instructions=(
        "Stay close to bestseller patterns. Use the most common phrases from the "
        "research brief's TITLE PATTERNS section. Aim for safe, proven SEO. "
        "Avoid novel angles."
    ),
    keyword_bias="competitor_common",
    description_voice="warm and personal",
    description_instructions=(
        "Standard product description structure. Lead with what it is, then quality, "
        "then occasions. Use the most common 2-3 phrases from research brief title patterns."
    ),
    tag_distribution={"mainstream": 6, "medium": 4, "niche": 3},
    tag_instructions="Prefer high-volume proven tags. The shop is going for safe SEO.",
    short_rationale="Follows proven bestseller patterns for reliable organic ranking.",
)

ANGLE_DIFFERENTIATED = VariantAngle(
    label="Differentiated",
    prompt_instructions=(
        "Use 2-3 keywords from the UNDERUSED HIGH-VALUE KEYWORDS section "
        "prominently. Find a fresh angle that no competitor in the brief uses. "
        "Still follow all hard rules but be bolder."
    ),
    keyword_bias="underused",
    description_voice="fresh and distinctive",
    description_instructions=(
        "Open with an unconventional hook — sensory detail or specific use case. "
        "Avoid generic openers entirely. Include 1-2 underused keywords from the research brief."
    ),
    tag_distribution={"mainstream": 2, "medium": 4, "niche": 7},
    tag_instructions=(
        "Lean heavily on niche tags (<10M searches). These are less competitive and capture "
        "buyers with very specific intent. Mainstream tags are okay if they're a perfect fit."
    ),
    short_rationale="Uses underused keywords to stand out from competitors.",
)

ANGLE_GIFT_FOCUSED = VariantAngle(
    label="Gift-focused",
    prompt_instructions=(
        "Lead with gift framing. Use 'Gift for [recipient]' style phrases. "
        "Recipients: Mom, Daughter, Wife, Girlfriend, Sister, Grandma. "
        "Still include core niche keyword but secondary to the gift angle."
    ),
    keyword_bias="gift_phrases",
    description_voice="heartfelt and emotional",
    description_instructions=(
        "Lead with the moment the recipient receives this gift. Reference common gift "
        "occasions (birthday, Mother's Day, anniversary, Christmas, graduation). "
        "Build product details around the gifting narrative."
    ),
    tag_distribution={"mainstream": 5, "medium": 5, "niche": 3},
    tag_instructions=(
        "Include 'Gift for X' patterns: gift for her, gift for mom, gift for daughter, etc. "
        "Mix gift-occasion tags (birthday gift, christmas gift, bridesmaid gift)."
    ),
    short_rationale="Targets gift-driven shoppers with recipient and occasion framing.",
)


# ── Seasonal / material swap-in angles ───────────────────────────────────────

ANGLE_HOLIDAY = VariantAngle(
    label="Holiday / Christmas",
    prompt_instructions=(
        "Lead with Christmas or holiday gift framing. Use 'Christmas Gift for [recipient]', "
        "'Stocking Stuffer', 'Holiday Gift'. Treat seasonality as the primary hook."
    ),
    keyword_bias="gift_phrases",
    description_voice="festive and warm",
    description_instructions=(
        "Open with a Christmas gifting scene. Reference holiday shipping urgency, "
        "gift-wrap availability, and the joy of giving. Tie the product attributes to "
        "why it's the perfect Christmas gift."
    ),
    tag_distribution={"mainstream": 5, "medium": 5, "niche": 3},
    tag_instructions=(
        "Include Christmas-specific tags: christmas gift, stocking stuffer, holiday jewelry, "
        "christmas necklace. Mix with recipient tags."
    ),
    short_rationale="Christmas / holiday season framing for Q4 gift demand.",
)

ANGLE_VALENTINES = VariantAngle(
    label="Valentine's Day",
    prompt_instructions=(
        "Lead with Valentine's Day gift angle. Use 'Valentine Gift for Her/Him', "
        "'Love Necklace', 'Romance' framing. Core product keyword second."
    ),
    keyword_bias="gift_phrases",
    description_voice="romantic and intimate",
    description_instructions=(
        "Open with a romantic gifting moment. Reference Valentine's Day, anniversary, "
        "love, and couples. Emphasise the emotional significance and premium feel."
    ),
    tag_distribution={"mainstream": 5, "medium": 5, "niche": 3},
    tag_instructions=(
        "Include: valentines gift, gift for her, love necklace, romantic jewelry, "
        "anniversary gift. Mix with core product tags."
    ),
    short_rationale="Valentine's Day and romance framing for February gifting demand.",
)

ANGLE_MOTHERS_DAY = VariantAngle(
    label="Mother's Day",
    prompt_instructions=(
        "Lead with Mother's Day gift framing. Use 'Gifts for Mom', 'Mother's Day Gift', "
        "'Gift for Grandma', 'Gift for Mom from Daughter'. "
        "Note: do NOT use the phrase 'Mother's Day Gift' verbatim in the title — "
        "use 'Gifts for Mom' instead (business rule). Core product keyword second."
    ),
    keyword_bias="gift_phrases",
    description_voice="warm and appreciative",
    description_instructions=(
        "Open with a Mother's Day gifting scene. Reference motherhood, gratitude, and "
        "family bonds. Include 'Gifts for Mom', graduation, and spring occasions."
    ),
    tag_distribution={"mainstream": 5, "medium": 5, "niche": 3},
    tag_instructions=(
        "Include: gifts for mom, mother necklace, mom jewelry, gift from daughter, "
        "mothers day gift. Avoid the exact phrase 'Mother's Day Gift' per business rules."
    ),
    short_rationale="Mother's Day framing for spring gifting demand.",
)

ANGLE_PREMIUM = VariantAngle(
    label="Premium / Fine Jewelry",
    prompt_instructions=(
        "Emphasise material quality and craftsmanship. Use 'Solid Gold', '14K Gold', "
        "'Fine Jewelry', 'Luxury' framing. Position as an investment piece, not just an accessory."
    ),
    keyword_bias="competitor_common",
    description_voice="elegant and premium",
    description_instructions=(
        "Lead with material quality and craftsmanship. Reference the gold purity, "
        "durability, and heirloom quality. Use sophisticated, premium vocabulary. "
        "Avoid casual phrasing."
    ),
    tag_distribution={"mainstream": 4, "medium": 5, "niche": 4},
    tag_instructions=(
        "Include: solid gold necklace, 14k gold jewelry, fine jewelry, luxury necklace, "
        "gold pendant. Balance with niche-specific tags."
    ),
    short_rationale="Positions as premium / fine jewelry to justify higher price point.",
)
