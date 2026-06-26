# Phase 6

From the Full Spec. Implement in order. Each step ends with a validation block.

---

## PHASE 6: LLM CONTENT PIPELINE

### Step 6.0: Variant Strategy (Architectural Foundation)
**Goal:** Define how the LLM pipeline produces **3 strategically distinct listing variants per product**, not a single output or 5 disjoint title options.

**Why three variants:**
Eğitim docs Section 1's title/tag rules are constraints, not strategy. Within those constraints multiple SEO angles exist. User wants to see 3 coherent listings, each pursuing a different angle, then pick one to publish (or hybridize). Each variant is a **complete, internally-consistent listing**: title + 13 tags + description all aligned with the same strategic angle.

**The 3 angles:**

| Variant | Angle | Title example | When to use |
|---------|-------|---------------|-------------|
| **A — Conservative** | Niche-focused, closest to competitor patterns. Safest SEO bet. | "Dainty Gold Cross Necklace, Tiny Sideways Cross Pendant..." | Mainstream niche, want quick organic ranking |
| **B — Differentiated** | Uses underused-keyword opportunities heavily. Novel angle. | "Confirmation Cross Necklace, Everyday Minimalist Christian Jewelry..." | Want to stand out, less competition |
| **C — Gift-focused** | Heavy emphasis on use case + gift recipient. | "Cross Necklace Gift for Daughter, Faith Necklace for Confirmation..." | Holiday seasons, gift-driven niches |

The variant assignment isn't hardcoded — the orchestrator picks the 3 most promising angles based on the research context. For some niches "Premium / 14K solid gold" might replace "Gift-focused"; for sport jewelry it might be "Team / fan-focused".

**Implementation contract:**
```python
@dataclass
class ListingVariant:
    """One complete, internally-consistent listing proposal."""
    variant_id: str            # "A", "B", "C"
    strategy_label: str        # e.g. "Conservative niche", "Differentiated", "Gift-focused"
    strategy_rationale: str    # 1-2 sentences explaining the angle (for human approval UI)
    title: str                 # 137-140 chars
    tags: list[str]            # exactly 13
    description: str           # 150-220 words
    estimated_ctr_signal: str  # "high" | "medium" | "low" — heuristic based on research alignment
    
@dataclass
class VariantBundle:
    """The 3 variants generated for a single product."""
    product_sku: str
    variants: list[ListingVariant]  # always 3, in order A/B/C
    shared_image_specs: ImageSpec   # images are variant-agnostic (same product)
    research_snapshot_id: str       # which research snapshot was used
    generated_at: datetime
```

**Key constraint:** Each variant uses the **same** research context (same niche, same competitors), but applies a **different generation prompt** that biases toward one strategic angle.

The orchestrator (Step 6.7, defined later) coordinates calls to the per-component generators (title, tags, description), passing each generator the chosen angle. Then it composes the final `VariantBundle`.

---

### Step 6.1: Anthropic Claude Client Wrapper
**Goal:** Centralized LLM client with prompt templates.

**Implementation:**
- Use `anthropic` SDK
- Wrapper class with methods for each content type
- All prompts stored in `src/config/prompts.py`
- Use Claude Sonnet 4.6 by default

**Validation:**
- Client successfully calls API
- Token usage logged
- Errors handled gracefully

---

### Step 6.2: Title Generator (Per Variant Angle)
**Goal:** Generate **1 title for a given strategic angle**. The orchestrator (Step 6.7) calls this 3 times — once per variant. Internally we still generate ~3 candidates per call and pick the best for that angle.

