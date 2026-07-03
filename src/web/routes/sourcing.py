"""
Phase 4 — Sourcing Intelligence API Routes

POST /sourcing/suggest-keywords  — Layer A standalone (vision keyword candidates)
POST /sourcing/analyze            — Full A+B+C analysis (async, returns analysis_id)
GET  /sourcing/{analysis_id}      — Poll analysis status + results
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.dependencies import get_session
from src.db.models import (
    CompetitorListing,
    KeywordCandidate,
    KeywordScore,
    SourcingAnalysis,
    SourcingStatus,
)
from src.db.session import SessionLocal
from src.sourcing.image_io import download_remote_image, save_uploaded_image
from src.sourcing.mini_phase1 import MiniPhase1Runner
from src.sourcing.opportunity_scorer import OpportunityScorer
from src.sourcing.rexven_scraper import scrape_rexven_product
from src.sourcing.vision_keyword_suggester import VisionKeywordSuggester

_log = structlog.get_logger(__name__)
_settings = Settings()

router = APIRouter(prefix="/sourcing", tags=["sourcing"])


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

async def _build_analysis_from_inputs(
    session: Session,
    rexven_url: str | None,
    rexven_sku: str | None,
    image: UploadFile | None,
) -> SourcingAnalysis:
    """Create and persist a SourcingAnalysis from whichever input was provided."""
    from src.db.models import Product

    analysis = SourcingAnalysis(status=SourcingStatus.PENDING.value)

    if rexven_url:
        try:
            scraped = scrape_rexven_product(rexven_url)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not scrape Rexven URL: {e}") from e

        analysis.rexven_url = rexven_url
        analysis.image_url = scraped.get("image_url")
        if scraped.get("image_url"):
            try:
                analysis.image_path = download_remote_image(scraped["image_url"])
            except Exception as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Could not download product image: {e}",
                ) from e
        analysis.rexven_title_tr = scraped.get("title_tr")
        analysis.rexven_title_en = scraped.get("title_en")
        analysis.rexven_cost_usd_cents = scraped.get("cost_cents")
        analysis.rexven_premium_cost_usd_cents = scraped.get("premium_cost_cents")
        analysis.rexven_category = scraped.get("category")
        analysis.rexven_has_satisa_uygun_badge = scraped.get("satisa_uygun", False)
        analysis.rexven_has_yeni_badge = scraped.get("yeni", False)

    elif rexven_sku:
        product = session.query(Product).filter_by(sku=rexven_sku).first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {rexven_sku} not found")
        analysis.rexven_sku = rexven_sku
        # Try to get image from product's images
        if product.images:
            from pathlib import Path
            for img in product.images:
                if img.file_path and Path(img.file_path).exists():
                    analysis.image_path = img.file_path
                    break
        analysis.rexven_title_tr = product.user_provided_title
        analysis.rexven_category = product.carrier_pillar
        if product.cost:
            analysis.rexven_cost_usd_cents = int(float(product.cost) * 100)

    elif image:
        analysis.image_path = await save_uploaded_image(image)

    if not analysis.image_path:
        raise HTTPException(
            status_code=422,
            detail="Could not determine a product image path. Provide a valid Rexven URL, SKU with saved images, or upload an image directly.",
        )

    session.add(analysis)
    session.commit()
    session.refresh(analysis)
    return analysis


# ---------------------------------------------------------------------------
# Layer A standalone — keyword candidates only
# ---------------------------------------------------------------------------

@router.post("/suggest-keywords")
async def suggest_keywords(
    rexven_url: str | None = Form(None),
    rexven_sku: str | None = Form(None),
    image: UploadFile | None = File(None),
    session: Session = Depends(get_session),
):
    """
    Layer A standalone — produce 15 keyword candidates from a Rexven product image.
    Accepts one of: rexven_url, rexven_sku, or direct image upload.
    """
    if not any([rexven_url, rexven_sku, image]):
        raise HTTPException(status_code=400, detail="Provide rexven_url, rexven_sku, or image file")

    analysis = await _build_analysis_from_inputs(session, rexven_url, rexven_sku, image)

    suggester = VisionKeywordSuggester(session, api_key=_settings.ANTHROPIC_API_KEY)
    try:
        candidates = await asyncio.to_thread(suggester.run, analysis)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vision LLM failed: {e}") from e

    detected = candidates[0].detected_attributes if candidates else {}

    return JSONResponse({
        "analysis_id": analysis.id,
        "status": analysis.status,
        "detected_attributes": detected,
        "candidates": [
            {
                "id": c.id,
                "keyword": c.keyword,
                "tier": c.tier,
                "rationale": c.rationale,
            }
            for c in candidates
        ],
        "cost_cents": analysis.vision_cost_usd_cents,
    })


# ---------------------------------------------------------------------------
# Full A + B + C analysis (async)
# ---------------------------------------------------------------------------

@router.post("/analyze")
async def analyze_product(
    background_tasks: BackgroundTasks,
    rexven_url: str | None = Form(None),
    rexven_sku: str | None = Form(None),
    image: UploadFile | None = File(None),
    force_refresh: bool = Form(False),
    session: Session = Depends(get_session),
):
    """
    Full Layer A + B + C analysis.
    - Layer A (vision) runs synchronously before this endpoint returns.
    - Layers B and C run in a background task.
    - Returns analysis_id immediately; client should poll GET /sourcing/{id}.
    """
    if not any([rexven_url, rexven_sku, image]):
        raise HTTPException(status_code=400, detail="Provide rexven_url, rexven_sku, or image file")

    analysis = await _build_analysis_from_inputs(session, rexven_url, rexven_sku, image)

    # Layer A: fast (~3-5s), run synchronously before returning
    suggester = VisionKeywordSuggester(session, api_key=_settings.ANTHROPIC_API_KEY)
    try:
        candidates = await asyncio.to_thread(suggester.run, analysis)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Layer A (vision) failed: {e}") from e

    # Layers B + C: kick off in background
    background_tasks.add_task(_run_layer_b_and_c, analysis.id)

    return JSONResponse({
        "analysis_id": analysis.id,
        "status": analysis.status,
        "candidates_count": len(candidates),
        "poll_url": f"/sourcing/{analysis.id}",
        "message": "Layer A complete. Layers B and C are running in the background.",
    })


def _run_layer_b_and_c(analysis_id: int) -> None:
    """Background task — runs mini-Phase-1 scraping, scoring, and CLIP enrichment."""
    session = SessionLocal()
    try:
        analysis = session.query(SourcingAnalysis).filter_by(id=analysis_id).first()
        if not analysis:
            return

        # ── LAYER B: scrape + score ────────────────────────────────────────
        keywords = [c.keyword for c in analysis.candidates]

        runner = MiniPhase1Runner(session)
        runner.run(analysis, keywords)

        scorer = OpportunityScorer(session)
        scores = scorer.score_analysis(analysis)

        # ── LAYER C: CLIP visual similarity (optional, skip if model unavailable)
        _run_layer_c(session, analysis, scores)

        if analysis.status != SourcingStatus.FAILED.value:
            analysis.status = SourcingStatus.COMPLETED.value
            analysis.completed_at = datetime.utcnow()
            session.commit()

        _log.info("full_analysis_complete", analysis_id=analysis_id)

    except Exception as e:
        _log.exception("full_analysis_failed", analysis_id=analysis_id)
        try:
            analysis = session.query(SourcingAnalysis).filter_by(id=analysis_id).first()
            if analysis:
                analysis.status = SourcingStatus.FAILED.value
                analysis.error_message = str(e)
                session.commit()
        except Exception:
            pass
    finally:
        session.close()


def _run_layer_c(session, analysis: SourcingAnalysis, scores: list) -> None:
    """Attempt Layer C CLIP enrichment. Fails gracefully if model unavailable."""
    try:
        from src.sourcing.clip_embedder import ClipEmbedder
        from src.sourcing.rank_prediction import predict_rank
        from src.sourcing.visual_similarity import VisualSimilaritySearch

        analysis.status = SourcingStatus.LAYER_C_RUNNING.value
        session.commit()

        embedder = ClipEmbedder()
        searcher = VisualSimilaritySearch(session, embedder)

        similar = searcher.find_similar(
            analysis.image_path, top_k=50, min_similarity=0.70
        )

        # Enrich existing scores with rank predictions
        for score in scores:
            prediction = predict_rank(similar, target_keyword=score.keyword)
            score.estimated_rank = prediction["estimated_rank"]
            score.estimated_page = prediction["estimated_page"]
            score.visual_similarity_support = prediction["support_count"]

        # Propose novel keywords from Layer C (keywords similar listings rank for)
        from src.db.models import KeywordCandidate, KeywordTier
        empirical_keywords = searcher.extract_keyword_distribution(similar)
        layer_a_keywords = {c.keyword for c in analysis.candidates}

        for kw, count, _weighted in empirical_keywords[:10]:
            if kw not in layer_a_keywords and count >= 3:
                novel_candidate = KeywordCandidate(
                    analysis_id=analysis.id,
                    keyword=kw,
                    tier=KeywordTier.NICHE.value,
                    rationale=f"{count} visually similar listings rank for this keyword",
                    source_layer="C",
                )
                session.add(novel_candidate)

        analysis.layer_c_completed = True
        session.commit()
        _log.info("layer_c_complete", analysis_id=analysis.id, similar_count=len(similar))

    except ImportError:
        _log.info("layer_c_skipped_no_clip", analysis_id=analysis.id)
        analysis.layer_c_completed = False
        session.commit()
    except Exception as e:
        _log.warning("layer_c_failed_gracefully", analysis_id=analysis.id, error=str(e))
        analysis.layer_c_completed = False
        session.commit()


# ---------------------------------------------------------------------------
# Ingest extension Phase-1 cards + run Layer B+C
# ---------------------------------------------------------------------------

def _card_to_listing_from_extension(
    card: dict,
    analysis_id: int,
) -> "CompetitorListing | None":
    """Map a Chrome extension Phase-1 search card to a CompetitorListing ORM row."""
    listing_id = str(card.get("listing_id") or "").strip()
    if not listing_id:
        return None

    listed_date = None
    if card.get("eh_listed_date"):
        try:
            listed_date = date.fromisoformat(str(card["eh_listed_date"])[:10])
        except (ValueError, TypeError):
            pass

    return CompetitorListing(
        listing_id=listing_id,
        url=card.get("url") or f"https://www.etsy.com/listing/{listing_id}",
        keyword_searched=card.get("keyword"),
        rank_in_search=card.get("rank"),
        title=card.get("title") or "",
        image_url=card.get("image_url") or "",
        shop_name=card.get("shop_name") or card.get("shop") or None,
        shop_id=str(card.get("shop_id") or "") or None,
        price_cents=card.get("price_cents"),
        currency=card.get("currency"),
        rating=card.get("rating"),
        review_count=card.get("review_count"),
        is_bestseller=bool(card.get("is_bestseller")),
        is_star_seller=bool(card.get("is_star_seller")),
        is_popular_now=bool(card.get("is_popular_now")),
        is_etsys_pick=bool(card.get("is_etsys_pick")),
        is_ad=bool(card.get("is_ad")),
        has_video=bool(card.get("has_video")),
        keyword_total_results=card.get("keyword_total_results"),
        eh_sales_total=card.get("eh_sales_total"),
        eh_sales_recent=card.get("eh_sales_recent"),
        eh_favorites=card.get("eh_favorites"),
        eh_shop_weekly_sales=card.get("eh_shop_weekly_sales"),
        eh_listed_date=listed_date,
        scraped_for_sourcing=True,
        sourcing_analysis_id=analysis_id,
        imported_at=datetime.utcnow(),
    )


@router.post("/{analysis_id}/ingest-and-score")
async def ingest_and_score(
    analysis_id: int,
    background_tasks: BackgroundTasks,
    request: Request,
    session: Session = Depends(get_session),
):
    """
    Ingest Phase-1 search cards collected by the Chrome extension and kick off
    Layer B + C scoring.  Called after the extension has scraped Etsy in-browser
    for the keyword candidates that Layer A suggested.

    Body: { "cards": [ <extension Phase-1 card>, ... ] }
    """
    analysis = session.query(SourcingAnalysis).filter_by(id=analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail=f"Analysis {analysis_id} not found")

    body = await request.json()
    cards: list[dict] = body.get("cards", [])

    ingested = 0
    seen_in_batch: set[str] = set()
    for card in cards:
        listing_id = str(card.get("listing_id") or "").strip()
        if not listing_id:
            continue
        if listing_id in seen_in_batch:
            continue
        seen_in_batch.add(listing_id)

        already = session.query(CompetitorListing).filter_by(listing_id=listing_id).first()
        if already:
            # Update sourcing link if not already set
            if not already.scraped_for_sourcing:
                already.scraped_for_sourcing = True
                already.sourcing_analysis_id = analysis_id
            continue
        listing = _card_to_listing_from_extension(card, analysis_id)
        if listing:
            session.add(listing)
            ingested += 1

    session.commit()
    _log.info("ingest_and_score_cards", analysis_id=analysis_id, ingested=ingested, total=len(cards))

    background_tasks.add_task(_run_layer_b_and_c, analysis_id)

    return JSONResponse({
        "analysis_id": analysis_id,
        "cards_received": len(cards),
        "cards_ingested": ingested,
        "message": "Cards ingested. Layer B+C scoring running in background.",
    })


# ---------------------------------------------------------------------------
# Poll endpoint
# ---------------------------------------------------------------------------

@router.get("/{analysis_id}")
async def get_analysis(
    analysis_id: int,
    session: Session = Depends(get_session),
):
    """Return analysis status and top-5 recommended keywords."""
    analysis = session.query(SourcingAnalysis).filter_by(id=analysis_id).first()
    if not analysis:
        raise HTTPException(status_code=404, detail=f"Analysis {analysis_id} not found")

    scores = sorted(
        analysis.scores,
        key=lambda s: s.rank_in_recommendation or 999,
    )

    # Build detected_attributes from first candidate (they all share the same)
    detected = {}
    if analysis.candidates:
        for c in analysis.candidates:
            if c.detected_attributes:
                detected = c.detected_attributes
                break

    return JSONResponse({
        "analysis_id": analysis.id,
        "status": analysis.status,
        "rexven_title": analysis.rexven_title_en or analysis.rexven_title_tr,
        "rexven_url": analysis.rexven_url,
        "layer_a_done": analysis.layer_a_completed,
        "layer_b_done": analysis.layer_b_completed,
        "layer_c_done": analysis.layer_c_completed,
        "detected_attributes": detected,
        "recommended_keywords": [
            {
                "rank": s.rank_in_recommendation,
                "keyword_score_id": s.id,
                "keyword": s.keyword,
                "opportunity_score": round(s.opportunity_score or 0, 3),
                "sub_scores": {
                    "new_shop_opportunity": round(s.score_new_shop_share or 0, 2),
                    "price_alignment": round(s.score_price_alignment or 0, 2),
                    "market_activity": round(s.score_activity or 0, 2),
                    "competition_inverted": round(s.score_competition or 0, 2),
                    "diversity": round(s.score_diversity or 0, 2),
                },
                "market_snapshot": {
                    "avg_price_usd": round((s.top20_avg_price_cents or 0) / 100, 2),
                    "avg_shop_age_years": round(s.top20_avg_shop_age or 0, 1),
                    "total_etsy_results": s.top20_keyword_total_results,
                    "unique_shops_in_top20": s.top20_unique_shops,
                    "listings_with_recent_sales": s.top20_with_recent_sales,
                },
                "estimated_rank": s.estimated_rank,
                "estimated_page": s.estimated_page,
                "visual_similarity_support": s.visual_similarity_support,
            }
            for s in scores[:5]
        ],
        "error": analysis.error_message,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        "completed_at": analysis.completed_at.isoformat() if analysis.completed_at else None,
    })


# ---------------------------------------------------------------------------
# List analyses (optional convenience endpoint)
# ---------------------------------------------------------------------------

@router.get("")
async def list_analyses(
    limit: int = 20,
    session: Session = Depends(get_session),
):
    """List recent sourcing analyses."""
    analyses = (
        session.query(SourcingAnalysis)
        .order_by(SourcingAnalysis.created_at.desc())
        .limit(limit)
        .all()
    )
    return JSONResponse({
        "analyses": [
            {
                "id": a.id,
                "status": a.status,
                "rexven_title": a.rexven_title_en or a.rexven_title_tr,
                "rexven_url": a.rexven_url,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "completed_at": a.completed_at.isoformat() if a.completed_at else None,
                "layer_a_done": a.layer_a_completed,
                "layer_b_done": a.layer_b_completed,
                "layer_c_done": a.layer_c_completed,
            }
            for a in analyses
        ]
    })
