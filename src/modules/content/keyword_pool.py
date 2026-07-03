"""
Phase 6.6 — KeywordPoolManager

Wraps the ``keyword_pool`` table to provide:
  - get_for_pillar(pillar) → list of keyword strings for title generation
  - get_candidates(pillar, features, exclude_in_title) → rich candidate list for tag generation
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from src.db.models import KeywordPool


class KeywordPoolManager:
    """DB-backed keyword pool queries for content generators."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_pillar(self, pillar: str, limit: int = 40) -> list[str]:
        """
        Return keyword strings for the given carrier pillar, ordered by category
        (big → medium → niche) so LLM sees the highest-traffic keywords first.
        """
        rows = (
            self._session.query(KeywordPool)
            .filter(KeywordPool.carrier_pillar == pillar)
            .order_by(
                # coerce category sort: big first, then medium, then niche (b < m < n alphabetically)
                KeywordPool.category.asc(),
                KeywordPool.keyword.asc(),
            )
            .limit(limit)
            .all()
        )
        return [r.keyword for r in rows]

    def get_candidates(
        self,
        pillar: str,
        features: str | None = None,
        exclude_in_title: str | None = None,
        limit: int = 60,
    ) -> list[str]:
        """
        Return tag candidates for the given pillar.

        Features (e.g. product shape) are used to bias the query toward
        relevant keywords when the keyword text contains that feature term.

        Words already prominent in *exclude_in_title* are filtered out so we
        don't waste tag slots duplicating what's in the title.
        """
        q = self._session.query(KeywordPool).filter(
            KeywordPool.carrier_pillar == pillar
        )

        rows = q.limit(limit * 2).all()   # over-fetch, then filter client-side

        title_words: set[str] = set()
        if exclude_in_title:
            title_words = {w.lower() for w in exclude_in_title.split()}

        candidates: list[str] = []
        for row in rows:
            kw = row.keyword
            # skip if entire keyword string is a single word already in the title
            if kw.lower() in title_words:
                continue
            # boost relevance when product feature appears in keyword
            if features and features.lower() in kw.lower():
                candidates.insert(0, kw)
            else:
                candidates.append(kw)
            if len(candidates) >= limit:
                break

        return candidates

    def all_keywords(self, pillar: str | None = None) -> list[KeywordPool]:
        """Return all KeywordPool rows, optionally filtered by pillar."""
        q = self._session.query(KeywordPool)
        if pillar:
            q = q.filter(KeywordPool.carrier_pillar == pillar)
        return q.order_by(KeywordPool.carrier_pillar, KeywordPool.category, KeywordPool.keyword).all()

    def upsert_from_csv(self, rows: list[dict]) -> int:
        """
        Upsert keyword rows from parsed CSV dicts.
        Each dict must have keys: keyword, category, carrier_pillar.
        Returns count of rows inserted/updated.
        """
        count = 0
        for row in rows:
            kw = row.get("keyword", "").strip()
            cat = row.get("category", "niche").strip().lower()
            pillar = row.get("carrier_pillar", "").strip().lower()
            if not kw or not pillar:
                continue

            existing = (
                self._session.query(KeywordPool)
                .filter_by(keyword=kw)
                .first()
            )
            if existing:
                existing.category = cat
                existing.carrier_pillar = pillar
            else:
                self._session.add(KeywordPool(
                    keyword=kw,
                    category=cat,
                    carrier_pillar=pillar,
                ))
            count += 1

        self._session.commit()
        return count
