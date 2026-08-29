"""
Business-rule validators for titles, tags, and descriptions.
"""
from __future__ import annotations

import re
from collections import Counter

from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

from src.config.business_rules import (
    BROAD_TAG_TERMS,
    CLICHE_DESCRIPTION_PHRASES,
    DESCRIPTION_MAX_SIMILARITY,
    DESCRIPTION_MAX_WORDS,
    DESCRIPTION_MIN_WORDS,
    FORBIDDEN_TAG_PHRASES,
    FORBIDDEN_TITLE_KEYWORDS,
    FORBIDDEN_TITLE_KEYWORD_EXCEPTIONS,
    MATERIAL_CLAIM_TERMS,
    NICHE_ZONE_FORBIDDEN_TERMS,
    PENDANT_MUST_BE,
    SOLID_GOLD_PLATED_CONFLICT,
    TAG_COUNT,
    TAG_MAX_BROAD,
    TAG_MAX_LENGTH,
    TAG_MIN_NICHE,
    TITLE_FIRST_NICHE_CHARS,
    TITLE_MAX_LENGTH,
    TITLE_MIN_LENGTH,
    VARIANT_MAX_TAG_OVERLAP,
)
from src.db.models import Product

# Stop words excluded from the repeated-word check
_STOP_WORDS: frozenset[str] = frozenset(
    {"and", "for", "the", "with", "a", "an", "of", "in", "to", "by", "at"}
)

# Tokens that must keep their exact casing when a tag is title-cased.
_TAG_CASE_LITERALS: dict[str, str] = {
    "cz": "CZ",
    "14k": "14K",
    "18k": "18K",
    "22k": "22K",
    "925": "925",
    "usa": "USA",
}

# Short function words stay lowercase unless they lead the tag — the guide's own
# examples are "Gifts for Mom" and "Key of Life", not "Gifts For Mom".
_TAG_LOWERCASE_WORDS: frozenset[str] = frozenset(
    {"for", "of", "the", "with", "a", "an", "and", "in", "to", "by", "at"}
)


def _strip_keyword_exceptions(text: str) -> str:
    """Blank out legitimate compounds ("Birthstone") so the forbidden-keyword
    scan below cannot match the banned word hiding inside them."""
    for exception in FORBIDDEN_TITLE_KEYWORD_EXCEPTIONS:
        text = re.sub(rf"\b{re.escape(exception)}\b", " ", text, flags=re.IGNORECASE)
    return text


def _case_tag_word(word: str, is_first: bool) -> str:
    """Title-case one tag word, honouring literals ("14K") and keeping function
    words lowercase unless they lead the tag."""
    lower = word.lower()
    if lower in _TAG_CASE_LITERALS:
        return _TAG_CASE_LITERALS[lower]
    if not is_first and lower in _TAG_LOWERCASE_WORDS:
        return lower
    return word[:1].upper() + word[1:]


def _contains_phrase(haystack: str, phrase: str) -> bool:
    """Whole-phrase, case-insensitive containment with word boundaries, so
    "gold" does not match "Gold Plated" and "Stone" does not match "Birthstone"."""
    return re.search(rf"\b{re.escape(phrase)}\b", haystack, re.IGNORECASE) is not None

# Minimum characters for a sentence fragment to be worth embedding — drops
# stray "." splits and trivial fragments from similarity comparison.
_MIN_SENTENCE_CHARS: int = 12
_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+")


