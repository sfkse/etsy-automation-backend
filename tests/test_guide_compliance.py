"""
Regression tests built from a real audit of generated listings against the
training guide (``etsy_urun_yukleme_rehber.md``).

Four ankh/Ra necklace products were generated with 3 variants each; scoring them
by hand against the guide surfaced rules the validators did not yet encode. Each
fixture below is verbatim output from that batch, so these tests pin the exact
failures that shipped — and, just as importantly, pin the rules that were already
being met so they do not regress into false positives.
"""
from __future__ import annotations

import pytest

from src.config import business_rules as br
from src.domain.validators import (
    normalize_tags,
    validate_material_coherence,
    validate_tags,
    validate_title,
    validate_variant_divergence,
)
from src.modules.content.title_generator import _pad_to_band


# ─── Audited output (verbatim) ────────────────────────────────────────────────

P1_A_TITLE = (
    "Spiritual Ankh Cross Jewelry, Sterling Silver Egyptian Key of Life "
    "Necklace, Minimalist Birthstone Pendant Necklace"
)
P1_A_TAGS = [
    "Gold", "Sterling Silver", "Dainty", "Personalized", "925 Silver",
    "14K Gold Plated", "cross necklace", "protection necklace", "cross pendant",
    "religious necklace", "egyptian jewelry", "ankh necklace", "ankh pendant",
]

P1_C_TITLE = (
    "Spiritual Ankh Cross Jewelry Gift for Her, Sterling Silver Egyptian "
    "Necklace, Birthstone Pendant Necklace for Women"
)
P1_C_TAGS = [
    "gifts for mom", "birthday gift", "christmas gift", "gift for daughter",
    "bridesmaid gift", "cross necklace", "protection necklace", "cross pendant",
    "dainty", "minimalist", "religious necklace", "egyptian jewelry",
    "ankh necklace",
]

P2_A_TITLE = (
    "Egyptian Ankh Necklace Gold Plated Sterling Silver, Key of Life Pendant "
    "Necklace, Minimalist Cross Necklace for Women"
)

P4_A_TAGS = [
    "gift for her", "birthstone ankh", "minimalist necklace", "handmade gift",
    "dainty necklace", "personalized", "necklace for woman", "birthday gift",
    "pendant necklace", "layering necklace", "protection jewelry",
    "religious jewelry", "key of life",
]
P4_C_TAGS = [
    "gift for her", "birthstone ankh", "minimalist necklace", "handmade gift",
    "dainty necklace", "necklace for woman", "birthday gift",
    "gold ankh necklace", "layering necklace", "sterling silver ankh",
    "protection jewelry", "key of life", "religious jewelry",
]


def _violations(title: str, target_keyword: str | None = None) -> list[str]:
    return validate_title(title, target_keyword=target_keyword)[1]


# ─── The bug that caused the short titles ─────────────────────────────────────


class TestBirthstoneIsNotForbiddenStone:
    """"Stone" is banned; "Birthstone" is a carrier pillar. A substring scan
    conflated them, rejecting every birthstone title and pushing generation into
    its unvalidated fallback."""

    @pytest.mark.parametrize("title", [P1_A_TITLE, P1_C_TITLE])
    def test_birthstone_titles_do_not_trip_forbidden_stone(self, title: str) -> None:
        assert not any("Stone" in v and "Forbidden" in v for v in _violations(title))

    def test_bare_stone_still_forbidden(self) -> None:
        title = (
            "Gold Plated Stone Cross Pendant Necklace, Dainty Religious Jewelry, "
            "Christian Charm Necklace, Minimalist Cross Chain"
        )
        assert any("Forbidden keyword 'Stone'" in v for v in _violations(title))

    def test_birthstone_pillar_is_in_the_exception_list(self) -> None:
        assert "Birthstone" in br.FORBIDDEN_TITLE_KEYWORD_EXCEPTIONS
        assert "birthstone" in br.CARRIER_PILLARS


# ─── Title rules ──────────────────────────────────────────────────────────────


class TestTitleLengthBand:
    AUDITED = [P1_A_TITLE, P1_C_TITLE, P2_A_TITLE]

    @pytest.mark.parametrize("title", AUDITED)
    def test_audited_titles_were_below_the_guide_band(self, title: str) -> None:
        assert len(title) < br.TITLE_MIN_LENGTH

    @pytest.mark.parametrize("title", AUDITED)
    def test_padding_lifts_them_into_band(self, title: str) -> None:
        padded = _pad_to_band(title)
        assert br.TITLE_MIN_LENGTH <= len(padded) <= br.TITLE_MAX_LENGTH

    def test_padding_never_exceeds_the_cap(self) -> None:
        at_cap = "X" * br.TITLE_MAX_LENGTH
        assert _pad_to_band(at_cap) == at_cap

    def test_padding_does_not_reuse_words_already_present(self) -> None:
        # "Jewelry Gift" and "Gift for Her" would each add a second "Gift".
        padded = _pad_to_band(P1_C_TITLE)
        assert padded.lower().count("gift") <= 1


class TestNicheZonePurity:
    """Guide §2: the first 60 chars define the niche, not broad gift terms."""

    def test_broad_gift_phrase_in_niche_zone_is_flagged(self) -> None:
        assert any("niche zone" in v for v in _violations(P1_C_TITLE))

    def test_clean_niche_zone_passes(self) -> None:
        assert not any("niche zone" in v for v in _violations(P1_A_TITLE))