**Implementation:**
```python
class TitleGenerator:
    def __init__(self, llm_client, keyword_pool, validator, research_builder):
        self.llm = llm_client
        self.pool = keyword_pool
        self.validator = validator
        self.research = research_builder  # ResearchContextBuilder from Step 3.9

    async def generate_for_angle(self, product: Product, angle: VariantAngle) -> str:
        """
        Generate ONE title for the given strategic angle.
        Internally produces 3 candidates, validates them, picks the best.
        Retries with stronger angle bias if all fail validation.
        """
        prompt = self._build_prompt(product, angle)
        response = await self.llm.complete(prompt, max_tokens=800)
        candidates = self._parse_titles(response)

        # Validate
        valid = []
        for title in candidates:
            ok, violations = self.validator(title)
            if ok and not self._too_similar_to_competitors(product, title):
                valid.append(title)

        if not valid:
            # Retry once with adjusted prompt
            return await self._retry_with_relaxation(product, angle)

        # Pick the candidate with the best angle alignment score
        return self._pick_best_for_angle(valid, angle)

    def _build_prompt(self, product, angle: VariantAngle) -> str:
        keywords = self.pool.get_for_pillar(product.carrier_pillar)
        research_ctx = self.research.build_for_product(product)
        return TITLE_GENERATION_PROMPT.format(
            product_type=product.carrier_pillar,
            material=product.material,
            features=self._extract_features(product),
            keyword_pool=", ".join(keywords),
            research_brief=research_ctx.format_for_prompt(),
            angle_label=angle.label,           # NEW
            angle_instructions=angle.prompt_instructions,  # NEW
        )
```

**`VariantAngle` value object** (in `src/modules/llm/angles.py`):

```python
@dataclass
class VariantAngle:
    label: str  # "Conservative", "Differentiated", "Gift-focused"
    prompt_instructions: str  # The angle-specific guidance for the LLM
    keyword_bias: str  # "competitor_common" | "underused" | "gift_phrases"
    
ANGLE_CONSERVATIVE = VariantAngle(
    label="Conservative niche",
    prompt_instructions=(
        "Stay close to bestseller patterns. Use the most common phrases from the "
        "research brief's TITLE PATTERNS section. Aim for safe, proven SEO. "
        "Avoid novel angles."
    ),
    keyword_bias="competitor_common"
)

ANGLE_DIFFERENTIATED = VariantAngle(
    label="Differentiated",
    prompt_instructions=(
        "Use 2-3 keywords from the UNDERUSED HIGH-VALUE KEYWORDS section "
        "prominently. Find a fresh angle that no competitor in the brief uses. "
        "Still follow all hard rules but be bolder."
    ),
    keyword_bias="underused"
)

ANGLE_GIFT_FOCUSED = VariantAngle(
    label="Gift-focused",
    prompt_instructions=(
        "Lead with gift framing. Use 'Gift for [recipient]' style phrases. "
        "Recipients: Mom, Daughter, Wife, Girlfriend, Sister, Grandma. "
        "Still include core niche keyword but secondary to the gift angle."
    ),
    keyword_bias="gift_phrases"
)
```

**Prompt template skeleton** (in `src/config/prompts.py`):

```python
TITLE_GENERATION_PROMPT = """You are an Etsy SEO expert generating titles.

PRODUCT:
- Type: {product_type}
- Material: {material}
- Features: {features}

STRICT RULES (Section 1.1):
[... all the hardcoded rules ...]

KEYWORD POOL (base candidates):
{keyword_pool}

{research_brief}

STRATEGIC ANGLE FOR THIS GENERATION: {angle_label}
{angle_instructions}

INSTRUCTIONS:
1. Generate 3 candidate titles, each 137-140 chars
2. All 3 must adhere to the strategic angle above
3. Apply the structural patterns from the research brief, but DO NOT copy any title verbatim
4. Return ONLY the 3 titles, one per line, no numbering.
"""
```

**Validation:**
- Calling with `ANGLE_CONSERVATIVE` produces a title using competitor-common phrases (e.g. "dainty gold cross")
- Calling with `ANGLE_DIFFERENTIATED` produces a title using underused keywords from the research brief
- Calling with `ANGLE_GIFT_FOCUSED` produces a title starting with or prominently featuring gift framing
- All 3 angle outputs pass the validator (137-140 chars, no banned terms, etc.)
- Cold-start mode (no research data): all three angles still produce valid titles, falling back to keyword pool

---

### Step 6.3: Tag Generator (Per Variant Angle, Volume-Aware)
**Goal:** Generate **13 tags for a given strategic angle**, paired with the variant's title. Orchestrator (Step 6.7) calls this once per variant.

**Volume-aware strategy** (when EHunt tag volumes are present in research):
Each variant angle uses a different **volume profile** to differentiate. The research provides `volume_stratified_tags` with mainstream (>50M), medium (10–50M), and niche (<10M) buckets. Variants draw from these buckets in different ratios:

