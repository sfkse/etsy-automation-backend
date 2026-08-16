"""Unit tests for the in-memory per-slot regeneration registry."""
from __future__ import annotations

from src.modules.images import regen_jobs


def test_mark_running_then_done_tracks_state():
    sku, slot = "TAKI-TEST", "mannequin-1"
    regen_jobs.clear(sku, slot)

    assert regen_jobs.is_running(sku, slot) is False

    regen_jobs.mark_running(sku, slot)
    assert regen_jobs.is_running(sku, slot) is True
    assert slot in regen_jobs.running_slots(sku)
    assert regen_jobs.error_of(sku, slot) is None

    regen_jobs.mark_done(sku, slot)
    assert regen_jobs.is_running(sku, slot) is False
    assert slot not in regen_jobs.running_slots(sku)

    regen_jobs.clear(sku, slot)


def test_mark_done_records_error():
    sku, slot = "TAKI-TEST", "concept-2"
    regen_jobs.mark_running(sku, slot)
    regen_jobs.mark_done(sku, slot, error="boom")

    assert regen_jobs.is_running(sku, slot) is False
    assert regen_jobs.error_of(sku, slot) == "boom"

    # a fresh run clears the error again
    regen_jobs.mark_running(sku, slot)
    assert regen_jobs.error_of(sku, slot) is None

    regen_jobs.clear(sku, slot)


def test_running_slots_is_scoped_per_sku():
    regen_jobs.mark_running("SKU-A", "mannequin-1")
    regen_jobs.mark_running("SKU-B", "concept-1")

    assert regen_jobs.running_slots("SKU-A") == {"mannequin-1"}
    assert regen_jobs.running_slots("SKU-B") == {"concept-1"}

    regen_jobs.clear("SKU-A", "mannequin-1")
    regen_jobs.clear("SKU-B", "concept-1")
