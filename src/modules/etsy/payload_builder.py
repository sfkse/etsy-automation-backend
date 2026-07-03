"""
Etsy Listing Payload Builder (Section K of OPERATIONAL_INTEGRATION.md).

Consolidates Shop Settings, DefaultAttributes, PersonalizationTemplate,
VariationPreset, and VariationRow rows into the exact JSON payload that
Etsy's create/update-listing endpoints expect.

Only used when a product carries `variation_preset_id` (new Listing Builder
flow). Legacy `/products/new` products fall back to the pre-existing
publisher path.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from src.config.business_rules import QUANTITY_CONFIDENT
from src.db.models import (
    DefaultAttributes,
    PersonalizationTemplate,
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

    def build(self, product: Product, chosen_variant: Optional[dict] = None) -> dict:
        """
        Build the create-listing payload.

        Args:
            product: the Product row.
            chosen_variant: dict-shaped ListingVariant (matches ``ListingVariant.to_dict``).
                            When None, falls back to ``product.final_*`` fields.
        """
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
        payload["inventory"] = self._build_inventory(product, preset)

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

    def _build_inventory(
        self,
        product: Product,
        preset: Optional[VariationPreset],
    ) -> dict:
        rows = (
            self.session.query(VariationRow)
            .filter_by(product_id=product.id)
            .order_by(VariationRow.finish, VariationRow.length_inches, VariationRow.multi_count)
            .all()
        )
        if not rows:
            return {"products": []}

        quantity = (self.settings.default_quantity if self.settings else None) or QUANTITY_CONFIDENT
        products: list[dict] = []
        for row in rows:
            property_values: list[dict] = [
                {"property_name": "Finish", "values": [row.finish]},
            ]
            if row.length_inches is not None:
                property_values.append({
                    "property_name": "Length",
                    "values": [f'{row.length_inches}"'],
                })
            if row.multi_count is not None and preset is not None:
                label = preset.multi_count_label or "Count"
                property_values.append({
                    "property_name": label,
                    "values": [f"{row.multi_count} {label}"],
                })

            products.append({
                "sku": f"{product.sku}-{row.sku_suffix}",
                "property_values": property_values,
                "offerings": [{
                    "price": round(row.price_cents / 100.0, 2),
                    "quantity": quantity,
                    "is_enabled": True,
                }],
            })

        return {"products": products}

    # ── Personalization ───────────────────────────────────────────────────────

    @staticmethod
    def _build_personalization_block(pers: PersonalizationTemplate) -> str:
        parts = [pers.instruction_text or ""]
        if pers.example_text:
            parts.append(pers.example_text)
        if pers.reference_note:
            parts.append(pers.reference_note)
        return "\n\n".join(p for p in parts if p)
