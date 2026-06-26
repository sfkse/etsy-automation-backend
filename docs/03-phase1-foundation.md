# Phase 1

From the Full Spec. Implement in order. Each step ends with a validation block.

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