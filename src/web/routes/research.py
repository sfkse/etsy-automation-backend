"""
Research Module Routes (Step 3.2, 3.8)

GET  /research/import      — CSV upload form
POST /research/import      — parse CSV, dedupe, persist, trigger pipeline
GET  /research             — keyword index
GET  /research/shops       — competitor shop list
GET  /research/{keyword}   — keyword detail + refresh button
POST /research/{keyword}/refresh — re-run analyzers
"""
from __future__ import annotations

import io
from urllib.parse import unquote

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import distinct
from sqlalchemy.orm import Session

from src.db.dependencies import get_session
from src.db.models import CompetitorListing, CompetitorShop, KeywordResearch, ShopClassification
from src.modules.research.csv_import import merge_listing, parse_csv_to_listings
from src.modules.research.pipeline import refresh_keyword_research
from src.modules.research.scoring import compute_sales_signal_score
from src.modules.research.shop_classifier import upsert_competitor_shop
from src.utils.llm_client import get_llm_client

router = APIRouter(prefix="/research", tags=["research"])
templates: Jinja2Templates | None = None  # set by main.py after creating Jinja2Templates


def set_templates(t: Jinja2Templates) -> None:
    global templates
    templates = t


def _tmpl(name: str, request: Request, context: dict, **kwargs) -> HTMLResponse:
    """Compatibility wrapper for Starlette 1.x TemplateResponse (request-first API)."""
    return templates.TemplateResponse(request, name, context, **kwargs)


# ---------------------------------------------------------------------------
# CSV Import
# ---------------------------------------------------------------------------

@router.get("/import", response_class=HTMLResponse)
async def import_form(request: Request):
    return _tmpl("research/import.html", request, {"result": None, "error": None})


@router.post("/import", response_class=HTMLResponse)
async def import_csv(
    request: Request,
    file: UploadFile = File(...),
    refresh_analyzers: bool = Form(True),
    session: Session = Depends(get_session),
):
    llm_client = get_llm_client()

    content = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
    except Exception as exc:
        return _tmpl(
            "research/import.html", request,
            {"result": None, "error": f"Could not parse CSV: {exc}"},
            status_code=400,
        )

    summary = {"added": 0, "updated": 0, "skipped": 0, "keywords": set()}

    incoming_listings = parse_csv_to_listings(df)
    for listing in incoming_listings:
        if not listing.listing_id:
            summary["skipped"] += 1
            continue

        listing.sales_signal_score = compute_sales_signal_score(listing)

        existing = (
            session.query(CompetitorListing)
            .filter_by(listing_id=listing.listing_id)
            .first()
        )
        if existing:
            if listing.description_text and not existing.description_text:
                merge_listing(existing, listing)
                summary["updated"] += 1
            else:
                summary["skipped"] += 1
        else:
            session.add(listing)
            summary["added"] += 1

        if listing.keyword_searched:
            summary["keywords"].add(listing.keyword_searched)

    session.commit()

    # Upsert shops for all shop_ids seen
    shop_ids = {
        row[0]
        for row in session.query(distinct(CompetitorListing.shop_id))
        .filter(CompetitorListing.shop_id.isnot(None))
        .all()
    }
    for sid in shop_ids:
        upsert_competitor_shop(session, sid)
    session.commit()

    keywords_refreshed: list[str] = []
    if refresh_analyzers:
        for kw in summary["keywords"]:
            if kw:
                await refresh_keyword_research(session, kw, llm_client)
                keywords_refreshed.append(kw)

    result = {
        "added": summary["added"],
        "updated": summary["updated"],
        "skipped": summary["skipped"],
        "keywords_refreshed": keywords_refreshed,
        "filename": file.filename,
    }
    return _tmpl("research/import.html", request, {"result": result, "error": None})


# ---------------------------------------------------------------------------
# Keyword Index
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
async def research_index(request: Request, session: Session = Depends(get_session)):
    keywords = session.query(KeywordResearch).order_by(KeywordResearch.keyword).all()

    scraped_keywords = [
        row[0]
        for row in session.query(distinct(CompetitorListing.keyword_searched)).all()
        if row[0]
    ]
    analyzed_set = {r.keyword for r in keywords}
    unanalyzed = [kw for kw in scraped_keywords if kw not in analyzed_set]

    return _tmpl(
        "research/index.html", request,
        {"keywords": keywords, "unanalyzed": unanalyzed},
    )


# ---------------------------------------------------------------------------
# Competitor Shops
# ---------------------------------------------------------------------------

@router.get("/shops", response_class=HTMLResponse)
async def shops_list(request: Request, session: Session = Depends(get_session)):
    shops = (
        session.query(CompetitorShop)
        .order_by(CompetitorShop.classification, CompetitorShop.total_sales.desc())
        .all()
    )
    classification_labels = {c.value: c.value.replace("_", " ").title() for c in ShopClassification}
    return _tmpl(
        "research/shops.html", request,
        {"shops": shops, "classification_labels": classification_labels},
    )


# ---------------------------------------------------------------------------
# Keyword Detail
# ---------------------------------------------------------------------------

@router.get("/{keyword_slug}", response_class=HTMLResponse)
async def keyword_detail(
    keyword_slug: str,
    request: Request,
    session: Session = Depends(get_session),
):
    keyword = unquote(keyword_slug)
    research = session.query(KeywordResearch).filter_by(keyword=keyword).first()

    top_listings = (
        session.query(CompetitorListing)
        .filter_by(keyword_searched=keyword)
        .order_by(CompetitorListing.sales_signal_score.desc())
        .limit(20)
        .all()
    )

    return _tmpl(
        "research/keyword_detail.html", request,
        {"keyword": keyword, "research": research, "top_listings": top_listings},
    )


@router.post("/{keyword_slug}/refresh", response_class=HTMLResponse)
async def refresh_keyword(
    keyword_slug: str,
    request: Request,
    session: Session = Depends(get_session),
):
    keyword = unquote(keyword_slug)
    llm_client = get_llm_client()
    await refresh_keyword_research(session, keyword, llm_client)
    return RedirectResponse(url=f"/research/{keyword_slug}", status_code=303)
