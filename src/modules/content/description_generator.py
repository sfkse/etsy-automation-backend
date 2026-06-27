"""
Phase 6.4 — DescriptionGenerator (Per Variant Angle)

Generates ONE description per strategic angle, internally-consistent with the
variant's title and tags. Retries up to 3 times if cliché or originality
checks fail. Returns the last draft with logged warnings on total failure.
"""
from __future__ import annotations

import structlog

from src.config.business_rules import CLICHE_DESCRIPTION_PHRASES, DESCRIPTION_MIN_WORDS, DESCRIPTION_MAX_WORDS
from src.config.prompts import DESCRIPTION_GENERATION_PROMPT
from src.db.models import Product
from src.domain.validators import OriginalityChecker
from src.modules.llm.angles import VariantAngle
from src.modules.research.context_builder import ResearchContextBuilder
from src.utils.llm_client import LLMClient

_log = structlog.get_logger(__name__)

_MAX_ATTEMPTS = 3


def _product_summary(product: Product) -> str:
    parts = [
        f"Type: {product.carrier_pillar.replace('_', ' ').title()}",
        f"Material: {product.material or 'Gold Plated'}",
    ]
    if product.color:
        parts.append(f"Color: {product.color}")
    if product.shape:
        parts.append(f"Shape: {product.shape}")
    if product.style:
        parts.append(f"Style: {product.style}")
    if product.has_stone and product.stone_type:
        parts.append(f"Stone: {product.stone_type}")
    if product.occasion:
        parts.append(f"Occasion: {product.occasion}")
    if product.recipient:
        parts.append(f"Recipient: {product.recipient}")
    if product.size_info:
        parts.append(f"Size/Length: {product.size_info}")
    if product.selling_price:
        parts.append(f"Price: ${float(product.selling_price):.2f}")
    return "\n".join(f"- {p}" for p in parts)


def _word_count(text: str) -> int:
    return len(text.split())


def _check_word_count(description: str) -> tuple[bool, int]:
    count = _word_count(description)
    return (DESCRIPTION_MIN_WORDS <= count <= DESCRIPTION_MAX_WORDS), count


class DescriptionGenerator:
    """Generate one description per strategic angle, with quality retry loop."""

    def __init__(
        self,
        llm_client: LLMClient,
        originality_checker: OriginalityChecker,
        research_builder: ResearchContextBuilder,
    ) -> None:
        self.llm = llm_client
        self.originality = originality_checker
        self.research = research_builder

    async def generate_for_angle(
        self,
        product: Product,
        angle: VariantAngle,
        paired_title: str,
        paired_tags: list[str],
    ) -> str:
        """
        Generate ONE description for the given angle.
        The title and tags from the SAME variant are passed so the description
        echoes the same vocabulary — keeping the variant internally consistent.
        Up to 3 attempts; returns the last draft if all checks fail.
        """
        research_ctx = self.research.build_for_carrier_pillar(product.carrier_pillar)
        all_cliches = list(dict.fromkeys(
            CLICHE_DESCRIPTION_PHRASES + (research_ctx.cliches_to_avoid if research_ctx.has_data else [])
        ))

        prompt = DESCRIPTION_GENERATION_PROMPT.format(
            product_summary=_product_summary(product),
            voice=angle.description_voice,
            paired_title=paired_title,
            paired_tags=", ".join(paired_tags),
            forbidden_cliches=", ".join(f'"{c}"' for c in all_cliches),
            research_brief=research_ctx.format_for_prompt() if research_ctx.has_data else "",
            angle_label=angle.label,
            angle_instructions=angle.description_instructions,
        )

        draft = ""
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            response = await self.llm.complete(prompt, max_tokens=700)
            draft = self._parse_description(response)

            length_ok, word_count = _check_word_count(draft)
            if not length_ok:
                _log.warning(
                    "description_wrong_length",
                    attempt=attempt,
                    angle=angle.label,
                    word_count=word_count,
                    expected=f"{DESCRIPTION_MIN_WORDS}-{DESCRIPTION_MAX_WORDS}",
                )
                prompt = self._add_length_reminder(prompt, word_count)
                continue

            found_cliches = self.originality.check_cliches(draft)
            if found_cliches:
                _log.warning(
                    "description_cliches_found",
                    attempt=attempt,
                    angle=angle.label,
                    cliches=found_cliches,
                )
                prompt = self._add_cliche_reminder(prompt, found_cliches)
                continue

            is_original, similarity = self.originality.check(draft)
            if not is_original:
                _log.warning(
                    "description_not_original",
                    attempt=attempt,
                    angle=angle.label,
                    similarity=f"{similarity:.2f}",
                )
                prompt = self._add_originality_reminder(prompt, similarity)
                continue

            _log.info(
                "description_accepted",
                angle=angle.label,
                attempt=attempt,
                word_count=word_count,
            )
            return draft

        _log.error(
            "description_all_attempts_failed",
            angle=angle.label,
            word_count=_word_count(draft),
        )
        return draft

    @staticmethod
    def _parse_description(response: str) -> str:
        return response.strip()

    @staticmethod
    def _add_length_reminder(prompt: str, actual_count: int) -> str:
        return prompt + (
            f"\n\nCRITICAL: Previous attempt was {actual_count} words. "
            f"Target is {DESCRIPTION_MIN_WORDS}-{DESCRIPTION_MAX_WORDS} words. "
            "Count words carefully before submitting."
        )

    @staticmethod
    def _add_cliche_reminder(prompt: str, found: list[str]) -> str:
        return prompt + (
            f"\n\nCRITICAL: Previous attempt contained these forbidden clichés: "
            f"{', '.join(repr(c) for c in found)}. Rewrite without them."
        )

    @staticmethod
    def _add_originality_reminder(prompt: str, similarity: float) -> str:
        return prompt + (
            f"\n\nCRITICAL: Previous attempt was {similarity:.0%} similar to an existing "
            "product description in our store. Use significantly different phrasing, "
            "structure, and specific details."
        )
