"""
Research Context Builder (Step 3.9)

Produces a ResearchContext dataclass from KeywordResearch + CompetitorListing
data. The context is injected into Phase 6 LLM prompts to ground title/tag/
description generation in real bestseller data.

Step 3.10 empty-state handling:
  - ResearchContext.empty() is returned when no data exists
  - Settings.REQUIRE_RESEARCH_FOR_GENERATION controls whether generation
    proceeds without data (False = cold-start mode, True = hard block)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from sqlalchemy.orm import Session

from src.db.models import KeywordResearch
from src.domain.carrier_pillar import CarrierPillar


@dataclass
class ResearchContext:
    sample_size: int
    avg_title_length: float
    top_keywords_sales_weighted: list[tuple[str, float]]
    underused_keywords: list[str]
    structural_patterns: list[dict]
    top_tags: list[tuple[str, int]]
    cliches_to_avoid: list[str]
    volume_stratified_tags: dict | None = None
    avg_volume_by_position: list[int | None] | None = None

    @classmethod
    def empty(cls) -> "ResearchContext":
        return cls(
            sample_size=0,
            avg_title_length=0.0,
            top_keywords_sales_weighted=[],
            underused_keywords=[],
            structural_patterns=[],
            top_tags=[],
            cliches_to_avoid=[],
            volume_stratified_tags=None,
            avg_volume_by_position=None,
        )

    @property
    def has_data(self) -> bool:
        return self.sample_size > 0

    @property
    def has_volume_data(self) -> bool:
        return bool(self.volume_stratified_tags)

    def format_for_prompt(self) -> str:
        if not self.has_data:
            return "No competitor research available for this product category yet."

        lines = [
            f"COMPETITOR INTELLIGENCE (based on {self.sample_size} real Etsy listings):",
            "",
            f"- Average title length used by bestsellers: {self.avg_title_length:.0f} chars",
        ]

        if self.top_keywords_sales_weighted:
            kw_str = ", ".join(
                f"{k} ({v:.0f})" for k, v in self.top_keywords_sales_weighted[:15]
            )
            lines.append(f"- Most common keywords (sales-weighted): {kw_str}")

        if self.underused_keywords:
            lines.append(
                f"- Underused but promising (differentiation): {', '.join(self.underused_keywords[:10])}"
            )

        if self.structural_patterns:
            lines.append("- Top structural patterns:")
            for p in self.structural_patterns[:5]:
                lines.append(f"    • {p.get('pattern', '')}")

        if self.top_tags:
            tag_str = ", ".join(f"{t} ({c})" for t, c in self.top_tags[:20])
            lines.append(f"- Top tags by sales-weighted frequency: {tag_str}")

        if self.cliches_to_avoid:
            lines.append("- CLICHÉS TO AVOID in descriptions:")
            for c in self.cliches_to_avoid[:10]:
                lines.append(f"    • {c}")

        if self.has_volume_data:
            vs = self.volume_stratified_tags
            mainstream = ", ".join(
                f"{t} ({_fmt_vol(v)})" for t, v in (vs.get("mainstream") or [])[:8]
            )
            medium = ", ".join(
                f"{t} ({_fmt_vol(v)})" for t, v in (vs.get("medium") or [])[:8]
            )
            niche = ", ".join(
                f"{t} ({_fmt_vol(v)})" for t, v in (vs.get("niche") or [])[:10]
            )
            lines += [
                "",
                "TAG SEARCH VOLUME STRATIFICATION (EHunt — use for variant differentiation):",
                f"- MAINSTREAM tags (>50M searches, high competition): {mainstream or '(none in sample)'}",
                f"- MEDIUM tags (10M-50M, balanced): {medium or '(none in sample)'}",
                f"- NICHE tags (<10M, low competition, highly targeted): {niche or '(none in sample)'}",
            ]

        return "\n".join(lines)


class ResearchContextBuilder:
    """
    Given a product (with carrier_pillar + optional keyword hint), produce a
    compact intelligence brief from KeywordResearch + CompetitorListing data.
    """

    def __init__(self, session: Session):
        self.session = session

    def build_for_keywords(self, keywords: list[str]) -> ResearchContext:
        if not keywords:
            return ResearchContext.empty()

        research_rows = (
            self.session.query(KeywordResearch)
            .filter(KeywordResearch.keyword.in_(keywords))
            .all()
        )

        if not research_rows:
            return ResearchContext.empty()

        return ResearchContext(
            sample_size=sum(
                (r.total_listings_scraped or 0) for r in research_rows
            ),
            avg_title_length=_safe_mean(
                r.avg_title_length for r in research_rows if r.avg_title_length
            ),
            top_keywords_sales_weighted=_merge_keyword_freq(research_rows),
            underused_keywords=_merge_underused(research_rows),
            structural_patterns=_merge_patterns(research_rows),
            top_tags=_merge_tags(research_rows),
            cliches_to_avoid=_merge_cliches(research_rows),
            volume_stratified_tags=_merge_volume_stratified(research_rows),
            avg_volume_by_position=_merge_avg_volume_by_position(research_rows),
        )

    def build_for_carrier_pillar(self, pillar: str | CarrierPillar) -> ResearchContext:
        """Convenience: map carrier pillar → default search keywords."""
        pillar_str = pillar.value if isinstance(pillar, CarrierPillar) else str(pillar)
        keywords = _pillar_to_keywords(pillar_str)
        return self.build_for_keywords(keywords)


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------

def _merge_keyword_freq(rows: list[KeywordResearch]) -> list[tuple[str, float]]:
    combined: dict[str, float] = {}
    for row in rows:
        tp = row.title_patterns
        if not tp:
            continue
        for kw, score in (tp.get("sales_weighted_keywords") or []):
            combined[kw] = combined.get(kw, 0.0) + float(score)
    return sorted(combined.items(), key=lambda x: x[1], reverse=True)[:30]


def _merge_underused(rows: list[KeywordResearch]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for row in rows:
        for kw in (row.underused_keywords or []):
            if kw not in seen:
                seen.add(kw)
                result.append(kw)
    return result[:15]


def _merge_patterns(rows: list[KeywordResearch]) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        tp = row.title_patterns
        if not tp:
            continue
        for p in (tp.get("structural_patterns") or []):
            pat = p.get("pattern", "")
            if pat and pat not in seen:
                seen.add(pat)
                result.append(p)
    return result[:10]


def _merge_tags(rows: list[KeywordResearch]) -> list[tuple[str, int]]:
    combined: dict[str, int] = {}
    for row in rows:
        ttf = row.top_tags_by_frequency
        if not ttf:
            continue
        for tag, count in (ttf.get("all_tags_frequency") or []):
            combined[tag] = combined.get(tag, 0) + count
    return sorted(combined.items(), key=lambda x: x[1], reverse=True)[:30]


def _merge_cliches(rows: list[KeywordResearch]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for row in rows:
        for c in (row.common_cliches or []):
            if c not in seen:
                seen.add(c)
                result.append(c)
    return result[:20]


def _merge_volume_stratified(rows: list[KeywordResearch]) -> dict | None:
    merged: dict[str, dict[str, int]] = {
        "mainstream": {},
        "medium": {},
        "niche": {},
    }
    has_any = False
    for row in rows:
        vs = row.volume_stratified_tags
        if not vs:
            continue
        has_any = True
        for tier in ("mainstream", "medium", "niche"):
            for tag, vol in (vs.get(tier) or []):
                if tag not in merged[tier]:
                    merged[tier][tag] = vol
    if not has_any:
        return None
    return {
        tier: sorted(merged[tier].items(), key=lambda x: -x[1])[:20]
        for tier in ("mainstream", "medium", "niche")
    }


def _merge_avg_volume_by_position(rows: list[KeywordResearch]) -> list[int | None] | None:
    all_positions: list[list[int | None]] = []
    for row in rows:
        avp = row.avg_volume_by_position
        if avp and len(avp) == 13:
            all_positions.append(avp)
    if not all_positions:
        return None
    result: list[int | None] = []
    for pos in range(13):
        vals = [p[pos] for p in all_positions if p[pos] is not None]
        result.append(int(sum(vals) / len(vals)) if vals else None)
    return result


def _safe_mean(iterable) -> float:
    values = list(iterable)
    return mean(values) if values else 0.0


def _pillar_to_keywords(pillar: str) -> list[str]:
    """
    Rough mapping from carrier pillar name → typical Etsy search keywords.
    Refined by the user over time via the research import flow.
    """
    mapping: dict[str, list[str]] = {
        "cross": ["cross necklace", "gold cross necklace", "christian necklace"],
        "birthstone": ["birthstone necklace", "personalized birthstone jewelry"],
        "initial": ["initial necklace", "letter necklace", "personalized initial jewelry"],
        "name": ["name necklace", "personalized name jewelry", "custom name necklace"],
        "zodiac": ["zodiac necklace", "astrology jewelry", "zodiac sign jewelry"],
        "heart": ["heart necklace", "love necklace", "heart pendant jewelry"],
    }
    return mapping.get(pillar.lower(), [pillar.replace("_", " ")])


def _fmt_vol(v: int) -> str:
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.1f}B"
    if v >= 1_000_000:
        result = f"{v / 1_000_000:.1f}M"
        return result.replace(".0M", "M")
    if v >= 1_000:
        return f"{v / 1_000:.0f}K"
    return str(v)
