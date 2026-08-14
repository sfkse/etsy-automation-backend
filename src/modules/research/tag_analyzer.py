"""
Tag Frequency & Cliché Analyzer (Step 3.6)

Builds a sales-weighted frequency table of tags used by competitor listings.
When EHunt detail panel data is present (≥20% fill rate), also stratifies tags
by search volume (mainstream / medium / niche) for Phase 6 variant differentiation.

IMPORTANT: Since 2026, Etsy hides seller tags from the public DOM. The Chrome
extension v2.4+ recovers them from EHunt's injected detail panel. Tags come from
CompetitorListing.tags (list) and volumes from CompetitorListing.tag_volumes (dict).
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from statistics import median

from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.models import CompetitorListing

logger = logging.getLogger(__name__)
_settings = Settings()

STOPWORDS = {"the", "a", "an", "and", "or", "with", "for", "in", "to", "of", "on", "by"}


def analyze_tags_for_keyword(session: Session, keyword: str) -> dict | None:
    listings = session.query(CompetitorListing).filter_by(keyword_searched=keyword).all()
    if not listings:
        return None

    listings_with_tags = [l for l in listings if l.tags and len(l.tags) >= 3]
    real_tag_ratio = len(listings_with_tags) / len(listings)
    use_real_tags = real_tag_ratio >= 0.20

    if use_real_tags:
        source = "real_tags_via_ehunt"

        def tag_iter(l):
            return l.tags or []
    else:
        source = "title_derived"

        def tag_iter(l):
            return extract_title_ngrams(l.title) if l.title else []

    tag_weights: dict[str, float] = defaultdict(float)
    tag_counts: dict[str, int] = defaultdict(int)
    bestseller_tags: dict[str, int] = defaultdict(int)
    tag_volume_observations: dict[str, list[int]] = defaultdict(list)

    for listing in listings:
        if listing.tag_volumes:
            for tag, vol in listing.tag_volumes.items():
                tag_norm = tag.lower().strip()
                if isinstance(vol, (int, float)) and vol > 0:
                    tag_volume_observations[tag_norm].append(int(vol))

        for tag in tag_iter(listing):
            tag_normalized = tag.lower().strip()
            if len(tag_normalized) < 3 or len(tag_normalized) > 30:
                continue
            tag_counts[tag_normalized] += 1
            tag_weights[tag_normalized] += listing.sales_signal_score or 0.0
            if listing.is_bestseller:
                bestseller_tags[tag_normalized] += 1

    tag_volume_median = {
        t: int(median(vols)) for t, vols in tag_volume_observations.items() if vols
    }

    sales_weighted = sorted(tag_weights.items(), key=lambda x: x[1], reverse=True)

    volume_stratified: dict | None = None
    if tag_volume_median:
        mainstream, medium, niche = [], [], []
        for tag, _w in sales_weighted[:60]:
            vol = tag_volume_median.get(tag)
            if vol is None:
                continue
            if vol > 50_000_000:
                mainstream.append((tag, vol))
            elif vol > 10_000_000:
                medium.append((tag, vol))
            else:
                niche.append((tag, vol))
        volume_stratified = {
            "mainstream": mainstream[:20],
            "medium": medium[:20],
            "niche": niche[:20],
        }

    avg_volume_by_position: list[int | None] | None = None
    if use_real_tags and any(l.tag_volumes for l in listings_with_tags):
        position_vols: dict[int, list[int]] = defaultdict(list)
        for listing in listings_with_tags:
            if not listing.tag_volumes or not listing.tags:
                continue
            for pos, tag in enumerate(listing.tags):
                vol = listing.tag_volumes.get(tag)
                if vol:
                    position_vols[pos].append(int(vol))
        avg_volume_by_position = [
            int(sum(position_vols[i]) / len(position_vols[i])) if position_vols.get(i) else None
            for i in range(13)
        ]

    return {
        "sample_size": len(listings),
        "source": source,
        "real_tag_ratio": real_tag_ratio,
        "all_tags_frequency": sorted(tag_counts.items(), key=lambda x: -x[1])[:50],
        "sales_weighted_tags": sales_weighted[:30],
        "bestseller_tags": sorted(bestseller_tags.items(), key=lambda x: -x[1])[:20],
        "tag_volume_median": tag_volume_median,
        "volume_stratified_tags": volume_stratified,
        "avg_volume_by_position": avg_volume_by_position,
    }


def extract_title_ngrams(title: str) -> list[str]:
    """
    Extract 2-3 word phrases from a competitor title as tag candidates.
    Etsy titles are comma-separated phrases — split on commas first.
    """
    if not title:
        return []

    phrases = [p.strip().lower() for p in title.split(",")]
    candidates: list[str] = []

    for phrase in phrases:
        words = [w for w in phrase.split() if w and w not in STOPWORDS]
        if not words:
            continue
        if 2 <= len(words) <= 4:
            candidates.append(" ".join(words))
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            if bigram not in candidates:
                candidates.append(bigram)

    return candidates


async def extract_cliches(
    session: Session,
    keyword: str,
    llm_client,
) -> list[str]:
    """
    Pulls up to 20 competitor descriptions for the keyword, asks LLM to identify
    overused opening phrases. Returns empty list on LLM failure (non-blocking).
    """
    listings = (
        session.query(CompetitorListing)
        .filter_by(keyword_searched=keyword)
        .filter(CompetitorListing.description_text.isnot(None))
        .limit(20)
        .all()
    )

    if len(listings) < 5:
        return []

    descriptions = [l.description_text[:500] for l in listings]

    prompt = f"""Below are up to 20 Etsy product description openings for jewelry.

Identify phrases that appear in MULTIPLE descriptions or that have a
templated, AI-generated feel. These are clichés our system MUST AVOID.

Return JSON only:
{{"cliches": ["exact phrase 1", "exact phrase 2", ...]}}

Descriptions:
{chr(10).join(f"{i+1}. {d}" for i, d in enumerate(descriptions))}
"""

    try:
        # Cliché extraction is pattern-matching, not creative prose — Haiku is
        # enough. Pin the structured model explicitly so this stays cheap even
        # if a caller passes a Sonnet-configured client.
        response = await llm_client.complete(prompt, model=_settings.LLM_MODEL_STRUCTURED)
        return json.loads(response).get("cliches", [])
    except Exception as exc:
        logger.warning("Cliché extraction failed for %r: %s", keyword, exc)
        return []
