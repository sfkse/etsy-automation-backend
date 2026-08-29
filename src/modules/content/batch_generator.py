"""
Phase 6 — BatchTitleTagGenerator

Generates the title + 13 tags for ALL 3 variants in a SINGLE LLM call, instead of
6 separate calls (3 titles + 3 tags). Giving the model all 3 angles at once lets it
deliberately DIFFERENTIATE the variants (Christmas-2 principle) while cutting tokens.

On any parse or validation failure the whole batch is rejected (raises
``BatchGenerationError``); the orchestrator then falls back to the per-variant
``TitleGenerator`` / ``TagGenerator`` path. Description generation is unaffected —
it always stays per-variant.
"""
from __future__ import annotations

import json

import structlog

from src.config.prompts import BATCH_VARIANT_PROMPT
from src.config.settings import Settings
from src.db.models import Product
from src.domain.validators import (
    normalize_tags,
    validate_material_coherence,
    validate_tags,
    validate_title,
    validate_variant_divergence,
)
from src.modules.content.description_generator import _product_summary
from src.modules.content.title_generator import _pad_to_band
from src.modules.llm.angles import VariantAngle
from src.modules.research.context_builder import ResearchContextBuilder
from src.utils.llm_client import LLMClient

_log = structlog.get_logger(__name__)


class BatchGenerationError(Exception):
    """Raised when the batch response cannot be parsed or fails validation.

    The orchestrator catches this and falls back to per-variant generation.
    """


class BatchTitleTagGenerator:
    """Generate title + tags for all 3 variants in a single LLM call."""

    def __init__(
        self,
        llm_client: LLMClient,
        research_builder: ResearchContextBuilder,
    ) -> None:
        self.llm = llm_client
        self.research = research_builder

    async def generate_all(
        self, product: Product, angles: list[VariantAngle]
    ) -> dict[str, dict]:
        """Generate title + tags for all 3 variants at once.

        Returns ``{"A": {"title": str, "tags": [str]}, "B": {...}, "C": {...}}``
        keyed by each angle's ``variant_letter``.

        Raises ``BatchGenerationError`` if the response cannot be parsed or any
        variant fails title/tag validation.
        """
        assert len(angles) == 3, "batch generator expects exactly 3 angles"

        research_ctx = self.research.build_for_product(product)

        prompt = BATCH_VARIANT_PROMPT.format(
            product_summary=_product_summary(product),
            research_brief=(
                research_ctx.format_for_prompt()
                if research_ctx.has_data
                else "No competitor research available for this product yet."
            ),
            angle_a_label=angles[0].label,
            angle_a_instructions=angles[0].prompt_instructions,
            angle_a_distribution=self._format_distribution(angles[0].tag_distribution),
            angle_b_label=angles[1].label,
            angle_b_instructions=angles[1].prompt_instructions,
            angle_b_distribution=self._format_distribution(angles[1].tag_distribution),
            angle_c_label=angles[2].label,
            angle_c_instructions=angles[2].prompt_instructions,
            angle_c_distribution=self._format_distribution(angles[2].tag_distribution),
        )

        response = await self.llm.complete(
            prompt=prompt,
            max_tokens=1500,  # 3 variants of title + 13 tags
            model=Settings().LLM_MODEL_CREATIVE,
        )

        parsed = self._parse_json_response(response)
        validated = self._validate_all(parsed, product, angles)
        self._check_cross_variant_overlap(validated)
        return validated

    @staticmethod
    def _format_distribution(dist: dict) -> str:
        """Render a tag_distribution dict as a compact human string."""
        return (
            f"{dist.get('mainstream', 0)} mainstream / "
            f"{dist.get('medium', 0)} medium / "
            f"{dist.get('niche', 0)} niche"
        )

    @staticmethod
    def _parse_json_response(response: str) -> dict:
        """Parse the model's JSON, tolerating an accidental markdown fence."""
        clean = response.strip()
        if clean.startswith("```"):
            # Strip the opening fence (```/```json) and anything after the closing one.
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        try:
            return json.loads(clean.strip())
        except json.JSONDecodeError as exc:
            _log.warning("batch_json_parse_failed", error=str(exc))
            raise BatchGenerationError(f"batch JSON parse failed: {exc}") from exc

    def _validate_all(
        self, parsed: dict, product: Product, angles: list[VariantAngle]
    ) -> dict:
        """Validate every variant; raise on the first failure (whole-batch reject)."""
        result: dict[str, dict] = {}
        for angle in angles:
            letter = angle.variant_letter
            key = f"variant_{letter.lower()}"
            try:
                variant = parsed[key]
                title = variant["title"]
                tags = variant["tags"]
            except (KeyError, TypeError) as exc:
                _log.warning("batch_variant_missing", variant=letter, error=str(exc))
                raise BatchGenerationError(
                    f"variant {letter} missing or malformed"
                ) from exc

            # Auto-fix what can be fixed without a candidate pool: pad the title
            # into the length band, and re-case / de-duplicate the tags. The
            # title is deliberately NOT passed to normalize_tags — dropping a
            # title-duplicate tag here would leave fewer than TAG_COUNT with
            # nothing to backfill from. Those stay violations, which rejects the
            # batch and hands off to the per-variant path, which does backfill.
            title = _pad_to_band(title)
            tags, notes = normalize_tags(tags)
            if notes:
                _log.info("batch_tags_normalized", variant=letter, fixes=notes)

            title_ok, title_violations = validate_title(
                title, target_keyword=product.target_keyword
            )
            tags_ok, tag_violations = validate_tags(tags, title)

            mat_ok, mat_violations = validate_material_coherence(title, tags)
            tags_ok = tags_ok and mat_ok
            tag_violations = tag_violations + mat_violations

            if not title_ok or not tags_ok:
                _log.warning(
                    "batch_variant_failed_validation",
                    variant=letter,
                    title_violations=title_violations,
                    tag_violations=tag_violations,
                )
                raise BatchGenerationError(f"variant {letter} failed validation")

            result[letter] = {"title": title, "tags": tags}
        return result

    @staticmethod
    def _check_cross_variant_overlap(validated: dict) -> None:
        """Soft rule: warn (never raise) when two variants share too many tags.

        Uses the shared ``validate_variant_divergence`` so the batch path and the
        approval screen agree on the threshold (guide §14).
        """
        ok, violations = validate_variant_divergence(
            {letter: data["tags"] for letter, data in validated.items()}
        )
        if not ok:
            _log.warning("batch_variant_high_overlap", violations=violations)
