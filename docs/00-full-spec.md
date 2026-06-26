# 🤖 AI CODING AGENT - ETSY TAKI OTOMASYON SİSTEMİ
## Step-by-Step Architectural Implementation Prompt

> **Bu doküman, AI coding agent'a verilen TEK bir prompt'tur.**  
> Agent her adımı sırayla uygular, validation geçmeden sonraki adıma geçmez.

---

# 📌 SECTION 0: ROLE & MISSION

## Your Role
You are a senior Python developer building a **local-only** Etsy jewelry store automation system. You implement features **incrementally**, validate each step before proceeding, and **never** deviate from the strict business rules defined in this document.

## Your Mission
Build a modular system that:
1. Accepts manual product input (image + metadata)
2. **Ingests competitor research data (CSV from Chrome extension) and analyzes it**
3. Generates AI image variations via 3 selectable workflows
4. Generates LLM-based content (title, tags, description) following strict SEO rules — **enriched with competitor research insights when available**
5. Provides human approval interface
6. Uploads to Etsy via official API
7. Tracks performance and manages renew/scheduling

## Big-Picture User Flow (THE 3 LOOPS)

The system has three loops operating at different cadences. Understanding this shape is critical before writing any code.

**LOOP 1 — Niche Research (weekly):**
```
Run Chrome extension (Phase 1 + 2, captures ~30-50 detailed listings per niche)
  → Phase 1 scrapes Etsy search results + EHunt search-card data
  → Phase 2 scrapes listing detail pages + EHunt detail panel
    (the EHunt detail panel uniquely provides the listing's actual 13 seller tags
     + per-tag search volume, since Etsy hides tags from public DOM in 2026)
  → Export CSV (extension v2.4 schema with detail_tags, detail_tag_volumes, eh_detail_* fields)
  → Import to system (Step 3.2)
  → System analyzes: title patterns, tag frequency, volume stratification,
    clichés, underused keywords
  → Stored as KeywordResearch row in DB
  → APScheduler re-runs analysis weekly on Monday 03:00
```

**LOOP 2 — Product Generation (per product, runs many times per day):**
```
User uploads a product (image + metadata via Manual Input UI from Phase 4)
  → System triggers VariantBundleOrchestrator (Step 6.7)
  → For this single product, system generates 3 LISTING VARIANTS:
      • Variant A: Conservative niche (closest to bestseller patterns)
      • Variant B: Differentiated (uses underused keywords)
      • Variant C: Gift-focused (or seasonal/material-aware swap)
  → Each variant = its own title + 13 tags + description, internally consistent
  → All 3 variants saved to DB
```

**LOOP 3 — Human Approval & Publish (per product):**
```
User opens Approval UI (Phase 7) for the product
  → Sees 3 variants side-by-side
  → Picks one variant (or hybrid-edits to mix fields between variants)
  → Approves → variant sent to Phase 8 (Etsy API upload)
  → Listing published
```

The 3 variants matter because:
- One product → 3 distinct strategic angles → user gets to pick the angle that fits
- Variants are coherent (title + tags + description align within a variant)
- Research data is reused — same niche knowledge powers all 3 variants
- Same research powers 100+ different products in that niche over the weeks

## Critical Mindset
- **Local-first:** No cloud deploy, no production concerns. Everything runs on developer's machine.
- **Modular:** Each module is independently testable.
- **Business-rule-strict:** Training documents define non-negotiable rules.
- **Incremental:** One step at a time. Test before moving on.
- **No magic:** Explicit over implicit. Logs everywhere.

---

# 🚫 SECTION 1: STRICT BUSINESS RULES (NEVER VIOLATE)

These rules come from the Etsy training documents and are **non-negotiable**. Every output the system produces must comply.

## 1.1 Title Rules (HARDCODED VALIDATORS REQUIRED)
- Length: **EXACTLY 137-140 characters**
- First 60 characters: niche product description only (no "Gift for Mom" style big terms)
- **NEVER** use word "Stone" → use "CZ" or "Pave" instead
- **NEVER** use "Pendant" alone → always "Pendant Necklace"
- **NEVER** combine "Solid Gold" and "Gold Plated" in same title
- **NEVER** repeat the same word twice
- Use 2-3 synonyms for the main product
- Only 1-2 big-search terms at the end (e.g. "Gifts for Mom")
- Comma + space separator between phrases (NEVER pipe `|`)
- First letter of each word capitalized
- "Mother's Day Gift" → use "Gifts for Mom" instead
- "Animal" for sea creatures → use "Sea Animal" or "Ocean"
- "Floral" only for visual flowers (not script/letter flowers)
- "Diamond" → don't use for brass/plated products
- "Twisted" means twisted/burgulu (not dönen)
- For real silver products: include "925 Sterling Silver"
- For gold plated (brass-based): do NOT include karat
- 22K products: don't mention karat at all

## 1.2 Tag Rules
- **EXACTLY 13 tags**
- Distribution:
  - 8-9 niche/specific tags (long-tail)
  - 2-3 medium tags (Pendant Necklace, Minimalist Necklace, Everyday Necklace)
  - 1-2 big tags only (e.g. "Gifts for Mom")
- Max 20 characters per tag
- Don't repeat keywords already in title (waste of tag slot)
- Comma + space separator
- First letter of each word capitalized
- **NEVER** "Mother's Day Gift" → use "Gifts for Mom"

## 1.3 Description Rules
- 150-220 words
- **CRITICAL:** Each description must be UNIQUE. AI templated outputs get rejected by Etsy.
- Originality target: 96%+ vs existing descriptions in DB
- Must contain organically (not as a list):
  - Product description (1 sentence)
  - Material/stone details (2 sentences)
  - Gift positioning (1 sentence)
  - Size/weight (1 sentence)
  - Shipping note (1 sentence)
- Include 2-3 store-internal links (to similar products / collections)
- Forbidden cliché phrases:
  - "Discover the beauty of..."
  - "Elevate your style..."
  - "Perfect for any occasion"
  - "Add a touch of elegance"

## 1.4 Images Rules
- Minimum 8 images per listing (test showed 6 caused view drop)
- Image order strategy:
  - Image 1: Main product (mannequin or close-up)
  - Images 2-3: Variations/colors
  - Images 4-5: Trust shots (size chart, material detail)
  - Images 6-7: Lifestyle/gift-focused
  - Image 8: Box
  - Image 9: Variation chart (if applicable)
- Each image has SEO-friendly file name: `gold-plated-cross-necklace-1.jpg` (NOT `IMG_1234.jpg`)
- Each image has alt text:
  - Image 1: Main keyword phrase
  - Images 2-3: Variation + category
  - Images 4-7: Trust + materials
  - Images 5-6-7: Gift-focused
- All images 2000x2000 px minimum

## 1.5 Listing Attributes (NEVER LEAVE EMPTY)
Every Etsy listing must fill:
- Material (Gold Plated / Brass / Sterling Silver)
- Karat (for silver only)
- Has Stone? + details (Baguette Cut Garnet)
- Shape (Letter, Heart, Animal, Flower, Disk)
- Second Color (if applicable)
- Style (Minimalist, Gothic, Art Deco, Boho)
- Occasion (Mother's Day, Christmas, Valentine's, Graduation, 4th of July, Baptism, Confirmation, Easter)
- Recipient (Her, Him, Mom, Wife, Daughter)
- Personalization (Custom / Personalized)

## 1.6 Quantity Strategy
- For confident bestsellers → 999 (signals "I'm a producer")
- For test products → 10 initially, then raise to 300 after 2 sales (Etsy aktivlik sinyali)
- Never let it drop to 0

## 1.7 Section Strategy
- Etsy allows 20 sections per shop → use all 20
- Section names should be specific: "Cross Necklace", "Birthstone Necklace", "Birth Flower Necklace", "Family Necklace", "Pet Necklace", "Mother's Day Gifts", "Christmas Gifts", etc.

## 1.8 Renew Strategy
- 4 renews per day at Turkey time: **17:00, 21:00, 02:00, 05:00**
- Only renew:
  - Top selling products
  - Newly listed products with high confidence
- Never renew underperforming middle products

## 1.9 Carrier Pillars (Mağaza Strategy)
Every store needs 5-6 strong categories. Each product must belong to one:
1. Cross Necklace
2. Name Necklace
3. Birthstone Necklace
4. Birth Flower Necklace
5. Pet Necklace
6. Pendant Necklace (general)

## 1.10 AI-Generated Content Warning ⚠️
- **NEVER** publish raw AI output (especially descriptions)
- Etsy detects template-pattern AI text and rejects it
- Always require human approval gate before Etsy upload
- Originality validator must run before approval is allowed

## 1.11 Image Generation Hybrid Rule
For Etsy AI image policy compliance:
- **At least 3 images per listing** must be real Reksven photos (close-up, size, box)
- 5-6 images can be AI lifestyle (real jewelry + AI scene)
- This balance keeps Etsy compliance + AI scale