| Variant Angle | Mainstream | Medium | Niche | Rationale |
|---------------|-----------|--------|-------|-----------|
| A — Conservative | 6 tags | 4 tags | 3 tags | Safe SEO bet, ride proven traffic |
| B — Differentiated | 2 tags | 4 tags | 7 tags | Niche heavy → less competition, hyperspecific buyers |
| C — Gift-focused | 5 tags | 5 tags | 3 tags | Gift-pattern tags tend to be medium volume |

When volume data is unavailable (cold-start or no EHunt), fall back to the niche/medium/big distribution from training docs (8/3/2).

**Implementation:**
```python
class TagGenerator:
    def __init__(self, llm_client, keyword_pool, validator, research_builder):
        self.llm = llm_client
        self.pool = keyword_pool
        self.validator = validator
        self.research = research_builder  # ResearchContextBuilder from Step 3.9

    async def generate_for_angle(
        self, product: Product, angle: VariantAngle, paired_title: str
    ) -> list[str]:
        # Stage 1: Pool candidates for the carrier pillar
        pool_candidates = self.pool.get_candidates(
            pillar=product.carrier_pillar,
            features=product.shape,
            exclude_in_title=paired_title
        )

        # Stage 2: Research-derived candidates, stratified by volume when available
        research_ctx = self.research.build_for_product(product)
        volume_buckets = self._extract_volume_buckets(research_ctx)  # may be empty

        # Stage 3: Build the candidate pool for THIS angle
        if volume_buckets:
            # Volume-aware: pick from the right buckets per angle
            target = angle.tag_distribution  # e.g. {"mainstream": 6, "medium": 4, "niche": 3}
            angle_candidates = self._build_angle_pool(volume_buckets, target, pool_candidates)
            distribution_hint = (
                f"Use this volume mix: "
                f"{target['mainstream']} mainstream (>50M searches), "
                f"{target['medium']} medium (10-50M), "
                f"{target['niche']} niche (<10M). "
                "Each candidate is labeled with its search volume — prefer the right bucket per tag."
            )
        else:
            # Fallback: classic 8/3/2 niche/medium/big distribution
            research_tags = [t for t, _ in (research_ctx.top_tags[:30] if research_ctx.has_data else [])]
            angle_candidates = _merge_unique(research_tags, pool_candidates, max_items=60)
            distribution_hint = "Use the niche/medium/big distribution: 8 niche, 3 medium, 2 big."

        # Stage 4: LLM picks the final 13 honoring the angle and distribution
        prompt = TAG_GENERATION_PROMPT.format(
            candidates=self._format_candidates(angle_candidates),
            paired_title=paired_title,
            angle_label=angle.label,
            angle_instructions=angle.tag_instructions,
            distribution_hint=distribution_hint,
        )

        response = await self.llm.complete(prompt, max_tokens=400)
        tags = self._parse_tags(response)

        # Validate
        is_valid, violations = self.validator(tags, paired_title)
        if not is_valid:
            logger.warning(f"Tags rejected for variant {angle.label}: {violations}")
            # Retry once with a tighter prompt
            tags = await self._retry_generate(product, angle, paired_title, violations)

        return tags

    def _extract_volume_buckets(self, ctx) -> dict:
        """Pull volume_stratified_tags from research_ctx, or {} if not present."""
        if not ctx.has_data:
            return {}
        return getattr(ctx, 'volume_stratified_tags', None) or {}

    def _build_angle_pool(self, buckets: dict, target: dict, pool_candidates: list) -> list:
        """
        Build a candidate list weighted toward this angle's buckets.
        Format each candidate as "tag [vol: 47.3M]" so the LLM sees the volume.
        """
        result = []
        for bucket_name in ['mainstream', 'medium', 'niche']:
            slots = target.get(bucket_name, 0) * 2  # 2x oversample so LLM has choice
            items = buckets.get(bucket_name, [])[:slots]
            for tag, vol in items:
                result.append({"tag": tag, "volume": vol, "bucket": bucket_name})
        # Always include some pool candidates as ungrouped backup
        for tag in pool_candidates[:10]:
            if not any(r["tag"].lower() == tag.lower() for r in result):
                result.append({"tag": tag, "volume": None, "bucket": "pool"})
        return result
```

