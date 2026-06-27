from urllib.parse import quote_plus
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.config.settings import Settings
from src.web.routes import research as research_routes
from src.web.routes import input as input_routes
from src.web.routes import content as content_routes
from src.web.routes import approval as approval_routes
from src.web.routes import etsy as etsy_routes

_settings = Settings()

app = FastAPI(
    title="Etsy Jewelry Automation",
    version="0.1.0",
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

app.include_router(research_routes.router)
app.include_router(input_routes.router)
app.include_router(content_routes.router)
app.include_router(approval_routes.router)
app.include_router(etsy_routes.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/products", status_code=302)
