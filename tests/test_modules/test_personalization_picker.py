"""
Tests for the PersonalizationPicker (Section E).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.db.models import PersonalizationTemplate
from src.modules.listings.personalization_picker import PersonalizationPicker


def _templates() -> list[PersonalizationTemplate]:
    return [
        PersonalizationTemplate(
            name="birthstone_initial_single",
            applicable_categories=["necklace", "bracelet"],
            type_signature={"has_initial": True, "has_birthstone": True, "count": 1},
        ),
        PersonalizationTemplate(
            name="multi_birthstone_3",
            applicable_categories=["necklace"],
            type_signature={"has_initial": True, "has_birthstone": True, "count_max": 3},
        ),
        PersonalizationTemplate(
            name="name_only",
            applicable_categories=["necklace", "bracelet"],
            type_signature={"has_name": True, "count": 1},
        ),
        PersonalizationTemplate(
            name="name_date",
            applicable_categories=["necklace", "bracelet"],
            type_signature={"has_name": True, "has_date": True},
        ),
        PersonalizationTemplate(
            name="custom_text",
            applicable_categories=["necklace", "bracelet", "ring"],
            type_signature={"has_custom_text": True},
        ),
    ]


def _session() -> MagicMock:
    session = MagicMock()
    session.query.return_value.all.return_value = _templates()
    return session


def test_none_choice_returns_none():
    picker = PersonalizationPicker(_session())
    assert picker.pick("None", "necklace") is None


def test_single_birthstone_initial_maps():
    picker = PersonalizationPicker(_session())
    tpl = picker.pick("Single Birthstone + Initial", "necklace")
    assert tpl is not None
    assert tpl.name == "birthstone_initial_single"


def test_multi_birthstones_maps_to_multi_3():
    picker = PersonalizationPicker(_session())
    tpl = picker.pick("Multi (2-3) Birthstones", "necklace")
    assert tpl is not None
    assert tpl.name == "multi_birthstone_3"


def test_name_date_maps():
    picker = PersonalizationPicker(_session())
    tpl = picker.pick("Name + Date", "bracelet")
    assert tpl is not None
    assert tpl.name == "name_date"


def test_unknown_choice_returns_none():
    picker = PersonalizationPicker(_session())
    assert picker.pick("Not a Real Option", "necklace") is None


def test_category_mismatch_returns_none():
    picker = PersonalizationPicker(_session())
    # multi_birthstone_3 is necklace-only in our fixture
    assert picker.pick("Multi (2-3) Birthstones", "earring") is None
