"""Tests for ListingBuilder._ensure_shop_section (PR 6).

Drives the helper directly with a MagicMock session so we bypass the rest
of the build pipeline. Covers the three branches: flag off, new pillar,
duplicate pillar.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.db.models import Product, ShopSection, ShopSettings
from src.modules.listings.orchestrator import ListingBuilder


def _make_session(existing_section: ShopSection | None, max_order: int = 0) -> MagicMock:
    session = MagicMock()

    def query_side(model):
        q = MagicMock()
        if model is ShopSection:
            q.filter_by.return_value.first.return_value = existing_section
        else:
            q.filter_by.return_value.first.return_value = None
        # ``session.query(func.max(...)).scalar()`` path — arg is a SQL
        # expression, not a model class. Return the pre-set max_order.
        q.scalar.return_value = max_order
        return q

    session.query.side_effect = query_side
    return session


def _make_builder(session: MagicMock) -> ListingBuilder:
    builder = ListingBuilder.__new__(ListingBuilder)
    builder.session = session
    return builder


def _added_shop_sections(session: MagicMock) -> list[ShopSection]:
    return [
        c.args[0]
        for c in session.add.call_args_list
        if c.args and isinstance(c.args[0], ShopSection)
    ]


def test_flag_off_does_not_create_section():
    session = _make_session(existing_section=None)
    builder = _make_builder(session)
    product = Product(sku="TAKI-1", carrier_pillar="birthstone")
    settings = ShopSettings(id=1, auto_create_sections=False)

    builder._ensure_shop_section(product, settings)

    assert _added_shop_sections(session) == []


def test_new_pillar_inserts_named_section():
    session = _make_session(existing_section=None, max_order=0)
    builder = _make_builder(session)
    product = Product(sku="TAKI-2", carrier_pillar="birthstone")
    settings = ShopSettings(id=1, auto_create_sections=True)

    builder._ensure_shop_section(product, settings)

    added = _added_shop_sections(session)
    assert len(added) == 1
    section = added[0]
    assert section.name == "Birthstone Necklace"
    assert section.carrier_pillar == "birthstone"
    assert section.display_order == 1
    assert section.etsy_section_id is None
    session.commit.assert_called()


def test_new_pillar_falls_back_to_titleised_name():
    """Unknown pillar → titleised name derived from the pillar slug."""
    session = _make_session(existing_section=None, max_order=3)
    builder = _make_builder(session)
    product = Product(sku="TAKI-3", carrier_pillar="birth_flower")
    settings = ShopSettings(id=1, auto_create_sections=True)

    # Override the pillar to an unmapped value to exercise the fallback.
    product.carrier_pillar = "moon_phase"
    builder._ensure_shop_section(product, settings)

    added = _added_shop_sections(session)
    assert len(added) == 1
    assert added[0].name == "Moon Phase"
    assert added[0].display_order == 4


def test_duplicate_pillar_is_a_noop():
    existing = ShopSection(
        id=9, name="Birthstone Necklace", carrier_pillar="birthstone", display_order=1
    )
    session = _make_session(existing_section=existing, max_order=1)
    builder = _make_builder(session)
    product = Product(sku="TAKI-4", carrier_pillar="birthstone")
    settings = ShopSettings(id=1, auto_create_sections=True)

    builder._ensure_shop_section(product, settings)

    assert _added_shop_sections(session) == []


def test_missing_settings_row_does_not_create_section():
    session = _make_session(existing_section=None)
    builder = _make_builder(session)
    product = Product(sku="TAKI-5", carrier_pillar="birthstone")

    builder._ensure_shop_section(product, settings=None)

    assert _added_shop_sections(session) == []
