"""
Phase 4 — Visual Similarity Search (Layer C)

Given a Rexven product image, finds the top-K most visually similar
CompetitorListing rows using cosine similarity on CLIP embeddings.

Caches Rexven embeddings by image hash in rexven_product_embeddings.
Loads all embedded competitor listings into memory for batch matrix multiply
(suitable for up to ~100k listings; switch to pgvector for larger datasets).
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import structlog
from sqlalchemy.orm import Session

from src.db.models import CompetitorListing, RexvenProductEmbedding
from src.sourcing.clip_embedder import ClipEmbedder

_log = structlog.get_logger(__name__)


class VisualSimilaritySearch:
    """Find Etsy listings visually similar to a Rexven product image."""

    def __init__(self, session: Session, embedder: ClipEmbedder):
        self.session = session
        self.embedder = embedder

    def find_similar(
        self,
        rexven_image_path: str,
        top_k: int = 50,
        min_similarity: float = 0.70,
    ) -> list[tuple[CompetitorListing, float]]:
        """
        Return [(listing, similarity_score), ...] sorted descending.
        Filters out listings below min_similarity threshold.
        """
        rexven_emb = self._get_or_compute_rexven_embedding(rexven_image_path)

        # Load all embedded competitor listings
        listings_with_emb = (
            self.session.query(CompetitorListing)
            .filter(CompetitorListing.image_embedding.isnot(None))
            .all()
        )

        # Filter out sentinel rows ([] = failed embedding)
        valid = [
            l for l in listings_with_emb
            if l.image_embedding and len(l.image_embedding) > 0
        ]

        if not valid:
            _log.info("visual_similarity_no_embeddings")
            return []

        # Batch cosine similarity via matrix multiply
        emb_matrix = np.array([l.image_embedding for l in valid], dtype=np.float32)
        similarities = emb_matrix @ rexven_emb  # both L2-normalized

        scored = [
            (valid[i], float(similarities[i]))
            for i in range(len(valid))
            if similarities[i] >= min_similarity
        ]
        scored.sort(key=lambda x: x[1], reverse=True)

        _log.info(
            "visual_similarity_complete",
            candidates=len(valid),
            above_threshold=len(scored),
            top_k=top_k,
        )
        return scored[:top_k]

    def embed_product(self, image_path: str) -> np.ndarray:
        """Return the (cached) CLIP embedding for the product image."""
        return self._get_or_compute_rexven_embedding(image_path)

    def mean_similarity_by_keyword(
        self, product_emb: np.ndarray, keywords: list[str]
    ) -> dict[str, float | None]:
        """Self-relative visual relevance per keyword.

        For each keyword, returns the mean CLIP cosine similarity between the
        product image and the keyword's *own* scraped listings' images — i.e.
        "how much do this keyword's results look like the product?". A niche
        keyword whose listings are all the product type scores high; a broad
        catch-all whose listings are a grab-bag scores low. ``None`` when a
        keyword has no usable embedded listings.
        """
        if not keywords:
            return {}

        rows = (
            self.session.query(CompetitorListing)
            .filter(
                CompetitorListing.keyword_searched.in_(keywords),
                CompetitorListing.image_embedding.isnot(None),
            )
            .all()
        )

        by_kw: dict[str, list] = defaultdict(list)
        for l in rows:
            if l.image_embedding and len(l.image_embedding) > 0:
                by_kw[l.keyword_searched].append(l.image_embedding)

        result: dict[str, float | None] = {}
        for kw in keywords:
            embs = by_kw.get(kw)
            if not embs:
                result[kw] = None
                continue
            matrix = np.array(embs, dtype=np.float32)
            sims = matrix @ product_emb  # both L2-normalized → cosine
            result[kw] = float(np.mean(sims))
        return result

    def extract_keyword_distribution(
        self, similar_listings: list[tuple[CompetitorListing, float]]
    ) -> list[tuple[str, int, float]]:
        """
        From a list of (listing, similarity) pairs, return:
        [(keyword, count, similarity_weighted_count), ...] sorted by weighted count descending.

        The weighted count gives higher votes to more visually similar listings.
        """
        counts: dict[str, int] = defaultdict(int)
        weighted: dict[str, float] = defaultdict(float)

        for listing, sim in similar_listings:
            if listing.keyword_searched:
                counts[listing.keyword_searched] += 1
                weighted[listing.keyword_searched] += sim

        result = [
            (kw, counts[kw], weighted[kw])
            for kw in counts
        ]
        result.sort(key=lambda x: x[2], reverse=True)
        return result

    def _get_or_compute_rexven_embedding(self, image_path: str) -> np.ndarray:
        """Cache Rexven product embeddings by image hash to avoid recomputing."""
        img_hash = ClipEmbedder.image_hash(image_path)

        cached = (
            self.session.query(RexvenProductEmbedding)
            .filter_by(image_hash=img_hash)
            .first()
        )
        if cached:
            _log.info("rexven_embedding_cache_hit", hash=img_hash[:12])
            return np.array(cached.embedding, dtype=np.float32)

        emb = self.embedder.embed_image(image_path)

        record = RexvenProductEmbedding(
            image_hash=img_hash,
            image_path=image_path,
            embedding=emb.tolist(),
            model_name=self.embedder.MODEL_NAME,
        )
        self.session.add(record)
        self.session.commit()

        _log.info("rexven_embedding_computed", hash=img_hash[:12])
        return emb
