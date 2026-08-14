"""
Phase 6 — LLM prompt templates.

All prompts live here. Generators import and `.format()` them with their
per-call context. Never inline prompt strings inside generator classes.
"""

from src.config.business_rules import (
    TAG_COUNT,
    TAG_MAX_LENGTH,
    TITLE_FIRST_NICHE_CHARS,
    TITLE_MAX_LENGTH,
    TITLE_MIN_LENGTH,
)

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


NOUN_VARIATION_LADDER = """\
NOUN VARIATION VOCABULARY (rotate these within a title to avoid repeating the
same word 5 times):

Necklace family:
- Necklace
- Pendant Necklace  (never just "Pendant" — always "Pendant Necklace")
- Chain Necklace
- Choker  (short 14-16 inch)

Bracelet family:
- Bracelet
- Bangle  (rigid, slip-on)
- Cuff Bracelet  (open, C-shaped)
- Wristband  (casual, softer term)

Earring family:
- Earrings
- Studs  (small, close to earlobe)
- Drop Earrings  (dangle)
- Hoop Earrings

Ring family:
- Ring
- Band  (plain/thin ring)
- Signet Ring  (flat top with engraving)

Rule: use 2-3 different noun variations from the same family within a single
title if possible. E.g. "Dainty Cross Necklace, Tiny Cross Pendant Necklace,
Sideways Cross Chain Necklace" uses 3 noun variations of the necklace family.
"""


# Prompt-caching split: the STATIC prefix is byte-identical across every title
# call (preamble + strict rules + both ladders) and is sent as a cached content
# block; the DYNAMIC template carries the per-product/per-angle fields. Assemble
# order is [static prefix] + [dynamic] — see src/utils/llm_client.py.
TITLE_STATIC_PREFIX = f"""\
You are an expert Etsy SEO copywriter specialising in jewelry listings.

STRICT RULES (must never be violated):
1. Each title must be {TITLE_MIN_LENGTH}-{TITLE_MAX_LENGTH} characters (count carefully).
2. Do NOT use any of these forbidden keywords: Stone, Mother's Day Gift, Diamond (for non-solid-gold), Floral (unless product has actual flowers).
3. "Pendant" must always appear as "Pendant Necklace", never alone.
4. Do NOT use both "Solid Gold" and "Gold Plated" in the same title.
5. No repeated non-stop words (stop words: and, for, the, with, a, an, of, in, to, by, at).
6. Separate phrase groups with ", " (comma + space). Never use "|".
7. The first 60 characters must contain the core niche keyword.
8. Use 2-3 different noun variations from the same family (see NOUN
   VARIATION VOCABULARY below) to expand keyword coverage.

{JEWELRY_ADJECTIVE_LADDER}

{NOUN_VARIATION_LADDER}"""


TITLE_DYNAMIC_TEMPLATE = f"""\
PRODUCT:
- Type: {{product_type}}
- Material: {{material}}
- Features: {{features}}

TARGET KEYWORD (must appear naturally, ideally within the first 60 characters): {{target_keyword}}

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

# Prompt-caching split (see TITLE_STATIC_PREFIX). The static prefix here is
# small (preamble + rules); it is well below the Sonnet-4.5 1024-token cache
# floor, so on that model it is a harmless no-op — plumbed for uniformity and to
# future-proof for larger models/prefixes.
TAG_STATIC_PREFIX = """\
You are an expert Etsy SEO specialist generating tags for a jewelry listing.

STRICT RULES (must never be violated):
1. Return EXACTLY 13 tags.
2. Each tag must be 2-20 characters (including spaces).
3. No duplicate tags (case-insensitive).
4. Do NOT use the phrase "Mother's Day Gift" — use "gifts for mom" instead.
5. Do NOT repeat phrases already prominent in the paired title (those slots are wasted).
6. Tags should be multi-word phrases when possible (2-4 words) — single generic words rank poorly."""


TAG_DYNAMIC_TEMPLATE = """\
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

# ── Batch Variant Generation (title + tags, all 3 variants in one call) ───────

