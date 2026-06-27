"""
Title Pattern Analyzer (Step 3.5)

For each keyword: n-gram frequency, sales-weighted keyword ranking,
underused differentiation candidates, and LLM structural pattern extraction.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from statistics import quantiles

from sqlalchemy.orm import Session

from src.db.models import CompetitorListing

logger = logging.getLogger(__name__)

STOPWORDS = {
    "the", "a", "an", "and", "or", "with", "for", "in", "to", "of",
    "on", "by", "at", "from", "is", "are", "was", "it", "its",
}


async def analyze_titles_for_keyword(
    session: Session,
    keyword: str,
    llm_client,
) -> dict | None:
    """
    Returns analysis dict with:
    - avg_length, length_p5_p50_p95
    - top_unigrams, top_bigrams, top_trigrams
    - sales_weighted_keywords
    - structural_patterns (LLM-extracted)
    - underused_keywords
    """
    listings = (
        session.query(CompetitorListing)
        .filter_by(keyword_searched=keyword)
        .order_by(CompetitorListing.sales_signal_score.desc())
        .limit(50)
        .all()
    )

    if not listings:
        return None

    titles = [l.title for l in listings if l.title]
    if not titles:
        return None

    lengths = [len(t) for t in titles]
    avg_length = sum(lengths) / len(lengths)
    length_percentiles = _percentiles(lengths, [5, 50, 95])

    ngram_freq = _compute_ngram_frequency(titles)
    weighted_freq = _compute_weighted_frequency(listings, ngram_freq)
    underused = _find_underused_keywords(ngram_freq, weighted_freq, threshold=0.30)

    patterns = []
    try:
        patterns = await _llm_extract_patterns(llm_client, keyword, titles[:20])
    except Exception as exc:
        logger.warning("LLM pattern extraction failed for %r: %s", keyword, exc)

    return {
        "keyword": keyword,
        "sample_size": len(titles),
        "avg_length": avg_length,
        "length_p5_p50_p95": length_percentiles,
        "top_unigrams": ngram_freq["1"][:15],
        "top_bigrams": ngram_freq["2"][:10],
        "top_trigrams": ngram_freq["3"][:5],
        "sales_weighted_keywords": weighted_freq[:20],
        "structural_patterns": patterns,
        "underused_keywords": underused,
    }


def _tokenize(text: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[a-z']+", text.lower()) if w not in STOPWORDS and len(w) > 1]


def _compute_ngram_frequency(titles: list[str]) -> dict[str, list[tuple[str, int]]]:
    counters: dict[str, Counter] = {"1": Counter(), "2": Counter(), "3": Counter()}
    for title in titles:
        words = _tokenize(title)
        for w in words:
            counters["1"][w] += 1
        for i in range(len(words) - 1):
            counters["2"][f"{words[i]} {words[i+1]}"] += 1
        for i in range(len(words) - 2):
            counters["3"][f"{words[i]} {words[i+1]} {words[i+2]}"] += 1

    return {
        "1": counters["1"].most_common(),
        "2": counters["2"].most_common(),
        "3": counters["3"].most_common(),
    }


def _compute_weighted_frequency(
    listings: list,
    ngram_freq: dict[str, list[tuple[str, int]]],
) -> list[tuple[str, float]]:
    """Sum sales_signal_score for each listing that contains the word/phrase."""
    word_scores: dict[str, float] = defaultdict(float)
    for listing in listings:
        if not listing.title:
            continue
        score = listing.sales_signal_score or 0.0
        words = set(_tokenize(listing.title))
        for w in words:
            word_scores[w] += score
        # Also score bigrams
        word_list = _tokenize(listing.title)
        for i in range(len(word_list) - 1):
            bigram = f"{word_list[i]} {word_list[i+1]}"
            word_scores[bigram] += score

    return sorted(word_scores.items(), key=lambda x: x[1], reverse=True)


def _find_underused_keywords(
    ngram_freq: dict[str, list[tuple[str, int]]],
    weighted_freq: list[tuple[str, float]],
    threshold: float = 0.30,
    total_listings: int | None = None,
) -> list[str]:
    """
    Keywords that appear in fewer than `threshold` fraction of titles
    but appear in the sales-weighted top-30 (i.e. bestsellers use them
    even though the majority don't).
    """
    # Total occurrences proxy: use the most frequent unigram's count as denominator
    if not ngram_freq["1"]:
        return []
    max_count = ngram_freq["1"][0][1] if ngram_freq["1"] else 1

    low_freq_unigrams = {
        word for word, count in ngram_freq["1"]
        if count / max_count < threshold
    }

    top_weighted_words = {word for word, _ in weighted_freq[:30]}
    underused = list(low_freq_unigrams & top_weighted_words)
    return sorted(underused)[:15]


def _percentiles(values: list[int | float], pcts: list[int]) -> list[float]:
    if len(values) < 2:
        return [float(values[0])] * len(pcts) if values else [0.0] * len(pcts)
    qs = quantiles(values, n=100, method="inclusive")
    return [qs[p - 1] for p in pcts]


async def _llm_extract_patterns(llm_client, keyword: str, titles: list[str]) -> list[dict]:
    titles_numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    prompt = f"""You are analyzing Etsy listing titles for the keyword "{keyword}".
Below are up to 20 actual titles from the top-selling listings.

Extract 3-5 structural patterns you observe. A pattern is a TEMPLATE,
not a literal title. For example:
- "[Material] + [Size adjective] + [Product] + [Religious term] + [Gift phrase]"
- "[Style] + [Product] Necklace, [Synonym] Pendant, [Gift phrase]"

Output JSON only:
{{
  "patterns": [
    {{"pattern": "...", "examples": ["title1", "title2"]}},
    ...
  ]
}}

Titles:
{titles_numbered}"""

    response = await llm_client.complete(prompt)
    data = json.loads(response)
    return data.get("patterns", [])
