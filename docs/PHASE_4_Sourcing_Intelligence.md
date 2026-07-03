# PHASE 4: SOURCING INTELLIGENCE MODULE
## Reverse Sourcing — Rexven Product → Etsy Keyword + Rank Prediction

> **Purpose:** Given a Rexven supplier product (image + metadata), determine (a) which Etsy keywords this product can realistically rank for, and (b) where it would likely appear in search results. This module reverses the existing research flow: instead of "I have a keyword, scrape competitors", it answers "I have a product, find me keywords".
>
> **Why this matters:** The system currently requires the user to know which keyword to scrape in Phase 1. The "Adım B — gözünü kapat ürünleri tarif et" step from `Keyword_Strategy.md` is currently manual (10 minutes per product, error-prone, biased). Phase 4 automates this with three composable layers (A/B/C) that can be deployed independently or combined.
>
> **Input:** Rexven product URL OR uploaded jewelry image OR existing Rexven product SKU already in DB.
> **Output:** Ranked list of 5 recommended Etsy keywords + per-keyword opportunity score + estimated search page position + suggested tag pool (feeds Phase 6 content pipeline).
>
> **Prerequisites (backend already completed):**
> - Phase 1 scraper exists (top-60 listings per keyword)
> - `CompetitorListing`, `KeywordResearch`, `CompetitorShop` tables populated
> - EHunt enrichment columns present (`eh_sales_total`, `eh_sales_recent`, `eh_listed_date`, etc.)
> - Anthropic client wired up (used by Phase 6)
> - FastAPI router pattern established
> - Chrome extension v2.4+ deployed

---

## SECTION 4.0: ARCHITECTURAL OVERVIEW

### The Three Layers

Phase 4 is structured as three composable layers. Each can ship independently and provides value alone, but they combine multiplicatively.

```
┌─────────────────────────────────────────────────────────────────┐
│                  PHASE 4: SOURCING INTELLIGENCE                  │
└─────────────────────────────────────────────────────────────────┘

LAYER A — Vision-LLM Keyword Suggester           (Section 4.1-4.3)
    ┌────────────────────────────────────────┐
    │ Rexven image  →  Claude Sonnet 4.6     │
    │                  vision API             │
    │                       │                 │
    │                       ▼                 │
    │              15 keyword candidates      │
    │   (8-10 niche / 3-5 medium / 1-2 broad) │
    └────────────────────────────────────────┘
         │
         │  candidates fed into ↓
         ▼
LAYER B — Opportunity Scoring                    (Section 4.4-4.6)
    ┌────────────────────────────────────────┐
    │ For each candidate:                     │
    │   - Trigger mini-Phase-1 (top 20)       │
    │   - Compute opportunity score using:    │
    │     · shop_age distribution             │
    │     · price band alignment              │
    │     · eh_sales_recent activity          │
    │     · keyword_total_results             │
    │     · single-shop dominance penalty     │
    │   - Output: 5 ranked keywords + scores  │
    └────────────────────────────────────────┘
         │
         │  enriched by ↓ (optional but powerful)
         ▼
LAYER C — CLIP Visual Similarity                 (Section 4.7-4.12)
    ┌────────────────────────────────────────┐
    │ Pre-computed embeddings on entire       │
    │ CompetitorListing table.                │
    │                                          │
    │ Rexven image  →  CLIP embedding         │
    │                       │                  │
    │                       ▼                  │
    │   Top-50 visually-similar listings       │
    │   from existing scrape data              │
    │                       │                  │
    │   ┌───────────────────┴────────────────┐ │
    │   ▼                                    ▼ │
    │ Empirical keyword distribution   Estimated │
    │ (which keywords do similar       rank      │
    │  products actually rank for?)              │
    └────────────────────────────────────────┘
```

### Layer dependencies and ship order

| Layer | Depends on | Standalone value | Build time |
|-------|-----------|------------------|------------|
| A | Anthropic vision API | Replaces manual brainstorm step | 1-2 days |
| B | Layer A output + existing Phase 1 scraper | Validates keywords against real market data | 1 week |
| C | `CompetitorListing` table populated + CLIP model | Empirical, not LLM-guessed | 2 weeks |

**Ship order:** A → B → C. Each builds on the previous but each is also independently useful. C can run in "shadow mode" alongside A+B for several weeks, then graduate to the primary signal once the embedding DB is dense enough (~5,000+ listings recommended).

### Module boundaries

- **Phase 4 consumes** read-only from `CompetitorListing`, `KeywordResearch`. Never writes to those tables.
- **Phase 4 produces** new tables (`SourcingAnalysis`, `KeywordCandidate`, `KeywordScore`, `RexvenProductEmbedding`) and a new column on `CompetitorListing` (`image_embedding`).
- **Phase 4 outputs into Phase 6:** when a user clicks "Generate Content" on a Rexven product, the chosen `KeywordScore` row is injected into the content pipeline's context — title/tag/description generation is grounded in the winning keyword's real top-20 patterns.
- **Phase 4 does NOT touch:** Etsy upload (Phase 8), AI image generation (Phase 5), originality check.

### Integration with existing user flow

Update the existing **3 Loops** model from Section 0:

| Loop | Cadence | What changes with Phase 4 |
|------|---------|---------------------------|
| Research Loop | Weekly | Now optionally triggered BY Phase 4 instead of starting it. User points at a Rexven product → Phase 4 picks keywords → Research Loop scrapes deeper if needed. |
| Production Loop | Per-product | Now starts with Sourcing analysis instead of manual keyword entry. Pipeline becomes: Sourcing → Keyword choice → Content + Image (Stage 2 parallel) → Approval. |
| Operations Loop | Daily | Unchanged. |

---

## LAYER A — Vision-LLM Keyword Suggester

### Step 4.1: Sourcing Domain Models
**Goal:** SQLAlchemy models for sourcing analysis runs and keyword candidates.

**Implementation:**

Add to `src/db/models.py`:

```python
class SourcingAnalysis(Base):
    """One row per 'analyze this Rexven product' invocation."""
    __tablename__ = "sourcing_analyses"
    
    id = Column(Integer, primary_key=True)
    
    # Source identification — accept any of three inputs
    rexven_url = Column(String(500), nullable=True, index=True)
    rexven_sku = Column(String(50), nullable=True, index=True)  # if product already in Product table
    image_path = Column(String(500), nullable=True)  # local path to uploaded jewelry image
    image_url = Column(String(500), nullable=True)   # remote URL if scraped from Rexven
    
    # Rexven metadata (scraped or manually provided)
    rexven_title_tr = Column(String(255))   # "Multicolor CZ Stone and Gold Disc Station Chain Necklace"
    rexven_title_en = Column(String(255))
    rexven_cost_usd_cents = Column(Integer)         # supplier cost (e.g. 738 for $7.38)
    rexven_premium_cost_usd_cents = Column(Integer) # premium-tier price (e.g. 660 for $6.60)
    rexven_category = Column(String(50))            # "Kolye", "Küpe", "Bileklik", etc.
    rexven_has_satisa_uygun_badge = Column(Boolean, default=False)  # red "satışa uygun" marker
    rexven_has_yeni_badge = Column(Boolean, default=False)
    
    # Analysis state
    status = Column(Enum(SourcingStatus), default=SourcingStatus.PENDING)
    layer_a_completed = Column(Boolean, default=False)
    layer_b_completed = Column(Boolean, default=False)
    layer_c_completed = Column(Boolean, default=False)
    error_message = Column(Text, nullable=True)
    
    # Cost tracking
    vision_tokens_used = Column(Integer, default=0)
    vision_cost_usd_cents = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    candidates = relationship("KeywordCandidate", back_populates="analysis", cascade="all, delete-orphan")
    scores = relationship("KeywordScore", back_populates="analysis", cascade="all, delete-orphan")


class SourcingStatus(str, Enum):
    PENDING = "pending"
    LAYER_A_RUNNING = "layer_a_running"   # vision LLM
    LAYER_B_RUNNING = "layer_b_running"   # mini Phase 1 + scoring
    LAYER_C_RUNNING = "layer_c_running"   # CLIP similarity
    COMPLETED = "completed"
    FAILED = "failed"


class KeywordCandidate(Base):
    """Raw output from Layer A — keyword candidate before scoring."""
    __tablename__ = "keyword_candidates"
    
    id = Column(Integer, primary_key=True)
    analysis_id = Column(Integer, ForeignKey("sourcing_analyses.id"), nullable=False)
    
    keyword = Column(String(100), nullable=False, index=True)
    tier = Column(Enum(KeywordTier), nullable=False)  # NICHE / MEDIUM / BROAD
    
    # Vision-LLM reasoning — why this keyword?
    rationale = Column(Text)                # "tennis racket pendant + sport-themed niche"
    detected_attributes = Column(JSON)      # {"form": "racket", "style": "pave", "theme": "sport"}
    
    # Source — which layer proposed this candidate?
    source_layer = Column(String(10), default="A")  # "A" or "C" (when C suggests novel keywords)
    
    analysis = relationship("SourcingAnalysis", back_populates="candidates")


class KeywordTier(str, Enum):
    NICHE = "niche"     # 8-10 long-tail, "engraved tennis racket pendant"
    MEDIUM = "medium"   # 3-5, "tennis necklace"
    BROAD = "broad"     # 1-2, "sports gift"


class KeywordScore(Base):
    """Post-Layer-B opportunity-scored keyword. One per candidate that passed scoring."""
    __tablename__ = "keyword_scores"
    
    id = Column(Integer, primary_key=True)
    analysis_id = Column(Integer, ForeignKey("sourcing_analyses.id"), nullable=False)
    candidate_id = Column(Integer, ForeignKey("keyword_candidates.id"), nullable=False)
    
    keyword = Column(String(100), nullable=False)
    
    # Sub-scores (all 0.0 - 1.0)
    score_new_shop_share = Column(Float)         # fraction of top-20 that are shop_age < 2yr
    score_price_alignment = Column(Float)        # how well does Rexven cost fit avg top-20 price
    score_activity = Column(Float)               # share of top-20 with eh_sales_recent ≥ 1
    score_competition = Column(Float)            # inverted — based on keyword_total_results
    score_diversity = Column(Float)              # penalty for single-shop dominance
    
    # Aggregate
    opportunity_score = Column(Float, index=True)   # weighted sum, 0.0 - 1.0
    
    # Empirical data captured at scoring time
    top20_avg_price_cents = Column(Integer)
    top20_avg_shop_age = Column(Float)
    top20_keyword_total_results = Column(Integer)
    top20_unique_shops = Column(Integer)
    top20_with_recent_sales = Column(Integer)
    
    # Layer C enrichment (if available)
    estimated_rank = Column(Integer, nullable=True)
    estimated_page = Column(Integer, nullable=True)
    visual_similarity_support = Column(Integer, nullable=True)  # how many similar listings rank here
    
    rank_in_recommendation = Column(Integer)  # 1 = top recommended
    
    analysis = relationship("SourcingAnalysis", back_populates="scores")
```