**Add to `VariantAngle`:**
```python
@dataclass
class VariantAngle:
    label: str
    prompt_instructions: str        # title
    keyword_bias: str
    description_voice: str          # description
    description_instructions: str
    tag_distribution: dict          # {"mainstream": int, "medium": int, "niche": int} — must sum to 13
    tag_instructions: str           # NEW — angle guidance for tags specifically
    variant_letter: str = "A"

ANGLE_CONSERVATIVE.tag_distribution = {"mainstream": 6, "medium": 4, "niche": 3}
ANGLE_CONSERVATIVE.tag_instructions = "Prefer high-volume proven tags. The shop is going for safe SEO."

ANGLE_DIFFERENTIATED.tag_distribution = {"mainstream": 2, "medium": 4, "niche": 7}
ANGLE_DIFFERENTIATED.tag_instructions = (
    "Lean heavily on niche tags (<10M searches). These are less competitive and capture "
    "buyers with very specific intent. Mainstream tags are okay if they're a perfect fit."
)

ANGLE_GIFT_FOCUSED.tag_distribution = {"mainstream": 5, "medium": 5, "niche": 3}
ANGLE_GIFT_FOCUSED.tag_instructions = (
    "Include 'Gift for X' patterns: gift for her, gift for mom, gift for daughter, etc. "
    "Mix gift-occasion tags (birthday gift, christmas gift, bridesmaid gift)."
)
```

**Prompt template additions:**
```
STRATEGIC ANGLE: {angle_label}
{angle_instructions}

DISTRIBUTION REQUIREMENT:
{distribution_hint}

PAIRED TITLE (tags must complement, not duplicate, words already in title):
{paired_title}

CANDIDATE TAGS (with search volumes where known — prefer these over invented tags):
{candidates}

INSTRUCTIONS:
1. Pick exactly 13 tags following the distribution above
2. Each tag 2-20 characters
3. No duplicate words across tags
4. Don't repeat substantial phrases that are already in the title
5. Return ONLY the 13 tags as a comma-separated list, no numbering.
```

**Validation:**
- Returns exactly 13 tags
- When volume data present: distribution matches `target` within ±1 tag per bucket
- When volume data absent: distribution matches 8/3/2 niche/medium/big (classic rule)
- All pass tag validator
- No duplicates with title
- When research data exists: at least 50% of selected tags should come from research-derived candidates (log this ratio)
- Variant A and B tag sets should differ by ≥50% (different buckets pull different tags)

---

### Step 6.4: Description Generator (Per Variant Angle)
**Goal:** Generate **1 description for a given strategic angle**, aligned with that variant's title and tags. The orchestrator (Step 6.7) calls this 3 times.

**Implementation:**
```python
class DescriptionGenerator:
    def __init__(self, llm_client, originality_checker, research_builder):
        self.llm = llm_client
        self.originality = originality_checker
        self.research = research_builder

    async def generate_for_angle(
        self, product: Product, angle: VariantAngle, paired_title: str, paired_tags: list[str]
    ) -> str:
        """
        Generate ONE description for the given angle. The title and tags from the
        SAME variant are passed in so the description echoes the same vocabulary —
        keeps the variant internally consistent.
        """
        research_ctx = self.research.build_for_product(product)
        all_cliches = list(set(
            CLICHE_DESCRIPTION_PHRASES + research_ctx.cliches_to_avoid
        ))

        prompt = DESCRIPTION_GENERATION_PROMPT.format(
            product=product.to_dict(),
            voice=angle.description_voice,  # angle-specific tone
            paired_title=paired_title,        # NEW — for internal consistency
            paired_tags=", ".join(paired_tags),  # NEW
            forbidden_cliches=all_cliches,
            research_brief=research_ctx.format_for_prompt() if research_ctx.has_data else "",
            angle_label=angle.label,
            angle_instructions=angle.description_instructions
        )

        # Try up to 3 times to get one that passes all checks
        for attempt in range(3):
            response = await self.llm.complete(prompt, max_tokens=600)
            draft = self._parse_description(response)

            found_cliches = self.originality.check_cliches(draft)
            if found_cliches:
                logger.warning(f"Cliches found (attempt {attempt+1}): {found_cliches}")
                continue

            is_original, similarity = self.originality.check(draft)
            if not is_original:
                logger.warning(f"Too similar to existing (attempt {attempt+1}): {similarity:.2f}")
                continue

            return draft

        # All 3 attempts failed — return the last one with logged warnings
        logger.error("Description generator failed all originality checks; using fallback")
        return draft
```

