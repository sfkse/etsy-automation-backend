"""
Tests for the EtsyListingPayloadBuilder (Section K).

Uses a MagicMock session and hand-constructed ORM objects.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.db.models import (
    DefaultAttributes,
    MaterialType,
    PersonalizationTemplate,
    Product,
    RenewalOption,
    ShopSettings,
    VariationPreset,
    VariationRow,
)
from src.modules.etsy.payload_builder import EtsyListingPayloadBuilder


def _settings() -> ShopSettings:
    return ShopSettings(
        id=1,
        production_partner_id="pp_42",
        renewal_option=RenewalOption.AUTOMATIC.value,
        default_quantity=999,
        feature_listing_default=False,
        default_shipping_profile_id="ship_1",
    )


def _defaults() -> DefaultAttributes:
    return DefaultAttributes(
        category="necklace",
        style="Minimalist",
        theme="Love & Friendship",
        holiday_default="Christmas",
        sustainability="Made with Recycled Metals",
        chain_style="Cable Chain",
        adjustable=True,
        convertible=True,
        default_occasion="Birthday",
        default_recipients=["Her", "Mother"],
    )


def _brass_preset() -> VariationPreset:
    return VariationPreset(
        id=1,
        name="necklace_brass_multi_birthstone",
        category="necklace",
        material_type=MaterialType.BRASS.value,
        finishes=["Gold", "Silver"],
        lengths_inches=[],
        multi_count_label="Birthstone",
        multi_count_range=[1, 2, 3],
        has_length_variation=False,
    )


def _silver_preset() -> VariationPreset:
    return VariationPreset(
        id=2,
        name="necklace_silver_standard",
        category="necklace",
        material_type=MaterialType.SILVER_925.value,
        finishes=["Gold", "Silver", "Rose"],
        lengths_inches=[12, 14, 16, 18, 20, 22, 24],
        has_length_variation=True,
    )


def _pers() -> PersonalizationTemplate:
    return PersonalizationTemplate(
        id=1,
        name="birthstone_initial_single",
        instruction_text="Please Provide: birthstone + initial",
        example_text="For example: May, E",
        reference_note="See photo.",
        max_characters=0,
        is_optional=False,
    )


def _rows_brass_multi() -> list[VariationRow]:
    return [
        VariationRow(product_id=1, finish="Gold", multi_count=n,
                     length_inches=None, price_cents=3000 + n * 500,
                     sku_suffix=f"GO-N{n}", is_loss_leader=False)
        for n in (1, 2, 3)
    ] + [
        VariationRow(product_id=1, finish="Silver", multi_count=n,
                     length_inches=None, price_cents=2900 + n * 500,
                     sku_suffix=f"SI-N{n}", is_loss_leader=False)
        for n in (1, 2, 3)
    ]


def _rows_silver_standard() -> list[VariationRow]:
    rows = []
    for finish in ("Gold", "Silver", "Rose"):
        for length in (12, 14, 16, 18, 20, 22, 24):
            rows.append(VariationRow(
                product_id=1, finish=finish, length_inches=length, multi_count=None,
                price_cents=3000, sku_suffix=f"{finish[:2].upper()}-L{length}",
                is_loss_leader=(finish == "Rose" and length == 12),
            ))
    return rows


def _session(*, preset, defaults, personalization, rows):
    session = MagicMock()

    def query_side(model):
        q = MagicMock()
        if model is VariationPreset:
            q.get.return_value = preset
        elif model is DefaultAttributes:
            q.filter_by.return_value.first.return_value = defaults
        elif model is PersonalizationTemplate:
            q.get.return_value = personalization
        else:
            # ShopSection lookup — return None (not exercised here)
            q.filter_by.return_value.first.return_value = None
            q.filter_by.return_value.order_by.return_value.all.return_value = rows
            q.filter_by.return_value.all.return_value = rows
            # For VariationRow query chain
            q.filter_by.return_value.order_by.return_value.all.return_value = rows
        return q

    session.query.side_effect = query_side
    return session


def _product(preset_id: int = 1, pers_id: int | None = 1) -> Product:
    return Product(
        id=1,
        sku="TAKI-0042",
        carrier_pillar="birthstone",
        final_title="Test Title",
        final_tags=["a", "b", "c"],
        final_description="Body.",
        variation_preset_id=preset_id,
        personalization_template_id=pers_id,
        material_type=MaterialType.BRASS.value,
        theme=None,
    )


def test_brass_multi_birthstone_produces_six_inventory_products():
    session = _session(
        preset=_brass_preset(),
        defaults=_defaults(),
        personalization=_pers(),
        rows=_rows_brass_multi(),
    )
    builder = EtsyListingPayloadBuilder(session, settings=_settings())
    payload = builder.build(_product())

    assert len(payload["inventory"]["products"]) == 6
    assert payload["production_partner_ids"] == ["pp_42"]
    assert payload["should_auto_renew"] is True
    assert payload["is_personalizable"] is True
    assert "Please Provide" in payload["personalization_instructions"]


def test_silver_standard_produces_21_inventory_products():
    session = _session(
        preset=_silver_preset(),
        defaults=_defaults(),
        personalization=None,
        rows=_rows_silver_standard(),
    )
    product = _product(preset_id=2, pers_id=None)
    product.material_type = MaterialType.SILVER_925.value
    builder = EtsyListingPayloadBuilder(session, settings=_settings())
    payload = builder.build(product)

    assert len(payload["inventory"]["products"]) == 21
    assert payload["is_personalizable"] is False


def test_holiday_mapping_islamic_theme():
    session = _session(
        preset=_brass_preset(),
        defaults=_defaults(),
        personalization=None,
        rows=_rows_brass_multi(),
    )
    product = _product(pers_id=None)
    product.theme = "Islamic Ramadan gift"
    builder = EtsyListingPayloadBuilder(session, settings=_settings())
    payload = builder.build(product)
    assert payload["attributes"]["holiday"] == "Eid"


def test_holiday_mapping_default_christmas():
    session = _session(
        preset=_brass_preset(),
        defaults=_defaults(),
        personalization=None,
        rows=_rows_brass_multi(),
    )
    product = _product(pers_id=None)
    product.theme = None
    builder = EtsyListingPayloadBuilder(session, settings=_settings())
    payload = builder.build(product)
    assert payload["attributes"]["holiday"] == "Christmas"


def test_holiday_override_wins():
    session = _session(
        preset=_brass_preset(),
        defaults=_defaults(),
        personalization=None,
        rows=_rows_brass_multi(),
    )
    product = _product(pers_id=None)
    product.holiday_override = "Halloween"
    product.theme = "Christmas red green"
    builder = EtsyListingPayloadBuilder(session, settings=_settings())
    payload = builder.build(product)
    assert payload["attributes"]["holiday"] == "Halloween"


def test_first_offering_price_is_serialised_as_float():
    session = _session(
        preset=_brass_preset(),
        defaults=_defaults(),
        personalization=None,
        rows=_rows_brass_multi(),
    )
    builder = EtsyListingPayloadBuilder(session, settings=_settings())
    payload = builder.build(_product(pers_id=None))
    first_offering = payload["inventory"]["products"][0]["offerings"][0]
    assert isinstance(first_offering["price"], float)
    assert first_offering["quantity"] == 999
