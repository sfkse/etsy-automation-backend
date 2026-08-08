"""
Phase 6 — LLM prompt templates.

All prompts live here. Generators import and `.format()` them with their
per-call context. Never inline prompt strings inside generator classes.
"""

from src.config.business_rules import TITLE_MAX_LENGTH, TITLE_MIN_LENGTH

# ── Title Generation ──────────────────────────────────────────────────────────

# Section F of OPERATIONAL_INTEGRATION.md — approved adjective vocabulary that
# the model should draw from consistently across variants.
JEWELRY_ADJECTIVE_LADDER = f"""\
APPROVED ADJECTIVE VOCABULARY (use these to vary titles within the {TITLE_MIN_LENGTH}-{TITLE_MAX_LENGTH} char limit):

Personalization-type adjectives (pick 1-2 per title):
- Custom
- Personalized
- Customized

Aesthetic adjectives (pick 1-2 per title):
- Dainty
- Minimalist

Material adjectives (pick 1, must match the actual material):
- Gold
- 14K Gold        (only if actually 14K solid or 14K plated)
- Silver
- Sterling Silver (only if 925 sterling — never for brass)

Forbidden combinations:
- "Solid Gold" + "Gold Plated" — never both in the same title
- "Sterling Silver" + brass material — never together
- "Stone" alone — use "CZ" or "Pave" instead
- "Pendant" alone — always "Pendant Necklace"

Shape descriptors (use only if the visible product has that shape):
- Drop / Water Drop  (for teardrop-shaped stones)
- Heart
- Round
- Pear
- Marquise
- Pave
- Baguette
"""


TITLE_GENERATION_PROMPT = f"""\
You are an expert Etsy SEO copywriter specialising in jewelry listings.

PRODUCT:
- Type: {{product_type}}
- Material: {{material}}
- Features: {{features}}

TARGET KEYWORD (must appear naturally, ideally within the first 60 characters): {{target_keyword}}

STRICT RULES (must never be violated):
1. Each title must be {TITLE_MIN_LENGTH}-{TITLE_MAX_LENGTH} characters (count carefully).
2. Do NOT use any of these forbidden keywords: Stone, Mother's Day Gift, Diamond (for non-solid-gold), Floral (unless product has actual flowers).
3. "Pendant" must always appear as "Pendant Necklace", never alone.
4. Do NOT use both "Solid Gold" and "Gold Plated" in the same title.
5. No repeated non-stop words (stop words: and, for, the, with, a, an, of, in, to, by, at).
6. Separate phrase groups with ", " (comma + space). Never use "|".
7. The first 60 characters must contain the core niche keyword.

{{adjective_ladder}}

KEYWORD POOL (base candidates — use these, do not invent keywords):
{{keyword_pool}}

{{research_brief}}

STRATEGIC ANGLE FOR THIS GENERATION: {{angle_label}}
{{angle_instructions}}

INSTRUCTIONS:
1. Generate exactly 3 candidate titles.
2. All 3 must strongly reflect the strategic angle above.
3. Apply structural patterns from the research brief, but DO NOT copy any competitor title verbatim.
4. Count characters precisely. Titles outside {TITLE_MIN_LENGTH}-{TITLE_MAX_LENGTH} chars will be rejected.
5. Return ONLY the 3 titles, one per line, no numbering, no extra text.
"""

# ── Tag Generation ────────────────────────────────────────────────────────────

TAG_GENERATION_PROMPT = """\
You are an expert Etsy SEO specialist generating tags for a jewelry listing.

STRICT RULES (must never be violated):
1. Return EXACTLY 13 tags.
2. Each tag must be 2-20 characters (including spaces).
3. No duplicate tags (case-insensitive).
4. Do NOT use the phrase "Mother's Day Gift" — use "gifts for mom" instead.
5. Do NOT repeat phrases already prominent in the paired title (those slots are wasted).
6. Tags should be multi-word phrases when possible (2-4 words) — single generic words rank poorly.

PAIRED TITLE (tags must complement, not duplicate, this title):
{paired_title}

STRATEGIC ANGLE: {angle_label}
{angle_instructions}

DISTRIBUTION REQUIREMENT:
{distribution_hint}

CANDIDATE TAGS (prefer these over invented ones — they come from real competitor data):
{candidates}

INSTRUCTIONS:
1. Pick exactly 13 tags following the distribution requirement above.
2. Prefer candidates from the list above. Only invent tags if the list is insufficient.
3. Prioritise tags that a buyer would actually type into the Etsy search bar.
4. Return ONLY the 13 tags as a comma-separated list on a single line. No numbering, no extra text.
"""

# ── Description Generation ────────────────────────────────────────────────────

DESCRIPTION_GENERATION_PROMPT = """\
You are an expert Etsy copywriter generating product descriptions for a jewelry listing.

PRODUCT:
{product_summary}

STRICT RULES (must never be violated):
1. Length: 150-220 words (count carefully).
2. Do NOT use any of these cliché phrases: {forbidden_cliches}
3. Be specific — avoid vague generalities.
4. No markdown formatting (no **, no bullet points with -, no headers). Plain paragraphs only.
5. Reuse at least 3-5 phrases from the paired title and 2-3 concepts from the paired tags.

INTERNAL CONSISTENCY — this description must echo its variant's title and tags:
- Paired title: {paired_title}
- Paired tags: {paired_tags}
- Reinforce the same vocabulary and angle as the title — do NOT contradict it.

STRATEGIC ANGLE: {angle_label}
VOICE: {voice}
{angle_instructions}

{research_brief}

INSTRUCTIONS:
1. Write ONE description, 150-220 words, as plain prose paragraphs.
2. Apply the voice and angle instructions above as the primary creative direction.
3. Count words precisely before returning.
4. Return ONLY the description text. No labels, no extra commentary.
"""