## 1.12 Forbidden Keywords (Auto-Reject)
| Forbidden | Use Instead |
|-----------|-------------|
| Stone | CZ or Pave |
| Diamond (in plated) | (don't use) |
| Mother's Day Gift | Gifts for Mom |
| Pendant (alone) | Pendant Necklace |
| Pave (misspelling "Pawe") | Pave (P-A-V-E) |
| Twisted (as "dönen") | Twist Chain |

---

# 🏛️ SECTION 2: SYSTEM ARCHITECTURE OVERVIEW

## High-Level Components (All Local)

```
┌─────────────────────────────────────────────────────────────┐
│              LOCAL WEB UI (FastAPI + HTML)                   │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────────┐  │
│  │ Manual     │  │ Research   │  │ Human Approval       │  │
│  │ Input Form │  │ Dashboard  │  │ Interface            │  │
│  └────────────┘  └────────────┘  └──────────────────────┘  │
└──────────────────┬───────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│                  ORCHESTRATOR                                │
│           (FastAPI background tasks / asyncio)               │
└──────────────────┬───────────────────────────────────────────┘
                   │
       ┌───────────┼─────────┬──────────┬─────────┬─────────┐
       ▼           ▼         ▼          ▼         ▼         ▼
  ┌────────┐  ┌─────────┐ ┌────────┐ ┌────────┐ ┌──────┐ ┌────────┐
  │ Image  │  │ Content │ │Research│ │ Etsy   │ │Stats │ │ Renew  │
  │ Module │  │ Module  │ │ Module │ │ API    │ │Module│ │Module  │
  └────┬───┘  └────┬────┘ └───┬────┘ └───┬────┘ └──┬───┘ └────────┘
       │           │ ◄────────┘          │         │
       │           │ (research enriches  │         │
       │           │  Content prompts)   │         │
       ▼           ▼                     ▼         ▼
  ┌──────────────────────────────────────────────────────┐
  │   PostgreSQL (Docker) + Local File Storage           │
  │   • Postgres container (docker-compose.yml)          │
  │   • ./data/images/SKU/... (real + AI images)         │
  │   • ./data/research/csv_archive/ (imported CSVs)     │
  └──────────────────────────────────────────────────────┘
            ▲
            │ (CSV upload)
            │
  ┌──────────────────────────────────────────┐
  │  External: Etsy Research Chrome Ext v2.4 │
  │  (scrapes competitors + EHunt detail     │
  │   panel for tags + per-tag volumes)      │
  └──────────────────────────────────────────┘
```

## Module Boundaries (clarified after Phase 3 addition)

- **Research Module (Phase 3):** Reads competitor CSV → DB → produces enrichment context. Has no live runtime dependency on Etsy or external APIs (except LLM for pattern extraction).
- **Content Module (Phase 6):** Pulls from both base `KeywordPool` (manual seed) AND `ResearchContextBuilder` (Phase 3 output) when generating titles/tags/descriptions. Works in cold-start mode if no research exists yet.
- **Image Module (Phase 5):** Independent of Research. Uses Reksven reference + selected AI workflow.
- **Etsy Module (Phase 8):** Only consumes finalized listings (post-human-approval). Never sees raw competitor data.

## Image Module — Multi-Workflow Design

```
┌──────────────────────────────────────────────────────┐
│         AbstractImageGenerator (Interface)            │
│  - generate(reference_image, prompt, params) -> img  │
└──────────────────────────────────────────────────────┘
                       ▲
        ┌──────────────┼──────────────┐
        │              │              │
┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│ GeminiImage  │ │ OpenAIImage  │ │ FluxImageGen     │
│ Generator    │ │ Generator    │ │ (via fal.ai)     │
└──────────────┘ └──────────────┘ └──────────────────┘

User selects workflow at runtime via UI.
System can run multiple workflows on same input
for side-by-side comparison.
```

## Processing Pipeline Flow (Orchestration)

When user clicks "Process Product" on a MANUAL_INPUT product, the pipeline runs in **3 stages**. Stages 1 and 3 are sequential; **Stage 2 runs image and content generation in parallel via `asyncio.gather`**.

```
[User clicks: "Process Product"]
                │
                ▼
    ┌──────────────────────────┐
    │ STAGE 1: Preprocessing   │  ~5-10 sec
    │ - Background remove      │
    │ - Resize to 2000x2000    │
    │ Status: IMAGE_PROCESSING │
    └──────────────────────────┘
                │
                ▼
    ┌──────────────────────────────────────────┐
    │ STAGE 2: PARALLEL GENERATION             │  ~30-60 sec
    │ Status: CONTENT_GENERATING               │
    │                                          │
    │ ┌─────────────────┐  ┌─────────────────┐│
    │ │ Image Gen       │  │ Content Gen     ││ asyncio.gather
    │ │ - 5-6 images    │  │ - 5 titles      ││ (concurrent)
    │ │ - Selected      │  │ - 13 tags       ││
    │ │   workflow      │  │ - 3 descriptions││
    │ └─────────────────┘  └─────────────────┘│
    └──────────────────────────────────────────┘
                │
                ▼
    ┌──────────────────────────────┐
    │ STAGE 3: Validation          │  ~2-5 sec
    │ - Title validator            │
    │ - Tag validator              │
    │ - Originality check          │
    │ - Cliché check               │
    │ Status: AWAITING_APPROVAL    │
    └──────────────────────────────┘
                │
                ▼
        [Human approval gate]  ← Hard requirement, cannot skip
                │
                ▼
        [Etsy bulk upload (paced)]  ← Separate user action
```

### Orchestration Requirements

The orchestrator (used in Phase 5 + 5 implementation) must:
- Be triggered via FastAPI `BackgroundTasks` (non-blocking response to user)
- Update `Product.status` after each stage (frontend polls for progress)
- Use `asyncio.gather` for Stage 2 parallel execution of image + content
- Wrap each stage in try/except → failure flips status to `FAILED` with stored error message
- **Never proceed past Stage 3 automatically** — human approval is a hard gate per Section 1.10

### Reference Implementation Sketch

```python
async def process_product_pipeline(sku: str, workflow_name: str):
    try:
        product = await db.get_product(sku)
        
        # === STAGE 1: Sequential Preprocessing ===
        await update_status(sku, ProductStatus.IMAGE_PROCESSING)
        bg_removed = await remove_background(product.original_image_path)
        save_preprocessed(sku, bg_removed)
        
        # === STAGE 2: PARALLEL Generation ===
        await update_status(sku, ProductStatus.CONTENT_GENERATING)
        
        image_task = generate_images(sku, bg_removed, workflow_name)
        content_task = generate_content(sku, product)
        
        images, content = await asyncio.gather(image_task, content_task)
        
        # === STAGE 3: Validation ===
        valid_titles = [t for t in content['titles'] if validate_title(t)[0]]
        valid_tag_sets = [tg for tg in content['tags'] if validate_tags(tg)[0]]
        valid_descs = [d for d in content['descriptions'] 
                       if originality_check(d)[0] and not check_cliches(d)]
        
        await db.update_product(sku, {
            'generated_titles': valid_titles,
            'generated_tags': valid_tag_sets,
            'generated_descriptions': valid_descs,
            'images': images,
            'image_workflow_used': workflow_name,
            'status': ProductStatus.AWAITING_APPROVAL,
        })
        
    except Exception as e:
        logger.exception(f"Pipeline failed for {sku}")
        await update_status(sku, ProductStatus.FAILED, error=str(e))
```

### FastAPI Trigger + Status Polling

```python
@app.post("/products/{sku}/process")
async def process_product(
    sku: str,
    workflow: str,
    background_tasks: BackgroundTasks
):
    """One-click trigger. Returns immediately, work runs in background."""
    background_tasks.add_task(process_product_pipeline, sku, workflow)
    return {"status": "started", "sku": sku, "estimated_seconds": 60}


@app.get("/products/{sku}/status")
async def get_status(sku: str):
    """Frontend polls every 2-3 seconds for progress."""
    product = await db.get_product(sku)
    return {
        "sku": sku,
        "status": product.status,
        "current_step_label": _label_for_status(product.status),
        "is_ready_for_approval": product.status == ProductStatus.AWAITING_APPROVAL,
        "error": product.error_message,
    }
```

**Note:** The orchestrator is not a separate step — it's the integration pattern used by Phase 5 (image generation) and Phase 6 (content generation). Implement individual generators first, then wire them through this orchestrator.

---

# 🛠️ SECTION 3: TECH STACK CONSTRAINTS

## Required Stack (Use These, Nothing Else)
- **Language:** Python 3.11+
- **Web Framework:** FastAPI
- **Database:** PostgreSQL 16 (via Docker, accessed via SQLAlchemy + psycopg[binary])
- **Migrations:** Alembic
- **Async:** asyncio (no Celery/Redis for now - local doesn't need it)
- **Background Tasks:** FastAPI BackgroundTasks initially; upgrade to APScheduler when needed
- **HTTP Client:** httpx
- **Image Processing:** Pillow, OpenCV (cv2), rembg
- **Templates:** Jinja2 (server-side HTML)
- **Config:** python-dotenv + pydantic-settings
- **Testing:** pytest

## Database Notes
The project uses PostgreSQL via Docker Compose (single container, runs locally, no cloud). This is a deliberate upgrade from SQLite because:
- The `tag_volumes` and other JSON columns benefit from PostgreSQL's native **JSONB** type, which is queryable and indexable (e.g. "find listings where tag_volumes has key 'minimalist'"). SQLite's JSON is opaque text.
- The scheduler (APScheduler weekly research refresh) + UI + API can read/write concurrently without SQLite's whole-database locking.
- Description originality search via `pg_trgm` index outperforms in-Python similarity scans as the listing corpus grows.

A `docker-compose.yml` at repo root spins up the postgres container; the backend connects via `DATABASE_URL`. See Phase 1 for the exact setup.

## AI / LLM Stack
- **LLM:** anthropic Python SDK (Claude)
- **Image AI APIs:**
  - Gemini: google-genai SDK
  - OpenAI: openai SDK
  - Flux: fal-client SDK (fal.ai)
- **Embeddings:** sentence-transformers (local, free)

## External Integrations
- **Etsy:** requests + custom OAuth + rate limiter
- **Google Sheets/Drive:** google-api-python-client (LATER, not in early phases)

## What NOT to Use (Save Time)
- ❌ Production cloud deploy (local-only project — Docker postgres counts as local)
- ❌ Redis/Celery (asyncio is enough locally)
- ❌ React/Vue (server-side templates are enough)
- ❌ Kubernetes/managed databases
- ❌ Vela or other 3rd-party Etsy tools (we use direct API)

---

# 🪜 SECTION 4: PHASE-BY-PHASE IMPLEMENTATION

> **CRITICAL:** Complete each step's validation before moving to the next. Document any deviation.

---

## PHASE 1: PROJECT FOUNDATION

### Step 1.1: Repository Structure
**Goal:** Create the standard project directory layout.

**Implementation:**
Create this exact structure:
```
etsy-jewelry-automation/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── src/
│   ├── __init__.py
│   ├── main.py                   # FastAPI entry point
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py           # pydantic-settings
│   │   └── business_rules.py     # ALL training rules as constants
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── session.py
│   │   └── migrations/
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── product.py            # Product domain model
│   │   ├── carrier_pillar.py     # Enum
│   │   └── validators.py         # Title/tag validators
│   ├── modules/
│   │   ├── __init__.py
│   │   ├── input/                # Manual product input
│   │   ├── research/             # Phase 3: Competitor intelligence (CSV import + analyzers)
│   │   ├── images/               # AI image pipeline
│   │   ├── content/              # LLM content pipeline (consumes research)
│   │   ├── approval/             # Human approval
│   │   ├── etsy/                 # Etsy API
│   │   ├── tracking/             # Stats + sheets sync
│   │   └── scheduler/            # Renew + cron
│   ├── web/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   ├── templates/
│   │   └── static/
│   └── utils/
│       ├── __init__.py
│       ├── logger.py
│       └── exceptions.py
├── data/
│   ├── images/                   # SKU-based folders
│   ├── research/
│   │   └── csv_archive/          # Imported CSVs kept for re-runs
│   ├── keyword_pool.csv          # Provided by user
│   └── tag_pool.csv              # Provided by user
├── alembic/                      # Database migrations
│   ├── env.py
│   └── versions/
├── alembic.ini
├── docker-compose.yml            # Postgres container (local dev)
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_validators.py        # Business rule tests
    └── test_modules/
```

**`docker-compose.yml` content:**
```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: etsy_taki_pg
    restart: unless-stopped
    environment:
      POSTGRES_DB: etsy_taki
      POSTGRES_USER: etsy
      POSTGRES_PASSWORD: etsy_local_dev   # local-only; override via .env if you want
    ports:
      - "5432:5432"
    volumes:
      - etsy_taki_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U etsy -d etsy_taki"]
      interval: 5s
      timeout: 3s
      retries: 10

volumes:
  etsy_taki_pgdata:
```

Run with: `docker compose up -d`. Stop with: `docker compose stop`. Persists across restarts.

**Validation:**
- Run `tree -L 3` and confirm structure matches.
- `pyproject.toml` with all dependencies listed.
- `.env.example` with all required env vars.

**Pause and confirm before Step 1.2.**

---

### Step 1.2: Configuration Management
**Goal:** Centralized settings via pydantic-settings.

**Implementation:**
In `src/config/settings.py`:
- Load from `.env`
- Required keys:
  - `ANTHROPIC_API_KEY`
  - `GEMINI_API_KEY`
  - `OPENAI_API_KEY`
  - `FAL_API_KEY`
  - `ETSY_API_KEY`
  - `ETSY_SHARED_SECRET`
  - `ETSY_SHOP_ID`
  - `DATABASE_URL` (default: `postgresql+psycopg://etsy:etsy_local_dev@localhost:5432/etsy_taki`)
  - `IMAGES_DIR` (default: `./data/images`)
  - `LOG_LEVEL` (default: `INFO`)
  - `DEFAULT_IMAGE_WORKFLOW` (one of: `gemini`, `openai`, `flux`)

In `src/config/business_rules.py`:
- Encode ALL the rules from Section 1 as constants and validation functions.
- Examples:
```python
TITLE_MIN_LENGTH = 137
TITLE_MAX_LENGTH = 140
FIRST_NICHE_CHARS = 60
TAG_COUNT = 13
TAG_DISTRIBUTION = {"niche": 8, "medium": 3, "big": 2}
TAG_MAX_LENGTH = 20

FORBIDDEN_TITLE_KEYWORDS = ["Stone"]  # use CZ or Pave
FORBIDDEN_TAG_PHRASES = ["Mother's Day Gift"]  # use "Gifts for Mom"

PENDANT_ALONE_PATTERN = ...  # regex check
SOLID_GOLD_PLATED_CONFLICT = ...  # both keywords not allowed

CLICHE_DESCRIPTION_PHRASES = [
    "Discover the beauty of",
    "Elevate your style",
    "Perfect for any occasion",
    "Add a touch of elegance",
]

MIN_IMAGES_PER_LISTING = 8
MAX_REAL_IMAGES_REQUIRED = 3  # Etsy AI policy compliance

CARRIER_PILLARS = [
    "cross", "name", "birthstone", "birth_flower", "pet", "pendant"
]

RENEW_HOURS_TR = [17, 21, 2, 5]  # Turkey time
```

**Validation:**
- Loading `Settings()` works without `.env` (uses defaults).
- Loading with all env vars set, all values accessible.
- `business_rules.py` is purely declarative (no logic, just constants).

---

### Step 1.3: Database Setup
**Goal:** Run Postgres via Docker; wire SQLAlchemy + Alembic; create initial models.

**Setup order:**
1. `docker compose up -d` (starts the `postgres:16-alpine` container)
2. Wait for healthcheck: `docker compose ps` → status should be `healthy`
3. Install deps: `pip install psycopg[binary] sqlalchemy alembic`
4. `alembic init alembic` from repo root → produces `alembic/` + `alembic.ini`
5. Edit `alembic/env.py`: set `target_metadata = Base.metadata` and read `sqlalchemy.url` from settings (`Settings().DATABASE_URL`)
6. `alembic revision --autogenerate -m "initial"` → first migration
7. `alembic upgrade head` → tables created

**SQLAlchemy engine setup** (`src/db/session.py`):
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.config.settings import Settings

settings = Settings()
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,       # graceful reconnect after docker restart
    pool_size=10,
    max_overflow=20,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
```

**JSON column note:**
Use `sqlalchemy.dialects.postgresql.JSONB` rather than the generic `JSON` for all JSON columns. JSONB is binary-encoded, indexable, and queryable — important for `tag_volumes`, `title_patterns`, and `volume_stratified_tags`. Example:

```python
from sqlalchemy.dialects.postgresql import JSONB

class CompetitorListing(Base):
    # ...
    tags = Column(JSONB)
    tag_volumes = Column(JSONB)
```

Phase 2 / Phase 3 models in this prompt show `Column(JSON)` for brevity — substitute `JSONB` in actual implementation.

**Models in `src/db/models.py`:**

```python
class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True)
    sku = Column(String(20), unique=True, nullable=False)  # TAKI-XXXX
    carrier_pillar = Column(Enum(CarrierPillar), nullable=False)
    
    # Manual input fields
    user_provided_title = Column(String(255))  # what user typed
    material = Column(String(100))  # Gold Plated, etc.
    color = Column(String(50))
    has_stone = Column(Boolean, default=False)
    stone_type = Column(String(100))  # CZ Baguette
    shape = Column(String(50))
    style = Column(String(50))
    occasion = Column(String(100))
    recipient = Column(String(50))
    size_info = Column(Text)  # 14k chain length etc.
    cost = Column(Numeric(10, 2))
    selling_price = Column(Numeric(10, 2))
    
    # Generated content (3 variants — see Phase 6 architecture)
    generated_variants = Column(JSONB)  # list of 3 ListingVariant dicts
    
    # Final selections (after human approval)
    final_title = Column(String(140))
    final_tags = Column(JSONB)
    final_description = Column(Text)
    selected_variant_id = Column(String(10))  # "A", "B", "C", or "HYBRID"
    
    # Etsy
    etsy_listing_id = Column(String(50))
    etsy_section_id = Column(String(50))
    
    # Status
    status = Column(Enum(ProductStatus), default=ProductStatus.MANUAL_INPUT)
    image_workflow_used = Column(String(20))  # gemini/openai/flux
    
    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime)
    published_at = Column(DateTime)
    
    images = relationship("ProductImage", back_populates="product")
    stats = relationship("ProductStats", back_populates="product")


