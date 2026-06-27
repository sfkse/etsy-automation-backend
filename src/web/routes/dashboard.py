"""
Performance Dashboard (Phase 9, Step 9.3)

GET /dashboard — shows live metrics for all products:
  - Product counts by status
  - Today's aggregate views / sales
  - Top 10 performers over the last 7 days
  - Underperformers (published, 0 views in 7 days)
  - Renew schedule: next fire times + recent renew log
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.config.business_rules import RENEW_HOURS_TR
from src.db.dependencies import get_session
from src.db.models import Product, ProductStats, ProductStatus, RenewLog

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates: Jinja2Templates | None = None

TR_TZ = ZoneInfo("Europe/Istanbul")


def set_templates(t: Jinja2Templates) -> None:
    global templates
    templates = t


def _tmpl(name: str, request: Request, context: dict) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _status_counts(session: Session) -> dict[str, int]:
    rows = session.query(Product.status, func.count(Product.id)).group_by(Product.status).all()
    counts: dict[str, int] = {s.value: 0 for s in ProductStatus}
    for status, cnt in rows:
        counts[status] = cnt
    return counts


def _today_stats(session: Session) -> dict[str, int]:
    today = date.today()
    row = (
        session.query(
            func.coalesce(func.sum(ProductStats.views), 0),
            func.coalesce(func.sum(ProductStats.sales), 0),
            func.coalesce(func.sum(ProductStats.favorites), 0),
        )
        .filter(ProductStats.date == today)
        .first()
    )
    if row is None:
        return {"views": 0, "sales": 0, "favorites": 0}
    return {"views": int(row[0]), "sales": int(row[1]), "favorites": int(row[2])}


def _top_performers(session: Session, days: int = 7, limit: int = 10) -> list[dict]:
    cutoff = date.today() - timedelta(days=days)
    score_expr = func.coalesce(
        func.sum(ProductStats.views + ProductStats.sales * 5), 0
    ).label("score")
    rows = (
        session.query(Product, score_expr)
        .outerjoin(
            ProductStats,
            (ProductStats.product_id == Product.id) & (ProductStats.date >= cutoff),
        )
        .filter(Product.status == ProductStatus.PUBLISHED.value)
        .group_by(Product.id)
        .order_by(score_expr.desc())
        .limit(limit)
        .all()
    )
    result = []
    for product, score in rows:
        # Last stats row for this product
        last_stats = (
            session.query(ProductStats)
            .filter_by(product_id=product.id)
            .order_by(ProductStats.date.desc())
            .first()
        )
        result.append({
            "sku": product.sku,
            "title": product.final_title or product.user_provided_title or product.sku,
            "listing_id": product.etsy_listing_id,
            "score": int(score),
            "views": last_stats.views if last_stats else 0,
            "sales": last_stats.sales if last_stats else 0,
            "last_date": last_stats.date if last_stats else None,
        })
    return result


def _underperformers(session: Session, days: int = 7) -> list[dict]:
    """Published products with zero views recorded in the last `days` days."""
    cutoff = date.today() - timedelta(days=days)
    # Products that have NO stats row with views > 0 in the window
    products_with_views = (
        session.query(ProductStats.product_id)
        .filter(
            ProductStats.date >= cutoff,
            ProductStats.views > 0,
        )
        .distinct()
        .subquery()
    )
    rows = (
        session.query(Product)
        .filter(
            Product.status == ProductStatus.PUBLISHED.value,
            ~Product.id.in_(products_with_views),
        )
        .order_by(Product.published_at.asc())
        .all()
    )
    return [
        {
            "sku": p.sku,
            "title": p.final_title or p.user_provided_title or p.sku,
            "listing_id": p.etsy_listing_id,
            "published_at": p.published_at,
        }
        for p in rows
    ]


def _recent_renewals(session: Session, limit: int = 20) -> list[dict]:
    rows = (
        session.query(RenewLog, Product.sku, Product.final_title)
        .join(Product, RenewLog.product_id == Product.id)
        .order_by(RenewLog.renewed_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "sku": sku,
            "title": title or sku,
            "listing_id": log.listing_id,
            "renewed_at": log.renewed_at,
            "success": log.success,
            "error_message": log.error_message,
        }
        for log, sku, title in rows
    ]


def _next_renew_times() -> list[dict]:
    """Compute the next fire time for each renew slot relative to now (TR time)."""
    now_tr = datetime.now(tz=TR_TZ)
    entries = []
    for hour in sorted(RENEW_HOURS_TR):
        candidate = now_tr.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate <= now_tr:
            candidate = candidate + timedelta(days=1)
        entries.append({"hour": f"{hour:02d}:00", "next": candidate})
    entries.sort(key=lambda x: x["next"])
    return entries


# ── Route ──────────────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    session: Session = Depends(get_session),
):
    return _tmpl(
        "dashboard/index.html",
        request,
        {
            "status_counts": _status_counts(session),
            "today_stats": _today_stats(session),
            "top_performers": _top_performers(session),
            "underperformers": _underperformers(session),
            "recent_renewals": _recent_renewals(session),
            "next_renew_times": _next_renew_times(),
            "renew_hours": RENEW_HOURS_TR,
        },
    )