**Add to `VariantAngle`:**
```python
@dataclass
class VariantAngle:
    label: str
    prompt_instructions: str        # for titles
    keyword_bias: str
    description_voice: str          # NEW — e.g. "warm and personal", "elegant and premium"
    description_instructions: str   # NEW — angle guidance for description specifically
    tag_distribution: dict          # NEW — see Step 6.3

ANGLE_CONSERVATIVE.description_voice = "warm and personal"
ANGLE_CONSERVATIVE.description_instructions = (
    "Standard product description structure. Lead with what it is, then quality, "
    "then occasions. Use the most common 2-3 phrases from research brief title patterns."
)

ANGLE_DIFFERENTIATED.description_voice = "fresh and distinctive"
ANGLE_DIFFERENTIATED.description_instructions = (
    "Open with an unconventional hook — sensory detail or specific use case. "
    "Avoid generic openers entirely. Include 1-2 underused keywords from research brief."
)

ANGLE_GIFT_FOCUSED.description_voice = "heartfelt and emotional"
ANGLE_GIFT_FOCUSED.description_instructions = (
    "Lead with the moment the recipient receives this gift. Reference common gift "
    "occasions (birthday, Mother's Day, anniversary, Christmas, graduation). "
    "Build product details around the gifting narrative."
)
```

**Prompt template additions:**
```
STRATEGIC ANGLE: {angle_label}
{angle_instructions}

INTERNAL CONSISTENCY (this description must echo the variant's title/tags):
- Title: {paired_title}
- Tags: {paired_tags}
- Reuse 3-5 phrases from the title and 2-3 tag concepts in the description body
- Do NOT contradict the angle established by the title

VOICE: {voice}
```

**Validation:**
- Description for `ANGLE_CONSERVATIVE` uses common phrases from title patterns
- Description for `ANGLE_DIFFERENTIATED` uses underused keywords + unconventional opening
- Description for `ANGLE_GIFT_FOCUSED` leads with gift scenario, mentions occasions
- All 3 pass originality check (similarity < 0.85) and cliché check
- Each is 150-220 words
- Each reuses ≥3 phrases from its paired title (verifies internal consistency)

---

### Step 6.5: Mağaza-Internal Link Inserter
**Goal:** Add 2-3 internal links to similar products in the description.

**Implementation:**
- Query Product DB for live products in same carrier pillar
- Format as: `View our [Cross Necklace Collection](etsy-link)`
- Insert at end of description

**CRITICAL** (Section 1.3 rule):
- Links must point to actually similar products that exist
- If pillar has no other products, skip the link

**Validation:**
- Description has 2-3 internal links
- All links resolve to existing products
- Links categorized correctly

---

### Step 6.6: Keyword Pool Management
**Goal:** Manage the keyword pool table.

**Implementation:**
- Route: `GET /admin/keywords` — view all
- Route: `POST /admin/keywords/import` — import from CSV
- CSV format: `keyword, category, carrier_pillar`
- Categories: `niche`, `medium`, `big`
- User loads CSV file once at setup

**Validation:**
- Import 200+ keywords from CSV
- Categories distributed correctly
- Query by pillar returns relevant ones

---

### Step 6.7: VariantBundle Orchestrator
**Goal:** Compose the **3 final ListingVariants** for a product by coordinating per-component generators across angles. This is the entry point Phase 7 (Human Approval UI) calls.