class ProductImage(Base):
    __tablename__ = "product_images"
    
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    
    file_path = Column(String(500))  # ./data/images/TAKI-XXXX/...
    rank = Column(Integer)  # 1-9
    is_real = Column(Boolean, default=False)  # vs AI-generated
    workflow_source = Column(String(20))  # gemini/openai/flux/manual
    alt_text = Column(String(250))
    
    is_selected = Column(Boolean, default=False)  # included in final listing
    
    created_at = Column(DateTime, default=datetime.utcnow)


class KeywordPool(Base):
    """Niche keyword pool for tag generation."""
    __tablename__ = "keyword_pool"
    
    id = Column(Integer, primary_key=True)
    keyword = Column(String(50), unique=True, nullable=False)
    category = Column(Enum(TagCategory))  # niche, medium, big
    carrier_pillar = Column(Enum(CarrierPillar))


class ProductStats(Base):
    __tablename__ = "product_stats"
    
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    
    date = Column(Date)
    views = Column(Integer, default=0)
    favorites = Column(Integer, default=0)
    cart_adds = Column(Integer, default=0)
    sales = Column(Integer, default=0)
```

**Status enum:**
```python
class ProductStatus(str, Enum):
    MANUAL_INPUT = "manual_input"
    IMAGE_PROCESSING = "image_processing"
    CONTENT_GENERATING = "content_generating"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    PUBLISHED = "published"
    FAILED = "failed"
```

**Validation:**
- `docker compose ps` shows postgres `healthy`
- `psql postgresql://etsy:etsy_local_dev@localhost:5432/etsy_taki -c "\dt"` lists all tables after migration
- Insert sample product, query it back via SQLAlchemy session
- `alembic downgrade base` then `alembic upgrade head` cleanly rebuilds (idempotent)

---

### Step 1.4: Logging Infrastructure
**Goal:** Structured logging across all modules.

**Implementation:**
- Use `structlog` library
- Console output for dev, optional file output
- Log levels per module configurable
- Include `sku` and `step` in every business log

**Validation:**
- Importing logger from any module works
- Logs are structured JSON-ish, readable
- Each module's log shows `[module=image_pipeline sku=TAKI-0001 step=bg_remove]`

---

## PHASE 2: DOMAIN MODELS & VALIDATORS

### Step 2.1: Carrier Pillar Domain
**Goal:** Strict enum + helper functions.

**Implementation:**
- `CarrierPillar` enum with 6 values
- Function `get_section_name(pillar) -> str` returns Etsy section name
- Function `get_default_attributes(pillar) -> dict` returns common attrs

**Validation:**
- Each pillar maps to a section name
- Unit test covers all 6 pillars

---

### Step 2.2: Title Validator
**Goal:** Hardcoded function that validates a title against ALL Section 1.1 rules.

**Implementation:**
```python
def validate_title(title: str) -> tuple[bool, list[str]]:
    """
    Returns (is_valid, list_of_violations).
    Violations are human-readable error messages.
    """
    violations = []
    
    # 1. Length
    if not (137 <= len(title) <= 140):
        violations.append(f"Length {len(title)} not in [137, 140]")
    
    # 2. Stone keyword
    if "stone" in title.lower():
        violations.append("'Stone' keyword forbidden, use 'CZ' or 'Pave'")
    
    # 3. Pendant alone
    if re.search(r"\bPendant\b(?!\s+Necklace)", title):
        violations.append("'Pendant' alone not allowed, use 'Pendant Necklace'")
    
    # 4. Solid Gold + Gold Plated
    if "solid gold" in title.lower() and "gold plated" in title.lower():
        violations.append("'Solid Gold' and 'Gold Plated' cannot coexist")
    
    # 5. Repeated words (excluding common words)
    common = {"and", "for", "the", "with", "a", "an", "of", "in", "to"}
    words = [w.lower() for w in title.split() if w.lower() not in common]
    if len(words) != len(set(words)):
        duplicates = [w for w in words if words.count(w) > 1]
        violations.append(f"Repeated words: {set(duplicates)}")
    
    # 6. Mother's Day Gift
    if "mother's day gift" in title.lower():
        violations.append("Use 'Gifts for Mom' instead of 'Mother's Day Gift'")
    
    # 7. Capitalize first letter check (informational warning)
    # ... more rules as needed
    
    return (len(violations) == 0, violations)
```

**Validation:**
- Unit tests for each rule (both passing and failing cases)
- All 7 rules tested
- Edge cases: exact 137, exact 140, exact 136 (fail), exact 141 (fail)

---

### Step 2.3: Tag Validator
**Goal:** Validate 13-tag list against Section 1.2.

**Implementation:**
```python
def validate_tags(tags: list[str], title: str = "") -> tuple[bool, list[str]]:
    violations = []
    
    # Count
    if len(tags) != 13:
        violations.append(f"Tag count {len(tags)} != 13")
    
    # Length
    for tag in tags:
        if len(tag) > 20:
            violations.append(f"Tag '{tag}' exceeds 20 chars")
    
    # Forbidden phrases
    for tag in tags:
        if "mother's day gift" in tag.lower():
            violations.append(f"Tag '{tag}': use 'Gifts for Mom'")
    
    # Repeated tags
    if len(tags) != len(set(t.lower() for t in tags)):
        violations.append("Duplicate tags detected")
    
    # Duplicate with title (warning, not error)
    if title:
        title_words = set(title.lower().split())
        for tag in tags:
            if tag.lower() in title_words:
                violations.append(f"Tag '{tag}' already in title (wasted slot)")
    
    return (len(violations) == 0, violations)
```

**Validation:**
- Tests for count, length, forbidden phrases, duplicates

---

### Step 2.4: Description Originality Checker
**Goal:** Check new description doesn't match existing ones.

**Implementation:**
- Use `sentence-transformers` (model: `all-MiniLM-L6-v2`)
- Compute embedding of new description
- Compare against all existing descriptions in DB
- Return max similarity score
- Threshold: 0.85 means too similar → reject

```python
class OriginalityChecker:
    def __init__(self, session):
        self.session = session
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
    
    def check(self, new_description: str, threshold: float = 0.85) -> tuple[bool, float]:
        new_emb = self.model.encode(new_description)
        
        existing = self.session.query(Product.final_description).filter(
            Product.final_description.isnot(None)
        ).all()
        
        if not existing:
            return (True, 0.0)
        
        existing_embs = self.model.encode([d[0] for d in existing])
        similarities = cosine_similarity([new_emb], existing_embs)[0]
        
        max_sim = float(similarities.max())
        is_original = max_sim < threshold
        
        return (is_original, max_sim)
    
    def check_cliches(self, description: str) -> list[str]:
        """Check for forbidden cliché phrases."""
        found = []
        for cliche in CLICHE_DESCRIPTION_PHRASES:
            if cliche.lower() in description.lower():
                found.append(cliche)
        return found
```

**Validation:**
- Insert 3 sample descriptions, check 4th against them
- Test cliché detection

---

## PHASE 3: RESEARCH MODULE (Competitor Intelligence)

> **Purpose:** Ingest competitor data scraped from Etsy via the companion Chrome extension (Etsy Research Extension v1.1+) and turn it into structured intelligence that feeds the Content Pipeline (Phase 6). This module is what makes the LLM's title/tag/description generation grounded in **real bestseller data** instead of inventing from scratch.
>
> **Input:** CSV file exported from the Chrome extension (manual upload by user).
> **Output:** Populated `CompetitorListing`, `KeywordResearch`, `CompetitorShop` tables; analyzers produce summary objects that get injected into Phase 6 LLM prompts.

### Step 3.1: Research Domain Models
**Goal:** SQLAlchemy models for competitor intelligence.

**Implementation:**

Add to `src/db/models.py`:

```python
class CompetitorListing(Base):
    """One row per Etsy listing scraped via the Chrome extension."""
    __tablename__ = "competitor_listings"
    
    id = Column(Integer, primary_key=True)
    listing_id = Column(String(20), unique=True, nullable=False, index=True)
    url = Column(String(500))
    keyword_searched = Column(String(100), index=True)
    rank_in_search = Column(Integer)
    
    # Search-result-level fields (Phase 1 of extension)
    title = Column(String(255))
    image_url = Column(String(1000))  # primary thumbnail from search card
    shop_name = Column(String(100), index=True)
    shop_id = Column(String(20))
    shop_url = Column(String(500))
    shop_age_years = Column(Float)  # extracted from shop tooltip "X years on Etsy"
    price_cents = Column(Integer)
    currency = Column(String(10))
    original_price_cents = Column(Integer)
    discount_pct = Column(Integer)
    rating = Column(Float)
    review_count = Column(Integer)
    is_bestseller = Column(Boolean, default=False)
    is_star_seller = Column(Boolean, default=False)
    is_popular_now = Column(Boolean, default=False)
    is_etsys_pick = Column(Boolean, default=False)
    is_ad = Column(Boolean, default=False)
    has_video = Column(Boolean, default=False)
    
    # Page-level: total Etsy search results for the keyword (search volume proxy).
    # Same value for every row of the same keyword. Stored per-row for simplicity.
    keyword_total_results = Column(Integer)
    
    # ---- EHunt-injected enrichment (null if EHunt extension was not installed) ----
    # These come from EHunt's overlay on Etsy search pages. The user pays for EHunt;
    # we just read what EHunt has already placed in the DOM. No EHunt API calls.
    eh_sales_total = Column(Integer)        # e.g. 2700 (lifetime sales estimate)
    eh_sales_recent = Column(Integer)       # e.g. 15 (recent period, likely weekly)
    eh_favorites = Column(Integer)
    eh_shop_weekly_sales = Column(Integer)  # ground truth for "rising shop" detection
    eh_listed_date = Column(Date)           # when the listing was published
    
    # Listing-detail-level fields (Phase 2 of extension)
    views_24h_count = Column(String(20))  # e.g. "20+" or "150"
    cart_count = Column(Integer)
    stock_warning = Column(String(100))
    shop_total_sales = Column(Integer)
    has_sale_countdown = Column(Boolean, default=False)
    personalization_required = Column(Boolean, default=False)
    
    # Enrichment fields for LLM (extension v1.1+ only)
    tags = Column(JSON)  # list of strings — the listing's actual 13 seller tags (via EHunt panel)
    tag_volumes = Column(JSON)  # {tag: search_volume_int} — per-tag search volume from EHunt
    description_text = Column(Text)
    description_length = Column(Integer)
    image_count = Column(Integer)
    
    # ---- EHunt detail panel enrichment (extension v2.4+, listing-detail Phase 2 only) ----
    # When EHunt is installed, the listing detail page contains a #etsy-rank-tool-product-table
    # panel with these fields. They are richer than the Phase 1 EHunt search-card data:
    # the listing's actual 13 seller tags (otherwise hidden from public DOM since 2026),
    # search volumes per tag, release date, EHunt's own sales/reviews/favorites counts,
    # review ratio (good conversion proxy), Etsy category breadcrumb, current stock,
    # and average conversion rate (often "N/A").
    eh_detail_release_date = Column(Date)
    eh_detail_total_sales = Column(Integer)       # EHunt's Phase 2 sales count, may differ from Phase 1
    eh_detail_total_reviews = Column(Integer)
    eh_detail_total_favorites = Column(Integer)
    eh_detail_review_ratio = Column(String(20))   # e.g. "18.44%" — kept as string since EHunt formats it
    eh_detail_category = Column(String(255))      # e.g. "Weddings > Gifts & Mementos > Bridesmaids Gifts > Jewelry"
    eh_detail_stocks = Column(Integer)
    eh_detail_conv_rate = Column(String(20))      # often "N/A"; rarely a percent like "2.5%"
    
    # Computed
    sales_signal_score = Column(Float, index=True)  # see Step 3.7
    
    scraped_at = Column(DateTime)
    imported_at = Column(DateTime, default=datetime.utcnow)


class KeywordResearch(Base):
    """Aggregated stats per keyword. Refreshed after each CSV import."""
    __tablename__ = "keyword_research"
    
    id = Column(Integer, primary_key=True)
    keyword = Column(String(100), unique=True, nullable=False, index=True)
    
    total_listings_scraped = Column(Integer)
    bestseller_count = Column(Integer)
    star_seller_count = Column(Integer)
    avg_title_length = Column(Float)
    avg_review_count = Column(Float)
    avg_price_cents = Column(Float)
    avg_image_count = Column(Float)
    
    # Cached analyzer outputs (JSON blobs)
    title_patterns = Column(JSON)        # see Step 3.5
    top_tags_by_frequency = Column(JSON) # see Step 3.6
    common_cliches = Column(JSON)        # see Step 3.6
    underused_keywords = Column(JSON)    # see Step 3.5 — differentiation opportunity
    # Volume-stratified tag pools (only populated when ≥20% of listings have EHunt tag_volumes).
    # Used by Phase 6.3 to give each variant angle a different volume profile.
    volume_stratified_tags = Column(JSON)    # {"mainstream":[(tag,vol),...], "medium":[...], "niche":[...]}
    avg_volume_by_position = Column(JSON)    # list of 13 ints — typical volume per tag slot in the niche
    
    last_analyzed_at = Column(DateTime)


class CompetitorShop(Base):
    """Aggregated per-shop data for the 3-tier shop tracking strategy."""
    __tablename__ = "competitor_shops"
    
    id = Column(Integer, primary_key=True)
    shop_id = Column(String(20), unique=True, nullable=False)
    shop_name = Column(String(100), index=True)
    shop_url = Column(String(500))
    
    total_sales = Column(Integer)
    listings_in_research = Column(Integer)
    bestseller_listings = Column(Integer)
    avg_rating = Column(Float)
    
    # Classification per Section 1.9 strategy
    classification = Column(Enum(ShopClassification))  # ACTIVE_STRONG, LEGACY, RISING
    notes = Column(Text)  # manual notes
    
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime)


class ShopClassification(str, Enum):
    ACTIVE_STRONG = "active_strong"  # currently selling well
    LEGACY = "legacy"                # Star Seller but sales softened, old listings strong
    RISING = "rising"                # opened recently, hit thousands of sales fast
    UNKNOWN = "unknown"
```

