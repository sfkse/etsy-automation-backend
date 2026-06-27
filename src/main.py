from contextlib import asynccontextmanager
from urllib.parse import quote_plus
from pathlib import Path

from fastapi import FastAPI
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

    yield

    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Etsy Jewelry Automation",
    version="0.1.0",
    lifespan=lifespan,
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

app.include_router(research_routes.router)
app.include_router(input_routes.router)
app.include_router(content_routes.router)
app.include_router(approval_routes.router)
app.include_router(etsy_routes.router)
app.include_router(dashboard_routes.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/products", status_code=302)
