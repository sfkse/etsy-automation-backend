"""
Phase 6.3 — TagGenerator (Per Variant Angle, Volume-Aware)

Generates exactly 13 tags for a given strategic angle, paired with the
variant's title for internal consistency.

Volume-aware strategy:
  Each angle uses a different bucket ratio (mainstream / medium / niche) so
  that the 3 variants draw from different parts of the search volume spectrum.
  When EHunt volume data is absent, falls back to the classic 8-niche/3-medium/2-big rule.
"""
from __future__ import annotations

import structlog

from src.config.prompts import TAG_GENERATION_PROMPT
from src.db.models import Product
from src.domain.validators import validate_tags
from src.modules.llm.angles import VariantAngle
from src.modules.research.context_builder import ResearchContextBuilder
from src.modules.content.keyword_pool import KeywordPoolManager
from src.utils.llm_client import LLMClient

_log = structlog.get_logger(__name__)

_FALLBACK_DISTRIBUTION = "Use the classic distribution: 8 niche (<10M), 3 medium (10-50M), 2 big (>50M)."


def _fmt_vol(v: int | None) -> str:
    if v is None:
        return "?"
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.1f}B"
    if v >= 1_000_000:
        result = f"{v / 1_000_000:.1f}M"
        return result.replace(".0M", "M")
    if v >= 1_000:
        return f"{v / 1_000:.0f}K"
    return str(v)


def _merge_unique(primary: list[str], secondary: list[str], max_items: int = 60) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in primary + secondary:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
        if len(result) >= max_items:
            break
    return result


