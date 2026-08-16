"""Process-local registry of in-flight per-slot video generations.

A parallel of ``modules.images.regen_jobs`` for video clips, kept separate so
video status is independent of image-regeneration status. Same design: a tiny
in-memory, thread-locked store keyed by ``(sku, slot)``. Safe because the app
runs as a single uvicorn process; state need not survive a restart (a dropped
in-flight job simply stops showing a spinner, and the ``.mp4`` on disk is the
source of truth for the result).
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