**Implementation:**
```python
class VariantBundleOrchestrator:
    def __init__(self, title_gen, tag_gen, desc_gen, internal_linker, research_builder):
        self.title = title_gen
        self.tag = tag_gen
        self.desc = desc_gen
        self.linker = internal_linker
        self.research = research_builder

    async def generate_bundle(self, product: Product) -> VariantBundle:
        """Generate all 3 variants in parallel where possible."""
        # Pick the 3 angles for this niche. Default is A/B/C but research-driven
        # niches may swap (e.g. seasonal niches use ANGLE_HOLIDAY instead of GIFT).
        angles = self._select_angles_for_niche(product)

        # Generate the 3 variants. Each variant's title → tags → description must be
        # internally consistent, so we serialize within a variant but parallelize across.
        variant_tasks = [
            self._generate_one_variant(product, angle) for angle in angles
        ]
        variants = await asyncio.gather(*variant_tasks)

        snapshot = self.research.current_snapshot_id(product.carrier_pillar)
        return VariantBundle(
            product_sku=product.sku,
            variants=variants,
            shared_image_specs=product.image_specs,  # images same for all variants
            research_snapshot_id=snapshot,
            generated_at=datetime.utcnow()
        )

    async def _generate_one_variant(
        self, product: Product, angle: VariantAngle
    ) -> ListingVariant:
        # 1) Title first — it anchors the variant
        title = await self.title.generate_for_angle(product, angle)

        # 2) Tags — they should reuse keywords from the title
        tags = await self.tag.generate_for_angle(product, angle, paired_title=title)

        # 3) Description — uses title and tags for internal consistency
        description = await self.desc.generate_for_angle(
            product, angle, paired_title=title, paired_tags=tags
        )

        # 4) Internal links (Step 6.5) appended to description
        description = await self.linker.insert_links(description, product)

        # 5) Estimate CTR signal — heuristic based on how aligned the variant is
        #    with high-sales research signals
        ctr = self._estimate_ctr_signal(title, tags, angle, product)

        return ListingVariant(
            variant_id=angle.variant_letter,  # "A", "B", "C"
            strategy_label=angle.label,
            strategy_rationale=self._build_rationale(angle, product),
            title=title,
            tags=tags,
            description=description,
            estimated_ctr_signal=ctr
        )

    def _select_angles_for_niche(self, product: Product) -> list[VariantAngle]:
        """
        Pick the 3 most relevant angles for this niche.
        Default: [Conservative, Differentiated, Gift-focused]
        For sport jewelry: swap GIFT for TEAM/FAN
        For premium materials (14K solid): swap CONSERVATIVE for PREMIUM
        For seasonal periods (Oct-Dec): swap GIFT for HOLIDAY (specific occasion)
        """
        base = [ANGLE_CONSERVATIVE, ANGLE_DIFFERENTIATED, ANGLE_GIFT_FOCUSED]

        # Season-aware swap
        today = datetime.utcnow()
        if today.month in [10, 11, 12]:
            base[2] = ANGLE_HOLIDAY  # Christmas/Black Friday framing
        elif today.month in [2]:
            base[2] = ANGLE_VALENTINES
        elif today.month in [4, 5]:
            base[2] = ANGLE_MOTHERS_DAY

        # Material-aware swap
        if "solid gold" in product.material.lower() or "14k" in product.material.lower():
            base[0] = ANGLE_PREMIUM

        # Tag letters so user sees A/B/C consistently
        for letter, angle in zip(["A", "B", "C"], base):
            angle.variant_letter = letter

        return base

    def _estimate_ctr_signal(self, title, tags, angle, product) -> str:
        """Cheap heuristic — not an ML model, just a sanity flag.
        Compares variant against bestseller patterns from research."""
        research = self.research.build_for_product(product)
        if not research.has_data:
            return "unknown"

        # How many top-pattern phrases appear in title?
        top_patterns = research.top_title_ngrams[:10]
        hits = sum(1 for p in top_patterns if p.lower() in title.lower())

        if hits >= 3: return "high"
        if hits >= 1: return "medium"
        return "low"

    def _build_rationale(self, angle: VariantAngle, product: Product) -> str:
        """1-2 sentence human-readable explanation shown in approval UI."""
        return f"{angle.label}: {angle.short_rationale}"
```

**Why 3 angles per niche, not 5 or 10:**
- Each variant uses ~2K LLM tokens for title+tags+description → 3 variants ≈ 6K tokens / product
- 10 products/day × 6K = 60K tokens/day, well within Anthropic API budget
- More than 3 variants overwhelms the approval UI and decision-making

**Validation:**
- For a test product with research data: `generate_bundle()` returns exactly 3 `ListingVariant`s
- Each variant has different `strategy_label` and `variant_id` ("A", "B", "C")
- Within a variant: title/tags/description share ≥3 common phrases (internal consistency)
- Across variants: title bigrams differ by ≥40% (variants are actually distinct)
- Generation completes in <60 seconds total (parallel angle execution)
- Cold-start mode: all 3 variants still generated, falling back to keyword pool

---