def _split_sentences(text: str) -> list[str]:
    """Split *text* into trimmed sentences, dropping blanks and short fragments."""
    if not text:
        return []
    return [
        s.strip()
        for s in _SENTENCE_SPLIT_RE.split(text)
        if len(s.strip()) >= _MIN_SENTENCE_CHARS
    ]


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

    # 2. Forbidden keywords. Matched on word boundaries against a copy with the
    #    legitimate compounds removed — a plain substring scan flagged "Stone"
    #    inside "Birthstone", invalidating every birthstone title and pushing
    #    generation into its unvalidated fallback path.
    title_lower = title.lower()
    scannable = _strip_keyword_exceptions(title)
    for keyword in FORBIDDEN_TITLE_KEYWORDS:
        if _contains_phrase(scannable, keyword):
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

    # 7. The niche zone must describe the product, not chase broad terms. Guide
    #    §2: "Burada büyük tekler değil, niş tanımlama olmalı."
    niche_zone = title[:TITLE_FIRST_NICHE_CHARS]
    intruders = sorted(
        term for term in NICHE_ZONE_FORBIDDEN_TERMS
        if _contains_phrase(niche_zone, term)
    )
    if intruders:
        violations.append(
            f"Broad terms {intruders} inside the first "
            f"{TITLE_FIRST_NICHE_CHARS} chars (niche zone)"
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

    # 5. Tag phrase already in the title (wasted slot). Compares the whole phrase
    #    against the whole title — the old title.split() form only caught
    #    single-word tags, so "Sterling Silver" and "Key of Life" slipped through.
    if title:
        for tag in tags:
            if _contains_phrase(title, tag):
                violations.append(
                    f"Tag '{tag}' already appears in the title (wasted slot)"
                )

    # 6. Broad-tag ceiling (guide §3: 1-2 "büyük tek" only — more inflates ads)
    broad = [t for t in tags if t.strip().lower() in BROAD_TAG_TERMS]
    if len(broad) > TAG_MAX_BROAD:
        violations.append(
            f"{len(broad)} broad tags (max {TAG_MAX_BROAD}): {sorted(broad)}"
        )

    # 7. Long-tail floor (guide §3: 8-9 niche tags; "long-tail tag'ler altın").
    #    Single-word tags rank poorly and are never long-tail.
    niche = [
        t for t in tags
        if len(t.split()) > 1 and t.strip().lower() not in BROAD_TAG_TERMS
    ]
    if len(niche) < TAG_MIN_NICHE:
        single_word = sorted(t for t in tags if len(t.split()) == 1)
        detail = f"; single-word tags: {single_word}" if single_word else ""
        violations.append(
            f"Only {len(niche)} long-tail niche tags (min {TAG_MIN_NICHE}){detail}"
        )

    return (len(violations) == 0, violations)


def normalize_tags(tags: list[str], title: str = "") -> tuple[list[str], list[str]]:
    """
    Auto-fix the mechanical tag problems — the ones with exactly one right answer.

    * Title-case each word (guide §3: "Her kelimenin ilk harfi büyük"), keeping
      literals like ``925``, ``14K`` and ``CZ`` intact.
    * Drop tags whose phrase already appears in *title* (a wasted slot).
    * Drop case-insensitive duplicates, preserving first-seen order.

    Returns ``(cleaned_tags, notes)``. Callers are expected to backfill the freed
    slots from their candidate pool; judgment calls (broad-tag overage, material
    contradictions) are deliberately left to ``validate_tags`` instead.
    """
    cleaned: list[str] = []
    notes: list[str] = []
    seen: set[str] = set()

    for tag in tags:
        tag = tag.strip()
        if not tag:
            continue

        cased = " ".join(
            _case_tag_word(w, is_first=(i == 0))
            for i, w in enumerate(tag.split())
        )
        if cased != tag:
            notes.append(f"Re-cased '{tag}' -> '{cased}'")

        key = cased.lower()
        if key in seen:
            notes.append(f"Dropped duplicate tag '{cased}'")
            continue
        if title and _contains_phrase(title, cased):
            notes.append(f"Dropped '{cased}' — already in title (wasted slot)")
            continue

        seen.add(key)
        cleaned.append(cased)

    return cleaned, notes


def validate_material_coherence(title: str, tags: list[str]) -> tuple[bool, list[str]]:
    """
    Guide §15: one material story per listing.

    A title claiming sterling silver while the tags advertise 14K gold plating
    sends Etsy contradictory attribute signals. Returns ``(is_valid, violations)``.
    """
    title_claims = {
        family for family, terms in MATERIAL_CLAIM_TERMS.items()
        if any(_contains_phrase(title, term) for term in terms)
    }
    if not title_claims:
        return (True, [])

    violations: list[str] = []
    for family, terms in MATERIAL_CLAIM_TERMS.items():
        if family in title_claims:
            continue
        offenders = sorted(
            {tag for tag in tags for term in terms if _contains_phrase(tag, term)}
        )
        if offenders:
            violations.append(
                f"Title claims {sorted(title_claims)} but tags claim "
                f"'{family}': {offenders}"
            )

    return (len(violations) == 0, violations)


def validate_variant_divergence(
    variant_tags: dict[str, list[str]]
) -> tuple[bool, list[str]]:
    """
    Guide §14: the three variants exist to cast three different keyword nets.

    Flags any pair whose tag sets overlap beyond ``VARIANT_MAX_TAG_OVERLAP``
    (Jaccard). ``variant_tags`` maps variant id -> its 13 tags.
    """
    violations: list[str] = []
    ids = sorted(variant_tags)

    for i, left in enumerate(ids):
        for right in ids[i + 1:]:
            a = {t.strip().lower() for t in variant_tags[left]}
            b = {t.strip().lower() for t in variant_tags[right]}
            union = a | b
            if not union:
                continue
            shared = a & b
            overlap = len(shared) / len(union)
            if overlap > VARIANT_MAX_TAG_OVERLAP:
                violations.append(
                    f"Variants {left}/{right} share {len(shared)} tags "
                    f"(overlap {overlap:.0%}, max {VARIANT_MAX_TAG_OVERLAP:.0%})"
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

    def find_similar_phrases(self, text: str, top_k: int = 5) -> list[str]:
        """Top-K corpus sentences that *text* most closely echoes.

        For each sentence in *text*, find its nearest neighbour among all
        sentences in the existing final-description corpus, then return the
        distinct corpus sentences with the highest similarity. Used by the
        description retry prompt to tell the LLM exactly what phrasing to avoid.
        Returns an empty list when there is no corpus or no usable sentences.
        """
        text_sentences = _split_sentences(text)
        if not text_sentences:
            return []

        existing_rows = (
            self.session.query(Product.final_description)
            .filter(Product.final_description.isnot(None))
            .all()
        )
        corpus_sentences: list[str] = []
        for row in existing_rows:
            corpus_sentences.extend(_split_sentences(row[0]))
        if not corpus_sentences:
            return []

        text_embs = self.model.encode(text_sentences)
        corpus_embs = self.model.encode(corpus_sentences)
        similarities = cosine_similarity(text_embs, corpus_embs)

        # Best corpus match per draft sentence, keeping the highest score seen
        # for each distinct corpus sentence.
        best_by_phrase: dict[str, float] = {}
        for row_sims in similarities:
            j = int(row_sims.argmax())
            phrase = corpus_sentences[j]
            score = float(row_sims[j])
            if score > best_by_phrase.get(phrase, -1.0):
                best_by_phrase[phrase] = score

        ranked = sorted(best_by_phrase.items(), key=lambda kv: kv[1], reverse=True)
        return [phrase for phrase, _ in ranked[:top_k]]