class TestWordRepetition:
    def test_necklace_three_times_is_flagged(self) -> None:
        assert any("repeated 3+" in v for v in _violations(P2_A_TITLE))

    def test_necklace_twice_is_fine(self) -> None:
        assert not any("repeated 3+" in v for v in _violations(P1_A_TITLE))


class TestRulesThatAlreadyPassed:
    """These were clean in the audit — guard against new false positives."""

    @pytest.mark.parametrize("title", [P1_A_TITLE, P1_C_TITLE, P2_A_TITLE])
    def test_pendant_never_bare(self, title: str) -> None:
        assert not any("Pendant" in v and "without" in v for v in _violations(title))

    @pytest.mark.parametrize("title", [P1_A_TITLE, P1_C_TITLE, P2_A_TITLE])
    def test_no_taboo_keywords(self, title: str) -> None:
        assert not any("Forbidden keyword" in v for v in _violations(title))


# ─── Tag rules ────────────────────────────────────────────────────────────────


class TestBroadTagCeiling:
    """Guide §3: at most 1-2 broad tags — more inflates ad spend."""

    def test_six_broad_tags_flagged(self) -> None:
        violations = validate_tags(P1_A_TAGS, P1_A_TITLE)[1]
        assert any("broad tags" in v for v in violations)

    def test_seven_broad_gift_tags_flagged(self) -> None:
        violations = validate_tags(P1_C_TAGS, P1_C_TITLE)[1]
        assert any("broad tags" in v for v in violations)

    def test_two_broad_tags_allowed(self) -> None:
        tags = ["Gifts for Mom", "Birthday Gift"] + [
            f"Ankh Pendant {i:02d}" for i in range(11)
        ]
        assert not any("broad tags" in v for v in validate_tags(tags)[1])


class TestLongTailFloor:
    def test_single_word_tags_counted_against_floor(self) -> None:
        violations = validate_tags(P1_A_TAGS, P1_A_TITLE)[1]
        assert any("long-tail niche tags" in v for v in violations)

    def test_thirteen_long_tail_tags_pass(self) -> None:
        tags = [f"Ankh Pendant {i:02d}" for i in range(13)]
        assert not any("long-tail" in v for v in validate_tags(tags)[1])


class TestTitleOverlapIsPhraseBased:
    """The old check compared against title.split(), so only single-word tags
    were caught — multi-word ones silently wasted a slot."""

    def test_multi_word_tag_in_title_is_flagged(self) -> None:
        violations = validate_tags(P1_A_TAGS, P1_A_TITLE)[1]
        assert any("Sterling Silver" in v and "wasted slot" in v for v in violations)

    def test_tag_absent_from_title_is_not_flagged(self) -> None:
        violations = validate_tags(P1_A_TAGS, P1_A_TITLE)[1]
        assert not any("ankh necklace" in v and "wasted slot" in v for v in violations)


class TestNormalizeTags:
    def test_lowercase_tags_are_title_cased(self) -> None:
        cleaned, _ = normalize_tags(["cross necklace", "egyptian jewelry"])
        assert cleaned == ["Cross Necklace", "Egyptian Jewelry"]

    def test_literals_keep_their_casing(self) -> None:
        cleaned, _ = normalize_tags(["925 silver", "14k gold plated", "cz pave"])
        assert cleaned == ["925 Silver", "14K Gold Plated", "CZ Pave"]

    def test_title_duplicates_are_dropped(self) -> None:
        cleaned, notes = normalize_tags(P1_A_TAGS, P1_A_TITLE)
        assert "Sterling Silver" not in cleaned
        assert any("wasted slot" in n for n in notes)

    def test_case_insensitive_duplicates_collapse(self) -> None:
        cleaned, _ = normalize_tags(["Ankh Necklace", "ankh necklace"])
        assert cleaned == ["Ankh Necklace"]

    def test_output_is_reported_in_notes(self) -> None:
        _, notes = normalize_tags(["cross necklace"])
        assert any("Re-cased" in n for n in notes)


# ─── Material coherence (guide §15) ───────────────────────────────────────────


class TestMaterialCoherence:
    def test_silver_title_with_gold_tags_is_flagged(self) -> None:
        ok, violations = validate_material_coherence(P1_A_TITLE, P1_A_TAGS)
        assert not ok
        assert any("gold" in v for v in violations)

    def test_consistent_silver_listing_passes(self) -> None:
        tags = ["Ankh Necklace", "925 Silver", "Egyptian Jewelry"]
        assert validate_material_coherence(P1_A_TITLE, tags)[0]

    def test_title_with_no_material_claim_is_not_judged(self) -> None:
        assert validate_material_coherence("Ankh Pendant Necklace", ["14K Gold"])[0]


# ─── Cross-variant divergence (guide §14) ─────────────────────────────────────


class TestVariantDivergence:
    def test_near_identical_variants_flagged(self) -> None:
        ok, violations = validate_variant_divergence({"A": P4_A_TAGS, "C": P4_C_TAGS})
        assert not ok
        assert any("A/C" in v for v in violations)

    def test_distinct_variants_pass(self) -> None:
        a = [f"Ankh Pendant {i:02d}" for i in range(13)]
        b = [f"Ra Symbol Charm {i:02d}" for i in range(13)]
        assert validate_variant_divergence({"A": a, "B": b})[0]
