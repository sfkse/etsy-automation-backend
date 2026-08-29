"""
Phase 6.3 — TagGenerator (Per Variant Angle, Volume-Aware)

Generates exactly 13 tags for a given strategic angle, paired with the
variant's title for internal consistency.

Volume-aware strategy:
  Each angle uses a different bucket ratio (mainstream / medium / niche) so
  that the 3 variants draw from different parts of the search volume spectrum.
  When EHunt volume data is absent, falls back to the classic 9-niche/3-medium/1-big rule.

Mechanical defects (casing, tags duplicating the title) are auto-corrected by
``normalize_tags`` before validation; judgment calls (broad-tag overage, too few
long-tail tags) stay as violations for the approval screen.
"""
from __future__ import annotations

import structlog

from src.config.business_rules import TAG_COUNT
from src.config.prompts import TAG_DYNAMIC_TEMPLATE, TAG_STATIC_PREFIX
from src.db.models import Product
from src.domain.validators import normalize_tags, validate_tags
from src.modules.llm.angles import VariantAngle
from src.modules.research.context_builder import ResearchContextBuilder
from src.modules.content.keyword_pool import KeywordPoolManager
from src.utils.llm_client import LLMClient

_log = structlog.get_logger(__name__)

_FALLBACK_DISTRIBUTION = (
    "Use the classic distribution: 9 niche (<10M), 3 medium (10-50M), 1 big (>50M). "
    "Never exceed 2 big tags — they inflate ad spend without a matching lift."
)


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

        research_ctx = self.research.build_for_product(product)
        volume_buckets = self._extract_volume_buckets(research_ctx)
        research_tags = [
            t for t, _ in (research_ctx.top_tags[:30] if research_ctx.has_data else [])
        ]

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
            angle_candidates_raw = _merge_unique(research_tags, pool_candidates, max_items=60)
            # Format as simple strings for the prompt
            angle_candidates = [{"tag": t, "volume": None, "bucket": "pool"} for t in angle_candidates_raw]
            distribution_hint = _FALLBACK_DISTRIBUTION

        angle_candidates = self._prepend_universals(angle_candidates)

        prompt = TAG_DYNAMIC_TEMPLATE.format(
            paired_title=paired_title,
            angle_label=angle.label,
            angle_instructions=angle.tag_instructions,
            distribution_hint=distribution_hint,
            candidates=self._format_candidates(angle_candidates),
        )

        response = await self.llm.complete(
            prompt=prompt, cached_prefix=TAG_STATIC_PREFIX, max_tokens=400
        )
        tags = self._normalize_and_backfill(
            self._parse_tags(response), paired_title, angle, pool_candidates,
            research_tags=research_tags,
        )

        is_valid, violations = validate_tags(tags, paired_title)
        if not is_valid:
            _log.warning("tags_invalid", angle=angle.label, violations=violations)
            tags = await self._retry_generate(
                product, angle, paired_title, violations, research_tags=research_tags
            )

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

    def _normalize_and_backfill(
        self,
        tags: list[str],
        paired_title: str,
        angle: VariantAngle,
        pool_candidates: list[str],
        research_tags: list[str] | None = None,
    ) -> list[str]:
        """Auto-correct casing / title-duplicate tags, then refill the freed slots
        so the count never drops below ``TAG_COUNT``.

        Etsy gives every listing 13 tag slots and the guide treats all 13 as
        mandatory, so shipping fewer is strictly worse than shipping a redundant
        one. Replacements are tried in order — pillar pool, then research tags,
        then universal staples — and if every source is exhausted the dropped
        tags go back in. ``validate_tags`` still reports the wasted slot, so a
        human sees it; the listing just never goes out under-filled.
        """
        original_count = len(tags)
        cleaned, notes = normalize_tags(tags, paired_title)
        if notes:
            _log.info("tags_normalized", angle=angle.label, fixes=notes)
        if len(cleaned) >= TAG_COUNT:
            return cleaned[:TAG_COUNT]

        dropped_count = original_count - len(cleaned)
        taken = {t.lower() for t in cleaned}

        def _take_from(source: list[str], allow_title_dupes: bool = False) -> int:
            added = 0
            for candidate in source:
                if len(cleaned) >= TAG_COUNT:
                    break
                # Passing no title skips the wasted-slot drop, which is what the
                # last-resort restore needs.
                normalized, _ = normalize_tags(
                    [candidate], "" if allow_title_dupes else paired_title
                )
                if not normalized or normalized[0].lower() in taken:
                    continue
                cleaned.append(normalized[0])
                taken.add(normalized[0].lower())
                added += 1
            return added

        from_pool = _take_from(pool_candidates)
        from_research = _take_from(research_tags or [])
        from_universal = _take_from(self.pool.get_universal_keywords())

        # Last resort: put back what we dropped rather than ship an empty slot.
        restored = _take_from(tags, allow_title_dupes=True)

        _log.info(
            "tags_backfilled",
            angle=angle.label,
            dropped=dropped_count,
            from_pool=from_pool,
            from_research=from_research,
            from_universal=from_universal,
            restored=restored,
            final=len(cleaned),
        )
        if len(cleaned) < TAG_COUNT:
            _log.warning(
                "tags_still_short",
                angle=angle.label,
                count=len(cleaned),
                expected=TAG_COUNT,
                hint="keyword_pool has no rows for this carrier_pillar",
            )

        return cleaned[:TAG_COUNT]

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

    def _prepend_universals(self, candidates: list[dict]) -> list[dict]:
        """Ensure every universal SEO staple appears in the candidate list, marked
        with the ``universal`` bucket. They are candidates only — the LLM chooses
        based on product fit. Existing entries duplicating a universal are dropped
        and re-added (marked) so all 9 render with the [universal] suffix."""
        universal_kws = self.pool.get_universal_keywords()
        if not universal_kws:
            return candidates
        universal_lower = {kw.lower() for kw in universal_kws}
        deduped = [c for c in candidates if c.get("tag", "").lower() not in universal_lower]
        universal_dicts = [
            {"tag": kw, "volume": None, "bucket": "universal"} for kw in universal_kws
        ]
        return universal_dicts + deduped

    @staticmethod
    def _format_candidates(candidates: list[dict]) -> str:
        lines = []
        for c in candidates:
            vol_str = f" [vol: {_fmt_vol(c['volume'])}]" if c.get("volume") else ""
            bucket = c.get("bucket")
            if bucket == "universal":
                bucket_str = " [universal]"
            elif bucket and bucket != "pool":
                bucket_str = f" ({bucket})"
            else:
                bucket_str = ""
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
        research_tags: list[str] | None = None,
    ) -> list[str]:
        """Retry with a tighter prompt that lists the specific violations."""
        pool_candidates = self.pool.get_candidates(
            pillar=product.carrier_pillar,
            features=product.shape,
            exclude_in_title=paired_title,
        )
        candidate_dicts = [{"tag": t, "volume": None, "bucket": "pool"} for t in pool_candidates[:40]]
        candidate_dicts = self._prepend_universals(candidate_dicts)

        violation_text = "; ".join(violations)
        retry_prompt = TAG_DYNAMIC_TEMPLATE.format(
            paired_title=paired_title,
            angle_label=angle.label,
            angle_instructions=angle.tag_instructions,
            distribution_hint=_FALLBACK_DISTRIBUTION,
            candidates=self._format_candidates(candidate_dicts),
        ) + f"\n\nPREVIOUS ATTEMPT VIOLATIONS (fix these): {violation_text}"

        response = await self.llm.complete(
            prompt=retry_prompt, cached_prefix=TAG_STATIC_PREFIX, max_tokens=400
        )
        tags = self._normalize_and_backfill(
            self._parse_tags(response), paired_title, angle, pool_candidates,
            research_tags=research_tags,
        )
        is_valid, remaining = validate_tags(tags, paired_title)
        if not is_valid:
            _log.error("tag_retry_also_failed", angle=angle.label, violations=remaining)
        return tags
