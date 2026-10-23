"""Process-local registry of in-flight per-field variant regenerations.

The approval page kicks off a title / tags / description regeneration as a
FastAPI background task (see ``web.routes.approval``) so a slow LLM call never
holds the request open. The page then polls ``/approval/{sku}/regen/status``;
this store is what that endpoint reads — so a spinner is restored after a
reload and the finished text is swapped in on the next poll.

Mirrors ``modules.images.regen_jobs``: a tiny in-memory store, safe because the
app runs as a single uvicorn process. State need not survive a restart — the
committed variant in the DB is the source of truth for the result.
"""
from __future__ import annotations

import threading

# (sku, variant_id, field) -> {"running": bool, "error": str | None, "result": dict | None}
_JOBS: dict[tuple[str, str, str], dict] = {}
_LOCK = threading.Lock()


def mark_running(sku: str, variant_id: str, field: str) -> None:
    with _LOCK:
        _JOBS[(sku, variant_id, field)] = {"running": True, "error": None, "result": None}


def mark_done(
    sku: str,
    variant_id: str,
    field: str,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    with _LOCK:
        _JOBS[(sku, variant_id, field)] = {
            "running": False,
            "error": error,
            "result": result,
        }


def is_running(sku: str, variant_id: str, field: str) -> bool:
    with _LOCK:
        job = _JOBS.get((sku, variant_id, field))
        return bool(job and job["running"])


def jobs_for(sku: str) -> dict[str, dict]:
    """All job records for ``sku``, keyed ``"{variant_id}:{field}"``."""
    with _LOCK:
        return {
            f"{vid}:{field}": dict(job)
            for (s, vid, field), job in _JOBS.items()
            if s == sku
        }


def clear(sku: str, variant_id: str, field: str) -> None:
    """Forget a job record (e.g. once the page has applied its result)."""
    with _LOCK:
        _JOBS.pop((sku, variant_id, field), None)


__all__ = ["mark_running", "mark_done", "is_running", "jobs_for", "clear"]
