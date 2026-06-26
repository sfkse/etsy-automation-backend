from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(
    title="Etsy Jewelry Automation",
    version="0.1.0",
)

# Static files and templates wired in later phases
# app.mount("/static", StaticFiles(directory="src/web/static"), name="static")
