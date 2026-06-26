"""
Tests for business-rule validators (title, tags, description).
Validator logic is implemented in Phase 2; placeholder tests live here.
"""
import pytest
from src.config import business_rules as br


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