**Validation:**
- Alembic migration runs cleanly on existing DB
- Create a sample `SourcingAnalysis` with one `KeywordCandidate` and one `KeywordScore`, query back with all relationships intact
- Foreign key cascade delete works (deleting an analysis removes its candidates and scores)

---

### Step 4.2: Vision-LLM Keyword Suggester
**Goal:** Use Claude Sonnet 4.6 vision API to produce 15 keyword candidates from a single jewelry image.

**Implementation:**

Create `src/sourcing/vision_keyword_suggester.py`:

```python
import base64
import json
from pathlib import Path
from anthropic import Anthropic
from sqlalchemy.orm import Session

from src.db.models import (
    SourcingAnalysis, KeywordCandidate, KeywordTier, SourcingStatus
)


VISION_KEYWORD_PROMPT = """You are an Etsy SEO expert specializing in handmade jewelry.

I will show you a single jewelry product image from a Turkish supplier (Rexven). Your job is to predict how an American Etsy buyer would search for this exact product or very similar ones.

OUTPUT: a strict JSON object with three tiers of keywords.

TIER DEFINITIONS:
- "niche": 8-10 long-tail keywords (3-5 words each). These are specific, low-competition phrases an intentional buyer would type. Example: "dainty tennis racket pendant necklace", "sport themed gift for tennis player".
- "medium": 3-5 mid-tail keywords (2-3 words). These describe the product category clearly. Example: "tennis necklace", "minimalist sport jewelry".
- "broad": 1-2 high-volume head terms. These are competition giants — used only for context. Example: "gifts for her".

WHAT TO INFER FROM THE IMAGE:
1. Product form (what is it — pendant shape, chain style, earring type)
2. Material perception (gold-plated, silver, pearl, gemstone, enamel)
3. Style category (minimalist, boho, gothic, art deco, dainty, statement, vintage)
4. Theme or motif (animal, floral, religious, sport, celestial, alphabet/initial, birthstone)
5. Target recipient implied by style (mom, daughter, teen, bride, friend, pet owner)
6. Likely occasion (everyday, wedding, mother's day, christmas, valentine's, graduation, baptism)

CRITICAL RULES:
- Each keyword must be something a real buyer would type, not marketing copy.
- Do NOT include the words "Etsy", "handmade", or seller-side jargon.
- Each keyword max 30 characters.
- NICHE tier keywords must include at least 2 descriptive modifiers (style + form, or form + theme).
- For each keyword, give a one-sentence rationale tied to a visual feature.

ADDITIONAL CONTEXT (use to refine keyword choices):
- Supplier title (Turkish/English): {title}
- Supplier category: {category}
- Supplier cost: ${cost_usd}
- Premium pricing tier: ${premium_cost_usd}
- Supplier flagged this as a "Satışa Uygun" (sales-suitable) item: {satisa_uygun}

Return ONLY valid JSON in this exact shape (no markdown, no preamble):
{{
  "detected_attributes": {{
    "form": "...",
    "material": "...",
    "style": "...",
    "theme": "...",
    "recipient": "...",
    "occasion": "..."
  }},
  "niche": [
    {{"keyword": "...", "rationale": "..."}},
    ...
  ],
  "medium": [
    {{"keyword": "...", "rationale": "..."}},
    ...
  ],
  "broad": [
    {{"keyword": "...", "rationale": "..."}},
    ...
  ]
}}
"""


class VisionKeywordSuggester:
    """Layer A — produces keyword candidates from a Rexven product image."""
    
    MODEL = "claude-sonnet-4-6"
    # Cost reference (update from product-self-knowledge skill if needed):
    # Vision input ~$3/M tokens, output ~$15/M tokens.
    
    def __init__(self, client: Anthropic, session: Session):
        self.client = client
        self.session = session
    
    def _encode_image(self, image_path: str) -> tuple[str, str]:
        """Return (base64_data, media_type)."""
        path = Path(image_path)
        suffix = path.suffix.lower()
        media_type = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(suffix, "image/jpeg")
        
        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode("utf-8")
        return data, media_type
    
    def run(self, analysis: SourcingAnalysis) -> list[KeywordCandidate]:
        """Execute Layer A for a sourcing analysis. Persists candidates."""
        analysis.status = SourcingStatus.LAYER_A_RUNNING
        self.session.commit()
        
        try:
            image_data, media_type = self._encode_image(analysis.image_path)
            
            prompt = VISION_KEYWORD_PROMPT.format(
                title=analysis.rexven_title_en or analysis.rexven_title_tr or "(not provided)",
                category=analysis.rexven_category or "jewelry",
                cost_usd=f"{(analysis.rexven_cost_usd_cents or 0) / 100:.2f}",
                premium_cost_usd=f"{(analysis.rexven_premium_cost_usd_cents or 0) / 100:.2f}",
                satisa_uygun="yes" if analysis.rexven_has_satisa_uygun_badge else "no",
            )
            
            response = self.client.messages.create(
                model=self.MODEL,
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
            
            # Cost tracking
            analysis.vision_tokens_used = (
                response.usage.input_tokens + response.usage.output_tokens
            )
            analysis.vision_cost_usd_cents = self._estimate_cost_cents(
                response.usage.input_tokens, response.usage.output_tokens
            )
            
            raw_text = response.content[0].text.strip()
            parsed = self._parse_response(raw_text)
            
            # Persist candidates
            candidates = self._persist_candidates(analysis, parsed)
            
            analysis.layer_a_completed = True
            self.session.commit()
            return candidates
        
        except Exception as e:
            analysis.status = SourcingStatus.FAILED
            analysis.error_message = f"Layer A failed: {str(e)}"
            self.session.commit()
            raise
    
    def _parse_response(self, raw_text: str) -> dict:
        """Strip any markdown fences and parse JSON."""
        cleaned = raw_text.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(f"Vision LLM returned malformed JSON: {e}\nRaw: {raw_text[:500]}")
    
    def _persist_candidates(
        self, analysis: SourcingAnalysis, parsed: dict
    ) -> list[KeywordCandidate]:
        detected = parsed.get("detected_attributes", {})
        candidates = []
        
        for tier_key, tier_enum in [
            ("niche", KeywordTier.NICHE),
            ("medium", KeywordTier.MEDIUM),
            ("broad", KeywordTier.BROAD),
        ]:
            for item in parsed.get(tier_key, []):
                kw = item.get("keyword", "").strip().lower()
                rationale = item.get("rationale", "").strip()
                
                if not kw or len(kw) > 30:
                    continue
                
                candidate = KeywordCandidate(
                    analysis_id=analysis.id,
                    keyword=kw,
                    tier=tier_enum,
                    rationale=rationale,
                    detected_attributes=detected,
                    source_layer="A",
                )
                self.session.add(candidate)
                candidates.append(candidate)
        
        self.session.flush()
        return candidates
    
    @staticmethod
    def _estimate_cost_cents(input_tokens: int, output_tokens: int) -> int:
        """Rough estimate. Replace with product-self-knowledge values if outdated."""
        # $3 per 1M input + $15 per 1M output, converted to cents
        cost_usd = (input_tokens / 1_000_000) * 3.0 + (output_tokens / 1_000_000) * 15.0
        return int(round(cost_usd * 100))
```

