"""
Scheduled job implementations for Phase 9 and Phase 10.

jobs:
  stats_sync_job        — daily 06:00 TR: fetch Etsy listing stats → product_stats
  renew_job             — 17:00 / 21:00 / 02:00 / 05:00 TR: renew top performers
  research_refresh_job  — weekly Mon 03:00 TR: re-analyze all keywords
  sheets_sync_job       — every 15 min: sync editable Sheets fields back to DB
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Callable

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import Product, ProductStats, ProductStatus, RenewLog
from src.modules.etsy.client import EtsyClient

_log = structlog.get_logger(__name__)

# How many top performers to renew per slot
RENEW_LIMIT_DEFAULT: int = 10


# ── 10.1 Google Sheets sync ───────────────────────────────────────────────────

async def sheets_sync_job(
    session_factory: Callable[[], Session],
    settings,
) -> None:
    """Pull Sheets → DB: update editable manual-input fields every 15 minutes."""
    from src.modules.sheets.sync import sync_sheets_to_db

    _log.info("sheets_sync_job started")
    summary = sync_sheets_to_db(session_factory=session_factory, settings=settings)
    _log.info("sheets_sync_job complete", **summary)


# ── 9.1 Stats sync ────────────────────────────────────────────────────────────

async def stats_sync_job(
    etsy_client: EtsyClient,
    session_factory: Callable[[], Session],
) -> None:
    """Fetch yesterday's listing stats from Etsy and upsert into product_stats."""
    yesterday = date.today() - timedelta(days=1)
    date_str = yesterday.isoformat()

    with session_factory() as session:
        published = (
            session.query(Product)
            .filter(
                Product.status == ProductStatus.PUBLISHED.value,
                Product.etsy_listing_id.isnot(None),
            )
            .all()
        )

    _log.info("stats_sync_job started", products=len(published), date=date_str)

    for product in published:
        try:
            payload = await etsy_client.get_listing_stats(
                listing_id=product.etsy_listing_id,
                start_date=date_str,
                end_date=date_str,
            )
            _upsert_stats(session_factory, product.id, yesterday, payload)
            _log.info(
                "stats_sync_ok",
                sku=product.sku,
                listing_id=product.etsy_listing_id,
            )
        except Exception as exc:
            _log.error(
                "stats_sync_error",
                sku=product.sku,
                listing_id=product.etsy_listing_id,
                error=str(exc),
            )

    _log.info("stats_sync_job complete", date=date_str)


def _upsert_stats(
    session_factory: Callable[[], Session],
    product_id: int,
    stat_date: date,
    payload: dict,
) -> None:
    """Insert or update a product_stats row from the Etsy stats payload."""
    # Etsy stats payload keys vary; handle both 'stats' wrapper and flat dict
    data: dict = payload.get("stats", payload) if isinstance(payload, dict) else {}

    views = int(data.get("views", 0) or 0)
    favorites = int(data.get("num_favorers", data.get("favorites", 0)) or 0)
    sales = int(data.get("transactions", data.get("sales", 0)) or 0)

    with session_factory() as session:
        row = (
            session.query(ProductStats)
            .filter_by(product_id=product_id, date=stat_date)
            .first()
        )
        if row is None:
            row = ProductStats(product_id=product_id, date=stat_date)
            session.add(row)
        row.views = views
        row.favorites = favorites
        row.sales = sales
        session.commit()


# ── 9.2 Renew top performers ───────────────────────────────────────────────────

async def renew_job(
    etsy_client: EtsyClient,
    session_factory: Callable[[], Session],
    limit: int = RENEW_LIMIT_DEFAULT,
) -> None:
    """Renew the top-performing published listings.

    Ranking: SUM(views + sales * 5) over last 7 days, descending.
    Only products with etsy_listing_id and status=published are considered.
    """
    cutoff = date.today() - timedelta(days=7)

    with session_factory() as session:
        # Score each product by weighted stats over the last 7 days
        scored = (
            session.query(
                Product,
                func.coalesce(
                    func.sum(ProductStats.views + ProductStats.sales * 5), 0
                ).label("score"),
            )
            .outerjoin(
                ProductStats,
                (ProductStats.product_id == Product.id)
                & (ProductStats.date >= cutoff),
            )
            .filter(
                Product.status == ProductStatus.PUBLISHED.value,
                Product.etsy_listing_id.isnot(None),
            )
            .group_by(Product.id)
            .order_by(func.coalesce(func.sum(ProductStats.views + ProductStats.sales * 5), 0).desc())
            .limit(limit)
            .all()
        )

    _log.info("renew_job started", candidates=len(scored), limit=limit)

    for product, score in scored:
        success = True
        error_msg: str | None = None
        try:
            await etsy_client.renew_listing(product.etsy_listing_id)
            _log.info(
                "renew_ok",
                sku=product.sku,
                listing_id=product.etsy_listing_id,
                score=score,
            )
        except Exception as exc:
            success = False
            error_msg = str(exc)
            _log.error(
                "renew_error",
                sku=product.sku,
                listing_id=product.etsy_listing_id,
                error=error_msg,
            )

        with session_factory() as session:
            session.add(
                RenewLog(
                    product_id=product.id,
                    listing_id=product.etsy_listing_id,
                    renewed_at=datetime.utcnow(),
                    success=success,
                    error_message=error_msg,
                )
            )
            session.commit()

        # Small pause between API calls to avoid bursting the rate limiter
        await asyncio.sleep(0.2)

    _log.info("renew_job complete", renewed=len(scored))


# ── Weekly research refresh ────────────────────────────────────────────────────

async def research_refresh_job(
    session_factory: Callable[[], Session],
    llm_client,
) -> None:
    """Re-analyze all keywords — wraps the existing refresh_all_keywords_job."""
    from src.modules.research.pipeline import refresh_all_keywords_job

    _log.info("research_refresh_job started")
    with session_factory() as session:
        await refresh_all_keywords_job(session, llm_client)
    _log.info("research_refresh_job complete")
