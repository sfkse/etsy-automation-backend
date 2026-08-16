"""Process-local registry of in-flight per-slot image regenerations.

The per-slot images page kicks off a regeneration as a FastAPI background task
(see ``web.routes.input``). Because that work outlives the browser request that
started it, the page needs a server-side way to know which slots are currently
regenerating — so a spinner can be restored after the user navigates away and
back, and the finished image can be swapped in on the next poll.

This is a deliberately tiny in-memory store keyed by ``(sku, slot)``. It is safe
because the app runs as a single uvicorn process (no ``--workers``); state does
not need to survive a restart (a dropped in-flight job simply stops showing a
spinner, and the committed image on disk is the source of truth for the result).
"""
from __future__ import annotations

import threading

# (sku, slot) -> {"running": bool, "error": str | None}
_JOBS: dict[tuple[str, str], dict] = {}
_LOCK = threading.Lock()


def mark_running(sku: str, slot: str) -> None:
    with _LOCK:
        _JOBS[(sku, slot)] = {"running": True, "error": None}


def mark_done(sku: str, slot: str, error: str | None = None) -> None:
    with _LOCK:
        _JOBS[(sku, slot)] = {"running": False, "error": error}


def is_running(sku: str, slot: str) -> bool:
    with _LOCK:
        job = _JOBS.get((sku, slot))
        return bool(job and job["running"])


def running_slots(sku: str) -> set[str]:
    with _LOCK:
        return {slot for (s, slot), job in _JOBS.items() if s == sku and job["running"]}


def error_of(sku: str, slot: str) -> str | None:
    with _LOCK:
        job = _JOBS.get((sku, slot))
        return job["error"] if job else None


def clear(sku: str, slot: str) -> None:
    """Forget a slot's job record (e.g. after its error has been surfaced)."""
    with _LOCK:
        _JOBS.pop((sku, slot), None)


__all__ = [
    "mark_running",
    "mark_done",
    "is_running",
    "running_slots",
    "error_of",
    "clear",
]