**Validation:**
- Run on 3 distinct Rexven products (cross necklace, animal pendant, hoop earring)
- Each invocation produces 12-17 candidates spanning all three tiers
- `detected_attributes` is non-empty
- Each candidate has rationale tied to a visual feature
- Cost per call < $0.05 (~5 cents)
- JSON parsing handles trailing whitespace, fences, and stray commas

---

### Step 4.3: Layer A API Endpoint
**Goal:** FastAPI endpoint that runs Layer A standalone.

**Implementation:**

Create `src/api/routes/sourcing.py`:

```python
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.db.models import SourcingAnalysis, SourcingStatus
from src.db.session import get_session
from src.sourcing.vision_keyword_suggester import VisionKeywordSuggester
from src.clients.anthropic_client import get_anthropic_client
from src.sourcing.rexven_scraper import scrape_rexven_product
from src.sourcing.image_io import save_uploaded_image, download_remote_image

router = APIRouter(prefix="/sourcing", tags=["sourcing"])


@router.post("/suggest-keywords")
async def suggest_keywords(
    rexven_url: str | None = Form(None),
    rexven_sku: str | None = Form(None),
    image: UploadFile | None = File(None),
    session: Session = Depends(get_session),
):
    """
    Layer A standalone — produce keyword candidates from a Rexven product.
    
    Accepts any ONE of: rexven_url, rexven_sku (existing in DB), or direct image upload.
    """
    if not any([rexven_url, rexven_sku, image]):
        raise HTTPException(400, "Provide rexven_url, rexven_sku, or image upload")
    
    # Build the analysis record
    analysis = SourcingAnalysis(status=SourcingStatus.PENDING)
    
    if rexven_url:
        # Scrape Rexven to get image + metadata
        scraped = scrape_rexven_product(rexven_url)
        analysis.rexven_url = rexven_url
        analysis.image_url = scraped["image_url"]
        analysis.image_path = download_remote_image(scraped["image_url"])
        analysis.rexven_title_tr = scraped["title_tr"]
        analysis.rexven_title_en = scraped["title_en"]
        analysis.rexven_cost_usd_cents = scraped["cost_cents"]
        analysis.rexven_premium_cost_usd_cents = scraped["premium_cost_cents"]
        analysis.rexven_category = scraped["category"]
        analysis.rexven_has_satisa_uygun_badge = scraped["satisa_uygun"]
        analysis.rexven_has_yeni_badge = scraped["yeni"]
    
    elif rexven_sku:
        # Pull existing product
        from src.db.models import Product
        product = session.query(Product).filter_by(sku=rexven_sku).first()
        if not product:
            raise HTTPException(404, f"Product {rexven_sku} not found")
        analysis.rexven_sku = rexven_sku
        analysis.image_path = product.original_image_path
        analysis.rexven_title_tr = product.title_tr
        analysis.rexven_category = product.category
    
    elif image:
        analysis.image_path = save_uploaded_image(image)
    
    session.add(analysis)
    session.commit()
    session.refresh(analysis)
    
    # Run Layer A synchronously (it's fast, ~3-5 seconds)
    suggester = VisionKeywordSuggester(get_anthropic_client(), session)
    candidates = suggester.run(analysis)
    
    return JSONResponse({
        "analysis_id": analysis.id,
        "status": analysis.status.value,
        "detected_attributes": candidates[0].detected_attributes if candidates else {},
        "candidates": [
            {
                "keyword": c.keyword,
                "tier": c.tier.value,
                "rationale": c.rationale,
            }
            for c in candidates
        ],
        "cost_cents": analysis.vision_cost_usd_cents,
    })
```

**Validation:**
- `curl` with image upload returns valid JSON in < 10s
- `curl` with `rexven_url` triggers scraper then runs Layer A end-to-end
- `curl` with `rexven_sku` for an existing product works
- Bad input (no image at all) returns 400
- Anthropic API failure flips status to `FAILED` with stored error message

---

## LAYER B — Opportunity Scoring + Mini Phase 1

### Step 4.4: Mini-Phase-1 Trigger
**Goal:** Programmatically invoke the existing Phase 1 scraper for a single keyword with reduced depth (top 20 instead of top 60).

**Implementation:**

The existing Phase 1 scraper is triggered by the Chrome extension and writes to `CompetitorListing`. For Layer B we need a programmatic alternative that:
- Accepts a list of keywords (the Layer A candidates)
- Scrapes only top 20 per keyword
- Tags scraped rows with `keyword_searched` so they're queryable
- Does NOT pollute the main research dataset — uses a flag

Add a column to `CompetitorListing`:

```python
# In src/db/models.py — extend existing CompetitorListing
class CompetitorListing(Base):
    # ... existing columns ...
    
    # NEW: distinguish sourcing-driven scrapes from main research scrapes
    scraped_for_sourcing = Column(Boolean, default=False, index=True)
    sourcing_analysis_id = Column(Integer, ForeignKey("sourcing_analyses.id"), nullable=True)
```

Then create `src/sourcing/mini_phase1.py`:

```python
from sqlalchemy.orm import Session
from src.db.models import CompetitorListing, SourcingAnalysis
from src.research.phase1_scraper import Phase1Scraper  # existing scraper


class MiniPhase1Runner:
    """Programmatically invokes Phase 1 scraper with reduced depth."""
    
    LISTINGS_PER_KEYWORD = 20  # vs. 60 for main Phase 1
    
    def __init__(self, session: Session, scraper: Phase1Scraper):
        self.session = session
        self.scraper = scraper
    
    def run(
        self, analysis: SourcingAnalysis, keywords: list[str]
    ) -> dict[str, list[CompetitorListing]]:
        """
        Scrape top-20 for each keyword. Returns dict keyword -> listings.
        Reuses cached listings from CompetitorListing if a recent scrape exists.
        """
        results = {}
        
        for keyword in keywords:
            # Cache lookup: did we scrape this keyword in last 7 days?
            cached = self._lookup_recent_cache(keyword, max_age_days=7)
            if cached and len(cached) >= self.LISTINGS_PER_KEYWORD:
                results[keyword] = cached[:self.LISTINGS_PER_KEYWORD]
                continue
            
            # Trigger scraper
            listings = self.scraper.scrape_keyword(
                keyword=keyword,
                limit=self.LISTINGS_PER_KEYWORD,
            )
            
            # Tag rows for sourcing
            for listing in listings:
                listing.scraped_for_sourcing = True
                listing.sourcing_analysis_id = analysis.id
            
            self.session.add_all(listings)
            self.session.commit()
            results[keyword] = listings
        
        return results
    
    def _lookup_recent_cache(self, keyword: str, max_age_days: int) -> list[CompetitorListing]:
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        
        return (
            self.session.query(CompetitorListing)
            .filter(
                CompetitorListing.keyword_searched == keyword,
                CompetitorListing.created_at >= cutoff,
            )
            .order_by(CompetitorListing.rank_in_search.asc())
            .limit(self.LISTINGS_PER_KEYWORD)
            .all()
        )
```

**Note on scraper reuse:** the Phase 1 scraper currently expects to be driven by the Chrome extension. If it's not callable directly from Python (e.g. relies on the user's logged-in browser session), implement this step using the Etsy public search HTML scraping path used in cold-start cases, OR queue the keywords for the user to scrape manually via the extension and have `MiniPhase1Runner` wait on the result. The cache-first design above means in steady-state usage most candidates will hit cached data anyway.

**Validation:**
- Run with 5 keywords on a fresh DB → 5 × 20 = 100 new `CompetitorListing` rows with `scraped_for_sourcing=True`
- Re-run within 7 days → 0 new scrapes, all cache hits
- Re-run after 7+ days → re-scrapes

---

