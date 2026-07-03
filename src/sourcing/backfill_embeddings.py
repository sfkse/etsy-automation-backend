"""
Phase 4 — CLIP Embedding Backfill Job (Layer C)

One-time batch job that computes CLIP embeddings for all CompetitorListing
rows where image_embedding IS NULL.

Resumable: safe to interrupt and re-run — only processes rows that haven't
been processed yet (NULL embedding). Failed downloads are stored as an empty
list [] to distinguish "tried and failed" from "not yet tried" (NULL).

Usage:
  python -m src.sourcing.backfill_embeddings
  python -m src.sourcing.backfill_embeddings --batch-size 100 --max-listings 5000
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime

import structlog

_log = structlog.get_logger(__name__)


def backfill_listing_embeddings(
    session,
    embedder,
    batch_size: int = 50,
    max_listings: int | None = None,
) -> dict:
    """
    Compute and store CLIP embeddings for all CompetitorListing rows
    where image_embedding IS NULL.

    Returns summary dict: {"processed": int, "failed": int, "skipped": int}.
    """
    from src.db.models import CompetitorListing

    query = (
        session.query(CompetitorListing)
        .filter(
            CompetitorListing.image_embedding.is_(None),
            CompetitorListing.image_url.isnot(None),
        )
    )

    total = query.count()
    if max_listings is not None:
        total = min(total, max_listings)

    _log.info("backfill_start", total=total, batch_size=batch_size)
    print(f"[backfill] Processing {total} listings without embeddings...")

    processed = 0
    failed = 0
    start = time.time()

    while processed < total:
        batch = (
            session.query(CompetitorListing)
            .filter(
                CompetitorListing.image_embedding.is_(None),
                CompetitorListing.image_url.isnot(None),
            )
            .limit(batch_size)
            .all()
        )
        if not batch:
            break

        for listing in batch:
            try:
                emb = embedder.embed_image_url(listing.image_url)
                listing.image_embedding = emb.tolist()
                listing.image_embedding_model = embedder.MODEL_NAME
                listing.image_embedding_computed_at = datetime.utcnow()
                processed += 1
            except Exception as e:
                _log.warning(
                    "backfill_listing_failed",
                    listing_id=listing.listing_id,
                    error=str(e),
                )
                failed += 1
                # [] sentinel = "tried but failed"; NULL = "not yet tried"
                listing.image_embedding = []
                listing.image_embedding_computed_at = datetime.utcnow()

        session.commit()

        elapsed = time.time() - start
        rate = (processed + failed) / elapsed if elapsed > 0 else 0
        remaining = total - processed - failed
        eta = remaining / rate if rate > 0 else 0
        print(
            f"[backfill] {processed + failed}/{total}  "
            f"ok={processed}  fail={failed}  "
            f"rate={rate:.1f}/s  eta={eta:.0f}s"
        )

    summary = {"processed": processed, "failed": failed}
    _log.info("backfill_complete", **summary)
    print(f"\n[backfill] Complete. Processed: {processed}, Failed: {failed}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill CLIP embeddings for competitor listings")
    parser.add_argument("--batch-size", type=int, default=50, help="Rows per DB commit")
    parser.add_argument("--max-listings", type=int, default=None, help="Cap total rows processed")
    args = parser.parse_args()

    from src.db.session import SessionLocal
    from src.sourcing.clip_embedder import ClipEmbedder

    session = SessionLocal()
    embedder = ClipEmbedder()

    try:
        backfill_listing_embeddings(
            session=session,
            embedder=embedder,
            batch_size=args.batch_size,
            max_listings=args.max_listings,
        )
    finally:
        session.close()