**Validation:**
- Run alembic migration
- Insert sample CompetitorListing row, query back with all JSON fields intact
- Foreign key referential integrity if applicable

---

### Step 3.2: CSV Import Endpoint
**Goal:** Web UI + API endpoint to upload a CSV exported from the Chrome extension.

**Implementation:**
- Route: `GET /research/import` — simple upload form (file input + submit)
- Route: `POST /research/import` — accepts the CSV, parses, dedupes, persists
- Parse CSV with `pandas` or `csv` module
- For each row:
  - Build `CompetitorListing` instance
  - Parse `detail_tags` from `"tag1 | tag2 | tag3"` format → JSON list
  - Parse boolean fields (extension uses lowercase "true"/"false")
  - Skip duplicates by `listing_id` (or upsert: prefer the row with more detail data)
- After import: trigger analyzer pipeline (Steps 3.5-3.7) for affected keywords
- Show import summary: rows added, updated, skipped + per-keyword counts

```python
@router.post("/research/import")
async def import_research_csv(
    file: UploadFile = File(...),
    refresh_analyzers: bool = True,
    session: Session = Depends(get_session)
):
    df = pd.read_csv(file.file, encoding='utf-8-sig')  # BOM handling
    
    summary = {"added": 0, "updated": 0, "skipped": 0, "keywords": set()}
    
    for _, row in df.iterrows():
        listing = _parse_row_to_listing(row)
        if not listing.listing_id:
            summary["skipped"] += 1
            continue
        
        existing = session.query(CompetitorListing).filter_by(
            listing_id=listing.listing_id
        ).first()
        
        if existing:
            # Prefer the version with more detail (Phase 2 data > Phase 1 only)
            if listing.description_text and not existing.description_text:
                _merge_listing(existing, listing)
                summary["updated"] += 1
        else:
            session.add(listing)
            summary["added"] += 1
        
        summary["keywords"].add(row.get("keyword"))
    
    session.commit()
    
    if refresh_analyzers:
        for kw in summary["keywords"]:
            await refresh_keyword_research(session, kw)
    
    return {
        "added": summary["added"],
        "updated": summary["updated"],
        "skipped": summary["skipped"],
        "keywords_refreshed": list(summary["keywords"]),
    }
```

**CSV column mapping (from extension v2.4):**

| CSV column | DB field | Notes |
|------------|----------|-------|
| keyword | keyword_searched | |
| rank | rank_in_search | |
| listing_id | listing_id | primary key |
| title | title | search-result title |
| image_url | image_url | thumbnail URL — used in research dashboard |
| detail_title | (fallback for title) | use if title is empty |
| price_cents | price_cents | from hidden form when present, else parse from text |
| keyword_total_results | keyword_total_results | search-volume proxy, same per keyword |
| shop / detail_shop | shop_name | |
| shop_age_years | shop_age_years | from shop tooltip ("X years on Etsy") |
| rating / detail_rating | rating | prefer detail_rating |
| review_count | review_count | |
| is_bestseller / detail_is_bestseller | is_bestseller | OR them |
| is_star_seller / detail_is_star_seller | is_star_seller | OR them |
| **eh_sales_total** | **eh_sales_total** | **EHunt Phase 1: lifetime sales estimate** |
| **eh_sales_recent** | **eh_sales_recent** | **EHunt Phase 1: recent period (likely weekly)** |
| **eh_favorites** | **eh_favorites** | **EHunt Phase 1: favorites estimate** |
| **eh_shop_weekly_sales** | **eh_shop_weekly_sales** | **EHunt Phase 1: store weekly sales** |
| **eh_listed_date** | **eh_listed_date** | **EHunt Phase 1: when listing was published (ISO)** |
| views_24h_count | views_24h_count | string (can be "20+") |
| cart_count | cart_count | |
| cart_count_raw | (informational, optional column) | original badge text, e.g. "In 20+ carts" |
| shop_total_sales | shop_total_sales | |
| **detail_tags** | **tags** | **split on " \| ". When EHunt panel present, these are the ACTUAL 13 seller tags (Etsy hides them from public DOM since 2026, but EHunt fetches them via its own backend)** |
| **detail_tag_volumes** | **tag_volumes** | **JSON string `{tag: search_volume_int}`. Parse with json.loads. From EHunt detail panel.** |
| detail_description_text | description_text | |
| detail_description_length | description_length | |
| detail_image_count | image_count | |
| **eh_detail_release_date** | **eh_detail_release_date** | **EHunt detail panel: listing publish date** |
| **eh_detail_total_sales** | **eh_detail_total_sales** | **EHunt detail panel: Phase 2 sales count** |
| **eh_detail_total_reviews** | **eh_detail_total_reviews** | **EHunt detail panel** |
| **eh_detail_total_favorites** | **eh_detail_total_favorites** | **EHunt detail panel** |
| **eh_detail_review_ratio** | **eh_detail_review_ratio** | **kept as string e.g. "18.44%"** |
| **eh_detail_category** | **eh_detail_category** | **breadcrumb e.g. "Weddings > Gifts & Mementos > Bridesmaids Gifts > Jewelry"** |
| **eh_detail_stocks** | **eh_detail_stocks** | **current stock count from EHunt panel** |
| **eh_detail_conv_rate** | **eh_detail_conv_rate** | **often "N/A"; rarely a percent. Stored as string.** |

**Validation:**
- Upload sample CSV with 50 rows → 50 added, 0 skipped
- Upload same CSV again → 0 added, 0 updated, 50 skipped (or all updated if data richer)
- Tags column correctly parsed to list
- tag_volumes column correctly parsed from JSON (e.g. `{"Gifts": 83600000, ...}`)
- description_text preserved fully (test with row containing commas, newlines, quotes)
- EHunt detail panel fields populated for ~70% of Phase 2 listings (some listings aren't in EHunt's DB)

---

### Step 3.3: Sales Signal Scorer
**Goal:** Compute a single 0-100 score combining all sales signals so analyzers can rank listings by "actually-selling-ness".

**Implementation:**
Two-tier formula in `src/modules/research/scoring.py`. EHunt data, when present, is **ground truth** and dominates the score. When EHunt is absent, fall back to the proxy-based heuristic from the training.

```python
def compute_sales_signal_score(listing: CompetitorListing) -> float:
    """
    Returns 0-100. Higher = stronger evidence the listing is actively selling.
    
    TIER A: EHunt data present (ground truth from EHunt subscription)
    --------------------------------------------------------------------
    EHunt shows lifetime sales + recent-period sales + store weekly sales.
    These are aggregated estimates from EHunt's data lake, not heuristics.
    When available, this tier dominates the score.
    
    TIER B: EHunt data absent (proxy heuristics, per training docs)
    --------------------------------------------------------------------
    Signal weights:
    - Bestseller badge: 25 pts (Etsy's own 6-month-top-performer stamp)
    - Star Seller badge: 10 pts (shop-level, weaker signal for individual listing)
    - Popular Now: 15 pts (currently trending)
    - 24h views > 0: 0-25 pts scaled (most current activity signal)
    - Cart count > 0: 0-15 pts scaled
    - Review count: 0-10 pts scaled (training: 1 review ≈ 5-10 sales)
    """
    
    # ---- TIER A: EHunt available ----
    if listing.eh_sales_recent is not None or listing.eh_sales_total is not None:
        score = 0.0
        
        # Recent-period sales (likely weekly) is the strongest signal
        if listing.eh_sales_recent is not None:
            if listing.eh_sales_recent >= 100: score += 50
            elif listing.eh_sales_recent >= 50: score += 40
            elif listing.eh_sales_recent >= 20: score += 30
            elif listing.eh_sales_recent >= 10: score += 20
            elif listing.eh_sales_recent >= 5: score += 10
            elif listing.eh_sales_recent >= 1: score += 5
        
        # Lifetime sales — validates the listing isn't a fluke
        if listing.eh_sales_total is not None:
            if listing.eh_sales_total >= 5000: score += 20
            elif listing.eh_sales_total >= 1000: score += 15
            elif listing.eh_sales_total >= 500: score += 10
            elif listing.eh_sales_total >= 100: score += 5
        
        # Store weekly sales — corroborating signal for the shop's health
        if listing.eh_shop_weekly_sales is not None:
            if listing.eh_shop_weekly_sales >= 500: score += 15
            elif listing.eh_shop_weekly_sales >= 100: score += 10
            elif listing.eh_shop_weekly_sales >= 20: score += 5
        
        # Bonus: Etsy's own badges still add credibility
        if listing.is_bestseller: score += 10
        if listing.is_popular_now: score += 5
        
        return min(100, score)
    
    # ---- TIER B: Proxy heuristics (training-doc fallback) ----
    score = 0.0
    if listing.is_bestseller: score += 25
    if listing.is_popular_now: score += 15
    if listing.is_star_seller: score += 10
    
    views = _parse_views_count(listing.views_24h_count)
    if views is not None:
        score += min(25, views / 4)  # 100 views = 25 pts
    
    if listing.cart_count:
        score += min(15, listing.cart_count / 5)
    
    if listing.review_count:
        score += min(10, listing.review_count / 200)  # 2000 reviews = 10 pts
    
    return min(100, score)
```

Run this on every CompetitorListing during import (or as a separate pass).

**Validation:**
- Listing with EHunt eh_sales_recent=50 + bestseller → score ≥ 50 (Tier A path)
- Listing with no EHunt data + bestseller + 20+ views + 50 in cart → score 50-75 (Tier B path)
- Listing with nothing (only review_count=10) → score < 10
- All listings get a non-null score after import
- Tier A path takes precedence whenever ANY eh_* field is non-null

---

### Step 3.4: Shop Classification (3-Tier from Training)
**Goal:** Classify every shop into the training's 3 buckets (Active/Legacy/Rising) using `shop_age_years` and aggregated sales signals.