### Step 4.5: Opportunity Score Calculator
**Goal:** Compute the 5 sub-scores and aggregate `opportunity_score` per keyword candidate.

**Scoring rationale (from `Keyword_Strategy.md`):**

| Sub-score | Signal | Why it matters |
|-----------|--------|----------------|
| `score_new_shop_share` | Fraction of top-20 with shop_age < 2yr | High = new shops can still rank here. Your shop has age 0. |
| `score_price_alignment` | Rexven cost × 4 fits within p25-p75 of top-20 prices | Buyers in this band are conditioned to your price point. |
| `score_activity` | Share of top-20 with `eh_sales_recent ≥ 1` | Living market vs. dead keyword. |
| `score_competition` | Inverted log of `keyword_total_results` | Lower total results = thinner field. |
| `score_diversity` | 1 - (max single-shop count / 20) | Penalty if one shop dominates → that shop is the moat. |

**Implementation:**

Create `src/sourcing/opportunity_scorer.py`:

```python
import math
import statistics
from collections import Counter
from sqlalchemy.orm import Session

from src.db.models import (
    SourcingAnalysis, KeywordCandidate, KeywordScore,
    CompetitorListing, SourcingStatus
)


class OpportunityScorer:
    """Layer B — score keyword candidates against the empirical top-20."""
    
    # Sub-score weights — tune via backtesting once you have post-launch data
    WEIGHTS = {
        "new_shop_share": 0.30,
        "price_alignment": 0.25,
        "activity":        0.25,
        "competition":     0.10,
        "diversity":       0.10,
    }
    
    # Your shop's profile — read from config
    YOUR_SHOP_AGE_YEARS = 0.0  # update as shop matures
    # Rexven-to-retail multiplier (Etsy listing price ÷ Rexven cost). 
    # Use 4.0 as baseline; conservative because Etsy fees + ads eat margin.
    RETAIL_MULTIPLIER = 4.0
    
    def __init__(self, session: Session):
        self.session = session
    
    def score_analysis(self, analysis: SourcingAnalysis) -> list[KeywordScore]:
        """Compute scores for all candidates of an analysis. Persists results."""
        analysis.status = SourcingStatus.LAYER_B_RUNNING
        self.session.commit()
        
        # Determine target retail price from Rexven cost
        rexven_cost = (analysis.rexven_premium_cost_usd_cents 
                       or analysis.rexven_cost_usd_cents 
                       or 0)
        target_retail_cents = int(rexven_cost * self.RETAIL_MULTIPLIER)
        
        scores = []
        for candidate in analysis.candidates:
            top20 = self._fetch_top20(candidate.keyword)
            if len(top20) < 5:
                # Skip — not enough data
                continue
            
            score_row = self._score_single(analysis, candidate, top20, target_retail_cents)
            scores.append(score_row)
        
        # Sort by opportunity_score desc, assign rank_in_recommendation
        scores.sort(key=lambda s: s.opportunity_score, reverse=True)
        for i, score in enumerate(scores, start=1):
            score.rank_in_recommendation = i
        
        self.session.add_all(scores)
        analysis.layer_b_completed = True
        self.session.commit()
        return scores
    
    def _fetch_top20(self, keyword: str) -> list[CompetitorListing]:
        return (
            self.session.query(CompetitorListing)
            .filter(CompetitorListing.keyword_searched == keyword)
            .order_by(CompetitorListing.rank_in_search.asc())
            .limit(20)
            .all()
        )
    
    def _score_single(
        self,
        analysis: SourcingAnalysis,
        candidate: KeywordCandidate,
        top20: list[CompetitorListing],
        target_retail_cents: int,
    ) -> KeywordScore:
        # Sub-score 1: new shop share
        new_shops = sum(1 for l in top20 if (l.shop_age_years or 99) < 2)
        score_new_shop_share = new_shops / len(top20)
        
        # Sub-score 2: price alignment
        prices = [l.price_cents for l in top20 if l.price_cents]
        if len(prices) >= 5:
            p25 = statistics.quantiles(prices, n=4)[0]
            p75 = statistics.quantiles(prices, n=4)[2]
            if p25 <= target_retail_cents <= p75:
                score_price_alignment = 1.0
            else:
                # Distance penalty — sigmoid-ish
                median_price = statistics.median(prices)
                distance = abs(target_retail_cents - median_price) / max(median_price, 1)
                score_price_alignment = max(0.0, 1.0 - distance)
        else:
            score_price_alignment = 0.5  # not enough data
        
        # Sub-score 3: activity
        with_sales = sum(1 for l in top20 if (l.eh_sales_recent or 0) >= 1)
        score_activity = with_sales / len(top20)
        
        # Sub-score 4: competition (inverted log of total search results)
        total_results = top20[0].keyword_total_results if top20[0].keyword_total_results else 1
        # log10(1) = 0, log10(1M) = 6. Map [0, 6] -> [1.0, 0.0]
        log_results = math.log10(max(total_results, 1))
        score_competition = max(0.0, 1.0 - log_results / 6.0)
        
        # Sub-score 5: diversity (anti-dominance)
        shop_counts = Counter(l.shop_id for l in top20 if l.shop_id)
        max_share = max(shop_counts.values()) / len(top20) if shop_counts else 0
        score_diversity = 1.0 - max_share
        
        # Aggregate
        opportunity_score = (
            self.WEIGHTS["new_shop_share"]  * score_new_shop_share +
            self.WEIGHTS["price_alignment"] * score_price_alignment +
            self.WEIGHTS["activity"]        * score_activity +
            self.WEIGHTS["competition"]     * score_competition +
            self.WEIGHTS["diversity"]       * score_diversity
        )
        
        # Empirical stats for the UI
        avg_price = int(statistics.mean(prices)) if prices else 0
        avg_shop_age = statistics.mean([l.shop_age_years for l in top20 if l.shop_age_years]) or 0
        
        return KeywordScore(
            analysis_id=analysis.id,
            candidate_id=candidate.id,
            keyword=candidate.keyword,
            score_new_shop_share=score_new_shop_share,
            score_price_alignment=score_price_alignment,
            score_activity=score_activity,
            score_competition=score_competition,
            score_diversity=score_diversity,
            opportunity_score=opportunity_score,
            top20_avg_price_cents=avg_price,
            top20_avg_shop_age=avg_shop_age,
            top20_keyword_total_results=total_results,
            top20_unique_shops=len(shop_counts),
            top20_with_recent_sales=with_sales,
        )
```

