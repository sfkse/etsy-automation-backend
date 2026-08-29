"""
Phase 6.2 — TitleGenerator

Generates ONE title per strategic angle. Internally produces 3 candidates,
validates them against business rules, then picks the best for the angle.
Retries once with a relaxed prompt if all candidates fail validation.
"""
from __future__ import annotations

import re
from collections import Counter

import structlog

from src.config.business_rules import (
    TITLE_MAX_LENGTH,
    TITLE_MIN_LENGTH,
    TITLE_PADDING_PHRASES,
    TITLE_SEPARATOR,
)
from src.config.prompts import (
    TITLE_DYNAMIC_TEMPLATE,
    TITLE_STATIC_PREFIX,
)
from src.db.models import Product
from src.domain.validators import validate_title
from src.modules.llm.angles import VariantAngle
from src.modules.research.context_builder import ResearchContextBuilder
from src.modules.content.keyword_pool import KeywordPoolManager
from src.utils.llm_client import LLMClient

_log = structlog.get_logger(__name__)

# Mirrors validators._STOP_WORDS — padding phrases like "for Women" must not be
# rejected just because the title already contains "for".
_PAD_STOP_WORDS: frozenset[str] = frozenset(
    {"and", "for", "the", "with", "a", "an", "of", "in", "to", "by", "at"}
)


def _extract_features(product: Product) -> str:
    parts = []
    if product.shape:
        parts.append(product.shape)
    if product.style:
        parts.append(product.style)
    if product.has_stone and product.stone_type:
        # The type already names the stone ("Birthstone", "Cubic Zirconia"), so
        # appending "stone" produced "Birthstone stone" — and FORBIDDEN_TITLE_KEYWORDS
        # bans the bare word "Stone" in titles ("use CZ or Pave"). Harmless while
        # nothing set has_stone; the listing-builder flow now does.
        parts.append(product.stone_type)
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


def _significant_words(text: str) -> list[str]:
    return [
        cleaned
        for w in text.split()
        if (cleaned := re.sub(r"[^\w]", "", w).lower())
        and cleaned not in _PAD_STOP_WORDS
    ]


def _pad_to_band(title: str) -> str:
    """
    Lift a short title into the ``TITLE_MIN_LENGTH``-``TITLE_MAX_LENGTH`` band by
    appending approved phrases, so the model is never asked to count characters.

    Each round picks the *best-fitting* eligible phrase — the longest one that
    still lands under the cap — rather than walking the list in order, which is
    what lets a single pass close gaps of very different sizes. A phrase is
    ineligible if it would push any word to three occurrences (the threshold
    ``validate_title`` flags) or overflow the cap.

    Returns the title unchanged when it is already in band or cannot be padded;
    the caller still validates, so padding is never trusted blindly.
    """
    title = title.strip().rstrip(",")
    if len(title) >= TITLE_MIN_LENGTH:
        return title

    counts = Counter(_significant_words(title))
    unused = list(TITLE_PADDING_PHRASES)

    while len(title) < TITLE_MIN_LENGTH:
        best: str | None = None
        best_words: list[str] = []
        best_lands_in_band = False

        for phrase in unused:
            result_len = len(title) + len(TITLE_SEPARATOR) + len(phrase)
            if result_len > TITLE_MAX_LENGTH:
                continue
            words = _significant_words(phrase)
            # Adding this phrase must not take any word to 3 occurrences.
            if any(counts[w] + n >= 3 for w, n in Counter(words).items()):
                continue

            # Prefer a phrase that finishes the job outright. Picking purely by
            # length strands titles just below the floor: the biggest fitting
            # phrase can leave a gap too small for any remaining phrase to fill.
            lands_in_band = result_len >= TITLE_MIN_LENGTH
            if best is None or (lands_in_band, len(phrase)) > (
                best_lands_in_band, len(best)
            ):
                best, best_words, best_lands_in_band = phrase, words, lands_in_band

        if best is None:
            break

        title = f"{title}{TITLE_SEPARATOR}{best}"
        counts.update(best_words)
        unused.remove(best)

    return title


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
        response = await self.llm.complete(
            prompt=prompt, cached_prefix=TITLE_STATIC_PREFIX, max_tokens=800
        )
        candidates = [_pad_to_band(t) for t in self._parse_titles(response)]

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
        return TITLE_DYNAMIC_TEMPLATE.format(
            product_type=product.carrier_pillar.replace("_", " ").title(),
            material=product.material or "Gold Plated",
            features=_extract_features(product),
            target_keyword=product.target_keyword or "(none specified — use your best niche keyword judgement)",
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

        relaxed_prompt = TITLE_DYNAMIC_TEMPLATE.format(
            product_type=product.carrier_pillar.replace("_", " ").title(),
            material=product.material or "Gold Plated",
            features=_extract_features(product),
            target_keyword=product.target_keyword or "(none specified — use your best niche keyword judgement)",
            keyword_pool=", ".join(keywords) if keywords else "(no pool keywords)",
            research_brief=research_ctx.format_for_prompt(),
            angle_label=angle.label,
            angle_instructions=(
                angle.prompt_instructions
                + f"\n\nCRITICAL: Previous attempt produced titles outside {TITLE_MIN_LENGTH}-{TITLE_MAX_LENGTH} chars. "
                "Count characters on each title before writing it. Use padding phrases like "
                + ", ".join(f"'{p}'" for p in TITLE_PADDING_PHRASES[:3])
                + f" to reach {TITLE_MIN_LENGTH}-{TITLE_MAX_LENGTH} chars."
            ),
        )

        response = await self.llm.complete(
            prompt=relaxed_prompt, cached_prefix=TITLE_STATIC_PREFIX, max_tokens=800
        )
        candidates = [_pad_to_band(t) for t in self._parse_titles(response)]

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
