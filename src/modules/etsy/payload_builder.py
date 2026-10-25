"""
Etsy Listing Payload Builder (Section K of OPERATIONAL_INTEGRATION.md).

Consolidates Shop Settings, DefaultAttributes, PersonalizationTemplate,
VariationPreset, and VariationRow rows into the exact JSON payload that
Etsy's create/update-listing endpoints expect.

Only used when a product carries `variation_preset_id` (Listing Builder
flow). Products without a variation matrix (legacy rows predating the
Listing Builder) fall back to the pre-existing publisher path.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from src.config.business_rules import QUANTITY_CONFIDENT
from src.db.models import (
    DefaultAttributes,
    PersonalizationTemplate,
    PricingStrategy,
    Product,
    RenewalOption,
    ShopSection,
    ShopSettings,
    VariationPreset,
    VariationRow,
)


class EtsyListingPayloadBuilder:
    """Compose an Etsy v3 listing payload from a Product built via the Listing Builder."""

    def __init__(self, session: Session, settings: Optional[ShopSettings] = None) -> None:
        self.session = session
        self.settings = settings or session.query(ShopSettings).filter_by(id=1).first()

    def build(
        self,
        product: Product,
        variant_id: Optional[str] = None,
        chosen_variant: Optional[dict] = None,
        region: Optional[str] = None,
    ) -> dict:
        """
        Build the create-listing payload.

        region: when publishing the same product as a separate listing per
        shipping profile (e.g. "US"/"UK"/"DE"), applies that region's
        PricingStrategy.region_price_adjustments_pct on top of every variant
        price below — e.g. DE priced +10% to cover its typically higher
        shipping cost. None (single-listing / legacy path) applies none.

        Args:
            product: the Product row.
            variant_id: id ("A"/"B"/"C"/"HYBRID") of the variant to build. When given
                        (and ``chosen_variant`` is not), the matching entry is loaded
                        from ``product.generated_variants``. This is the multi-listing
                        entry point — each published variant is built by id.
            chosen_variant: dict-shaped ListingVariant (matches ``ListingVariant.to_dict``).
                            When both are None, falls back to ``product.final_*`` fields.
        """
        if chosen_variant is None and variant_id:
            from src.modules.approval.service import get_variant_by_id
            chosen_variant = get_variant_by_id(product, variant_id)
        preset = (
            self.session.query(VariationPreset).get(product.variation_preset_id)
            if product.variation_preset_id
            else None
        )
        defaults = (
            self.session.query(DefaultAttributes).filter_by(
                category=preset.category if preset else "necklace"
            ).first()
        )
        personalization = (
            self.session.query(PersonalizationTemplate).get(product.personalization_template_id)
            if product.personalization_template_id
            else None
        )
        section = (
            self.session.query(ShopSection).filter_by(
                carrier_pillar=product.carrier_pillar
            ).first()
        )

        title = (chosen_variant or {}).get("title") or product.final_title or ""
        tags = (chosen_variant or {}).get("tags") or product.final_tags or []
        description = (chosen_variant or {}).get("description") or product.final_description or ""

        payload: dict = {
            "title": title,
            "tags": tags[:13],
            "description": description,
            "materials": self._materials_list(preset),
            "who_made": "someone_else",
            "when_made": "made_to_order",
            "is_supply": False,
            "state": "draft",
        }

        if self.settings and self.settings.production_partner_id:
            payload["production_partner_ids"] = [self.settings.production_partner_id]

        if self.settings:
            payload["should_auto_renew"] = (
                (self.settings.renewal_option or RenewalOption.AUTOMATIC.value)
                == RenewalOption.AUTOMATIC.value
            )
            if self.settings.default_shipping_profile_id:
                payload["shipping_profile_id"] = self.settings.default_shipping_profile_id

        payload["is_personalizable"] = personalization is not None
        if personalization is not None:
            payload["personalization_is_required"] = not personalization.is_optional
            payload["personalization_char_count_max"] = personalization.max_characters or 0
            payload["personalization_instructions"] = self._build_personalization_block(personalization)
        else:
            payload["personalization_is_required"] = False

        if section and section.etsy_section_id:
            payload["shop_section_id"] = section.etsy_section_id

        payload["is_featured"] = bool(
            product.is_featured
            or (self.settings.feature_listing_default if self.settings else False)
        )

        payload["attributes"] = self._build_attributes(product, defaults)
        payload["inventory"] = self._build_inventory(product, preset, region)

        return payload

    # ── Attributes ────────────────────────────────────────────────────────────

    def _build_attributes(
        self,
        product: Product,
        defaults: Optional[DefaultAttributes],
    ) -> dict:
        attrs: dict = {}
        if defaults is not None:
            attrs["style"] = defaults.style
            attrs["sustainability"] = defaults.sustainability
            attrs["is_adjustable"] = defaults.adjustable
            attrs["is_convertible"] = defaults.convertible
            attrs["chain_style"] = product.chain_style or defaults.chain_style
            attrs["theme"] = product.theme or defaults.theme
            attrs["occasions"] = product.occasions_json or [defaults.default_occasion]
            attrs["recipients"] = product.recipients_json or (defaults.default_recipients or [])
        else:
            attrs["occasions"] = product.occasions_json or []
            attrs["recipients"] = product.recipients_json or []

        attrs["holiday"] = self._pick_holiday(product, defaults)
        attrs["shape"] = product.stone_shape
        attrs["has_stone"] = bool(product.stone_shape) or bool(product.has_stone)
        return attrs

    @staticmethod
    def _pick_holiday(
        product: Product,
        defaults: Optional[DefaultAttributes],
    ) -> str:
        """Holiday selection per Section K training rules."""
        if product.holiday_override:
            return product.holiday_override

        theme = (product.theme or "").lower()
        if "islamic" in theme or "ramadan" in theme or "eid" in theme:
            return "Eid"
        if "halloween" in theme or "spooky" in theme:
            return "Halloween"
        if "valentine" in theme or "love" in theme:
            return "Valentine's Day"
        if "christmas" in theme:
            return "Christmas"

        if defaults and defaults.holiday_default:
            return defaults.holiday_default
        return "Christmas"

    @staticmethod
    def _materials_list(preset: Optional[VariationPreset]) -> list[str]:
        if preset is None:
            return []
        from src.db.models import MaterialType
        if preset.material_type == MaterialType.SILVER_925.value:
            return ["925 Sterling Silver"]
        if preset.material_type == MaterialType.BRASS.value:
            return ["Brass", "Gold Plating"]
        return ["Gold Plated"]

    # ── Inventory ─────────────────────────────────────────────────────────────

    # Etsy requires property_id as an int on every property_values entry (a
    # bare property_name 400s with "Expected int value for 'property_id'").
    # These ids are confirmed against this shop's own 87 real active listings
    # (surveyed live, not guessed): 200 "Primary color" is the established
    # convention for metal Finish (Gold/Silver/Rose Gold all appear under it
    # across multiple real listings). 47626759838 "Necklace length" is this
    # taxonomy's real length property. 514 is one of Etsy's two generic
    # "Custom" property slots (513/514), seen reused across real listings for
    # different concepts via property_name (e.g. "Enamel Color", "Number of
    # Charms") — used here the same way for multi-count variations.
    _FINISH_PROPERTY_ID = 200
    _LENGTH_PROPERTY_ID = 47626759838
    _MULTI_COUNT_PROPERTY_ID = 514

    def _build_inventory(
        self,
        product: Product,
        preset: Optional[VariationPreset],
        region: Optional[str] = None,
    ) -> dict:
        rows = (
            self.session.query(VariationRow)
            .filter_by(product_id=product.id)
            .order_by(VariationRow.id)
            .all()
        )
        if not rows:
            return {"products": []}

        quantity = (self.settings.default_quantity if self.settings else None) or QUANTITY_CONFIDENT
        price_multiplier = self._region_price_multiplier(region)

        if product.variant_axes:
            return self._build_inventory_generic(product, rows, quantity, price_multiplier)
        return self._build_inventory_legacy(product, rows, preset, quantity, price_multiplier)

    def _region_price_multiplier(self, region: Optional[str]) -> float:
        """1.0 + PricingStrategy.region_price_adjustments_pct[region]/100, or
        1.0 (no adjustment) when there's no region or no configured entry."""
        if not region:
            return 1.0
        pricing = self.session.query(PricingStrategy).filter_by(id=1).first()
        adjustments = (pricing.region_price_adjustments_pct if pricing else None) or {}
        pct = adjustments.get(region, 0.0) or 0.0
        return 1.0 + pct / 100.0

    def _build_inventory_generic(
        self,
        product: Product,
        rows: list[VariationRow],
        quantity: int,
        price_multiplier: float = 1.0,
    ) -> dict:
        """Build inventory from the generic axis scheme (Product.variant_axes
        / VariationRow.axis_values) — see modules/listings/variant_axes.py.
        """
        axis_by_name = {a["name"]: a for a in product.variant_axes}
        # Etsy caps a listing at 2 variation properties, counting any axis
        # present in property_values regardless of how many values it has
        # (confirmed live: PUT .../inventory 409s with "Could not update
        # inventory with unsupported number of variations. The maximum
        # number of supported variations is 2" the instant a 3rd property
        # appears). An axis with a single value isn't a real variation
        # anyway — it's constant across every row — so it's dropped here
        # rather than silently creating an orphaned draft on every publish.
        variation_axis_names = {
            a["name"] for a in product.variant_axes if len(a.get("values") or []) > 1
        }

        products: list[dict] = []
        price_affecting_ids: set[int] = set()
        for row in rows:
            property_values: list[dict] = []
            for axis_name, value in (row.axis_values or {}).items():
                if axis_name not in variation_axis_names:
                    continue
                axis = axis_by_name.get(axis_name)
                property_id = axis["etsy_property_id"] if axis else None
                if property_id is None:
                    continue
                property_value: dict = {
                    "property_id": property_id,
                    "property_name": axis_name,
                    "values": [str(value)],
                }
                # Scaled properties (e.g. Necklace length / Inches) 400 with
                # "invalid ott_value_qualifier" without their scale_id —
                # confirmed live. Most properties (e.g. Color) aren't scaled.
                scale_id = axis.get("etsy_scale_id") if axis else None
                if scale_id is not None:
                    property_value["scale_id"] = scale_id
                property_values.append(property_value)
                # Only axes actually marked as price-affecting declare
                # price_on_property — confirmed against a real listing
                # (4593295765): 7 lengths x 3 colors, but price_on_property
                # there is [Primary color] only, not length, even though
                # every length/color combination exists as its own option.
                if axis is None or axis.get("affects_price", True):
                    price_affecting_ids.add(property_id)

            product_entry: dict = {
                "property_values": property_values,
                "offerings": [{
                    "price": round(row.price_cents / 100.0 * price_multiplier, 2),
                    "quantity": quantity,
                    "is_enabled": True,
                }],
            }
            if product.rexven_sku:
                product_entry["sku"] = product.rexven_sku
            products.append(product_entry)

        return {
            "products": products,
            "price_on_property": sorted(price_affecting_ids),
            "quantity_on_property": [],
            "sku_on_property": [],
        }

    def _build_inventory_legacy(
        self,
        product: Product,
        rows: list[VariationRow],
        preset: Optional[VariationPreset],
        quantity: int,
        price_multiplier: float = 1.0,
    ) -> dict:
        """Build inventory from the legacy fixed Finish/Length/MultiCount
        columns — still used by products created before the generic
        variant-axes scheme.
        """
        products: list[dict] = []
        varying_property_ids: set[int] = set()
        for row in rows:
            property_values: list[dict] = [
                {
                    "property_id": self._FINISH_PROPERTY_ID,
                    "property_name": "Primary color",
                    "values": [row.finish],
                },
            ]
            varying_property_ids.add(self._FINISH_PROPERTY_ID)
            if row.length_inches is not None:
                property_values.append({
                    "property_id": self._LENGTH_PROPERTY_ID,
                    "property_name": "Necklace length",
                    "values": [f'{row.length_inches}"'],
                })
                varying_property_ids.add(self._LENGTH_PROPERTY_ID)
            if row.multi_count is not None and preset is not None:
                label = preset.multi_count_label or "Count"
                property_values.append({
                    "property_id": self._MULTI_COUNT_PROPERTY_ID,
                    "property_name": label,
                    "values": [f"{row.multi_count} {label}"],
                })
                varying_property_ids.add(self._MULTI_COUNT_PROPERTY_ID)

            product_entry: dict = {
                "property_values": property_values,
                "offerings": [{
                    "price": round(row.price_cents / 100.0 * price_multiplier, 2),
                    "quantity": quantity,
                    "is_enabled": True,
                }],
            }
            # Etsy's one SKU field is for the seller's own inventory/fulfillment
            # tracking — real listings in this shop share one supplier SKU
            # (e.g. "REX-950") across every variant, not a per-variant-unique
            # one. Confirmed live by inspecting this shop's own active
            # listings. Omitted (not blank) when the product has no Rexven
            # SKU, since Etsy's SKU field is optional.
            if product.rexven_sku:
                product_entry["sku"] = product.rexven_sku
            products.append(product_entry)

        # Etsy requires an explicit declaration of which property id each of
        # price/quantity/sku varies BY — without declaring it, differing
        # prices across products 400 with "price must be consistent across
        # all products" (confirmed live). Quantity and SKU are never
        # per-variant here (one shared default quantity, one shared supplier
        # SKU), matching real listings in this shop, which likewise declare
        # quantity_on_property/sku_on_property empty.
        on_property = sorted(varying_property_ids)
        return {
            "products": products,
            "price_on_property": on_property,
            "quantity_on_property": [],
            "sku_on_property": [],
        }

    # ── Personalization ───────────────────────────────────────────────────────

    @staticmethod
    def _build_personalization_block(pers: PersonalizationTemplate) -> str:
        parts = [pers.instruction_text or ""]
        if pers.example_text:
            parts.append(pers.example_text)
        if pers.reference_note:
            parts.append(pers.reference_note)
        return "\n\n".join(p for p in parts if p)
