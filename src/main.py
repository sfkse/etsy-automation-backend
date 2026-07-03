from contextlib import asynccontextmanager
from urllib.parse import quote_plus
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config.settings import Settings
from src.db.session import SessionLocal
from src.web.routes import research as research_routes
from src.web.routes import input as input_routes
from src.web.routes import content as content_routes
from src.web.routes import approval as approval_routes
from src.web.routes import etsy as etsy_routes
from src.web.routes import dashboard as dashboard_routes
from src.web.routes import sourcing as sourcing_routes
from src.web.routes import admin as admin_routes
from src.web.routes import listings as listings_routes
from src.web.routes import settings as settings_routes

_settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start APScheduler on startup; shut it down cleanly on exit."""
    from src.modules.etsy.client import EtsyClient
    from src.modules.etsy.token_manager import TokenManager
    from src.modules.scheduler.setup import create_scheduler
    from src.utils.llm_client import LLMClient

    token_manager = TokenManager(
        api_key=_settings.ETSY_API_KEY,
        redirect_uri=_settings.ETSY_REDIRECT_URI,
    )
    etsy_client = EtsyClient(
        token_manager=token_manager,
        shop_id=_settings.ETSY_SHOP_ID,
        api_key=_settings.ETSY_API_KEY,
    )
    llm_client = LLMClient(api_key=_settings.ANTHROPIC_API_KEY)

    scheduler = create_scheduler(
        etsy_client=etsy_client,
        session_factory=SessionLocal,
        llm_client=llm_client,
        settings=_settings,
    )
    scheduler.start()

    # Operational Integration v2.5 — best-effort seed of shop defaults so a
    # fresh install boots with usable variation/pricing/description rows.
    try:
        from src.db.seed_shop_defaults import seed_all as _seed_shop_defaults

        with SessionLocal() as _seed_session:
            _seed_shop_defaults(_seed_session)
    except Exception as _seed_exc:  # pragma: no cover — startup best-effort
        import structlog
        structlog.get_logger(__name__).warning(
            "shop_defaults_seed_skipped", error=str(_seed_exc)
        )

    yield

    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Etsy Jewelry Automation",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow Chrome extension + local admin UI to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"chrome-extension://.*|http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?",
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="src/web/static"), name="static")

# Serve generated images from the data directory
_images_dir = Path(_settings.IMAGES_DIR)
_images_dir.mkdir(parents=True, exist_ok=True)
app.mount("/images", StaticFiles(directory=str(_images_dir)), name="images")

templates = Jinja2Templates(directory="src/web/templates")
# Jinja2 has no built-in urlencode filter; add one
templates.env.filters["urlencode"] = quote_plus

research_routes.set_templates(templates)
input_routes.set_templates(templates)
content_routes.set_templates(templates)
approval_routes.set_templates(templates)
etsy_routes.set_templates(templates)
dashboard_routes.set_templates(templates)
admin_routes.set_templates(templates)

app.include_router(research_routes.router)
app.include_router(input_routes.router)
app.include_router(content_routes.router)
app.include_router(approval_routes.router)
app.include_router(etsy_routes.router)
app.include_router(dashboard_routes.router)
app.include_router(sourcing_routes.router)
app.include_router(admin_routes.router)
app.include_router(listings_routes.router)
app.include_router(settings_routes.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/products", status_code=302)