**Implementation:**
```python
def classify_shop(session, shop_id: str) -> ShopClassification:
    """
    Per training (Section 1.9):
    - ACTIVE_STRONG: established shop, still selling well now
    - LEGACY:       older shop, soft current sales but strong back catalog
    - RISING:       opened ≤ 24 months ago, already shipping volume
    """
    shop = session.query(CompetitorShop).filter_by(shop_id=shop_id).first()
    if not shop:
        return ShopClassification.UNKNOWN
    
    # Pull a representative listing for eh_shop_weekly_sales (same value across
    # all listings in a shop). Also use total_sales as a long-term proxy.
    sample = session.query(CompetitorListing).filter_by(shop_id=shop_id).first()
    weekly = (sample.eh_shop_weekly_sales if sample else None) or 0
    age = shop.opening_year_months_ago or 999
    total = shop.total_sales or 0
    
    if age <= 24 and total >= 1000:
        return ShopClassification.RISING       # young + already shipping
    if weekly >= 50 and total >= 5000:
        return ShopClassification.ACTIVE_STRONG
    if total >= 10000 and weekly < 30:
        return ShopClassification.LEGACY       # big back catalog, current activity dropped
    if weekly >= 30:
        return ShopClassification.ACTIVE_STRONG
    return ShopClassification.UNKNOWN
```

Run after every CSV import. Store the classification on the `CompetitorShop` row. Surface in the research dashboard so the user can prioritize **RISING** shops (training: these are the model-after targets).

**Validation:**
- A shop with 2-year age + 5000 total sales + 200 weekly → RISING
- A shop with 8-year age + 100K total + 500 weekly → ACTIVE_STRONG
- A shop with 8-year age + 100K total + 5 weekly → LEGACY
- Shops without enough data → UNKNOWN (no false positives)

---

### Step 3.5: Title Pattern Analyzer
**Goal:** For each keyword, identify common title patterns + the keyword frequency that bestsellers use.

**Implementation:**
In `src/modules/research/title_analyzer.py`:

```python
async def analyze_titles_for_keyword(
    session: Session, 
    keyword: str,
    llm_client
) -> dict:
    """
    Returns a dict with:
    - avg_length
    - length_distribution (5th/50th/95th percentile)
    - common_opening_words (top 10)
    - common_phrases (3-word ngrams, top 20)
    - keyword_frequency: {keyword: (count, weighted_count)}
        weighted_count = sum of sales_signal_score for listings containing the keyword
    - underused_keywords: keywords that appear in <30% of titles but are in 
        bestsellers (differentiation opportunities)
    - llm_extracted_patterns: structural patterns from LLM analysis
    """
    
    # Get top 50 listings by sales_signal_score for this keyword
    listings = session.query(CompetitorListing).filter_by(
        keyword_searched=keyword
    ).order_by(CompetitorListing.sales_signal_score.desc()).limit(50).all()
    
    if not listings:
        return None
    
    titles = [l.title for l in listings if l.title]
    
    # 1. Length stats
    lengths = [len(t) for t in titles]
    avg_length = sum(lengths) / len(lengths)
    
    # 2. N-gram frequency (1, 2, 3 grams)
    keyword_freq = _compute_ngram_frequency(titles, n_range=(1, 3))
    
    # 3. Sales-weighted frequency
    weighted_freq = _compute_weighted_frequency(listings, keyword_freq)
    
    # 4. LLM structural pattern extraction
    patterns = await _llm_extract_patterns(llm_client, titles[:20])
    
    # 5. Underused differentiation candidates
    underused = _find_underused_keywords(
        keyword_freq, weighted_freq, threshold=0.30
    )
    
    return {
        "keyword": keyword,
        "sample_size": len(titles),
        "avg_length": avg_length,
        "length_p5_p50_p95": _percentiles(lengths, [5, 50, 95]),
        "top_unigrams": keyword_freq["1"][:15],
        "top_bigrams": keyword_freq["2"][:10],
        "top_trigrams": keyword_freq["3"][:5],
        "sales_weighted_keywords": weighted_freq[:20],
        "structural_patterns": patterns,
        "underused_keywords": underused,
    }
```

LLM pattern extraction prompt:

```
You are analyzing Etsy listing titles for the keyword "{keyword}".
Below are 20 actual titles from the top-selling listings.

Extract 3-5 structural patterns you observe. A pattern is a TEMPLATE, 
not a literal title. For example:
- "[Material] + [Size adjective] + [Product] + [Religious term] + [Gift phrase]"
- "[Style] + [Product] Necklace, [Synonym] Pendant, [Gift phrase]"

Output JSON only:
{{
  "patterns": [
    {{"pattern": "...", "examples": ["title1", "title2"]}},
    ...
  ]
}}

Titles:
{titles_numbered}
```

Persist result to `KeywordResearch.title_patterns`.

**Validation:**
- Run on a keyword with 30+ scraped listings
- Output includes 5-10 patterns, plausible n-grams, and underused keywords
- Top n-grams contain the keyword itself + common modifiers

---

### Step 3.6: Tag Frequency & Cliché Analyzer
**Goal:** Build a sales-weighted frequency table of tag-like keywords used by competitor listings + extract cliché phrases from descriptions. **Bonus when EHunt detail panel is present:** stratify tags by search volume (mainstream vs medium vs niche) — this is critical for Phase 6's variant strategy.

**CRITICAL ARCHITECTURAL NOTE — Tags come from EHunt, not Etsy:**
As of 2026, Etsy hides the seller's actual 13 tags from the public listing-page DOM (across all locales). The Chrome extension v2.4+ recovers them by reading EHunt extension's injected detail panel (`#etsy-rank-tool-product-table`) on listing detail pages. EHunt fetches tags via its own backend and renders them with **per-tag search volume** (e.g. "Personalized Gift (113.0M)" → 113,000,000 monthly searches). The extension parses this panel and populates two columns:

- `CompetitorListing.tags` — list of strings (the 13 real tags)
- `CompetitorListing.tag_volumes` — dict of `{tag: search_volume_int}`

Expected fill rate: ~70% of Phase 2 listings have real tags (some new/niche listings aren't in EHunt's DB).

For the remaining ~30%, we fall back to title-derived n-grams (which correlate ~85% with actual tag sets for the same niche). Sources in order of reliability:
1. **Primary:** `CompetitorListing.tags` from EHunt panel (with `tag_volumes` for stratification)
2. **Fallback:** Title-derived bigrams/trigrams from `CompetitorListing.title`
3. **Secondary:** Description-derived noun-phrases (used for cliché detection)

**Implementation:**
In `src/modules/research/tag_analyzer.py`:

```python
def analyze_tags_for_keyword(session: Session, keyword: str) -> dict:
    """
    Returns:
    - sample_size, source, real_tag_ratio
    - all_tags_frequency: [(tag, count), ...] sorted desc
    - sales_weighted_tags: [(tag, weighted_score), ...] — best tags by sales signal
    - bestseller_tags: tags that bestsellers use
    - volume_stratified_tags: {                # NEW — only when real tags present
        "mainstream":  [(tag, volume), ...]   # >50M searches
        "medium":      [(tag, volume), ...]   # 10M-50M
        "niche":       [(tag, volume), ...]   # <10M, underused goldmines
      }
    - avg_tag_volume_by_position: [vol, vol, ...]  # mean volume per slot 1..13
                                                    # tells us what the niche typically uses
    """
    listings = session.query(CompetitorListing).filter_by(
        keyword_searched=keyword
    ).all()
    if not listings:
        return None

    # Decide tag source: prefer real tags (from EHunt) if at least 20% of listings have them
    listings_with_tags = [l for l in listings if l.tags and len(l.tags) >= 3]
    real_tag_ratio = len(listings_with_tags) / len(listings)
    use_real_tags = real_tag_ratio >= 0.20

    if use_real_tags:
        source = 'real_tags_via_ehunt'
        tag_iter = lambda l: l.tags or []
    else:
        source = 'title_derived'
        tag_iter = lambda l: extract_title_ngrams(l.title) if l.title else []

    tag_weights = defaultdict(float)
    tag_counts = defaultdict(int)
    bestseller_tags = defaultdict(int)
    # Aggregate tag volumes across all listings that have EHunt data.
    # If a tag appears with different volume numbers (it shouldn't but EHunt may report
    # slightly different numbers across listings), we take the median.
    from statistics import median
    tag_volume_observations = defaultdict(list)

    for listing in listings:
        # Capture per-tag volumes from EHunt data
        if listing.tag_volumes:
            for tag, vol in listing.tag_volumes.items():
                tag_norm = tag.lower().strip()
                if isinstance(vol, (int, float)) and vol > 0:
                    tag_volume_observations[tag_norm].append(int(vol))

        for tag in tag_iter(listing):
            tag_normalized = tag.lower().strip()
            if len(tag_normalized) < 3 or len(tag_normalized) > 30:
                continue
            tag_counts[tag_normalized] += 1
            tag_weights[tag_normalized] += listing.sales_signal_score or 0
            if listing.is_bestseller:
                bestseller_tags[tag_normalized] += 1

    # Per-tag median volume
    tag_volume_median = {
        t: int(median(vols)) for t, vols in tag_volume_observations.items()
    }

    sales_weighted = sorted(tag_weights.items(), key=lambda x: x[1], reverse=True)

    # Volume stratification — only if we have real volume data
    volume_stratified = None
    if tag_volume_median:
        # Only stratify tags we've actually seen in the data, ranked by sales weight
        mainstream, medium, niche = [], [], []
        for tag, _w in sales_weighted[:60]:
            vol = tag_volume_median.get(tag)
            if vol is None:
                continue
            if vol > 50_000_000:
                mainstream.append((tag, vol))
            elif vol > 10_000_000:
                medium.append((tag, vol))
            else:
                niche.append((tag, vol))
        volume_stratified = {
            "mainstream": mainstream[:20],
            "medium": medium[:20],
            "niche": niche[:20],  # these are the goldmine — Phase 6 Variant B uses them
        }

    # Per-position volume average across listings (slot 1..13)
    avg_volume_by_position = None
    if use_real_tags and any(l.tag_volumes for l in listings_with_tags):
        position_vols = defaultdict(list)
        for l in listings_with_tags:
            if not l.tag_volumes or not l.tags:
                continue
            for pos, tag in enumerate(l.tags):
                vol = l.tag_volumes.get(tag)
                if vol:
                    position_vols[pos].append(int(vol))
        avg_volume_by_position = [
            int(sum(position_vols[i]) / len(position_vols[i])) if position_vols[i] else None
            for i in range(13)
        ]

    return {
        "sample_size": len(listings),
        "source": source,
        "real_tag_ratio": real_tag_ratio,
        "all_tags_frequency": sorted(tag_counts.items(), key=lambda x: -x[1])[:50],
        "sales_weighted_tags": sales_weighted[:30],
        "bestseller_tags": sorted(bestseller_tags.items(), key=lambda x: -x[1])[:20],
        "tag_volume_median": tag_volume_median,
        "volume_stratified_tags": volume_stratified,
        "avg_volume_by_position": avg_volume_by_position,
    }


def extract_title_ngrams(title: str) -> list[str]:
    """
    Extract 2-3 word phrases from a competitor title as tag candidates.
    Etsy titles are comma-separated phrases — split on commas first, then
    drop stopword-only fragments, deduplicate.
    """
    if not title:
        return []
    
    # Etsy titles are comma-separated phrases like
    # "Dainty Gold Cross Necklace, Tiny Sideways Cross Pendant, Gift for Her"
    phrases = [p.strip().lower() for p in title.split(',')]
    
    candidates = []
    STOPWORDS = {'the', 'a', 'an', 'and', 'or', 'with', 'for', 'in', 'to', 'of', 'on', 'by'}
    for phrase in phrases:
        words = [w for w in phrase.split() if w and w not in STOPWORDS]
        if not words:
            continue
        # Whole phrase is one candidate
        if 2 <= len(words) <= 4:
            candidates.append(' '.join(words))
        # Also add 2-grams from the phrase (captures sub-tags)
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            if bigram not in candidates:
                candidates.append(bigram)
    
    return candidates


async def extract_cliches(
    session: Session, 
    keyword: str,
    llm_client
) -> list[str]:
    """
    Pulls 20 competitor descriptions for the keyword, asks LLM to identify
    overused opening phrases / templated sentences.
    These get added to the dynamic cliché blacklist used in Phase 6 description generation.
    """
    listings = session.query(CompetitorListing).filter_by(
        keyword_searched=keyword
    ).filter(CompetitorListing.description_text.isnot(None)).limit(20).all()
    
    if len(listings) < 5:
        return []
    
    descriptions = [l.description_text[:500] for l in listings]
    
    prompt = f"""Below are 20 Etsy product description openings for jewelry.

Identify phrases that appear in MULTIPLE descriptions or that have a 
templated, AI-generated feel. These are clichés our system MUST AVOID.

Return JSON only:
{{"cliches": ["exact phrase 1", "exact phrase 2", ...]}}

Descriptions:
{chr(10).join(f"{i+1}. {d}" for i, d in enumerate(descriptions))}
"""
    
    response = await llm_client.complete(prompt)
    return json.loads(response).get("cliches", [])
```

