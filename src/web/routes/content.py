"""
Phase 6 Routes

POST /products/{sku}/generate-content
    Triggers the LLM content pipeline as a background task.
    Sets status → content_generating, then runs the orchestrator,
    stores the VariantBundle in Product.generated_variants, and
    sets status → awaiting_approval.

GET  /admin/keywords
    List all KeywordPool rows, filterable by pillar.

GET  /admin/keywords/import
    Render CSV upload form.

POST /admin/keywords/import
    Parse uploaded CSV and upsert into keyword_pool table.
"""
from __future__ import annotations

import csv
import io

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.config.business_rules import CARRIER_PILLARS
from src.config.settings import Settings
from src.db.dependencies import get_session
from src.db.models import Product, ProductStatus
from src.db.session import SessionLocal
from src.domain.validators import OriginalityChecker
from src.modules.content.description_generator import DescriptionGenerator
from src.modules.content.internal_linker import InternalLinker
from src.modules.content.keyword_pool import KeywordPoolManager
from src.modules.content.orchestrator import VariantBundleOrchestrator
from src.modules.content.tag_generator import TagGenerator
from src.modules.content.title_generator import TitleGenerator
from src.modules.research.context_builder import ResearchContextBuilder
from src.modules.sheets.sync import upsert_product_row
from src.utils.llm_client import get_content_llm_client

_log = structlog.get_logger(__name__)
_settings = Settings()

router = APIRouter(tags=["content"])
templates: Jinja2Templates | None = None


def set_templates(t: Jinja2Templates) -> None:
    global templates
    templates = t


def _tmpl(name: str, request: Request, context: dict, **kwargs) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context, **kwargs)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _build_orchestrator(session: Session) -> VariantBundleOrchestrator:
    llm = get_content_llm_client()
    pool = KeywordPoolManager(session)
    research = ResearchContextBuilder(session)
    originality = OriginalityChecker(session)

    title_gen = TitleGenerator(llm, pool, research)
    tag_gen = TagGenerator(llm, pool, research)
    desc_gen = DescriptionGenerator(llm, originality, research)
    linker = InternalLinker(session)

    return VariantBundleOrchestrator(title_gen, tag_gen, desc_gen, linker, research)


async def _run_content_pipeline(product_sku: str) -> None:
    """
    Background task: opens its own DB session, runs the orchestrator,
    stores the VariantBundle as JSON, and advances the product status.
    """
    session = SessionLocal()
    try:
        product = session.query(Product).filter_by(sku=product_sku).first()
        if not product:
            _log.error("content_pipeline_product_not_found", sku=product_sku)
            return

        orchestrator = _build_orchestrator(session)

        try:
            bundle = await orchestrator.generate_bundle(product)
        except Exception as exc:
            _log.exception("content_pipeline_failed", sku=product_sku, error=str(exc))
            product.status = ProductStatus.FAILED.value
            session.commit()
            upsert_product_row(product, _settings)
            return

        # Store bundle as list of variant dicts in the JSONB column
        product.generated_variants = [v.to_dict() for v in bundle.variants]
        product.status = ProductStatus.AWAITING_APPROVAL.value
        session.commit()
        upsert_product_row(product, _settings)
        _log.info("content_pipeline_complete", sku=product_sku, variants=len(bundle.variants))

    finally:
        session.close()


# ── Content Generation Trigger ────────────────────────────────────────────────

@router.post("/products/{sku}/generate-content")
async def trigger_content_generation(
    sku: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """
    Trigger the LLM content pipeline for the product.
    Sets status → content_generating and enqueues the background task.
    """
    product = session.query(Product).filter_by(sku=sku).first()
    if not product:
        return JSONResponse({"error": f"Product {sku} not found."}, status_code=404)

    if product.status not in (
        ProductStatus.AWAITING_APPROVAL.value,
        ProductStatus.FAILED.value,
    ):
        return JSONResponse(
            {"error": f"Product is in status '{product.status}'. Content generation requires awaiting_approval or failed."},
            status_code=409,
        )

    product.status = ProductStatus.CONTENT_GENERATING.value
    session.commit()
    upsert_product_row(product, _settings)

    background_tasks.add_task(_run_content_pipeline, sku)
    return RedirectResponse(url=f"/products/{sku}/progress", status_code=303)


# ── Keyword Pool Admin ────────────────────────────────────────────────────────

@router.get("/admin/keywords", response_class=HTMLResponse)
async def keyword_list(
    request: Request,
    pillar: str = "",
    session: Session = Depends(get_session),
):
    pool = KeywordPoolManager(session)
    keywords = pool.all_keywords(pillar=pillar or None)
    return _tmpl(
        "content/keywords.html",
        request,
        {
            "keywords": keywords,
            "pillar_filter": pillar,
            "pillar_options": _pillar_options(),
            "total": len(keywords),
        },
    )


@router.get("/admin/keywords/import", response_class=HTMLResponse)
async def keyword_import_form(request: Request):
    return _tmpl(
        "content/keywords_import.html",
        request,
        {
            "error": None,
            "success": None,
            "pillar_options": _pillar_options(),
        },
    )


@router.post("/admin/keywords/import", response_class=HTMLResponse)
async def keyword_import(
    request: Request,
    csv_file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    if not csv_file.filename or not csv_file.filename.endswith(".csv"):
        return _tmpl(
            "content/keywords_import.html",
            request,
            {
                "error": "Please upload a valid .csv file.",
                "success": None,
                "pillar_options": _pillar_options(),
            },
            status_code=422,
        )

    content = await csv_file.read()
    try:
        text = content.decode("utf-8-sig")  # handle BOM
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    except Exception as exc:
        return _tmpl(
            "content/keywords_import.html",
            request,
            {
                "error": f"Failed to parse CSV: {exc}",
                "success": None,
                "pillar_options": _pillar_options(),
            },
            status_code=422,
        )

    required_cols = {"keyword", "category", "carrier_pillar"}
    if not rows or not required_cols.issubset({k.strip().lower() for k in rows[0].keys()}):
        return _tmpl(
            "content/keywords_import.html",
            request,
            {
                "error": f"CSV must have columns: {', '.join(sorted(required_cols))}",
                "success": None,
                "pillar_options": _pillar_options(),
            },
            status_code=422,
        )

    # Normalise column names to lowercase
    normalised = [{k.strip().lower(): v for k, v in row.items()} for row in rows]

    pool = KeywordPoolManager(session)
    count = pool.upsert_from_csv(normalised)
    _log.info("keyword_import_complete", count=count, filename=csv_file.filename)

    return _tmpl(
        "content/keywords_import.html",
        request,
        {
            "error": None,
            "success": f"Successfully imported {count} keywords from {csv_file.filename}.",
            "pillar_options": _pillar_options(),
        },
    )


def _pillar_options() -> list[str]:
    return CARRIER_PILLARS