**Validation:**
- Run on a sourcing analysis with 15 candidates and 100% cache-hit top-20
- All sub-scores fall in [0.0, 1.0]
- `opportunity_score` is monotonic in sub-scores (perturb one input, score changes in expected direction)
- Candidates with < 5 listings in top20 are skipped, not crashed
- Final ranking matches manual sanity check (the one keyword with most new shops + best price fit ranks #1)

---

### Step 4.6: Full Layer-A-plus-B Sourcing Endpoint
**Goal:** Single endpoint that runs Vision-LLM, mini-Phase-1, and scoring as one orchestrated flow.

**Implementation:**

Add to `src/api/routes/sourcing.py`:

```python
from fastapi import BackgroundTasks
from src.sourcing.mini_phase1 import MiniPhase1Runner
from src.sourcing.opportunity_scorer import OpportunityScorer
from src.research.phase1_scraper import Phase1Scraper


@router.post("/analyze")
async def analyze_product(
    background_tasks: BackgroundTasks,
    rexven_url: str | None = Form(None),
    rexven_sku: str | None = Form(None),
    image: UploadFile | None = File(None),
    session: Session = Depends(get_session),
):
    """
    Full Layer A + B analysis. Returns immediately with analysis_id; client polls
    GET /sourcing/{analysis_id} for completion.
    """
    # ... same input handling as suggest-keywords ...
    analysis = _build_analysis_from_inputs(
        session, rexven_url, rexven_sku, image
    )
    
    # Layer A is fast — run synchronously
    suggester = VisionKeywordSuggester(get_anthropic_client(), session)
    candidates = suggester.run(analysis)
    
    # Layer B has scraping — kick off in background
    background_tasks.add_task(_run_layer_b, analysis.id)
    
    return {
        "analysis_id": analysis.id,
        "status": analysis.status.value,
        "candidates_count": len(candidates),
        "poll_url": f"/sourcing/{analysis.id}",
    }


def _run_layer_b(analysis_id: int):
    """Background task — runs scraping + scoring."""
    from src.db.session import SessionLocal
    session = SessionLocal()
    try:
        analysis = session.query(SourcingAnalysis).filter_by(id=analysis_id).first()
        
        scraper = Phase1Scraper(...)  # initialize per your setup
        runner = MiniPhase1Runner(session, scraper)
        keywords_to_score = [c.keyword for c in analysis.candidates]
        runner.run(analysis, keywords_to_score)
        
        scorer = OpportunityScorer(session)
        scorer.score_analysis(analysis)
        
        analysis.status = SourcingStatus.COMPLETED
        analysis.completed_at = datetime.utcnow()
        session.commit()
    except Exception as e:
        analysis.status = SourcingStatus.FAILED
        analysis.error_message = str(e)
        session.commit()
    finally:
        session.close()


@router.get("/{analysis_id}")
async def get_analysis(analysis_id: int, session: Session = Depends(get_session)):
    analysis = session.query(SourcingAnalysis).filter_by(id=analysis_id).first()
    if not analysis:
        raise HTTPException(404)
    
    scores = sorted(
        analysis.scores,
        key=lambda s: s.rank_in_recommendation or 999,
    )
    
    return {
        "analysis_id": analysis.id,
        "status": analysis.status.value,
        "rexven_title": analysis.rexven_title_en or analysis.rexven_title_tr,
        "layer_a_done": analysis.layer_a_completed,
        "layer_b_done": analysis.layer_b_completed,
        "layer_c_done": analysis.layer_c_completed,
        "recommended_keywords": [
            {
                "rank": s.rank_in_recommendation,
                "keyword": s.keyword,
                "opportunity_score": round(s.opportunity_score, 3),
                "sub_scores": {
                    "new_shop_opportunity": round(s.score_new_shop_share, 2),
                    "price_alignment":      round(s.score_price_alignment, 2),
                    "market_activity":      round(s.score_activity, 2),
                    "competition_inverted": round(s.score_competition, 2),
                    "diversity":            round(s.score_diversity, 2),
                },
                "market_snapshot": {
                    "avg_price_usd": s.top20_avg_price_cents / 100,
                    "avg_shop_age_years": round(s.top20_avg_shop_age, 1),
                    "total_etsy_results": s.top20_keyword_total_results,
                    "unique_shops_in_top20": s.top20_unique_shops,
                    "listings_with_recent_sales": s.top20_with_recent_sales,
                },
                "estimated_rank": s.estimated_rank,
                "estimated_page": s.estimated_page,
            }
            for s in scores[:5]  # top 5 only
        ],
        "error": analysis.error_message,
    }
```

**Validation:**
- End-to-end: POST `/sourcing/analyze` with a Rexven URL → status becomes `COMPLETED` within ~2 minutes (cache miss) or ~10 seconds (cache hit)
- Top 5 recommended keywords appear in poll response, sorted by opportunity_score
- A single failing keyword (scrape error) doesn't tank the whole analysis — other 14 still score

---

## LAYER C — CLIP Visual Similarity

### Step 4.7: Image Embedding Migration
**Goal:** Add storage for CLIP embeddings on existing `CompetitorListing` rows.

**Storage choice:**
- If using PostgreSQL with pgvector extension installed → use native `vector(512)` column (fastest similarity search)
- If pgvector unavailable → store as JSON array, use Python-side cosine similarity (slower but works on any backend)

Recommendation: ship with JSON first to avoid infra dependency, migrate to pgvector later when scrape volume justifies it (>50k embeddings).

**Implementation:**

Alembic migration:

```python
# alembic/versions/XXXX_add_image_embeddings.py
def upgrade():
    op.add_column(
        "competitor_listings",
        sa.Column("image_embedding", sa.JSON(), nullable=True),
    )
    op.add_column(
        "competitor_listings",
        sa.Column("image_embedding_model", sa.String(50), nullable=True),
    )
    op.add_column(
        "competitor_listings",
        sa.Column("image_embedding_computed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_listings_has_embedding",
        "competitor_listings",
        ["image_embedding_computed_at"],
    )


class RexvenProductEmbedding(Base):
    """Cached embedding for a Rexven product image — avoids recomputing on re-analysis."""
    __tablename__ = "rexven_product_embeddings"
    
    id = Column(Integer, primary_key=True)
    image_hash = Column(String(64), unique=True, nullable=False, index=True)  # sha256
    image_path = Column(String(500))
    embedding = Column(JSON, nullable=False)
    model_name = Column(String(50))
    computed_at = Column(DateTime, default=datetime.utcnow)
```

**Validation:**
- Migration applies cleanly
- Existing data unchanged
- Insert a row with a sample 512-float embedding, query back, similarity computation works

---

### Step 4.8: CLIP Embedder
**Goal:** Wrapper around CLIP model for image → 512-dim embedding.

**Implementation:**

Create `src/sourcing/clip_embedder.py`:

```python
import hashlib
from pathlib import Path
import numpy as np
from PIL import Image
import torch
from transformers import CLIPProcessor, CLIPModel


class ClipEmbedder:
    """Wrapper around OpenAI CLIP for image embeddings."""
    
    MODEL_NAME = "openai/clip-vit-base-patch32"  # 512-dim embeddings, ~150MB
    # For better recall consider clip-vit-large-patch14 (768-dim, ~890MB) once you scale
    
    def __init__(self, device: str = "cpu"):
        self.device = device
        self.model = CLIPModel.from_pretrained(self.MODEL_NAME).to(device)
        self.processor = CLIPProcessor.from_pretrained(self.MODEL_NAME)
        self.model.eval()
    
    @torch.no_grad()
    def embed_image(self, image_path: str | Path) -> np.ndarray:
        """Return L2-normalized embedding (512-dim float array)."""
        img = Image.open(image_path).convert("RGB")
        inputs = self.processor(images=img, return_tensors="pt").to(self.device)
        features = self.model.get_image_features(**inputs)
        features = features / features.norm(dim=-1, keepdim=True)  # L2 normalize
        return features.cpu().numpy().flatten().astype(np.float32)
    
    @torch.no_grad()
    def embed_image_url(self, url: str) -> np.ndarray:
        """Download + embed an image URL."""
        import requests
        from io import BytesIO
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGB")
        inputs = self.processor(images=img, return_tensors="pt").to(self.device)
        features = self.model.get_image_features(**inputs)
        features = features / features.norm(dim=-1, keepdim=True)
        return features.cpu().numpy().flatten().astype(np.float32)
    
    @staticmethod
    def image_hash(image_path: str | Path) -> str:
        with open(image_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    
    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Both vectors must be L2-normalized."""
        return float(np.dot(a, b))
```

**Validation:**
- Embed 3 identical copies of same image → all 3 embeddings identical
- Embed two visually similar products (both cross necklaces) → similarity > 0.85
- Embed two dissimilar products (cross necklace vs. cat earring) → similarity < 0.65
- First call takes ~3s (model load), subsequent calls < 200ms on CPU

---

### Step 4.9: Backfill Job
**Goal:** One-time batch job to compute CLIP embeddings for all existing `CompetitorListing` rows.

**Implementation:**

Create `src/sourcing/backfill_embeddings.py`:

```python
import time
from datetime import datetime
from sqlalchemy.orm import Session
from src.db.models import CompetitorListing
from src.sourcing.clip_embedder import ClipEmbedder


def backfill_listing_embeddings(
    session: Session,
    embedder: ClipEmbedder,
    batch_size: int = 50,
    max_listings: int | None = None,
):
    """
    Compute and store CLIP embeddings for all CompetitorListing rows
    where image_embedding IS NULL.
    Resumable — re-run if interrupted, only processes remaining rows.
    """
    query = session.query(CompetitorListing).filter(
        CompetitorListing.image_embedding.is_(None),
        CompetitorListing.image_url.isnot(None),
    )
    
    total = query.count() if max_listings is None else min(query.count(), max_listings)
    print(f"Backfilling embeddings for {total} listings...")
    
    processed = 0
    failed = 0
    start = time.time()
    
    while processed < total:
        batch = query.limit(batch_size).all()
        if not batch:
            break
        
        for listing in batch:
            try:
                emb = embedder.embed_image_url(listing.image_url)
                listing.image_embedding = emb.tolist()
                listing.image_embedding_model = embedder.MODEL_NAME
                listing.image_embedding_computed_at = datetime.utcnow()
                processed += 1
            except Exception as e:
                print(f"  FAILED listing {listing.listing_id}: {e}")
                failed += 1
                # Mark with empty list to skip on next run
                listing.image_embedding = []
                listing.image_embedding_computed_at = datetime.utcnow()
        
        session.commit()
        elapsed = time.time() - start
        rate = processed / elapsed if elapsed > 0 else 0
        eta = (total - processed) / rate if rate > 0 else 0
        print(f"  {processed}/{total}  rate={rate:.1f}/s  eta={eta:.0f}s  failed={failed}")
    
    print(f"\nBackfill complete. Processed: {processed}, Failed: {failed}")
```

**Operational notes:**
- Initial backfill of ~10k listings takes ~2 hours on CPU. With CUDA GPU, ~15 minutes.
- Run as a one-shot script: `python -m src.sourcing.backfill_embeddings`
- Idempotent — safe to interrupt and resume
- After initial backfill, hook embedding generation into Phase 1 scraper so new listings get embedded automatically (add `embed_on_insert=True` flag)

**Validation:**
- Run on a DB with 100 sample listings → 100 embeddings stored
- Interrupt mid-way, re-run → resumes from where it stopped, doesn't duplicate work
- Failed downloads stored as `[]` (sentinel for "tried but failed"), not `None` (which means "not yet tried")
- Query: `SELECT COUNT(*) WHERE image_embedding IS NOT NULL` matches expectation

---

### Step 4.10: Visual Similarity Search
**Goal:** Given a Rexven image, find the top-K most visually similar `CompetitorListing` rows.

**Implementation:**

Create `src/sourcing/visual_similarity.py`:

```python
import numpy as np
from sqlalchemy.orm import Session
from src.db.models import CompetitorListing, RexvenProductEmbedding
from src.sourcing.clip_embedder import ClipEmbedder


class VisualSimilaritySearch:
    """Find Etsy listings visually similar to a Rexven product."""
    
    def __init__(self, session: Session, embedder: ClipEmbedder):
        self.session = session
        self.embedder = embedder
    
    def find_similar(
        self,
        rexven_image_path: str,
        top_k: int = 50,
        min_similarity: float = 0.70,
    ) -> list[tuple[CompetitorListing, float]]:
        """
        Returns list of (listing, similarity_score) tuples sorted desc.
        Filters out listings below min_similarity threshold.
        """
        rexven_emb = self._get_or_compute_rexven_embedding(rexven_image_path)
        
        # Load all embedded listings — at scale (>100k) switch to pgvector + ORDER BY ... LIMIT
        listings_with_emb = (
            self.session.query(CompetitorListing)
            .filter(CompetitorListing.image_embedding.isnot(None))
            .all()
        )
        
        # Filter out the "[]" sentinel rows (failed embeddings)
        listings_with_emb = [
            l for l in listings_with_emb 
            if l.image_embedding and len(l.image_embedding) > 0
        ]
        
        if not listings_with_emb:
            return []
        
        # Compute similarities in numpy bulk
        listing_embs = np.array([l.image_embedding for l in listings_with_emb], dtype=np.float32)
        similarities = listing_embs @ rexven_emb  # both already L2-normalized
        
        # Pair up, filter, sort
        scored = [
            (listings_with_emb[i], float(similarities[i]))
            for i in range(len(listings_with_emb))
            if similarities[i] >= min_similarity
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
    
    def _get_or_compute_rexven_embedding(self, image_path: str) -> np.ndarray:
        """Cache Rexven embeddings by image hash."""
        img_hash = ClipEmbedder.image_hash(image_path)
        cached = (
            self.session.query(RexvenProductEmbedding)
            .filter_by(image_hash=img_hash)
            .first()
        )
        if cached:
            return np.array(cached.embedding, dtype=np.float32)
        
        emb = self.embedder.embed_image(image_path)
        record = RexvenProductEmbedding(
            image_hash=img_hash,
            image_path=image_path,
            embedding=emb.tolist(),
            model_name=self.embedder.MODEL_NAME,
        )
        self.session.add(record)
        self.session.commit()
        return emb
    
    def extract_keyword_distribution(
        self, similar_listings: list[tuple[CompetitorListing, float]]
    ) -> list[tuple[str, int, float]]:
        """
        From a list of similar listings, return:
        [(keyword, count, similarity_weighted_count), ...] sorted desc.
        
        The similarity_weighted_count weights each appearance by visual similarity,
        so highly-similar listings vote more strongly.
        """
        from collections import defaultdict
        counts = defaultdict(int)
        weighted = defaultdict(float)
        
        for listing, sim in similar_listings:
            if listing.keyword_searched:
                counts[listing.keyword_searched] += 1
                weighted[listing.keyword_searched] += sim
        
        result = [
            (kw, counts[kw], weighted[kw])
            for kw in counts.keys()
        ]
        result.sort(key=lambda x: x[2], reverse=True)
        return result
```

**Validation:**
- Embed a known Rexven product image, search → top-50 listings should be visibly similar (manual spot-check)
- Run twice with same image → second call uses cached `RexvenProductEmbedding`
- `extract_keyword_distribution` returns keywords sorted by similarity-weighted vote
- With min_similarity=0.70, fewer false-positives than min_similarity=0.50

---

### Step 4.11: Rank Prediction
**Goal:** Estimate where the Rexven product would rank in search results for a given keyword.

**Algorithm:** Based on `Keyword_Strategy.md`'s observation that shop age and prior sales drive ranking. We use empirical data from similar listings to anchor the estimate.

```python
import statistics
from src.db.models import CompetitorListing


def predict_rank(
    similar_listings: list[tuple[CompetitorListing, float]],
    target_keyword: str,
    your_shop_age_years: float = 0.0,
    your_shop_total_sales: int = 0,
) -> dict:
    """
    Returns: {
      "estimated_rank": int (1-60+),
      "estimated_page": int (1, 2, 3+),
      "confidence": float (0.0 - 1.0),
      "support_count": int,  # how many similar listings rank for this keyword
      "reasoning": str,
    }
    """
    # Filter to listings that actually ranked for this keyword
    keyword_specific = [
        (l, sim) for l, sim in similar_listings
        if l.keyword_searched == target_keyword
    ]
    
    if not keyword_specific:
        return {
            "estimated_rank": None,
            "estimated_page": None,
            "confidence": 0.0,
            "support_count": 0,
            "reasoning": (
                "No visually similar listings have been observed ranking for this "
                "keyword. The keyword may be brand-new territory for this product type."
            ),
        }
    
    # Empirical avg rank of similar listings
    ranks = [l.rank_in_search for l, _ in keyword_specific if l.rank_in_search]
    if not ranks:
        return {"estimated_rank": None, "confidence": 0.0, "support_count": 0,
                "reasoning": "Similar listings exist but lack rank data."}
    
    avg_rank = statistics.mean(ranks)
    
    # Average shop age of similar listings
    shop_ages = [l.shop_age_years for l, _ in keyword_specific if l.shop_age_years]
    avg_shop_age = statistics.mean(shop_ages) if shop_ages else 5.0
    
    # New shop penalty — every year of age below avg costs ~3 positions
    shop_age_gap = max(0, avg_shop_age - your_shop_age_years)
    shop_penalty = shop_age_gap * 3.0
    
    estimated_rank = int(avg_rank + shop_penalty)
    estimated_page = (estimated_rank - 1) // 48 + 1  # Etsy shows 48 per page
    
    confidence = min(1.0, len(keyword_specific) / 5.0)  # need 5+ similar listings for high confidence
    
    reasoning = (
        f"{len(keyword_specific)} visually similar listings rank for '{target_keyword}'. "
        f"Their avg rank is {avg_rank:.1f} with avg shop age {avg_shop_age:.1f}yr. "
        f"Adjusted for your shop age ({your_shop_age_years:.1f}yr), "
        f"estimated rank is {estimated_rank} (page {estimated_page})."
    )
    
    return {
        "estimated_rank": estimated_rank,
        "estimated_page": estimated_page,
        "confidence": confidence,
        "support_count": len(keyword_specific),
        "reasoning": reasoning,
    }
```

**Note on calibration:** This formula is intentionally rough. The "3 positions per shop-age year" coefficient is a starting heuristic. Once you've published 20+ listings and observed their actual ranks, backfit this constant by fitting `actual_rank ~ predicted_rank + shop_age_gap` on your own data.

**Validation:**
- For a keyword with 8 visually-similar listings (avg rank 15, avg shop age 6yr), with your shop age 0, prediction is ~33 (rank 15 + 18 penalty)
- Confidence = 1.0 when 5+ supports, scales down linearly
- Returns null gracefully when no similar listings rank for the keyword

---

### Step 4.12: Layer C Integration into Sourcing Endpoint
**Goal:** Wire Layer C into the existing `/sourcing/analyze` flow so it enriches keyword scores with rank predictions and can also propose novel keywords.

**Implementation:**

Update `_run_layer_b` background task to also run Layer C:

```python
def _run_full_analysis(analysis_id: int):
    from src.db.session import SessionLocal
    session = SessionLocal()
    try:
        analysis = session.query(SourcingAnalysis).filter_by(id=analysis_id).first()
        
        # === LAYER B: scrape + score ===
        scraper = Phase1Scraper(...)
        runner = MiniPhase1Runner(session, scraper)
        keywords = [c.keyword for c in analysis.candidates]
        runner.run(analysis, keywords)
        
        scorer = OpportunityScorer(session)
        scores = scorer.score_analysis(analysis)
        
        # === LAYER C: visual similarity enrichment ===
        analysis.status = SourcingStatus.LAYER_C_RUNNING
        session.commit()
        
        embedder = ClipEmbedder()  # consider singleton/lazy init
        searcher = VisualSimilaritySearch(session, embedder)
        
        similar = searcher.find_similar(
            analysis.image_path, top_k=50, min_similarity=0.70
        )
        
        # Enrich existing scores with rank predictions
        for score in scores:
            prediction = predict_rank(
                similar, 
                target_keyword=score.keyword,
                your_shop_age_years=OpportunityScorer.YOUR_SHOP_AGE_YEARS,
            )
            score.estimated_rank = prediction["estimated_rank"]
            score.estimated_page = prediction["estimated_page"]
            score.visual_similarity_support = prediction["support_count"]
        
        # Propose novel keywords: keywords that similar listings rank for
        # but that Layer A didn't suggest
        empirical_keywords = searcher.extract_keyword_distribution(similar)
        layer_a_keywords = {c.keyword for c in analysis.candidates}
        
        novel = [
            (kw, count, weighted)
            for kw, count, weighted in empirical_keywords[:10]
            if kw not in layer_a_keywords and count >= 3
        ]
        
        # Persist novel candidates with source_layer="C"
        for kw, count, weighted in novel:
            novel_candidate = KeywordCandidate(
                analysis_id=analysis.id,
                keyword=kw,
                tier=KeywordTier.NICHE,  # empirical keywords default to niche
                rationale=f"{count} visually similar listings rank for this keyword",
                source_layer="C",
            )
            session.add(novel_candidate)
        session.commit()
        
        # Re-score with novel candidates included
        # (Optional — depends on whether you want to re-trigger scraping for novels.
        # For speed, only score novels if they share top-20 cache with existing candidates.)
        
        analysis.layer_c_completed = True
        analysis.status = SourcingStatus.COMPLETED
        analysis.completed_at = datetime.utcnow()
        session.commit()
    
    except Exception as e:
        analysis.status = SourcingStatus.FAILED
        analysis.error_message = str(e)
        session.commit()
    finally:
        session.close()
```

**Validation:**
- End-to-end run: top 5 keywords in `GET /sourcing/{id}` now include `estimated_rank` and `estimated_page` fields
- `source_layer="C"` candidates appear when visually-similar listings reveal keywords Layer A missed
- If embedder is unavailable (model not downloaded), Layer C fails gracefully — Layer A+B results still returned

---

## LAYER INTEGRATION

### Step 4.13: Bridge to Phase 6 Content Pipeline
**Goal:** When the user picks a keyword from the sourcing result, that selection flows into Phase 6's content generation context.

**Implementation:**

Add to the existing Phase 6 orchestration:

```python
# src/content/pipeline.py — extend existing function
def build_content_context(
    product: Product, 
    selected_keyword_score_id: int | None = None,
    session: Session,
) -> dict:
    """Build the context dict that goes into Phase 6 LLM prompts."""
    context = {
        # ... existing context ...
    }
    
    if selected_keyword_score_id:
        keyword_score = session.query(KeywordScore).filter_by(
            id=selected_keyword_score_id
        ).first()
        
        if keyword_score:
            # Pull the empirical top-20 for this keyword
            top20 = (
                session.query(CompetitorListing)
                .filter(CompetitorListing.keyword_searched == keyword_score.keyword)
                .order_by(CompetitorListing.rank_in_search.asc())
                .limit(20)
                .all()
            )
            
            context["sourcing"] = {
                "target_keyword": keyword_score.keyword,
                "opportunity_score": keyword_score.opportunity_score,
                "target_price_band": {
                    "min": keyword_score.top20_avg_price_cents * 0.8,
                    "max": keyword_score.top20_avg_price_cents * 1.2,
                },
                "competitor_titles": [l.title for l in top20[:10]],
                "competitor_tag_pool": _flatten_tags(top20),
            }
    
    return context
```

The Phase 6 title/tag/description generators already consume `context` — by adding `context["sourcing"]`, prompts can be updated to instruct the LLM to lean on `target_keyword` as the primary anchor and use `competitor_tag_pool` as the candidate set for tag generation.

**Validation:**
- Calling content generation without `selected_keyword_score_id` produces output identical to current behavior (backward compatible)
- With a selected keyword, generated title contains the target keyword in the first 60 chars
- Generated tags overlap meaningfully with `competitor_tag_pool`

---

## CHROME EXTENSION INTEGRATION

### Step 4.14: Extension UI — Sourcing Tab
**Goal:** Add a "Sourcing" tab to the existing Chrome extension popup alongside Phase 1 and Phase 2.

**Implementation:**

Extension files to modify:
- `popup/popup.html` — add tab nav entry
- `popup/sourcing.html` — new tab content
- `popup/sourcing.js` — tab logic
- `manifest.json` — add `https://*.rexven.com/*` to content_scripts matches

`popup/sourcing.html`:

```html
<div id="sourcing-tab" class="tab-content" style="display:none;">
  <h3>Sourcing Analysis</h3>
  
  <div class="input-group">
    <label>Mode:</label>
    <div>
      <input type="radio" name="src-mode" value="current-page" checked> 
        Use current Rexven page
      <input type="radio" name="src-mode" value="upload"> 
        Upload image
    </div>
  </div>
  
  <div id="src-upload-group" style="display:none;">
    <input type="file" id="src-image-upload" accept="image/*">
  </div>
  
  <button id="src-analyze-btn" class="primary-btn">Analyze Product</button>
  
  <div id="src-status" class="status-line"></div>
  
  <div id="src-results" style="display:none;">
    <h4>Detected attributes</h4>
    <div id="src-attributes" class="attribute-pills"></div>
    
    <h4>Recommended keywords</h4>
    <div id="src-keyword-list" class="keyword-list"></div>
  </div>
</div>
```

`popup/sourcing.js`:

```javascript
const BACKEND_URL = 'http://localhost:8000';

document.getElementById('src-analyze-btn').addEventListener('click', async () => {
  const mode = document.querySelector('input[name="src-mode"]:checked').value;
  const statusEl = document.getElementById('src-status');
  const resultsEl = document.getElementById('src-results');
  
  statusEl.textContent = 'Starting analysis...';
  resultsEl.style.display = 'none';
  
  try {
    let analysisId;
    
    if (mode === 'current-page') {
      // Ask the content script for the current Rexven page URL
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      
      if (!tab.url.includes('rexven.com')) {
        statusEl.textContent = 'Error: not on a Rexven page';
        return;
      }
      
      const formData = new FormData();
      formData.append('rexven_url', tab.url);
      
      const resp = await fetch(`${BACKEND_URL}/sourcing/analyze`, {
        method: 'POST',
        body: formData,
      });
      const data = await resp.json();
      analysisId = data.analysis_id;
    } else {
      const file = document.getElementById('src-image-upload').files[0];
      const formData = new FormData();
      formData.append('image', file);
      
      const resp = await fetch(`${BACKEND_URL}/sourcing/analyze`, {
        method: 'POST',
        body: formData,
      });
      const data = await resp.json();
      analysisId = data.analysis_id;
    }
    
    // Poll for completion
    statusEl.textContent = 'Layer A (vision) running...';
    let result;
    while (true) {
      await new Promise(r => setTimeout(r, 3000));
      const poll = await fetch(`${BACKEND_URL}/sourcing/${analysisId}`);
      result = await poll.json();
      
      if (result.layer_c_done) {
        statusEl.textContent = 'Complete';
        break;
      } else if (result.layer_b_done) {
        statusEl.textContent = 'Layer C (visual similarity) running...';
      } else if (result.layer_a_done) {
        statusEl.textContent = 'Layer B (scoring) running...';
      }
      
      if (result.status === 'failed') {
        statusEl.textContent = `Failed: ${result.error}`;
        return;
      }
    }
    
    renderResults(result);
    resultsEl.style.display = 'block';
    
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
  }
});

function renderResults(result) {
  // Attributes
  const attrEl = document.getElementById('src-attributes');
  attrEl.innerHTML = '';
  const attrs = result.detected_attributes || {};
  for (const [k, v] of Object.entries(attrs)) {
    if (v) {
      const pill = document.createElement('span');
      pill.className = 'pill';
      pill.textContent = `${k}: ${v}`;
      attrEl.appendChild(pill);
    }
  }
  
  // Keywords
  const kwListEl = document.getElementById('src-keyword-list');
  kwListEl.innerHTML = '';
  
  for (const kw of result.recommended_keywords) {
    const card = document.createElement('div');
    card.className = 'keyword-card';
    card.innerHTML = `
      <div class="kw-header">
        <span class="kw-rank">#${kw.rank}</span>
        <span class="kw-text">${kw.keyword}</span>
        <span class="kw-score">${(kw.opportunity_score * 100).toFixed(0)}/100</span>
      </div>
      <div class="kw-snapshot">
        avg $${kw.market_snapshot.avg_price_usd.toFixed(2)} · 
        ${kw.market_snapshot.unique_shops_in_top20} shops · 
        ${kw.market_snapshot.listings_with_recent_sales}/20 active
      </div>
      ${kw.estimated_rank ? `
        <div class="kw-rank-pred">
          Estimated rank: ~${kw.estimated_rank} (page ${kw.estimated_page})
        </div>
      ` : ''}
      <div class="kw-actions">
        <button class="kw-btn-scrape" data-kw="${kw.keyword}">
          Run full Phase 1
        </button>
        <button class="kw-btn-generate" data-kw-id="${kw.rank}">
          Generate content
        </button>
      </div>
    `;
    kwListEl.appendChild(card);
  }
  
  // Wire buttons
  document.querySelectorAll('.kw-btn-scrape').forEach(btn => {
    btn.addEventListener('click', () => {
      const kw = btn.dataset.kw;
      // Switch to Phase 1 tab and pre-fill keyword
      window.switchTab('phase1');
      document.getElementById('phase1-keyword-input').value = kw;
    });
  });
}
```

**Validation:**
- Open extension on a Rexven product page → click "Analyze Product" → see Layer A results in ~10s, then Layer B updating, then Layer C
- "Run full Phase 1" button switches tabs and pre-fills the keyword
- "Generate content" button correctly identifies the picked keyword score and calls the Phase 6 endpoint

---

### Step 4.15: Content Script — Rexven Page Injection
**Goal:** Inject a floating "Analyze with Etsy Research" button on Rexven product pages so the user doesn't need to open the popup.

**Implementation:**

`content_scripts/rexven_inject.js`:

```javascript
(function() {
  // Detect we're on a Rexven product detail page
  if (!window.location.href.match(/rexven\.com\/.*\/(product|urun)\//i)) return;
  
  // Wait for product info to load
  const observer = new MutationObserver((mutations, obs) => {
    const productImg = document.querySelector('img.product-main-image, .product-detail img');
    if (productImg) {
      injectButton(productImg);
      obs.disconnect();
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
  
  function injectButton(productImg) {
    const btn = document.createElement('button');
    btn.id = 'etsy-research-sourcing-btn';
    btn.textContent = '🔍 Etsy Sourcing Analysis';
    btn.style.cssText = `
      position: fixed; bottom: 20px; right: 20px; z-index: 99999;
      background: #f1641e; color: white; border: none;
      padding: 12px 20px; border-radius: 24px; cursor: pointer;
      font-weight: 600; box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    `;
    
    btn.addEventListener('click', () => {
      // Trigger the popup with sourcing tab active
      chrome.runtime.sendMessage({
        type: 'OPEN_SOURCING_TAB',
        rexven_url: window.location.href,
      });
    });
    
    document.body.appendChild(btn);
  }
})();
```

`background.js` — add message handler:

```javascript
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'OPEN_SOURCING_TAB') {
    // Store the URL so popup picks it up on open
    chrome.storage.local.set({ 
      pending_sourcing_url: msg.rexven_url,
      pending_action: 'auto_analyze',
    });
    chrome.action.openPopup();
  }
});
```

In `popup.js` on load:

```javascript
chrome.storage.local.get(['pending_sourcing_url', 'pending_action'], (data) => {
  if (data.pending_action === 'auto_analyze' && data.pending_sourcing_url) {
    chrome.storage.local.remove(['pending_sourcing_url', 'pending_action']);
    window.switchTab('sourcing');
    // Auto-trigger analyze
    setTimeout(() => {
      document.getElementById('src-analyze-btn').click();
    }, 100);
  }
});
```

**Validation:**
- Open Rexven product page → floating button appears
- Click button → popup opens on Sourcing tab → analysis auto-starts
- Button doesn't appear on Rexven category pages (only product detail)
- Button doesn't interfere with Rexven page interactions

---

## OPERATIONAL CONSIDERATIONS

### Cost & Performance Budget

| Operation | Per call | Per 100 products/month |
|-----------|---------|------------------------|
| Layer A vision call | ~$0.03 | $3 |
| Layer B mini-Phase-1 | Variable (cache-dependent) | ~50% cache hit → halves scraping cost |
| Layer C CLIP embed (per Rexven product) | $0 (local) | $0 |
| Layer C similarity search | $0 (in-memory) | $0 |
| Backfill (one-time) | ~$0 + 2hrs compute | one-time |

The vision LLM is the only meaningful per-product cost. At $0.03/product and 100 products/month, $3/month total. This is negligible.

### Caching Strategy

- **Vision results** are cached per `image_hash` in `RexvenProductEmbedding`. Re-analyzing the same product hits the cache, no LLM call.
- **Scrape results** cached per keyword for 7 days in `CompetitorListing` (existing behavior).
- **CLIP embeddings on competitor listings** are permanent — only recomputed if the underlying image URL changes (rare).
- **Layer B scores** are NOT cached — they're recomputed on every analysis because the underlying market data may have shifted.

### Failure Modes & Fallbacks

| Failure | Fallback |
|---------|----------|
| Vision LLM API down | Return cached Layer A result if available; else fail analysis with clear error |
| Phase 1 scraper unavailable | Use cached top-20 only; flag low-confidence scores |
| CLIP embedding fails | Skip Layer C; return Layer A+B results with `estimated_rank=null` |
| No visually-similar listings exist (cold start) | Layer C returns empty; Layer A+B carry the recommendation |
| Rexven page structure changes | Manual image upload mode still works |

### Re-analysis triggers

The system should re-analyze a Rexven product when:
- It's been more than 30 days since last analysis (market shifts)
- The product's "Satışa Uygun" badge state changes
- A previous keyword pick performed badly post-launch (feedback loop into scoring)

Implement a `force_refresh=true` query param on `/sourcing/analyze` that bypasses all caches.

### Privacy / detection considerations

- Layer B's mini-Phase-1 runs through the same scraping path as the main Phase 1 — same anti-detection measures apply (research browser profile, rotating user agents)
- Avoid analyzing more than ~50 distinct keywords/day per Etsy session to stay below rate-limit thresholds
- The Rexven scraper hits Rexven only, not Etsy, so it's independent of Etsy detection risk

---

## TESTING CHECKLIST

Before declaring Phase 4 complete, verify:

- [ ] Alembic migrations apply cleanly on a copy of production DB
- [ ] Backfill job completes on existing `CompetitorListing` data within budget time
- [ ] `POST /sourcing/suggest-keywords` works with image upload, Rexven URL, and existing SKU
- [ ] `POST /sourcing/analyze` triggers all three layers and reports correct progress
- [ ] `GET /sourcing/{id}` returns well-formed JSON with top-5 recommended keywords
- [ ] Chrome extension Sourcing tab displays results and wires actions correctly
- [ ] Rexven content script injects button only on product pages
- [ ] Cost per analysis ≤ $0.05
- [ ] End-to-end latency (cold cache): < 3 minutes
- [ ] End-to-end latency (warm cache): < 30 seconds
- [ ] Phase 6 content generation accepts `selected_keyword_score_id` and produces keyword-grounded output
- [ ] At least one full product cycle: Rexven page → Sourcing analysis → Keyword pick → Phase 6 content → Phase 5 images → Phase 8 listing upload

---

## FUTURE EXTENSIONS

Items intentionally out of scope for v1 but worth noting:

1. **Multi-image analysis** — Rexven shows 5-8 photos per product. Currently we use the main one; future Layer A could ensemble across all images for richer attribute detection.
2. **Cross-supplier sourcing** — same architecture works for Aliexpress, DHGate, etc. Layer A is supplier-agnostic.
3. **Profitability scoring** — combine `target_retail_cents` with Etsy fee + ad cost models to compute expected margin per keyword, not just opportunity score.
4. **Inverse search** — "Given my keyword X, which Rexven products would rank for it?" — same CLIP DB, just reverse the query direction.
5. **Active learning** — after a published listing's actual rank is known, fold that back into the rank-prediction calibration constants.
6. **Bulk mode** — accept a list of Rexven URLs and produce a portfolio-level recommendation: "of these 20 products, focus on these 5 keywords for max throughput."
