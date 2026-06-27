from urllib.parse import quote_plus

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.web.routes import research as research_routes

app = FastAPI(
    title="Etsy Jewelry Automation",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory="src/web/static"), name="static")

templates = Jinja2Templates(directory="src/web/templates")
# Jinja2 has no built-in urlencode filter; add one
templates.env.filters["urlencode"] = quote_plus

research_routes.set_templates(templates)

app.include_router(research_routes.router)
