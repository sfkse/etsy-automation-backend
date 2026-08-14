"""
Tests for DescriptionGenerator's originality retry escalation.

The generator retries up to 3 times when a draft is too similar to the existing
corpus. A mild miss (0.85–0.95) keeps the cheap soft reminder; a catastrophic
miss (>0.95) or the last shapeable attempt escalates to the aggressive
DESCRIPTION_RETRY_PROMPT. These tests pin that two-tier behaviour, plus
OriginalityChecker.find_similar_phrases which feeds the aggressive prompt.

asyncio_mode = "auto" (see pyproject.toml) → async tests need no decorator.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

from src.domain.validators import OriginalityChecker
from src.modules.content.description_generator import DescriptionGenerator

# A neutral, cliché-free draft of valid length (150–220 words). Reused as the
# LLM output on every attempt — the tests drive behaviour through the mocked
# originality check, not the draft content.
_VALID_DRAFT = " ".join(["handmade"] * 170)


def _angle() -> SimpleNamespace:
    return SimpleNamespace(
        label="A",
        description_voice="warm, personal",
        description_instructions="Lead with the recipient's moment.",
    )


def _product() -> MagicMock:
    product = MagicMock()
    product.carrier_pillar = "cross"
    product.material = "Gold Plated"
    product.color = "Gold"
    product.shape = "Round"
    product.style = "Dainty"
    product.has_stone = False
    product.stone_type = None
    product.occasion = "Birthday"
    product.recipient = "Mom"
    product.size_info = "18 inch"
    product.selling_price = 29.99
    return product


def _research_builder() -> MagicMock:
    research = MagicMock()
    ctx = MagicMock()
    ctx.has_data = False
    ctx.cliches_to_avoid = []
    research.build_for_product.return_value = ctx
    return research


def _generator(*, check_returns, similar_phrases=None) -> DescriptionGenerator:
    """Build a generator whose LLM always returns a valid draft and whose
    originality checker yields the supplied ``check()`` results in order."""
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=_VALID_DRAFT)

    originality = MagicMock()
    originality.check_cliches.return_value = []
    originality.check.side_effect = list(check_returns)
    originality.find_similar_phrases.return_value = similar_phrases or [
        "Discover the timeless charm of this piece",
    ]

    return DescriptionGenerator(llm, originality, _research_builder())


def _prompts_sent(gen: DescriptionGenerator) -> list[str]:
    return [c.kwargs["prompt"] for c in gen.llm.complete.call_args_list]


# ─── Happy path ───────────────────────────────────────────────────────────────


async def test_happy_path_returns_first_draft():
    gen = _generator(check_returns=[(True, 0.1)])
    with patch("src.modules.content.description_generator._log") as mock_log:
        result = await gen.generate_for_angle(_product(), _angle(), "Paired Title", ["tag one", "tag two"])

    assert result == _VALID_DRAFT
    gen.llm.complete.assert_awaited_once()
    events = [c.args[0] for c in mock_log.warning.call_args_list]
    assert "description_catastrophically_similar_escalating" not in events


# ─── Catastrophic miss → aggressive escalation ────────────────────────────────


async def test_catastrophic_similarity_escalates():
    # Attempt 1: catastrophically similar → escalate. Attempt 2: passes.
    gen = _generator(check_returns=[(False, 0.97), (True, 0.1)])
    with patch("src.modules.content.description_generator._log") as mock_log:
        result = await gen.generate_for_angle(_product(), _angle(), "Paired Title", ["tag one", "tag two"])

    assert result == _VALID_DRAFT
    assert gen.llm.complete.await_count == 2

    events = [c.args[0] for c in mock_log.warning.call_args_list]
    assert "description_catastrophically_similar_escalating" in events

    prompts = _prompts_sent(gen)
    # Attempt 1 is the base dynamic template; attempt 2 is the aggressive rewrite.
    assert "REJECTED DRAFT" not in prompts[0]
    assert "REJECTED DRAFT" in prompts[1]
    assert "COMMON PATTERNS DETECTED" in prompts[1]
    gen.originality.find_similar_phrases.assert_called_once()


# ─── Mild miss → soft reminder, no escalation ─────────────────────────────────


async def test_mild_miss_uses_soft_reminder():
    # Attempt 1: mild miss (0.88) on a non-final attempt → soft reminder only.
    gen = _generator(check_returns=[(False, 0.88), (True, 0.1)])
    with patch("src.modules.content.description_generator._log") as mock_log:
        result = await gen.generate_for_angle(_product(), _angle(), "Paired Title", ["tag one", "tag two"])

    assert result == _VALID_DRAFT
    assert gen.llm.complete.await_count == 2

    events = [c.args[0] for c in mock_log.warning.call_args_list]
    assert "description_catastrophically_similar_escalating" not in events

    prompts = _prompts_sent(gen)
    # Soft path: base template retained + appended reminder, NOT the rewrite prompt.
    assert "REJECTED DRAFT" not in prompts[1]
    assert "significantly different phrasing" in prompts[1]
    gen.originality.find_similar_phrases.assert_not_called()


async def test_final_attempt_escalates_even_on_mild_miss():
    # attempt 1 mild → soft, attempt 2 mild (last shapeable) → aggressive.
    gen = _generator(check_returns=[(False, 0.88), (False, 0.88), (True, 0.1)])
    result = await gen.generate_for_angle(_product(), _angle(), "Paired Title", ["tag one"])

    assert result == _VALID_DRAFT
    prompts = _prompts_sent(gen)
    assert "REJECTED DRAFT" not in prompts[1]   # attempt 2 prompt built after attempt-1 soft miss
    assert "REJECTED DRAFT" in prompts[2]        # attempt 3 prompt escalated after attempt-2 miss


# ─── find_similar_phrases ─────────────────────────────────────────────────────


@patch("src.domain.validators.SentenceTransformer")
def test_find_similar_phrases_returns_topk(mock_st_cls):
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [
        ("First existing sentence here. Second corpus line follows.",),
    ]
    mock_model = MagicMock()
    mock_st_cls.return_value = mock_model
    # encode called for draft sentences then corpus sentences (2 each).
    mock_model.encode.side_effect = [
        np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),   # draft sentences
        np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),   # corpus sentences
    ]

    checker = OriginalityChecker(session=session)
    result = checker.find_similar_phrases(
        "A draft sentence to compare. Another draft line here.", top_k=5
    )

    assert len(result) <= 5
    assert "First existing sentence here" in result
    assert "Second corpus line follows" in result


@patch("src.domain.validators.SentenceTransformer")
def test_find_similar_phrases_empty_corpus(mock_st_cls):
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    mock_model = MagicMock()
    mock_st_cls.return_value = mock_model

    checker = OriginalityChecker(session=session)
    assert checker.find_similar_phrases("Some draft sentence to compare.") == []
    mock_model.encode.assert_not_called()
