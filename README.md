# Etsy Jewelry Automation

Local-only automation system for managing an Etsy jewelry store.
Generates listing variants (title + 13 tags + description) via AI,
handles image generation, approval workflow, and Etsy API publishing.

## Quick Start

```bash
# 1. Copy env file and fill in your keys
cp .env.example .env

# 2. Start Postgres + API (runs migrations, then uvicorn on :8000)
docker compose up --build
```

The app is at http://localhost:8000. `./src` is bind-mounted into the container
with `--reload`, so host edits hot-reload without a rebuild.

ML models (`all-MiniLM-L6-v2`, `clip-ViT-B-32`, rembg's `u2net`) download on
first use into named volumes, so the first background removal or originality
check is slow and every one after that is not.

### On Windows

Setting up from scratch — WSL 2, Docker Desktop, and the failures worth knowing
about in advance — is covered step by step in [WINDOWS_SETUP.md](WINDOWS_SETUP.md).

Works, but rebuild rather than copying an image across machines — `docker
compose up --build` pulls the right architecture.

**Put the repo inside the WSL2 filesystem** (`\\wsl$\Ubuntu\home\you\...`), not
on `C:\`. inotify events don't cross the Windows→WSL2 boundary, so `--reload`
silently never fires from `C:\` — and bind-mount I/O is much slower there. If
you must work from `C:\`, uncomment `WATCHFILES_FORCE_POLLING` in
`docker-compose.yml`.

Three things don't arrive via `git clone` and must be copied by hand: `.env`,
`data/images/`, and the Postgres contents (`pg_dump -U etsy etsy_taki` on the
source machine, `psql -U etsy -d etsy_taki` on the target). `data/etsy_encryption.key`
*is* tracked, so it travels — no Fernet key mismatch — but you'll still need to
redo the Etsy OAuth flow, since the token file isn't tracked.

## Running without Docker

Still how the tests are run. Requires Postgres — `docker compose up -d postgres`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn src.main:app --reload
```

## Stack

- **Python 3.11+** — FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2
- **Postgres 16** — via Docker (`docker compose up -d`)
- **AI** — Anthropic Claude, Gemini, OpenAI, fal.ai (Flux)
- **Templates** — Jinja2 (server-side, no React/Vue)

## Docs

Implementation specs live in `docs/`. Start with `docs/00-overview.md`.
