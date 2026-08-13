"""
Business-rule validators for titles, tags, and descriptions.
"""
from __future__ import annotations

import re
from collections import Counter

from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

from src.config.business_rules import (
    CLICHE_DESCRIPTION_PHRASES,
    DESCRIPTION_MAX_SIMILARITY,
    DESCRIPTION_MAX_WORDS,
    DESCRIPTION_MIN_WORDS,
    FORBIDDEN_TAG_PHRASES,
    FORBIDDEN_TITLE_KEYWORDS,
    PENDANT_MUST_BE,
    SOLID_GOLD_PLATED_CONFLICT,
    TAG_COUNT,
    TAG_MAX_LENGTH,
    TITLE_FIRST_NICHE_CHARS,
    TITLE_MAX_LENGTH,
    TITLE_MIN_LENGTH,
)
from src.db.models import Product

# Stop words excluded from the repeated-word check
_STOP_WORDS: frozenset[str] = frozenset(
    {"and", "for", "the", "with", "a", "an", "of", "in", "to", "by", "at"}
)


# ─── Title ────────────────────────────────────────────────────────────────────


def validate_title(
    title: str, target_keyword: str | None = None
) -> tuple[bool, list[str]]:
    """
    Validate *title* against all Section 1.1 business rules.

    ``target_keyword``, when supplied, must have at least one of its
    significant words present within the first ``TITLE_FIRST_NICHE_CHARS``
    characters (the guide's "niche description zone"). Omitted when the
    caller has no product-specific keyword to check against.

    Returns ``(is_valid, violations)`` where *violations* is a list of
    human-readable error messages (empty when valid).
    """
    violations: list[str] = []

    # 1. Length
    length = len(title)
    if not (TITLE_MIN_LENGTH <= length <= TITLE_MAX_LENGTH):
        violations.append(
            f"Length {length} not in [{TITLE_MIN_LENGTH}, {TITLE_MAX_LENGTH}]"
        )

    # 2. Forbidden keywords (case-insensitive)
    title_lower = title.lower()
    for keyword in FORBIDDEN_TITLE_KEYWORDS:
        if keyword.lower() in title_lower:
            violations.append(f"Forbidden keyword '{keyword}' in title")

    # 3. "Pendant" must appear as "Pendant Necklace" at least once. Descriptive
    #    uses ("Cross Pendant", "Ankh Pendant") are fine as long as the canonical
    #    "Pendant Necklace" appears somewhere in the title.
    if "pendant" in title_lower and "pendant necklace" not in title_lower:
        violations.append(
            f"'Pendant' used without '{PENDANT_MUST_BE}'; include '{PENDANT_MUST_BE}' at least once"
        )

    # 4. "Solid Gold" and "Gold Plated" cannot coexist
    conflict_lower = [phrase.lower() for phrase in SOLID_GOLD_PLATED_CONFLICT]
    if all(phrase in title_lower for phrase in conflict_lower):
        violations.append(
            f"'{SOLID_GOLD_PLATED_CONFLICT[0]}' and "
            f"'{SOLID_GOLD_PLATED_CONFLICT[1]}' cannot coexist in the same title"
        )

    # 5. Excessive word repetition (keyword stuffing). Etsy titles legitimately
    #    repeat the product noun ("Necklace") across comma-separated phrases, so a
    #    word is only flagged at 3+ occurrences. Punctuation is stripped first so
    #    "Necklace," and "Necklace" count as the same word (the old check compared
    #    raw whitespace-split tokens, so it missed/false-flagged on punctuation).
    tokens = (re.sub(r"[^\w]", "", w).lower() for w in title.split())
    counts = Counter(w for w in tokens if w and w not in _STOP_WORDS)
    overused = sorted(w for w, n in counts.items() if n >= 3)
    if overused:
        violations.append(f"Words repeated 3+ times: {overused}")

    # 6. Niche keyword must appear in the first TITLE_FIRST_NICHE_CHARS chars
    if target_keyword:
        niche_zone = title_lower[:TITLE_FIRST_NICHE_CHARS]
        keyword_words = [
            w for w in target_keyword.lower().split() if w not in _STOP_WORDS
        ]
        if keyword_words and not any(w in niche_zone for w in keyword_words):
            violations.append(
                f"Target keyword '{target_keyword}' not found in first "
                f"{TITLE_FIRST_NICHE_CHARS} characters"
            )

    return (len(violations) == 0, violations)


