# Architecture (Section 2 of Full Spec)

High-level component layout and module boundaries. Read first to understand the shape.

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