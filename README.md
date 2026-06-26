# Etsy Jewelry Automation

Local-only automation system for managing an Etsy jewelry store.
Generates listing variants (title + 13 tags + description) via AI,
handles image generation, approval workflow, and Etsy API publishing.

## Quick Start

```bash
# 1. Copy env file and fill in your keys
cp .env.example .env

# 2. Start Postgres
docker compose up -d

# 3. Install dependencies
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 4. Run migrations (after Step 1.3)
alembic upgrade head

# 5. Start dev server
uvicorn src.main:app --reload
```

## Stack

- **Python 3.11+** — FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2
- **Postgres 16** — via Docker (`docker compose up -d`)
- **AI** — Anthropic Claude, Gemini, OpenAI, fal.ai (Flux)
- **Templates** — Jinja2 (server-side, no React/Vue)

## Docs

Implementation specs live in `docs/`. Start with `docs/00-overview.md`.