# ─── Tags ─────────────────────────────────────────────────────────────────────


def validate_tags(
    tags: list[str], title: str = ""
) -> tuple[bool, list[str]]:
    """
    Validate a 13-tag list against Section 1.2 business rules.

    Returns ``(is_valid, violations)``.
    The title overlap check is treated as a violation (wasted slot).
    """
    violations: list[str] = []

    # 1. Exactly 13 tags
    if len(tags) != TAG_COUNT:
        violations.append(f"Tag count {len(tags)} != {TAG_COUNT}")

    # 2. Each tag within max length
    for tag in tags:
        if len(tag) > TAG_MAX_LENGTH:
            violations.append(
                f"Tag '{tag}' is {len(tag)} chars (max {TAG_MAX_LENGTH})"
            )

    # 3. Forbidden phrases
    for tag in tags:
        for phrase in FORBIDDEN_TAG_PHRASES:
            if phrase.lower() in tag.lower():
                violations.append(
                    f"Tag '{tag}' contains forbidden phrase '{phrase}'"
                )

    # 4. Duplicate tags (case-insensitive)
    lower_tags = [t.lower() for t in tags]
    if len(lower_tags) != len(set(lower_tags)):
        violations.append("Duplicate tags detected")

    # 5. Tag already present as a single word in the title (wasted slot)
    if title:
        title_words = {w.lower() for w in title.split()}
        for tag in tags:
            if tag.lower() in title_words:
                violations.append(
                    f"Tag '{tag}' is a single word already in title (wasted slot)"
                )

    return (len(violations) == 0, violations)


# ─── Description ──────────────────────────────────────────────────────────────


def validate_description(description: str) -> tuple[bool, list[str]]:
    """
    Validate *description* against Section 1.3 business rules:
    word count (150-220) and absence of cliché phrases.

    Returns ``(is_valid, violations)``.
    """
    violations: list[str] = []

    word_count = len(description.split())
    if not (DESCRIPTION_MIN_WORDS <= word_count <= DESCRIPTION_MAX_WORDS):
        violations.append(
            f"Word count {word_count} not in [{DESCRIPTION_MIN_WORDS}, {DESCRIPTION_MAX_WORDS}]"
        )

    desc_lower = description.lower()
    for phrase in CLICHE_DESCRIPTION_PHRASES:
        if phrase.lower() in desc_lower:
            violations.append(f"Cliché phrase found: '{phrase}'")

    return (len(violations) == 0, violations)


class OriginalityChecker:
    """
    Embedding-based originality checker for product descriptions.

    The model is lazy-loaded on first call to ``check()`` so that
    ``check_cliches()`` is usable without network access.
    """

    _MODEL_NAME = "all-MiniLM-L6-v2"

    def __init__(self, session) -> None:
        self.session = session
        self._model: SentenceTransformer | None = None

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            self._model = SentenceTransformer(self._MODEL_NAME)
        return self._model

    def check(
        self,
        new_description: str,
        threshold: float = DESCRIPTION_MAX_SIMILARITY,
    ) -> tuple[bool, float]:
        """
        Compare *new_description* against all existing final descriptions.

        Returns ``(is_original, max_similarity)``.
        A description is considered original when ``max_similarity < threshold``.
        """
        new_emb = self.model.encode(new_description)

        existing_rows = (
            self.session.query(Product.final_description)
            .filter(Product.final_description.isnot(None))
            .all()
        )

        if not existing_rows:
            return (True, 0.0)

        existing_texts = [row[0] for row in existing_rows]
        existing_embs = self.model.encode(existing_texts)
        similarities = cosine_similarity([new_emb], existing_embs)[0]

        max_sim = float(similarities.max())
        is_original = max_sim < threshold

        return (is_original, max_sim)

    def check_cliches(self, description: str) -> list[str]:
        """Return any forbidden cliché phrases found in *description*."""
        found: list[str] = []
        desc_lower = description.lower()
        for phrase in CLICHE_DESCRIPTION_PHRASES:
            if phrase.lower() in desc_lower:
                found.append(phrase)
        return found