Persist to `KeywordResearch.top_tags_by_frequency` and `common_cliches`.

**Validation:**
- For a keyword with 20+ listings that have tags: top_tags_by_frequency has 20-50 entries, sorted correctly
- LLM cliché extraction returns 5-15 plausible phrases (test by inspection)
- Clichés correctly identified as overused (manual spot-check)

---

### Step 3.7: Research Refresh Pipeline (Weekly Schedule)
**Goal:** A function that re-runs all analyzers (Step 3.5, 3.6) for a given keyword and persists everything to KeywordResearch. Wired into APScheduler (Phase 9) to refresh **weekly** by default.

**Why weekly:**
- Etsy's bestseller turnover happens on the order of weeks, not days. Refreshing daily wastes EHunt budget and LLM tokens without changing the research output meaningfully.
- A weekly cadence catches seasonal shifts (e.g. Mother's Day → graduation → Father's Day) without being so frequent that "noise" overwhelms signal.
- User keeps the option to manually trigger refresh from the dashboard (Step 3.8) any time.

**Implementation:**
```python
async def refresh_keyword_research(
    session: Session, 
    keyword: str,
    llm_client
):
    # First compute sales signal for any unscored listings
    unscored = session.query(CompetitorListing).filter_by(
        keyword_searched=keyword,
        sales_signal_score=None
    ).all()
    for l in unscored:
        l.sales_signal_score = compute_sales_signal_score(l)
    session.commit()
    
    # Run analyzers
    title_analysis = await analyze_titles_for_keyword(session, keyword, llm_client)
    tag_analysis = analyze_tags_for_keyword(session, keyword)
    cliches = await extract_cliches(session, keyword, llm_client)
    
    # Upsert KeywordResearch
    research = session.query(KeywordResearch).filter_by(keyword=keyword).first()
    if not research:
        research = KeywordResearch(keyword=keyword)
        session.add(research)
    
    research.total_listings_scraped = title_analysis["sample_size"]
    research.avg_title_length = title_analysis["avg_length"]
    research.title_patterns = title_analysis
    research.top_tags_by_frequency = tag_analysis
    research.common_cliches = cliches
    research.underused_keywords = title_analysis["underused_keywords"]
    research.last_analyzed_at = datetime.utcnow()
    
    bestseller_count = session.query(CompetitorListing).filter_by(
        keyword_searched=keyword,
        is_bestseller=True
    ).count()
    research.bestseller_count = bestseller_count
    
    session.commit()


async def refresh_all_keywords_job(session, llm_client):
    """The weekly job — scheduled via APScheduler in Phase 9."""
    keywords = [k.keyword for k in session.query(KeywordResearch).all()]
    for kw in keywords:
        try:
            await refresh_keyword_research(session, kw, llm_client)
        except Exception as e:
            logger.error(f"Refresh failed for {kw}: {e}")
    logger.info(f"Weekly refresh complete: {len(keywords)} keywords")
```

**Schedule registration** (will be wired in Phase 9):
```python
# In Phase 9 scheduler setup:
scheduler.add_job(
    refresh_all_keywords_job,
    trigger='cron',
    day_of_week='mon',   # every Monday
    hour=3, minute=0,    # 03:00 local time (low-traffic window)
    args=[session, llm_client],
    id='research_weekly_refresh',
    replace_existing=True
)
```

Note: this only updates the **analysis** (title patterns, cliches, etc) from existing data. To get **new competitor listings**, the user must run the Chrome extension Phase 1 + 2 again and import the fresh CSV. The auto-refresh is for re-analysis, not re-scraping.

**Validation:**
- Calling `refresh_keyword_research()` on a keyword updates the KeywordResearch row
- All JSON fields populated
- Idempotent: calling twice yields same result (no duplicates, no corruption)
- The weekly job runs on schedule, logged each Monday at 03:00
- Manual refresh button in dashboard (Step 3.8) calls the same function

---

### Step 3.8: Research Dashboard UI
**Goal:** Browse imported research data per keyword. Used both for sanity-checking imports and for the user to manually decide which keyword to target.

**Implementation:**
- Route: `GET /research` — list all keywords with stats (sample size, bestseller count, last analyzed)
- Route: `GET /research/{keyword}` — detail view:
  - **Top 20 listings by sales_signal_score** rendered as a grid with thumbnails (using `CompetitorListing.image_url`) — visual scan to verify the keyword actually matches what you sell. If 80% of thumbnails look unrelated to your niche, the keyword is wrong.
  - Title patterns (cards)
  - Top tags chart (bar)
  - Common clichés (list)
  - Underused keywords (highlighted as differentiation opportunities)
  - Button: "Refresh analysis" → calls Step 3.7
- Route: `GET /research/shops` — competitor shop list with classification editor

**Visual relevance check (important):**
Use the thumbnails as a quick filter. Etsy's keyword matching is loose — a search for "cross necklace" can include random unrelated products. The dashboard should make it easy to spot when this is happening so the user knows to refine their scraping keywords.

**Validation:**
- Dashboard loads, shows all keywords
- Drill-down shows analyzer output cleanly
- Refresh button re-runs analyzers and updates display

---

### Step 3.9: Research Context Builder (Bridge to Phase 6)
**Goal:** A function that produces an "intelligence brief" string injected into Phase 6 content generation prompts.

**Implementation:**
```python
class ResearchContextBuilder:
    """
    Given a product (with carrier_pillar + features), produce a compact
    intelligence brief from KeywordResearch + CompetitorListing data.
    Output goes directly into the LLM prompts in Phase 6.
    """
    
    def __init__(self, session: Session):
        self.session = session
    
    def build_for_product(self, product: Product) -> ResearchContext:
        # Map product to relevant keyword(s)
        keywords = self._derive_keywords(product)
        
        # Aggregate research across these keywords
        research = self.session.query(KeywordResearch).filter(
            KeywordResearch.keyword.in_(keywords)
        ).all()
        
        if not research:
            return ResearchContext.empty()  # fallback: generate without enrichment
        
        return ResearchContext(
            sample_size=sum(r.total_listings_scraped for r in research),
            avg_title_length=mean(r.avg_title_length for r in research if r.avg_title_length),
            top_keywords_sales_weighted=self._merge_keyword_freq(research),
            underused_keywords=self._merge_underused(research),
            structural_patterns=self._merge_patterns(research),
            top_tags=self._merge_tags(research),
            cliches_to_avoid=self._merge_cliches(research),
            volume_stratified_tags=self._merge_volume_stratified(research),
            avg_volume_by_position=self._merge_avg_volume_by_position(research),
        )


@dataclass
class ResearchContext:
    sample_size: int
    avg_title_length: float
    top_keywords_sales_weighted: list[tuple[str, float]]
    underused_keywords: list[str]
    structural_patterns: list[dict]
    top_tags: list[tuple[str, int]]
    cliches_to_avoid: list[str]
    # Volume-aware fields (only populated when EHunt tag_volumes were available in research data)
    volume_stratified_tags: dict | None = None  # {"mainstream":[(tag,vol),...], "medium":[...], "niche":[...]}
    avg_volume_by_position: list[int] | None = None  # 13 ints: typical volume per tag slot
    
    @classmethod
    def empty(cls):
        return cls(0, 0.0, [], [], [], [], [], None, None)
    
    @property
    def has_data(self) -> bool:
        return self.sample_size > 0
    
    @property
    def has_volume_data(self) -> bool:
        return bool(self.volume_stratified_tags)
    
    def format_for_prompt(self) -> str:
        """Render as text block for LLM prompts."""
        if not self.has_data:
            return "No competitor research available for this product category yet."
        
        out = f"""
COMPETITOR INTELLIGENCE (based on {self.sample_size} real Etsy listings):

- Average title length used by bestsellers: {self.avg_title_length:.0f} chars
- Most common keywords (sales-weighted):
  {self._fmt_keywords(self.top_keywords_sales_weighted[:15])}
- Underused but promising (differentiation opportunities):
  {', '.join(self.underused_keywords[:10])}
- Top structural patterns:
  {self._fmt_patterns(self.structural_patterns[:5])}
- Top tags by sales-weighted frequency:
  {self._fmt_tags(self.top_tags[:20])}
- CLICHÉS TO AVOID in descriptions:
  {chr(10).join(f"  • {c}" for c in self.cliches_to_avoid[:10])}
"""
        # Append volume-aware section when available
        if self.has_volume_data:
            vs = self.volume_stratified_tags
            mainstream = ', '.join(f"{t} ({_fmt_vol(v)})" for t, v in (vs.get('mainstream') or [])[:8])
            medium     = ', '.join(f"{t} ({_fmt_vol(v)})" for t, v in (vs.get('medium')     or [])[:8])
            niche      = ', '.join(f"{t} ({_fmt_vol(v)})" for t, v in (vs.get('niche')      or [])[:10])
            out += f"""
TAG SEARCH VOLUME STRATIFICATION (from EHunt data — use this for variant differentiation):
- MAINSTREAM tags (>50M searches, high competition): {mainstream or '(none in sample)'}
- MEDIUM tags (10M-50M, balanced): {medium or '(none in sample)'}
- NICHE tags (<10M, low competition, highly targeted): {niche or '(none in sample)'}
"""
        return out


def _fmt_vol(v: int) -> str:
    """Format search volume compactly: 113000000 → '113M', 3800000 → '3.8M'."""
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M".replace(".0M", "M")
    if v >= 1_000:
        return f"{v / 1_000:.0f}K"
    return str(v)
```

**Validation:**
- For a product with carrier_pillar=cross, builder returns a non-empty ResearchContext (assuming research data exists)
- `format_for_prompt()` produces a readable text block under 2000 chars
- Empty case handled gracefully (no crash, just empty brief)

---

### Step 3.10: Empty State Handling
**Goal:** Define what happens when a product has no research data available.

**Implementation:**
Phase 6 generators (title, tag, description) must work in two modes:
1. **Enriched mode:** ResearchContext has data → inject into prompt
2. **Cold start mode:** No research → use generic keyword pool + base rules only

Add a config flag: `REQUIRE_RESEARCH_FOR_GENERATION` (default False during early use, True later for stricter quality).

When True: refuse to generate content for a product whose carrier_pillar has no research; surface a UI message "Please import competitor research first for: cross necklace, birthstone necklace, ..."

**Validation:**
- Generate content for a product with research → enriched prompt visible in LLM logs
- Generate for a product without research → fallback to base prompt, content still generated
- With strict flag on: refuses cleanly, user-facing error message

---

## PHASE 4: MANUAL INPUT MODULE

### Step 4.1: Manual Input Form (Web UI)
**Goal:** Web form for entering product manually.

**Implementation:**
- Route: `GET /products/new` and `POST /products/new`
- Form fields:
  - Carrier Pillar (dropdown: 6 pillars)
  - Material (Gold Plated / Brass / 925 Sterling Silver)
  - Color
  - Has stone? + stone type (CZ Baguette etc.)
  - Shape (dropdown)
  - Style (dropdown)
  - Occasion (multi-select)
  - Recipient (dropdown)
  - Size info (text)
  - Cost (decimal)
  - Selling price (decimal)
  - **Image upload:** at least 1 real product image (from Reksven)
  - Optional: additional reference images
- Submit → creates Product with status MANUAL_INPUT
- Auto-generates SKU: `TAKI-{next_number:04d}`

**Validation:**
- Form renders correctly
- File upload saves to `./data/images/{SKU}/originals/`
- Product is created in DB with all fields
- SKU auto-increments

---

### Step 4.2: Product List & Detail Views
**Goal:** See all products, click into one.

**Implementation:**
- Route: `GET /products` — list all products with status badges
- Route: `GET /products/{sku}` — detail view
  - Show: all fields, all images, status, generated content (if any)
  - Action buttons (status-dependent):
    - **"Process Product"** (if MANUAL_INPUT) — triggers the full async pipeline (Stage 1→2→3 from Section 2)
    - **"View Progress"** (if IMAGE_PROCESSING or CONTENT_GENERATING) — polls status endpoint, shows progress
    - **"Review & Approve"** (if AWAITING_APPROVAL) — opens approval interface
    - **"View Live Listing"** (if PUBLISHED) — opens Etsy listing in new tab
    - **"Retry"** (if FAILED) — re-runs pipeline from last successful stage
  - Workflow selector dropdown next to "Process Product" (default: from settings)