# Single self-contained prompt (no cached_prefix split): the static rules block is
# below the Sonnet-4.5 1024-token cache floor, so caching would be a no-op today.
# The LLM sees all 3 angles at once so it can deliberately DIFFERENTIATE the
# variants (Christmas-2 principle). Numeric limits are interpolated from
# business_rules so the prompt can never drift from validators.py.
BATCH_VARIANT_PROMPT = f"""\
You are an expert Etsy SEO copywriter specialising in jewelry listings.

Generate a title + {TAG_COUNT} tags for EACH of 3 DIFFERENT strategic angles for the
SAME product. The 3 variants MUST be internally distinct — different keyword mixes,
different framing. Do not let them converge on the same phrasing.

PRODUCT:
{{product_summary}}

RESEARCH BRIEF:
{{research_brief}}

VARIANT ANGLES:
A - {{angle_a_label}}: {{angle_a_instructions}}
    Tag distribution: {{angle_a_distribution}}
B - {{angle_b_label}}: {{angle_b_instructions}}
    Tag distribution: {{angle_b_distribution}}
C - {{angle_c_label}}: {{angle_c_instructions}}
    Tag distribution: {{angle_c_distribution}}

STRICT RULES (apply to every variant):
1. Title: exactly {TITLE_MIN_LENGTH}-{TITLE_MAX_LENGTH} characters (count carefully).
2. First {TITLE_FIRST_NICHE_CHARS} characters of the title: niche-descriptive, NOT gift framing.
3. Exactly {TAG_COUNT} tags per variant, each 2-{TAG_MAX_LENGTH} characters.
4. No word may appear both in a variant's title and in its own tags (wasted slot).
5. No two variants may share more than 50% of their tag set — differ meaningfully.
6. Forbidden: "Stone" alone (use "CZ" / "Pave"); "Pendant" alone (always "Pendant Necklace");
   "Solid Gold" and "Gold Plated" together in the same title.
7. Separate title phrase groups with ", " (comma + space). Never use "|".

RETURN STRICT JSON ONLY — no markdown fences, no preamble, no trailing commentary:
{{{{
  "variant_a": {{{{ "title": "...", "tags": ["tag1", "tag2", ..., "tag{TAG_COUNT}"] }}}},
  "variant_b": {{{{ "title": "...", "tags": ["tag1", "tag2", ..., "tag{TAG_COUNT}"] }}}},
  "variant_c": {{{{ "title": "...", "tags": ["tag1", "tag2", ..., "tag{TAG_COUNT}"] }}}}
}}}}
"""


# ── Description Generation ────────────────────────────────────────────────────

# Prompt-caching split (see TITLE_STATIC_PREFIX). Rule 2's cliché list is
# per-product (research-derived), so it lives in the DYNAMIC template as its own
# FORBIDDEN CLICHÉS block — keeping the static prefix byte-stable. As with tags,
# this prefix is below the Sonnet-4.5 cache floor and is a harmless no-op there.
DESCRIPTION_STATIC_PREFIX = """\
You are an expert Etsy copywriter generating product descriptions for a jewelry listing.

STRICT RULES (must never be violated):
1. Length: 150-220 words (count carefully).
2. Be specific — avoid vague generalities.
3. No markdown formatting (no **, no bullet points with -, no headers). Plain paragraphs only.
4. Reuse at least 3-5 phrases from the paired title and 2-3 concepts from the paired tags.
5. Do NOT use any of the forbidden cliché phrases listed below."""


DESCRIPTION_DYNAMIC_TEMPLATE = """\
PRODUCT:
{product_summary}

FORBIDDEN CLICHÉS (must never appear): {forbidden_cliches}

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


# Aggressive rewrite prompt used as the "escape hatch" when a draft is
# catastrophically similar to the existing corpus (or on the last shapeable
# retry). Unlike the soft reminder appended by _add_originality_reminder, this
# replaces the whole dynamic body: it quotes the rejected draft and the specific
# corpus sentences it echoed, and demands a structurally different rewrite. It is
# still sent with DESCRIPTION_STATIC_PREFIX as cached_prefix, so the strict
# length / no-cliché rules continue to apply.
DESCRIPTION_RETRY_PROMPT = """\
Your previous description was TOO SIMILAR to existing listings
(similarity: {similarity:.2f} — the acceptable threshold is 0.85 or lower).

REJECTED DRAFT:
{rejected_draft}

COMMON PATTERNS DETECTED (avoid ALL of these):
{similar_phrases}

Rewrite the description with:
1. A completely different opening sentence structure — do NOT start with
   the same subject as the rejected draft.
2. At least 3 sensory or specific detail hooks that were absent before
   (texture, weight, light interaction, specific occasion moment).
3. Different paragraph ordering — if you led with product features, lead
   with recipient emotion this time (or vice versa).
4. Preserve the paired title and tag vocabulary, but express it differently.

PRODUCT + PAIRED CONTEXT (same as before):
{product_summary}
Paired title: {paired_title}
Paired tags: {paired_tags}
Voice: {voice}

Return ONLY the rewritten description, 150-220 words.
"""
