"""
Tests for business-rule validators (title, tags, description).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from src.config import business_rules as br
from src.domain.carrier_pillar import CarrierPillar, get_default_attributes, get_section_name
from src.domain.validators import OriginalityChecker, validate_description, validate_tags, validate_title


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
        title = _make_title(120)
        valid, violations = validate_title(title)
        assert valid
        assert violations == []

    def test_exact_max_length_passes(self) -> None:
        title = _make_title(140)
        valid, violations = validate_title(title)
        assert valid
        assert violations == []

    def test_one_below_min_fails(self) -> None:
        title = _make_title(119)
        valid, violations = validate_title(title)
        assert not valid
        assert any("119" in v for v in violations)

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
        assert br.TITLE_MIN_LENGTH == 120
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


# ─── Description Validator ─────────────────────────────────────────────────────


def _make_description(word_count: int, include_cliche: str = "") -> str:
    """Build a description of exactly *word_count* words, optionally prepending a cliché."""
    if include_cliche:
        filler_count = max(0, word_count - len(include_cliche.split()))
        return include_cliche + " " + " ".join(["word"] * filler_count)
    return " ".join(["word"] * word_count)


class TestDescriptionValidator:
    def test_exact_min_words_passes(self) -> None:
        desc = _make_description(150)
        valid, violations = validate_description(desc)
        assert valid
        assert violations == []

    def test_exact_max_words_passes(self) -> None:
        desc = _make_description(220)
        valid, violations = validate_description(desc)
        assert valid
        assert violations == []

    def test_below_min_words_fails(self) -> None:
        desc = _make_description(149)
        valid, violations = validate_description(desc)
        assert not valid
        assert any("149" in v for v in violations)

    def test_above_max_words_fails(self) -> None:
        desc = _make_description(221)
        valid, violations = validate_description(desc)
        assert not valid
        assert any("221" in v for v in violations)

    def test_cliche_phrase_in_description_fails(self) -> None:
        desc = _make_description(155, include_cliche="Elevate your style")
        valid, violations = validate_description(desc)
        assert not valid
        assert any("Elevate your style" in v for v in violations)

    def test_no_cliche_clean_description_passes(self) -> None:
        desc = _make_description(180)
        valid, violations = validate_description(desc)
        assert valid
        assert violations == []

    def test_multiple_cliches_all_reported(self) -> None:
        desc = "Elevate your style with this ring. Treat yourself today. " + " ".join(["word"] * 148)
        valid, violations = validate_description(desc)
        assert not valid
        assert any("Elevate your style" in v for v in violations)
        assert any("Treat yourself" in v for v in violations)

    def test_word_count_and_cliche_both_violations(self) -> None:
        # Too short AND has a cliché
        desc = "Elevate your style with this ring."
        valid, violations = validate_description(desc)
        assert not valid
        assert len(violations) >= 2


# ─── Title Additional Rules ────────────────────────────────────────────────────


class TestTitleAdditionalRules:
    def test_floral_keyword_fails(self) -> None:
        padding = "X" * (140 - len("Floral "))
        title = "Floral " + padding
        valid, violations = validate_title(title)
        assert not valid
        assert any("Floral" in v for v in violations)

    def test_title_separator_constant_is_comma_space(self) -> None:
        assert br.TITLE_SEPARATOR == ", "

    def test_title_first_niche_chars_constant(self) -> None:
        assert br.TITLE_FIRST_NICHE_CHARS == 60

    def test_forbidden_keywords_list_contains_expected(self) -> None:
        expected = {"Stone", "Mother's Day Gift", "Diamond", "Floral"}
        assert expected.issubset(set(br.FORBIDDEN_TITLE_KEYWORDS))


# ─── Noun Variation Ladder (title prompt wiring) ──────────────────────────────


class TestNounVariationLadder:
    """The noun-variation vocabulary must be defined and wired into the title
    prompt so the LLM varies the head noun across the 3 variants."""

    def test_ladder_lists_all_four_families(self) -> None:
        from src.config.prompts import NOUN_VARIATION_LADDER
        for family in ("Necklace family:", "Bracelet family:",
                       "Earring family:", "Ring family:"):
            assert family in NOUN_VARIATION_LADDER

    def test_ladder_respects_pendant_necklace_rule(self) -> None:
        # The vocabulary must never suggest bare "Pendant"; validators.py flags it.
        from src.config.prompts import NOUN_VARIATION_LADDER
        assert "Pendant Necklace" in NOUN_VARIATION_LADDER

    def test_prompt_has_noun_ladder(self) -> None:
        # The noun ladder is baked into the cached static prefix (prompt caching
        # split), no longer a {noun_ladder} placeholder in a single template.
        from src.config.prompts import TITLE_STATIC_PREFIX
        assert "NOUN VARIATION VOCABULARY" in TITLE_STATIC_PREFIX

    def test_prompt_has_strict_rule_8(self) -> None:
        from src.config.prompts import TITLE_STATIC_PREFIX
        assert "noun variations from the same family" in TITLE_STATIC_PREFIX

    def test_prompt_formats_with_noun_ladder(self) -> None:
        # Proves both TitleGenerator .format() call sites render cleanly — a
        # missing kwarg would raise KeyError here — and that the noun ladder is
        # carried by the cached static prefix.
        from src.config.prompts import (
            TITLE_DYNAMIC_TEMPLATE,
            TITLE_STATIC_PREFIX,
        )
        rendered = TITLE_DYNAMIC_TEMPLATE.format(
            product_type="Necklace",
            material="Gold",
            features="cross",
            target_keyword="cross necklace",
            keyword_pool="cross necklace, dainty cross",
            research_brief="(no research)",
            angle_label="competitor_common",
            angle_instructions="Lean into common phrases.",
        )
        assert "STRATEGIC ANGLE" in rendered
        assert "NOUN VARIATION VOCABULARY" in TITLE_STATIC_PREFIX


# ─── Image Business Rules ──────────────────────────────────────────────────────


def _make_images(total: int, real_count: int) -> list[MagicMock]:
    """Return a list of mock ProductImage objects."""
    images = []
    for i in range(total):
        img = MagicMock()
        img.is_real = i < real_count
        img.rank = i + 1
        images.append(img)
    return images


class TestImageBusinessRules:
    def test_min_images_per_listing_constant(self) -> None:
        assert br.MIN_IMAGES_PER_LISTING == 8

    def test_max_real_images_required_constant(self) -> None:
        assert br.MAX_REAL_IMAGES_REQUIRED == 3

    def test_real_images_rule_passes(self) -> None:
        images = _make_images(total=8, real_count=3)
        real_count = sum(1 for img in images if img.is_real)
        assert real_count >= br.MAX_REAL_IMAGES_REQUIRED
        assert len(images) >= br.MIN_IMAGES_PER_LISTING

    def test_real_images_rule_fails_when_fewer_than_3_real(self) -> None:
        images = _make_images(total=8, real_count=2)
        real_count = sum(1 for img in images if img.is_real)
        assert real_count < br.MAX_REAL_IMAGES_REQUIRED

    def test_total_images_rule_fails_when_fewer_than_8(self) -> None:
        images = _make_images(total=7, real_count=3)
        assert len(images) < br.MIN_IMAGES_PER_LISTING


# ─── Quantity Rules ────────────────────────────────────────────────────────────


class TestQuantityRules:
    def test_quantity_forbidden_is_1(self) -> None:
        assert br.QUANTITY_FORBIDDEN == 1

    def test_quantity_confident_is_999(self) -> None:
        assert br.QUANTITY_CONFIDENT == 999

    def test_quantity_test_range(self) -> None:
        assert br.QUANTITY_TEST_MIN == 10
        assert br.QUANTITY_TEST_MAX == 300
        assert br.QUANTITY_TEST_MIN < br.QUANTITY_TEST_MAX

    def test_quantity_forbidden_never_zero(self) -> None:
        # The forbidden value is exactly 1 — never allow quantity to hit 0 or 1
        assert br.QUANTITY_FORBIDDEN > 0

    def test_quantity_confident_above_test_max(self) -> None:
        assert br.QUANTITY_CONFIDENT > br.QUANTITY_TEST_MAX


# ─── SKU Generation ────────────────────────────────────────────────────────────


class TestSKUGeneration:
    def _mock_session(self, last_sku: str | None) -> MagicMock:
        session = MagicMock()
        if last_sku is None:
            session.query.return_value.order_by.return_value.first.return_value = None
        else:
            session.query.return_value.order_by.return_value.first.return_value = (last_sku,)
        return session

    def test_first_sku_returns_taki_0001(self) -> None:
        from src.modules.input import generate_sku
        session = self._mock_session(None)
        assert generate_sku(session) == "TAKI-0001"

    def test_next_sku_increments(self) -> None:
        from src.modules.input import generate_sku
        session = self._mock_session("TAKI-0042")
        assert generate_sku(session) == "TAKI-0043"

    def test_sku_format(self) -> None:
        from src.modules.input import generate_sku
        session = self._mock_session("TAKI-0099")
        sku = generate_sku(session)
        assert re.fullmatch(r"TAKI-\d{4}", sku), f"Unexpected SKU format: {sku}"

    def test_sku_zero_padded_to_four_digits(self) -> None:
        from src.modules.input import generate_sku
        session = self._mock_session("TAKI-0009")
        assert generate_sku(session) == "TAKI-0010"

    def test_sku_large_number(self) -> None:
        from src.modules.input import generate_sku
        session = self._mock_session("TAKI-9998")
        assert generate_sku(session) == "TAKI-9999"


# ─── Approval Service ─────────────────────────────────────────────────────────


class TestApprovalService:
    def _make_product(self, variants: list[dict] | None = None) -> MagicMock:
        product = MagicMock()
        product.sku = "TAKI-0001"
        product.id = 1
        product.generated_variants = variants
        return product

    def test_get_variant_by_id_found(self) -> None:
        from src.modules.approval.service import get_variant_by_id
        product = self._make_product([{"id": "A", "title": "My Title"}])
        variant = get_variant_by_id(product, "A")
        assert variant is not None
        assert variant["title"] == "My Title"

    def test_get_variant_by_id_not_found(self) -> None:
        from src.modules.approval.service import get_variant_by_id
        product = self._make_product([{"id": "A", "title": "My Title"}])
        assert get_variant_by_id(product, "Z") is None

    def test_get_variant_by_id_no_variants(self) -> None:
        from src.modules.approval.service import get_variant_by_id
        product = self._make_product(None)
        assert get_variant_by_id(product, "A") is None

    @patch("src.modules.approval.service.upsert_product_row")
    def test_update_variant_field_title_updates(self, _mock_upsert) -> None:
        from src.modules.approval.service import update_variant_field
        product = self._make_product([{"id": "A", "title": "Old Title", "tags": [], "description": ""}])
        session = MagicMock()
        result = update_variant_field(session, product, "A", "title", "New Title")
        assert result is True
        updated_variant = next(v for v in product.generated_variants if v["id"] == "A")
        assert updated_variant["title"] == "New Title"

    @patch("src.modules.approval.service.upsert_product_row")
    def test_update_variant_field_unknown_field_rejected(self, _mock_upsert) -> None:
        from src.modules.approval.service import update_variant_field
        product = self._make_product([{"id": "A", "title": "Title"}])
        session = MagicMock()
        result = update_variant_field(session, product, "A", "nonexistent_field", "value")
        assert result is False

    @patch("src.modules.approval.service.upsert_product_row")
    def test_approve_variant_sets_final_fields(self, _mock_upsert) -> None:
        from src.modules.approval.service import approve_variant
        from src.db.models import ProductStatus
        product = self._make_product([{
            "id": "B",
            "title": "Best Title Here",
            "tags": ["tag1", "tag2"],
            "description": "A fine description.",
        }])
        session = MagicMock()
        result = approve_variant(session, product, "B")
        assert result is True
        assert product.final_title == "Best Title Here"
        assert product.final_tags == ["tag1", "tag2"]
        assert product.final_description == "A fine description."
        assert product.selected_variant_id == "B"

    @patch("src.modules.approval.service.upsert_product_row")
    def test_approve_variant_advances_status_to_approved(self, _mock_upsert) -> None:
        from src.modules.approval.service import approve_variant
        from src.db.models import ProductStatus
        product = self._make_product([{"id": "A", "title": "T", "tags": [], "description": "D"}])
        session = MagicMock()
        approve_variant(session, product, "A")
        assert product.status == ProductStatus.APPROVED.value

    def test_approve_variant_returns_false_when_variant_missing(self) -> None:
        from src.modules.approval.service import approve_variant
        product = self._make_product([{"id": "A", "title": "T", "tags": [], "description": "D"}])
        session = MagicMock()
        result = approve_variant(session, product, "Z")
        assert result is False


# ─── Validate Field (Approval Service) ───────────────────────────────────────


class TestValidateField:
    def test_validate_field_title_ok(self) -> None:
        from src.modules.approval.service import validate_field
        title = "X" * 138  # valid length, no forbidden words
        ok, violations = validate_field("title", title)
        assert ok
        assert violations == []

    def test_validate_field_title_fails_too_short(self) -> None:
        from src.modules.approval.service import validate_field
        ok, violations = validate_field("title", "Short")
        assert not ok
        assert len(violations) > 0

    def test_validate_field_tags_ok(self) -> None:
        from src.modules.approval.service import validate_field
        tags = [f"tag{i:02d}" for i in range(13)]
        ok, violations = validate_field("tags", tags)
        assert ok
        assert violations == []

    def test_validate_field_description_word_count_fail(self) -> None:
        from src.modules.approval.service import validate_field
        desc = "too short"
        ok, violations = validate_field("description", desc)
        assert not ok
        assert any("Word count" in v for v in violations)

    def test_validate_field_unknown_field_passes(self) -> None:
        from src.modules.approval.service import validate_field
        ok, violations = validate_field("unknown_field", "anything")
        assert ok
        assert violations == []


# ─── Rate Limiter ─────────────────────────────────────────────────────────────


class TestRateLimiter:
    def test_daily_counter_remaining_starts_full(self) -> None:
        from src.modules.etsy.rate_limiter import DailyCounter
        counter = DailyCounter()
        assert counter.remaining_today == DailyCounter.DAILY_LIMIT

    @pytest.mark.asyncio
    async def test_daily_counter_decrements_on_increment(self) -> None:
        from src.modules.etsy.rate_limiter import DailyCounter
        counter = DailyCounter()
        initial = counter.remaining_today
        await counter.increment()
        assert counter.remaining_today == initial - 1

    @pytest.mark.asyncio
    async def test_daily_counter_multiple_increments(self) -> None:
        from src.modules.etsy.rate_limiter import DailyCounter
        counter = DailyCounter()
        for _ in range(5):
            await counter.increment()
        assert counter.remaining_today == DailyCounter.DAILY_LIMIT - 5

    def test_token_bucket_starts_full(self) -> None:
        from src.modules.etsy.rate_limiter import TokenBucket
        bucket = TokenBucket(capacity=10)
        assert bucket._tokens == 10.0


# ─── Publisher Utilities ──────────────────────────────────────────────────────


class TestPublisherUtils:
    def test_is_new_shop_true_for_recent(self) -> None:
        from src.modules.etsy.publisher import _is_new_shop
        recent = (date.today() - timedelta(days=30)).isoformat()
        assert _is_new_shop(recent) is True

    def test_is_new_shop_false_for_old(self) -> None:
        from src.modules.etsy.publisher import _is_new_shop
        old = (date.today() - timedelta(days=200)).isoformat()
        assert _is_new_shop(old) is False

    def test_is_new_shop_empty_string_returns_false(self) -> None:
        from src.modules.etsy.publisher import _is_new_shop
        assert _is_new_shop("") is False

    def test_is_new_shop_invalid_date_returns_false(self) -> None:
        from src.modules.etsy.publisher import _is_new_shop
        assert _is_new_shop("not-a-date") is False

    def test_is_new_shop_boundary_182_days(self) -> None:
        from src.modules.etsy.publisher import _is_new_shop
        boundary = (date.today() - timedelta(days=182)).isoformat()
        assert _is_new_shop(boundary) is True

    def test_is_new_shop_boundary_183_days(self) -> None:
        from src.modules.etsy.publisher import _is_new_shop
        boundary = (date.today() - timedelta(days=183)).isoformat()
        assert _is_new_shop(boundary) is False