**Validation:**
- List shows all products, sortable
- Detail page shows everything correctly
- "Process Product" button triggers pipeline + redirects to progress view
- Progress view auto-refreshes via polling, then redirects to approval when ready

---

## PHASE 5: AI IMAGE PIPELINE (Multi-Workflow)

### Step 5.1: Abstract Image Generator Interface
**Goal:** Common interface for all 3 image models.

**Implementation:**
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from PIL import Image

@dataclass
class ImageGenerationRequest:
    reference_image: Image.Image  # Background-removed jewelry
    prompt: str
    style_hint: str  # e.g. "professional jewelry photography, soft natural lighting"
    num_outputs: int = 1
    seed: int | None = None
    extra_params: dict = None

@dataclass
class ImageGenerationResult:
    image: Image.Image
    model_name: str
    cost_estimate: float
    metadata: dict


class AbstractImageGenerator(ABC):
    @abstractmethod
    async def generate(self, request: ImageGenerationRequest) -> list[ImageGenerationResult]:
        pass
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        pass
    
    @property
    @abstractmethod
    def cost_per_image(self) -> float:
        pass
```

**Validation:**
- Interface is well-defined
- Subclasses must implement all abstract methods
- Type hints complete

---

### Step 5.2: Background Removal (Preprocessing)
**Goal:** Remove background from Reksven photo before AI generation.

**Implementation:**
- Use `rembg` library (local, no API cost)
- Function `remove_background(image_path) -> Image.Image` (returns transparent PNG)
- Save preprocessed image to `./data/images/{SKU}/preprocessed/`

**Validation:**
- Input real jewelry photo, output is clean jewelry with transparent BG
- Quality is good (no jagged edges)

---

### Step 5.3: Gemini Image Generator
**Goal:** Implement using Gemini 2.5 Flash Image (Nano Banana).

**Implementation:**
```python
from google import genai
from google.genai import types

class GeminiImageGenerator(AbstractImageGenerator):
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
    
    async def generate(self, request: ImageGenerationRequest) -> list[ImageGenerationResult]:
        # Save reference image temporarily
        ref_bytes = io.BytesIO()
        request.reference_image.save(ref_bytes, format='PNG')
        
        # Call Gemini with multi-image input
        full_prompt = f"{request.prompt}\n\nStyle: {request.style_hint}"
        
        response = self.client.models.generate_content(
            model='gemini-2.5-flash-image',
            contents=[
                types.Part.from_bytes(data=ref_bytes.getvalue(), mime_type='image/png'),
                full_prompt
            ]
        )
        
        # Parse image from response
        results = []
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                img = Image.open(io.BytesIO(part.inline_data.data))
                results.append(ImageGenerationResult(
                    image=img,
                    model_name=self.model_name,
                    cost_estimate=self.cost_per_image,
                    metadata={"prompt": full_prompt}
                ))
        
        return results
    
    @property
    def model_name(self) -> str:
        return "gemini-2.5-flash-image"
    
    @property
    def cost_per_image(self) -> float:
        return 0.039  # current Gemini pricing, check at runtime
```

**Validation:**
- Provide test jewelry image
- Generate 1 lifestyle scene
- Output is reasonable
- Cost is logged

---

### Step 5.4: OpenAI Image Generator
**Goal:** Implement using gpt-image-1.

**Implementation:**
- Use openai SDK
- Use image edit endpoint (better for reference-based generation)
- Same interface as Gemini

```python
class OpenAIImageGenerator(AbstractImageGenerator):
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
    
    async def generate(self, request: ImageGenerationRequest) -> list[ImageGenerationResult]:
        ref_bytes = io.BytesIO()
        request.reference_image.save(ref_bytes, format='PNG')
        ref_bytes.seek(0)
        
        response = self.client.images.edit(
            model="gpt-image-1",
            image=ref_bytes,
            prompt=f"{request.prompt}. {request.style_hint}",
            n=request.num_outputs,
            size="1024x1024"
        )
        
        results = []
        for img_data in response.data:
            img_bytes = base64.b64decode(img_data.b64_json)
            img = Image.open(io.BytesIO(img_bytes))
            results.append(ImageGenerationResult(
                image=img,
                model_name=self.model_name,
                cost_estimate=self.cost_per_image,
                metadata={"prompt": request.prompt}
            ))
        
        return results
    
    @property
    def model_name(self) -> str:
        return "gpt-image-1"
    
    @property
    def cost_per_image(self) -> float:
        return 0.04
```

**Validation:**
- Same as Gemini test
- Compare output side-by-side with Gemini

---

### Step 5.5: Flux (fal.ai) Image Generator
**Goal:** Implement using Flux + IP-Adapter via fal.ai.

**Implementation:**
- Use `fal-client` SDK
- Use Flux LoRA endpoint with IP-Adapter
- IP-Adapter scale 0.85-0.95 for jewelry preservation

```python
import fal_client

class FluxImageGenerator(AbstractImageGenerator):
    def __init__(self, api_key: str):
        os.environ['FAL_KEY'] = api_key
    
    async def generate(self, request: ImageGenerationRequest) -> list[ImageGenerationResult]:
        # Upload reference image to fal.ai
        ref_url = fal_client.upload_image(request.reference_image)
        
        # Call Flux with IP-Adapter
        result = await fal_client.run_async(
            "fal-ai/flux/dev/image-to-image",
            arguments={
                "image_url": ref_url,
                "prompt": f"{request.prompt}. {request.style_hint}",
                "strength": 0.85,  # Higher = more variation, lower = more preservation
                "num_images": request.num_outputs,
                "seed": request.seed,
            }
        )
        
        results = []
        for img_info in result['images']:
            img = await download_image(img_info['url'])
            results.append(ImageGenerationResult(
                image=img,
                model_name=self.model_name,
                cost_estimate=self.cost_per_image,
                metadata={"prompt": request.prompt, "seed": img_info.get('seed')}
            ))
        
        return results
    
    @property
    def model_name(self) -> str:
        return "flux-dev-img2img"
    
    @property
    def cost_per_image(self) -> float:
        return 0.025
```

**Validation:**
- Generate image, jewelry detail preserved
- IP-Adapter scale tested at different values

---

### Step 5.6: Workflow Factory & Selector
**Goal:** Runtime selection of which workflow to use.

**Implementation:**
```python
class ImageWorkflowFactory:
    _workflows = {
        "gemini": GeminiImageGenerator,
        "openai": OpenAIImageGenerator,
        "flux": FluxImageGenerator,
    }
    
    @classmethod
    def get(cls, workflow_name: str, settings) -> AbstractImageGenerator:
        if workflow_name not in cls._workflows:
            raise ValueError(f"Unknown workflow: {workflow_name}")
        
        api_key_map = {
            "gemini": settings.GEMINI_API_KEY,
            "openai": settings.OPENAI_API_KEY,
            "flux": settings.FAL_API_KEY,
        }
        
        return cls._workflows[workflow_name](api_key_map[workflow_name])
    
    @classmethod
    def get_all(cls, settings) -> dict[str, AbstractImageGenerator]:
        return {name: cls.get(name, settings) for name in cls._workflows}
```

**Validation:**
- Factory returns correct instance for each name
- Invalid name raises clear error

---

### Step 5.7: Comparison Workflow
**Goal:** Run same prompt through all 3 workflows for side-by-side test.

**Implementation:**
- Route: `POST /products/{sku}/generate-comparison`
- Generates 1 image per workflow with same prompt
- Saves to `./data/images/{SKU}/comparison/{workflow_name}.png`
- Returns a comparison view

**UI:**
- Show 3 images side by side
- Show cost, speed for each
- User can vote/select best one
- Selection saved to product metadata

**Validation:**
- All 3 workflows run successfully
- Comparison page loads
- User can select preferred workflow per product

---

### Step 5.8: Production Image Generation
**Goal:** Generate the 5-6 AI lifestyle images for the listing.

**Implementation:**
- After workflow selection, generate full set with selected workflow
- Prompts (use fixed templates):
  - "Woman wearing the necklace, soft natural lighting, neutral background"
  - "Necklace on marble surface flat lay, minimalist styling"
  - "Hand opening gift box containing necklace, lifestyle"
  - "Macro detail shot of necklace pendant"
  - "Young woman in cafe wearing necklace, candid lifestyle"
- Save each with proper naming: `{SKU}-lifestyle-{n}.jpg`
- Save with SEO filename pattern (kebab-case keywords)

**Critical:**
- Maintain **Section 1.11 rule**: at least 3 real Reksven photos must remain in the final image set.
- AI images are supplementary, not replacement.

**Validation:**
- Product has 8+ total images (3 real + 5 AI)
- All have file names following SEO pattern
- All sized 2000x2000

---

### Step 5.9: Alt Text Generator
**Goal:** Auto-generate alt text for each image.

**Implementation:**
- For each image, generate alt text based on:
  - Product main keyword (from carrier pillar + features)
  - Image position rank (1-9)
  - Image type (lifestyle, detail, size, box)
- Use rules from Section 1.4

```python
def generate_alt_text(product: Product, image: ProductImage) -> str:
    """Generate SEO alt text based on rank and product."""
    main_keyword = build_main_keyword(product)  # e.g. "gold plated cross necklace"
    
    if image.rank == 1:
        return f"{main_keyword} - main view"
    elif image.rank in [2, 3]:
        return f"{main_keyword} - color variation {image.rank}"
    elif image.rank in [4, 5]:
        return f"{main_keyword} - size and material details"
    elif image.rank in [6, 7]:
        return f"{main_keyword} - gift for {product.recipient}"
    elif image.rank == 8:
        return f"{main_keyword} - gift box presentation"
    else:
        return f"{main_keyword}"
```

**Validation:**
- All 9 image positions have meaningful alt text
- Alt text includes main keyword
- Length 50-150 chars each

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

## PHASE 7: HUMAN APPROVAL UI

### Step 7.1: Approval Queue View
**Goal:** Show all products awaiting approval.

**Implementation:**
- Route: `GET /approval`
- Lists products with status `AWAITING_APPROVAL`
- Shows: SKU, carrier pillar, image count, generated time

**Validation:**
- All AWAITING_APPROVAL products listed
- Sortable by creation time

---

### Step 7.2: Variant Comparison & Approval View
**Goal:** Show all 3 generated variants side-by-side for visual comparison, let user pick one (or hybrid-edit), then approve.

**Implementation:**
- Route: `GET /approval/{sku}`
- 3-column responsive grid (collapses to vertical on narrow screens). Each column shows one variant:

```
┌─────────────────────┬─────────────────────┬─────────────────────┐
│ VARIANT A           │ VARIANT B           │ VARIANT C           │
│ Conservative niche  │ Differentiated      │ Gift-focused        │
│ ⊙ Pick this         │ ⊙ Pick this         │ ⊙ Pick this         │
│ CTR signal: HIGH    │ CTR signal: MEDIUM  │ CTR signal: HIGH    │
│                     │                     │                     │
│ TITLE (138 chars):  │ TITLE (139 chars):  │ TITLE (137 chars):  │
│ "Dainty Gold        │ "Confirmation       │ "Cross Necklace     │
│  Cross Necklace,    │  Cross Necklace,    │  Gift for Daughter, │
│  Tiny Sideways..."  │  Everyday..."        │  Faith Necklace..." │
│                     │                     │                     │
│ TAGS (13):          │ TAGS (13):          │ TAGS (13):          │
│ • cross necklace    │ • cross necklace    │ • cross necklace    │
│ • dainty necklace   │ • confirmation gift │ • gift for daughter │
│ • gift for her      │ • everyday wear     │ • mothers day gift  │
│ ...                 │ ...                 │ ...                 │
│                     │                     │                     │
│ DESCRIPTION         │ DESCRIPTION         │ DESCRIPTION         │
│ (187 words)         │ (203 words)         │ (195 words)         │
│ "Discover the       │ "Quiet faith every  │ "She'll smile from  │
│  timeless beauty    │  morning. This..."  │  the moment she..." │
│  of..."             │                     │                     │
│ [Edit inline]       │ [Edit inline]       │ [Edit inline]       │
│                     │                     │                     │
│ STRATEGY RATIONALE: │ STRATEGY RATIONALE: │ STRATEGY RATIONALE: │
│ Closest to bestsel- │ Uses 3 underused    │ Leads with gift     │
│ ler patterns. Safe  │ keywords. Stands    │ moment for daughter │
│ SEO bet.            │ out from competitors│ recipient.          │
└─────────────────────┴─────────────────────┴─────────────────────┘

[Below all 3 columns:]
SHARED FIELDS (apply to whichever variant you pick):
- 9 product images (one set, used across all variants)
- Section assignment: [Cross Necklaces ▼]
- Price: $32.99
- Quantity: 999

[Actions]
- "Approve selected variant" — uses the picked variant
- "Save as draft" — keep all 3 for later
- "Reject all & regenerate" — sends back to Step 6.7
- "Hybrid edit" — opens an editor pre-filled with picked variant, user can swap in
                 fields from other variants (e.g. "take title from A, description from B")
