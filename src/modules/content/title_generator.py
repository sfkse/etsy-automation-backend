"""
Phase 6.2 — TitleGenerator

Generates ONE title per strategic angle. Internally produces 3 candidates,
validates them against business rules, then picks the best for the angle.
Retries once with a relaxed prompt if all candidates fail validation.
"""
from __future__ import annotations

import structlog

from src.config.business_rules import TITLE_MAX_LENGTH, TITLE_MIN_LENGTH
from src.config.prompts import JEWELRY_ADJECTIVE_LADDER, TITLE_GENERATION_PROMPT
from src.db.models import Product
from src.domain.validators import validate_title
from src.modules.llm.angles import VariantAngle
from src.modules.research.context_builder import ResearchContextBuilder
from src.modules.content.keyword_pool import KeywordPoolManager
from src.utils.llm_client import LLMClient

_log = structlog.get_logger(__name__)


def _extract_features(product: Product) -> str:
    parts = []
    if product.shape:
        parts.append(product.shape)
    if product.style:
        parts.append(product.style)
    if product.has_stone and product.stone_type:
        parts.append(f"{product.stone_type} stone")
    if product.color:
        parts.append(product.color)
    return ", ".join(parts) if parts else "standard"


def _angle_alignment_score(title: str, angle: VariantAngle) -> float:
    """
    Rough heuristic for how well a title reflects the requested angle.
    Higher is better. Used to pick among valid candidates.
    """
    title_lower = title.lower()
    score = 0.0

    if angle.keyword_bias == "gift_phrases":
        gift_words = ["gift", "for mom", "for daughter", "for wife", "for her",
                      "for sister", "for grandma", "for girlfriend"]
        score += sum(2.0 for w in gift_words if w in title_lower)

    elif angle.keyword_bias == "underused":
        # Reward for NOT starting with the most generic term
        # (a rough proxy — proper check happens via research brief keywords)
        generic_starters = ["gold necklace", "silver necklace", "cross necklace"]
        if not any(title_lower.startswith(g) for g in generic_starters):
            score += 3.0

    elif angle.keyword_bias == "competitor_common":
        common_phrases = ["dainty", "minimalist", "gold", "sterling silver", "pendant necklace"]
        score += sum(1.0 for p in common_phrases if p in title_lower)

    elif angle.keyword_bias == "premium":
        premium_words = ["solid gold", "14k", "fine jewelry", "luxury"]
        score += sum(2.0 for w in premium_words if w in title_lower)

    return score


def _too_similar_to_competitors(title: str) -> bool:
    """Placeholder — a full competitor-similarity check would query the DB.
    Currently just checks that the title isn't suspiciously short."""
    return len(title) < 100


class TitleGenerator:
    """Generate a single title per strategic angle for a product."""

    def __init__(
        self,
        llm_client: LLMClient,
        keyword_pool: KeywordPoolManager,
        research_builder: ResearchContextBuilder,
    ) -> None:
        self.llm = llm_client
        self.pool = keyword_pool
        self.research = research_builder

    async def generate_for_angle(self, product: Product, angle: VariantAngle) -> str:
        """
        Generate ONE title for the given strategic angle.
        Internally produces 3 candidates, validates them, picks the best.
        Retries with a tighter prompt if all fail validation.
        """
        prompt = self._build_prompt(product, angle)
        response = await self.llm.complete(prompt, max_tokens=800)
        candidates = self._parse_titles(response)

        valid = []
        for title in candidates:
            ok, violations = validate_title(title, target_keyword=product.target_keyword)
            if ok and not _too_similar_to_competitors(title):
                valid.append(title)
            else:
                _log.debug(
                    "title_candidate_rejected",
                    angle=angle.label,
                    title=title[:60],
                    violations=violations,
                )

        if not valid:
            _log.warning("title_all_candidates_invalid", angle=angle.label, retrying=True)
            return await self._retry_with_relaxation(product, angle)

        best = max(valid, key=lambda t: _angle_alignment_score(t, angle))
        _log.info("title_selected", angle=angle.label, title=best[:60])
        return best

    def _build_prompt(self, product: Product, angle: VariantAngle) -> str:
        keywords = self.pool.get_for_pillar(product.carrier_pillar)
        research_ctx = self.research.build_for_product(product)
        return TITLE_GENERATION_PROMPT.format(
            product_type=product.carrier_pillar.replace("_", " ").title(),
            material=product.material or "Gold Plated",
            features=_extract_features(product),
            target_keyword=product.target_keyword or "(none specified — use your best niche keyword judgement)",
            adjective_ladder=JEWELRY_ADJECTIVE_LADDER,
            keyword_pool=", ".join(keywords) if keywords else "(no pool keywords — use product type)",
            research_brief=research_ctx.format_for_prompt(),
            angle_label=angle.label,
            angle_instructions=angle.prompt_instructions,
        )

    @staticmethod
    def _parse_titles(response: str) -> list[str]:
        """Extract up to 3 title lines from the LLM response."""
        lines = [line.strip() for line in response.strip().splitlines() if line.strip()]
        # Remove any accidental numbering like "1." or "1)"
        cleaned = []
        for line in lines:
            if line and line[0].isdigit() and len(line) > 2 and line[1] in ".):":
                line = line[2:].strip()
            cleaned.append(line)
        return cleaned[:3]

    async def _retry_with_relaxation(self, product: Product, angle: VariantAngle) -> str:
        """
        Retry once with a more explicit length-focused prompt.
        Returns the best candidate even if it fails validation (logged as warning).
        """
        keywords = self.pool.get_for_pillar(product.carrier_pillar)
        research_ctx = self.research.build_for_product(product)

        relaxed_prompt = TITLE_GENERATION_PROMPT.format(
            product_type=product.carrier_pillar.replace("_", " ").title(),
            material=product.material or "Gold Plated",
            features=_extract_features(product),
            target_keyword=product.target_keyword or "(none specified — use your best niche keyword judgement)",
            adjective_ladder=JEWELRY_ADJECTIVE_LADDER,
            keyword_pool=", ".join(keywords) if keywords else "(no pool keywords)",
            research_brief=research_ctx.format_for_prompt(),
            angle_label=angle.label,
            angle_instructions=(
                angle.prompt_instructions
                + f"\n\nCRITICAL: Previous attempt produced titles outside {TITLE_MIN_LENGTH}-{TITLE_MAX_LENGTH} chars. "
                "Count characters on each title before writing it. Use padding phrases like "
                f"'for Women', 'Jewelry Gift', 'Layering Necklace' to reach {TITLE_MIN_LENGTH}-{TITLE_MAX_LENGTH} chars."
            ),
        )

        response = await self.llm.complete(relaxed_prompt, max_tokens=800)
        candidates = self._parse_titles(response)

        valid = [
            t for t in candidates
            if validate_title(t, target_keyword=product.target_keyword)[0]
        ]
        if valid:
            return max(valid, key=lambda t: _angle_alignment_score(t, angle))

        # Last resort: return first candidate and log warning
        fallback = candidates[0] if candidates else f"{product.carrier_pillar} necklace gold pendant jewelry gift for her layering minimalist"
        _log.error(
            "title_retry_also_failed",
            angle=angle.label,
            fallback=fallback[:60],
        )
        return fallback
