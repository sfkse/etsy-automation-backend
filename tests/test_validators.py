"""
Tests for business-rule validators (title, tags, description).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.config import business_rules as br
from src.domain.carrier_pillar import CarrierPillar, get_default_attributes, get_section_name
from src.domain.validators import OriginalityChecker, validate_tags, validate_title


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_title(length: int, filler: str = "X") -> str:
    """Build a syntactically trivial title of exactly *length* characters."""
    return filler * length


def _valid_tags(count: int = 13) -> list[str]:
    """Return *count* unique tags each within 20 chars."""
    return [f"tag{i:02d}" for i in range(count)]


# ─── Carrier Pillar Helpers ────────────────────────────────────────────────────


class TestCarrierPillarHelpers:
    def test_all_pillars_have_section_name(self) -> None:
        for pillar in CarrierPillar:
            name = get_section_name(pillar)
            assert isinstance(name, str) and name, f"No section name for {pillar}"

    def test_section_name_values(self) -> None:
        assert get_section_name(CarrierPillar.CROSS) == "Cross Necklaces"
        assert get_section_name(CarrierPillar.NAME) == "Name Necklaces"
        assert get_section_name(CarrierPillar.BIRTHSTONE) == "Birthstone Jewelry"
        assert get_section_name(CarrierPillar.BIRTH_FLOWER) == "Birth Flower Jewelry"
        assert get_section_name(CarrierPillar.PET) == "Pet Jewelry"
        assert get_section_name(CarrierPillar.PENDANT) == "Pendant Necklaces"

    def test_all_pillars_have_default_attributes(self) -> None:
        for pillar in CarrierPillar:
            attrs = get_default_attributes(pillar)
            assert isinstance(attrs, dict) and attrs, f"No attributes for {pillar}"

    def test_default_attributes_returns_copy(self) -> None:
        attrs = get_default_attributes(CarrierPillar.CROSS)
        attrs["extra"] = "should not persist"
        assert "extra" not in get_default_attributes(CarrierPillar.CROSS)

    def test_cross_default_attributes(self) -> None:
        attrs = get_default_attributes(CarrierPillar.CROSS)
        assert "material" in attrs
        assert "style" in attrs

    def test_birthstone_has_stone_flag(self) -> None:
        attrs = get_default_attributes(CarrierPillar.BIRTHSTONE)
        assert attrs.get("has_stone") is True


# ─── Title Validator ───────────────────────────────────────────────────────────


class TestTitleValidator:
    # ── Length rule ────────────────────────────────────────────────────────────

    def test_exact_min_length_passes(self) -> None:
        title = _make_title(137)
        valid, violations = validate_title(title)
        assert valid
        assert violations == []

    def test_exact_max_length_passes(self) -> None:
        title = _make_title(140)
        valid, violations = validate_title(title)
        assert valid
        assert violations == []

    def test_one_below_min_fails(self) -> None:
        title = _make_title(136)
        valid, violations = validate_title(title)
        assert not valid
        assert any("136" in v for v in violations)

    def test_one_above_max_fails(self) -> None:
        title = _make_title(141)
        valid, violations = validate_title(title)
        assert not valid
        assert any("141" in v for v in violations)

    # ── Forbidden keywords ─────────────────────────────────────────────────────

    def test_stone_keyword_fails(self) -> None:
        title = "Beautiful " + "stone" + " X" * 125
        title = title[:140]
        # Ensure length is in range by rebuilding properly
        base = "X" * 130
        title = "stone " + base  # 136 chars — adjust
        title = ("stone " + "X" * 134)[:140]
        valid, violations = validate_title(title)
        assert not valid
        assert any("Stone" in v or "stone" in v.lower() for v in violations)

    def test_mothers_day_gift_fails(self) -> None:
        phrase = "Mother's Day Gift"
        padding = "X" * (140 - len(phrase))
        title = phrase + padding
        valid, violations = validate_title(title)
        assert not valid
        assert any("Mother" in v for v in violations)

    def test_diamond_keyword_fails(self) -> None:
        padding = "X" * (140 - len("Diamond "))
        title = "Diamond " + padding
        valid, violations = validate_title(title)
        assert not valid
        assert any("Diamond" in v for v in violations)

    # ── Pendant rule ───────────────────────────────────────────────────────────

    def test_pendant_alone_fails(self) -> None:
        padding = "X" * (140 - len("Pendant "))
        title = "Pendant " + padding
        valid, violations = validate_title(title)
        assert not valid
        assert any("Pendant" in v for v in violations)

    def test_pendant_necklace_passes(self) -> None:
        base = "Pendant Necklace "
        title = base + "X" * (140 - len(base))
        valid, violations = validate_title(title)
        # Length passes; Pendant Necklace is allowed — no pendant violation
        assert not any("Pendant" in v and "alone" in v for v in violations)

    # ── Solid Gold + Gold Plated conflict ─────────────────────────────────────

    def test_solid_gold_and_gold_plated_conflict_fails(self) -> None:
        base = "Solid Gold Gold Plated "
        title = (base + "X" * 140)[:140]
        valid, violations = validate_title(title)
        assert not valid
        assert any("Solid Gold" in v or "Gold Plated" in v for v in violations)

    def test_solid_gold_alone_no_conflict(self) -> None:
        base = "Solid Gold "
        title = (base + "X" * 140)[:140]
        valid, violations = validate_title(title)
        assert not any("cannot coexist" in v for v in violations)

    # ── Repeated words ─────────────────────────────────────────────────────────

    def test_repeated_word_fails(self) -> None:
        # "ring ring" repeated non-stop-word
        base = "ring ring "
        title = (base * 20)[:140]
        valid, violations = validate_title(title)
        assert not valid
        assert any("Repeated" in v or "repeated" in v.lower() for v in violations)

    def test_stop_words_not_flagged_as_repeated(self) -> None:
        # Build a title using only stop words (repeated) + filler to fill length
        # "and and and ..." shouldn't trigger duplicate rule
        base = "and " * 35  # 140 chars
        title = base[:140]
        valid, violations = validate_title(title)
        assert not any("Repeated" in v for v in violations)

    def test_multiple_violations_collected(self) -> None:
        # Too short AND contains 'stone'
        title = "stone"
        valid, violations = validate_title(title)
        assert not valid
        assert len(violations) >= 2


# ─── Tag Validator ─────────────────────────────────────────────────────────────


class TestTagValidator:
    # ── Count ──────────────────────────────────────────────────────────────────

    def test_exactly_13_tags_passes(self) -> None:
        valid, violations = validate_tags(_valid_tags(13))
        assert valid
        assert violations == []

    def test_fewer_than_13_fails(self) -> None:
        valid, violations = validate_tags(_valid_tags(12))
        assert not valid
        assert any("12" in v for v in violations)

    def test_more_than_13_fails(self) -> None:
        valid, violations = validate_tags(_valid_tags(14))
        assert not valid
        assert any("14" in v for v in violations)

    # ── Length ─────────────────────────────────────────────────────────────────

    def test_tag_exactly_20_chars_passes(self) -> None:
        tags = _valid_tags(12) + ["A" * 20]
        valid, violations = validate_tags(tags)
        assert valid

    def test_tag_21_chars_fails(self) -> None:
        tags = _valid_tags(12) + ["A" * 21]
        valid, violations = validate_tags(tags)
        assert not valid
        assert any("21" in v or "exceeds" in v.lower() or "chars" in v for v in violations)

    # ── Forbidden phrases ──────────────────────────────────────────────────────

    def test_mothers_day_gift_tag_fails(self) -> None:
        bad_tag = "Mother's Day Gift"[:20]
        tags = _valid_tags(12) + [bad_tag]
        valid, violations = validate_tags(tags)
        assert not valid
        assert any("Mother" in v for v in violations)

    # ── Duplicates ─────────────────────────────────────────────────────────────

    def test_duplicate_tags_fail(self) -> None:
        tags = _valid_tags(12) + ["tag00"]  # tag00 already at index 0
        valid, violations = validate_tags(tags)
        assert not valid
        assert any("Duplicate" in v or "duplicate" in v.lower() for v in violations)

    def test_case_insensitive_duplicate_detection(self) -> None:
        tags = _valid_tags(12) + ["TAG00"]  # duplicate of "tag00" in different case
        valid, violations = validate_tags(tags)
        assert not valid
        assert any("uplicate" in v for v in violations)

    # ── Title overlap ──────────────────────────────────────────────────────────

    def test_tag_in_title_flagged(self) -> None:
        title = "Beautiful Necklace " + "X" * 121
        tags = _valid_tags(12) + ["Necklace"]
        valid, violations = validate_tags(tags, title=title)
        assert not valid
        assert any("Necklace" in v for v in violations)

    def test_multi_word_tag_not_flagged_for_overlap(self) -> None:
        # A multi-word tag can't be a single word in title_words
        title = "Beautiful Necklace " + "X" * 121
        tags = _valid_tags(12) + ["Beautiful Neck"]
        valid, violations = validate_tags(tags, title=title)
        assert not any("Beautiful Neck" in v and "wasted" in v for v in violations)

    def test_no_title_no_overlap_check(self) -> None:
        # Without a title, no overlap violations
        tags = _valid_tags(12) + ["Necklace"]
        valid, violations = validate_tags(tags)
        assert valid


# ─── Originality Checker ───────────────────────────────────────────────────────


class TestOriginalityChecker:
    # ── Cliché detection (no DB needed) ───────────────────────────────────────

    def test_cliche_detected(self) -> None:
        checker = OriginalityChecker(session=MagicMock())
        found = checker.check_cliches("Elevate your style with this piece.")
        assert "Elevate your style" in found

    def test_no_cliche_returns_empty(self) -> None:
        checker = OriginalityChecker(session=MagicMock())
        found = checker.check_cliches("A handmade cross necklace in sterling silver.")
        assert found == []

    def test_multiple_cliches_all_found(self) -> None:
        checker = OriginalityChecker(session=MagicMock())
        text = "Discover the beauty of silver. Treat yourself today."
        found = checker.check_cliches(text)
        assert "Discover the beauty of" in found
        assert "Treat yourself" in found

    def test_cliche_case_insensitive(self) -> None:
        checker = OriginalityChecker(session=MagicMock())
        found = checker.check_cliches("ELEVATE YOUR STYLE with this ring.")
        assert "Elevate your style" in found

    # ── check() with mocked model ─────────────────────────────────────────────

    @patch("src.domain.validators.SentenceTransformer")
    def test_check_no_existing_descriptions_is_original(self, mock_st_cls) -> None:
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = []

        mock_model = MagicMock()
        mock_st_cls.return_value = mock_model
        mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])

        checker = OriginalityChecker(session=session)
        is_original, max_sim = checker.check("Any description here.")
        assert is_original is True
        assert max_sim == 0.0

    @patch("src.domain.validators.SentenceTransformer")
    def test_check_similar_description_rejected(self, mock_st_cls) -> None:
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [
            ("Existing description text.",),
        ]

        mock_model = MagicMock()
        mock_st_cls.return_value = mock_model
        # Return identical embeddings → cosine similarity = 1.0
        vec = np.array([[1.0, 0.0, 0.0]])
        mock_model.encode.side_effect = [vec[0], vec]

        checker = OriginalityChecker(session=session)
        is_original, max_sim = checker.check("Existing description text.")
        assert not is_original
        assert max_sim >= 0.85

    @patch("src.domain.validators.SentenceTransformer")
    def test_check_different_description_accepted(self, mock_st_cls) -> None:
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [
            ("Something completely different.",),
        ]

        mock_model = MagicMock()
        mock_st_cls.return_value = mock_model
        # Orthogonal vectors → cosine similarity = 0.0
        mock_model.encode.side_effect = [
            np.array([1.0, 0.0, 0.0]),
            np.array([[0.0, 1.0, 0.0]]),
        ]

        checker = OriginalityChecker(session=session)
        is_original, max_sim = checker.check("A very different description.")
        assert is_original is True
        assert max_sim < 0.85

    @patch("src.domain.validators.SentenceTransformer")
    def test_check_custom_threshold(self, mock_st_cls) -> None:
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [
            ("Some description.",),
        ]

        mock_model = MagicMock()
        mock_st_cls.return_value = mock_model
        # Similarity ~0.7 — passes default 0.85 but fails strict 0.5
        mock_model.encode.side_effect = [
            np.array([1.0, 0.0]),
            np.array([[0.7, 0.714]]),  # cosine sim ≈ 0.7
        ]

        checker = OriginalityChecker(session=session)
        # With strict threshold of 0.5, this should be rejected
        is_original, _ = checker.check("Some description.", threshold=0.5)
        assert not is_original


# ─── Business Rule Constants (existing tests preserved) ───────────────────────


class TestBusinessRuleConstants:
    def test_title_length_range(self) -> None:
        assert br.TITLE_MIN_LENGTH == 137
        assert br.TITLE_MAX_LENGTH == 140
        assert br.TITLE_MIN_LENGTH < br.TITLE_MAX_LENGTH

    def test_tag_count(self) -> None:
        assert br.TAG_COUNT == 13

    def test_tag_max_length(self) -> None:
        assert br.TAG_MAX_LENGTH == 20

    def test_carrier_pillars_count(self) -> None:
        assert len(br.CARRIER_PILLARS) == 6

    def test_variant_count(self) -> None:
        assert br.VARIANT_COUNT == 3
        assert br.VARIANT_IDS == ["A", "B", "C"]

    def test_renew_hours(self) -> None:
        assert set(br.RENEW_HOURS_TR) == {17, 21, 2, 5}

    def test_quantity_forbidden_is_one(self) -> None:
        assert br.QUANTITY_FORBIDDEN == 1

    def test_forbidden_title_keywords_not_empty(self) -> None:
        assert len(br.FORBIDDEN_TITLE_KEYWORDS) > 0
        assert "Stone" in br.FORBIDDEN_TITLE_KEYWORDS

    def test_cliche_phrases_not_empty(self) -> None:
        assert len(br.CLICHE_DESCRIPTION_PHRASES) > 0

    def test_tag_distribution_covers_all_variants(self) -> None:
        for variant_id in br.VARIANT_IDS:
            assert variant_id in br.TAG_DISTRIBUTION
            dist = br.TAG_DISTRIBUTION[variant_id]
            assert sum(dist.values()) == br.TAG_COUNT