```

**Hybrid edit flow:**
- User clicks "Hybrid edit" → opens single-column editor
- Pre-filled with whichever variant was selected
- Sidebar shows the other 2 variants' fields with "← Use this" buttons
- Click "← Use this" next to Variant B's description → replaces description in current editor
- All edits go through validators in real-time
- Save → creates a `ListingVariant` with `variant_id="HYBRID"`, source angles logged

**Database flow:**
- All 3 variants saved to DB on generation (`listing_variants` table, FK to product)
- Selected variant marked `is_selected=True`
- Other 2 remain available for analytics: "user picks Conservative 60% of the time, Differentiated 30%, Gift 10%"

**Validation:**
- All 3 variants render with distinct titles/tags/descriptions
- Radio button selection updates which variant gets the "selected" highlight
- Inline edits update DB on blur (auto-save)
- Hybrid edit successfully composes mixed-field variant
- After approval, only the selected variant proceeds to Phase 8 (Etsy upload)

---

### Step 7.3: Edit/Override Capability
**Goal:** Let user override any AI-generated field.

**Implementation:**
- All form fields editable
- On save: re-run validators
- Display violations inline before final approve
- User can override violations with explicit confirmation (last resort)

**Validation:**
- User can type custom title → validator runs → shows errors if any
- User can override validator with checkbox: "I know this breaks rules, proceed anyway"
- Override logged in audit table

---

## PHASE 8: ETSY API INTEGRATION

### Step 8.1: OAuth 2.0 Setup
**Goal:** Get Etsy API access token for user's shop.

**Implementation:**
- Route: `GET /admin/etsy/connect` — initiates OAuth flow
- Use PKCE flow
- Save token in encrypted local file `./data/etsy_token.json`
- Auto-refresh when expired

**Validation:**
- User clicks Connect → redirected to Etsy → grants permission → returns
- Token saved successfully
- Refresh works after expiry

---

### Step 8.2: Rate-Limited Etsy Client
**Goal:** Etsy API client with built-in rate limiting (10/sec, 10k/day).

**Implementation:**
```python
class EtsyClient:
    BASE_URL = "https://openapi.etsy.com/v3"
    
    def __init__(self, token_manager, shop_id):
        self.token_manager = token_manager
        self.shop_id = shop_id
        self.rate_limiter = TokenBucket(capacity=10, refill_rate=10)
    
    async def request(self, method, endpoint, **kwargs):
        await self.rate_limiter.acquire()
        
        token = await self.token_manager.get_valid_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "x-api-key": settings.ETSY_API_KEY
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method, f"{self.BASE_URL}{endpoint}",
                headers=headers, **kwargs
            )
            
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                logger.warning(f"Rate limited, waiting {retry_after}s")
                await asyncio.sleep(retry_after)
                return await self.request(method, endpoint, **kwargs)
            
            response.raise_for_status()
            return response.json()
```

**Validation:**
- 10 rapid requests succeed within rate limit
- 11th request waits, not fails
- 429 triggers backoff

---

### Step 8.3: Listing Creation
**Goal:** Create listing on Etsy.

**Implementation:**
```python
async def create_listing(self, product: Product) -> str:
    """Returns Etsy listing_id"""
    
    payload = {
        "quantity": product.quantity or 999,  # Section 1.6
        "title": product.final_title,
        "description": product.final_description,
        "price": float(product.selling_price),
        "who_made": "i_did",
        "when_made": "made_to_order",
        "taxonomy_id": JEWELRY_NECKLACE_TAXONOMY_ID,
        "shipping_profile_id": settings.SHIPPING_PROFILE_ID,
        "return_policy_id": settings.RETURN_POLICY_ID,
        "tags": product.final_tags,
        "is_personalizable": product.is_personalized,
        "personalization_is_required": False,
        "state": "draft",  # don't go live until images uploaded
    }
    
    response = await self.request(
        "POST",
        f"/application/shops/{self.shop_id}/listings",
        json=payload
    )
    
    return response['listing_id']
```

**Validation:**
- Create test listing in draft mode
- All fields populated correctly
- Returns listing_id

---

### Step 8.4: Image Upload
**Goal:** Upload all 8-9 images to listing.

**Implementation:**
```python
async def upload_images(self, listing_id: str, images: list[ProductImage]):
    for image in sorted(images, key=lambda x: x.rank):
        with open(image.file_path, 'rb') as f:
            files = {'image': f}
            data = {
                'rank': image.rank,
                'alt_text': image.alt_text
            }
            
            await self.request(
                "POST",
                f"/application/shops/{self.shop_id}/listings/{listing_id}/images",
                files=files, data=data
            )
        
        # Human-like pacing (Section: avoid spam detection)
        await asyncio.sleep(random.uniform(1, 3))
```

**Validation:**
- All images uploaded in correct order
- Alt text set
- No rate limit hit

---

### Step 8.5: Attributes & Inventory
**Goal:** Set all attributes from Section 1.5.

**Implementation:**
- Fetch taxonomy attributes for jewelry necklace
- Map product fields to Etsy attribute IDs
- Set via API
- Set inventory (quantity, price) per variation if applicable

**Validation:**
- All 9 attribute categories filled (Section 1.5)
- Inventory shows correct quantity

---

### Step 8.6: Section Assignment
**Goal:** Assign listing to correct shop section.

**Implementation:**
- Map carrier_pillar → section_id
- API call to set section

**Validation:**
- Listing appears in correct section in Etsy shop view

---

### Step 8.7: Publish (Activate Listing)
**Goal:** Move from draft to active.

**Implementation:**
- After all images + attributes set, PATCH listing state to "active"
- Update product status to PUBLISHED in DB
- Save etsy_listing_id

**Validation:**
- Listing becomes live on Etsy
- All fields visible publicly

---

### Step 8.8: Bulk Upload with Pacing
**Goal:** Upload multiple approved products with human-like timing.

**Implementation:**
```python
async def bulk_publish(approved_skus: list[str]):
    is_new_shop = check_if_new_shop()  # < 6 months old
    max_per_day = 15 if is_new_shop else 50  # Spam prevention
    
    today_count = await get_today_publish_count()
    remaining_today = max_per_day - today_count
    
    to_publish = approved_skus[:remaining_today]
    
    for i, sku in enumerate(to_publish):
        product = await get_product(sku)
        listing_id = await create_listing(product)
        await upload_images(listing_id, product.images)
        await set_attributes(listing_id, product)
        await assign_section(listing_id, product)
        await activate_listing(listing_id)
        
        await update_status(sku, ProductStatus.PUBLISHED)
        
        # Human-like wait between products
        wait_time = random.uniform(30, 90)
        logger.info(f"Published {sku} ({i+1}/{len(to_publish)}). Waiting {wait_time:.0f}s")
        await asyncio.sleep(wait_time)
```

**Validation:**
- New shop limited to 15/day
- Old shop allowed 50/day
- 30-90 sec between listings
- Stops when daily limit reached

---

## PHASE 9: TRACKING & SCHEDULING (Initial)

### Step 9.1: Stats Sync Job
**Goal:** Daily fetch of listing stats from Etsy.

**Implementation:**
- APScheduler job runs daily at 6:00 AM TR time
- For each published product: fetch stats from Etsy
- Insert into `product_stats` table

**Validation:**
- Stats fetched for all live products
- Stored with date

---

### Step 9.2: Renew Scheduler
**Goal:** Auto-renew top performers at Section 1.8 hours.

**Implementation:**
- APScheduler jobs at TR 17:00, 21:00, 02:00, 05:00
- Query top-performing products (recent sales, high views)
- For each (configurable limit): call Etsy renew API
- Log each renew

**Validation:**
- Jobs fire at correct times
- Only top performers renewed
- Renew API call succeeds

---

### Step 9.3: Performance Dashboard
**Goal:** Local web view of all products and metrics.

**Implementation:**
- Route: `GET /dashboard`
- Show:
  - Total products by status
  - Today's views/sales
  - Top performers (last 7 days)
  - Underperformers (0 views in 7 days) — candidate for tag update
  - Renew schedule status

**Validation:**
- Dashboard loads with all key metrics
- Updates in real-time (poll or websocket optional)

---

## PHASE 10: GOOGLE SHEETS SYNC (Optional, Later)

### Step 10.1: Sheets Integration
**Goal:** Mirror PostgreSQL DB to Google Sheets for visibility.

**Implementation:**
- Use google-api-python-client
- On product status change → upsert row in Sheets
- Sheet columns match DB columns
- Conflict resolution: DB is source of truth

**Validation:**
- New product → row added to Sheets
- Update status → Sheets row updated
- Manual edit in Sheets → reflected in DB on next sync

---

## PHASE 11: TESTING & FINAL VALIDATION

### Step 11.1: Business Rule Tests
**Goal:** Comprehensive test of all validators.

**Implementation:**
- For each rule in Section 1, write at least 2 tests (passing + failing)
- Use pytest
- Include in CI workflow (if added later)

**Validation:**
- All tests pass
- Coverage of business rules > 90%

---

### Step 11.2: Integration Test (Full Pipeline)
**Goal:** End-to-end test with sample product.

**Implementation:**
- Test scenario:
  1. Create product manually
  2. Run image generation (use mock or test API)
  3. Run content generation
  4. Approve via UI
  5. Upload to Etsy test mode
  6. Verify Etsy listing exists with correct data

**Validation:**
- Full pipeline completes
- Final Etsy listing matches expectations
- All business rules respected throughout

---

# 📚 SECTION 5: REFERENCE DOCUMENTS

You have these reference documents available (referred to by name):
1. **Etsy_Taki_MASTER_Rehber.md** — Main jewelry training summary
2. **Etsy_Developer_AI_Pipeline.md** — Technical architecture reference
3. **Etsy_Taki_Otomasyon_Analizi.md** — Process automation analysis

When any business rule is ambiguous, refer to these documents. **Do not improvise rules.**

---

# ⚠️ SECTION 6: ABSOLUTE PROHIBITIONS

These behaviors are **NEVER ALLOWED**, regardless of optimization opportunities:

1. ❌ **Skip the human approval gate.** Even if all validators pass, human must approve before Etsy upload.
2. ❌ **Auto-publish without verifying images include 3+ real photos** (Etsy AI compliance).
3. ❌ **Modify business rules** (Section 1) without explicit user instruction.
4. ❌ **Use 3rd-party Etsy tools** (Vela, Sale Samurai, etc.) — direct API only.
5. ❌ **Generate content without running validators.**
6. ❌ **Publish AI-generated description without originality check.**
7. ❌ **Bulk upload faster than rate limits or shop-age limits.**
8. ❌ **Use forbidden keywords** (Section 1.12) anywhere in output.
9. ❌ **Skip carrier pillar assignment** for any product.
10. ❌ **Leave Etsy attributes empty.**

---

# ✅ SECTION 7: COMPLETION CRITERIA

The system is considered complete when:

1. ✅ All Phase 1-8 steps implemented and tested
2. ✅ Phase 3 (Research) ingests CSV from Chrome extension, populates DB, analyzers produce summaries
3. ✅ Phase 6 (Content) generators consume research context when available, fall back gracefully without it
4. ✅ Phase 9 (tracking + renew) operational
5. ✅ All business rule validators have unit tests
6. ✅ End-to-end test from manual input → Etsy upload passes
7. ✅ User can:
   - Import competitor research CSV via UI
   - View per-keyword analysis in research dashboard
   - Add product manually via UI
   - Pick image workflow (Gemini/OpenAI/Flux)
   - Compare workflows side-by-side
   - Review and approve generated content (with visible research influence in LLM logs)
   - Upload to Etsy with one click
   - See performance in dashboard
   - Auto-renew scheduled
8. ✅ Phase 10 (Sheets) is documented but optional
9. ✅ Documentation: README.md explains setup, env vars, Chrome extension companion, and usage

---

# 🎬 SECTION 8: HOW TO START

## Your First Action
**Begin with Phase 1, Step 1.1.** Do not jump ahead. Do not "preview" later phases by writing scaffolding code.

For each step:
1. State the step number and goal.
2. Show the implementation (code/config).
3. Run the validation.
4. Report success or failure.
5. **Wait for user confirmation** before proceeding to the next step.

If you encounter ambiguity:
1. Refer to the relevant reference document.
2. If still unclear, ASK the user — do not assume.

If you discover a missing rule:
1. STOP.
2. Surface the gap to the user.
3. Wait for clarification before encoding.

---

# 🧭 FINAL REMINDER

The training documents reflect real practitioner knowledge proven to work on Etsy. **Every shortcut you might be tempted to take has likely been tried and found inferior.** Trust the rules.

Your job is **not** to optimize Etsy SEO from scratch. Your job is to **encode and automate** the practitioner-proven rules without introducing your own theories.

Now begin with Step 1.1.