class TagGenerator:
    """Generate 13 tags per strategic angle, volume-aware when research data exists."""

    def __init__(
        self,
        llm_client: LLMClient,
        keyword_pool: KeywordPoolManager,
        research_builder: ResearchContextBuilder,
    ) -> None:
        self.llm = llm_client
        self.pool = keyword_pool
        self.research = research_builder

    async def generate_for_angle(
        self,
        product: Product,
        angle: VariantAngle,
        paired_title: str,
    ) -> list[str]:
        """Generate exactly 13 tags for the given angle, paired with the variant title."""

        pool_candidates = self.pool.get_candidates(
            pillar=product.carrier_pillar,
            features=product.shape,
            exclude_in_title=paired_title,
        )

        research_ctx = self.research.build_for_carrier_pillar(product.carrier_pillar)
        volume_buckets = self._extract_volume_buckets(research_ctx)

        if volume_buckets:
            target = angle.tag_distribution
            angle_candidates = self._build_angle_pool(volume_buckets, target, pool_candidates)
            distribution_hint = (
                f"Use this exact volume mix: "
                f"{target['mainstream']} mainstream (>50M searches), "
                f"{target['medium']} medium (10-50M searches), "
                f"{target['niche']} niche (<10M searches). "
                "Each candidate below is labelled with its bucket — pick from the right bucket."
            )
        else:
            research_tags = [t for t, _ in (research_ctx.top_tags[:30] if research_ctx.has_data else [])]
            angle_candidates_raw = _merge_unique(research_tags, pool_candidates, max_items=60)
            # Format as simple strings for the prompt
            angle_candidates = [{"tag": t, "volume": None, "bucket": "pool"} for t in angle_candidates_raw]
            distribution_hint = _FALLBACK_DISTRIBUTION

        prompt = TAG_GENERATION_PROMPT.format(
            paired_title=paired_title,
            angle_label=angle.label,
            angle_instructions=angle.tag_instructions,
            distribution_hint=distribution_hint,
            candidates=self._format_candidates(angle_candidates),
        )

        response = await self.llm.complete(prompt, max_tokens=400)
        tags = self._parse_tags(response)

        is_valid, violations = validate_tags(tags, paired_title)
        if not is_valid:
            _log.warning("tags_invalid", angle=angle.label, violations=violations)
            tags = await self._retry_generate(product, angle, paired_title, violations)

        # Log research-derivation ratio for monitoring
        if research_ctx.has_data:
            research_tag_set = {t.lower() for t, _ in research_ctx.top_tags}
            derived = sum(1 for t in tags if t.lower() in research_tag_set)
            _log.info(
                "tag_research_ratio",
                angle=angle.label,
                derived=derived,
                total=len(tags),
                ratio=f"{derived / len(tags):.0%}" if tags else "0%",
            )

        return tags

    def _extract_volume_buckets(self, ctx) -> dict:
        """Pull volume_stratified_tags from research_ctx, or {} if not present."""
        if not ctx.has_data:
            return {}
        return getattr(ctx, "volume_stratified_tags", None) or {}

    def _build_angle_pool(
        self, buckets: dict, target: dict, pool_candidates: list[str]
    ) -> list[dict]:
        """
        Build a candidate list weighted toward this angle's buckets.
        Each candidate is formatted as {"tag": str, "volume": int|None, "bucket": str}
        so the LLM sees the volume label.
        2x oversampling gives the LLM room to choose.
        """
        result: list[dict] = []
        for bucket_name in ("mainstream", "medium", "niche"):
            slots = target.get(bucket_name, 0) * 2
            items = buckets.get(bucket_name, [])[:slots]
            for tag, vol in items:
                result.append({"tag": tag, "volume": vol, "bucket": bucket_name})

        # Add pool keywords as unlabelled backup
        existing = {r["tag"].lower() for r in result}
        for tag in pool_candidates[:10]:
            if tag.lower() not in existing:
                result.append({"tag": tag, "volume": None, "bucket": "pool"})

        return result

    @staticmethod
    def _format_candidates(candidates: list[dict]) -> str:
        lines = []
        for c in candidates:
            vol_str = f" [vol: {_fmt_vol(c['volume'])}]" if c.get("volume") else ""
            bucket_str = f" ({c['bucket']})" if c.get("bucket") and c["bucket"] != "pool" else ""
            lines.append(f"- {c['tag']}{vol_str}{bucket_str}")
        return "\n".join(lines) if lines else "(no candidates — use product type keywords)"

    @staticmethod
    def _parse_tags(response: str) -> list[str]:
        """Parse comma-separated tags from LLM response."""
        text = response.strip()
        # Handle both comma-separated and newline-separated responses
        if "," in text:
            tags = [t.strip() for t in text.split(",")]
        else:
            tags = [t.strip() for t in text.splitlines() if t.strip()]

        # Strip any surrounding quotes or bullets
        cleaned = []
        for tag in tags:
            tag = tag.strip("\"'•-").strip()
            if tag:
                cleaned.append(tag)
        return cleaned[:13]

    async def _retry_generate(
        self,
        product: Product,
        angle: VariantAngle,
        paired_title: str,
        violations: list[str],
    ) -> list[str]:
        """Retry with a tighter prompt that lists the specific violations."""
        pool_candidates = self.pool.get_candidates(
            pillar=product.carrier_pillar,
            features=product.shape,
            exclude_in_title=paired_title,
        )
        candidate_dicts = [{"tag": t, "volume": None, "bucket": "pool"} for t in pool_candidates[:40]]

        violation_text = "; ".join(violations)
        retry_prompt = TAG_GENERATION_PROMPT.format(
            paired_title=paired_title,
            angle_label=angle.label,
            angle_instructions=angle.tag_instructions,
            distribution_hint=_FALLBACK_DISTRIBUTION,
            candidates=self._format_candidates(candidate_dicts),
        ) + f"\n\nPREVIOUS ATTEMPT VIOLATIONS (fix these): {violation_text}"

        response = await self.llm.complete(retry_prompt, max_tokens=400)
        tags = self._parse_tags(response)
        is_valid, remaining = validate_tags(tags, paired_title)
        if not is_valid:
            _log.error("tag_retry_also_failed", angle=angle.label, violations=remaining)
        return tags
