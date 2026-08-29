"""Tests for stone detection off Layer A's vision attributes.

`ListingBuilder.build` set only `stone_shape` — never `has_stone` or
`stone_type`. Both title (`_extract_features`) and description
(`_product_summary`) gate their stone branch on `has_stone AND stone_type`, so
neither ever fired for an extension-built listing: the word "birthstone" reached
the LLM only when the target keyword happened to contain it.

For REX-936 that meant a listing targeting "baptism gift cross necklace"
generated with no idea the product carries a birthstone — the feature that
justifies pricing above the market average.

The supplier's own spec block cannot supply this (REX-936's `rexven_attributes`
holds only care/color/style/packaging/size_info/chain_style), but Layer A's
vision pass names it outright.
"""
from __future__ import annotations

from src.modules.content.title_generator import _extract_features
from src.modules.listings.orchestrator import _detected_attributes, infer_stone

# The verbatim detected_attributes Layer A produced for analysis #10 (REX-936).
REX_936_DETECTED = {
    "form": "Cross pendant necklace with delicate chain",
    "style": "Minimalist, dainty, contemporary religious",
    "theme": "Christian cross with birthstone accent",
    "material": "Gold-plated brass with blue gemstone center",
    "occasion": "Baptism, confirmation, birthday, Christmas, everyday faith jewelry",
    "recipient": "Women, teens, religious gift recipient, birthstone jewelry lover",
}


def test_rex_936_is_recognised_as_a_birthstone_piece():
    assert infer_stone(REX_936_DETECTED) == (True, "Birthstone")


def test_specific_beats_generic_when_both_appear():
    """REX-936's blob says 'birthstone accent' AND 'gemstone center'. The named
    stone must win, or the listing advertises a generic gemstone."""
    detected = {"theme": "gemstone center", "material": "birthstone accent"}
    assert infer_stone(detected)[1] == "Birthstone"


def test_stoneless_product_stays_stoneless():
    detected = {
        "form": "Plain gold chain necklace",
        "theme": "Minimalist everyday layering",
        "material": "Gold-plated brass",
    }
    assert infer_stone(detected) == (False, None)


def test_stone_shape_alone_proves_a_stone_without_naming_it():
    """The popup's stone_shape field is independent evidence."""
    assert infer_stone(None, "Round") == (True, None)
    assert infer_stone({"theme": "plain cross"}, "Marquise") == (True, None)


def test_no_capture_at_all_is_stoneless():
    assert infer_stone(None) == (False, None)
    assert infer_stone({}) == (False, None)


def test_recipient_text_does_not_trigger_a_stone():
    """'birthstone jewelry lover' describes the buyer, not the product — scanning
    recipient/occasion would mark plain pieces as stone-bearing."""
    detected = {
        "form": "Plain cross necklace",
        "theme": "Christian faith",
        "material": "Gold-plated brass",
        "recipient": "birthstone jewelry lover",
        "occasion": "birthday",
    }
    assert infer_stone(detected) == (False, None)


def test_named_stones_are_mapped():
    assert infer_stone({"material": "freshwater pearl drop"})[1] == "Pearl"
    assert infer_stone({"material": "cubic zirconia pave"})[1] == "Cubic Zirconia"
    assert infer_stone({"theme": "fire opal centre"})[1] == "Opal"


# ---------------------------------------------------------------------------
# Reaching the blob from the analysis the build came from
# ---------------------------------------------------------------------------


class _Candidate:
    def __init__(self, detected):
        self.detected_attributes = detected


class _Analysis:
    def __init__(self, candidates):
        self.candidates = candidates


def test_detected_attributes_skips_candidates_without_the_blob():
    """Only some candidates carry it — Layer C-proposed ones have none — but every
    candidate that does shares the same blob."""
    analysis = _Analysis([_Candidate(None), _Candidate(REX_936_DETECTED)])
    assert _detected_attributes(analysis) == REX_936_DETECTED


def test_detected_attributes_handles_no_analysis():
    """A Build-tab build with no sourcing behind it still has to work."""
    assert _detected_attributes(None) is None
    assert _detected_attributes(_Analysis([])) is None


def test_end_to_end_glue_for_a_cross_targeted_listing():
    """The point of the whole change: a listing whose keyword never says
    'birthstone' still knows the product has one."""
    analysis = _Analysis([_Candidate(REX_936_DETECTED)])
    has_stone, stone_type = infer_stone(_detected_attributes(analysis), None)
    assert (has_stone, stone_type) == (True, "Birthstone")
    assert "Birthstone" in _extract_features(
        _Product(has_stone=has_stone, stone_type=stone_type)
    )


# ---------------------------------------------------------------------------
# The forbidden-word trap this feature switches on
# ---------------------------------------------------------------------------


class _Product:
    """Minimal stand-in — _extract_features only reads these attributes."""

    def __init__(self, **kw):
        self.shape = kw.get("shape")
        self.style = kw.get("style")
        self.has_stone = kw.get("has_stone", False)
        self.stone_type = kw.get("stone_type")
        self.color = kw.get("color")


def test_features_do_not_double_the_word_stone():
    """`f"{stone_type} stone"` produced "Birthstone stone" — and
    FORBIDDEN_TITLE_KEYWORDS bans the bare word "Stone" in titles."""
    features = _extract_features(_Product(has_stone=True, stone_type="Birthstone"))
    assert "Birthstone" in features
    assert "stone stone" not in features.lower()


def test_features_name_the_stone_once():
    features = _extract_features(
        _Product(has_stone=True, stone_type="Cubic Zirconia", color="Gold")
    )
    assert features == "Cubic Zirconia, Gold"


def test_features_omit_the_stone_when_there_is_none():
    assert "stone" not in _extract_features(_Product(color="Gold")).lower()
