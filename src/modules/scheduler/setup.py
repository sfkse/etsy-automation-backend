"""
APScheduler setup for Phase 9.

Call create_scheduler() at app startup; the returned scheduler is started
inside main.py's lifespan context manager.

All cron times are in Turkey time (Europe/Istanbul, UTC+3, no DST).
"""
from __future__ import annotations

from typing import Callable

import pytz
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from src.config.business_rules import RENEW_HOURS_TR
from src.modules.scheduler.jobs import renew_job, research_refresh_job, sheets_sync_job, stats_sync_job

_log = structlog.get_logger(__name__)

TR_TZ = pytz.timezone("Europe/Istanbul")


def create_scheduler(
    etsy_client,
    session_factory: Callable[[], Session],
    llm_client=None,
    renew_limit: int = 10,
    settings=None,
) -> AsyncIOScheduler:
    """Build and configure the AsyncIOScheduler.

    Args:
        etsy_client:     EtsyClient instance (may be None during early startup;
                         jobs will receive it via closure).
        session_factory: Callable that returns a new SQLAlchemy Session.
        llm_client:      LLM client for the weekly research refresh (optional).
        renew_limit:     Max products to renew per slot.

    Returns:
        Configured (but not yet started) AsyncIOScheduler.
    """
    scheduler = AsyncIOScheduler(timezone=TR_TZ)

    # ── 9.1  Daily stats sync at 06:00 TR ─────────────────────────────────────
    scheduler.add_job(
        _run_stats_sync,
        trigger=CronTrigger(hour=6, minute=0, timezone=TR_TZ),
        id="stats_sync",
        name="Daily stats sync (06:00 TR)",
        kwargs={"etsy_client": etsy_client, "session_factory": session_factory},
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # ── 9.2  Renew scheduler at TR 17:00, 21:00, 02:00, 05:00 ────────────────
    for hour in RENEW_HOURS_TR:
        scheduler.add_job(
            _run_renew,
            trigger=CronTrigger(hour=hour, minute=0, timezone=TR_TZ),
            id=f"renew_{hour:02d}",
            name=f"Auto-renew top performers ({hour:02d}:00 TR)",
            kwargs={
                "etsy_client": etsy_client,
                "session_factory": session_factory,
                "limit": renew_limit,
            },
            replace_existing=True,
            misfire_grace_time=1800,
        )

    # ── Weekly research keyword refresh — Monday 03:00 TR ─────────────────────
    if llm_client is not None:
        scheduler.add_job(
            _run_research_refresh,
            trigger=CronTrigger(day_of_week="mon", hour=3, minute=0, timezone=TR_TZ),
            id="research_refresh",
            name="Weekly keyword research refresh (Mon 03:00 TR)",
            kwargs={"session_factory": session_factory, "llm_client": llm_client},
            replace_existing=True,
            misfire_grace_time=7200,
        )

    # ── 10.1  Google Sheets sync every 15 minutes ──────────────────────────────
    if settings is not None and getattr(settings, "GOOGLE_SHEETS_ENABLED", False):
        scheduler.add_job(
            _run_sheets_sync,
            trigger=CronTrigger(minute="*/15", timezone=TR_TZ),
            id="sheets_sync",
            name="Google Sheets sync (every 15 min)",
            kwargs={"session_factory": session_factory, "settings": settings},
            replace_existing=True,
            misfire_grace_time=300,
        )

    _log.info(
        "scheduler_configured",
        jobs=[j.id for j in scheduler.get_jobs()],
    )
    return scheduler


# ── Thin wrappers so APScheduler can call async jobs ─────────────────────────
# APScheduler 3.x calls job functions synchronously unless the executor is set
# to AsyncIOExecutor.  We rely on the default AsyncIOScheduler behaviour which
# already runs coroutines on the event loop when job callables are coroutines.

async def _run_stats_sync(etsy_client, session_factory) -> None:
    await stats_sync_job(etsy_client, session_factory)


async def _run_renew(etsy_client, session_factory, limit: int) -> None:
    await renew_job(etsy_client, session_factory, limit)


async def _run_research_refresh(session_factory, llm_client) -> None:
    await research_refresh_job(session_factory, llm_client)


async def _run_sheets_sync(session_factory, settings) -> None:
    await sheets_sync_job(session_factory, settings)
