"""
Etsy taxonomy attribute mapping for jewelry necklaces (Step 8.5).

Jewelry > Necklaces taxonomy ID: 1588
Attribute IDs are stable Etsy API constants — keep this file as the single
source of truth.  Run `GET /application/seller-taxonomy/nodes/1588/properties`
to fetch the latest IDs and compare against the constants below.
"""
from __future__ import annotations

from src.db.models import Product
from src.domain.carrier_pillar import CarrierPillar

# ── Taxonomy ───────────────────────────────────────────────────────────────────

JEWELRY_NECKLACE_TAXONOMY_ID = 1588

# ── Attribute property IDs (Etsy Open API v3) ─────────────────────────────────

ATTR_MATERIAL = 506132
ATTR_STYLE = 506131
ATTR_OCCASION = 506134
ATTR_RECIPIENT = 501
ATTR_COLOR = 200
ATTR_HOLIDAY = 506133
ATTR_FINISH = 506135

# ── Value ID maps (property_value_id for each human-readable value) ───────────
# Run `GET /application/seller-taxonomy/nodes/1588/properties` to refresh.

MATERIAL_VALUE_IDS: dict[str, int] = {
    "Gold Plated":       1454  ,
    "Brass":             1596  ,
    "925 Sterling Silver": 1469,
    "Silver":            1469  ,
    "Gold":              1454  ,
}

STYLE_VALUE_IDS: dict[str, int] = {
    "Minimalist":   1628,
    "Personalized": 1604,
    "Floral":       1629,
    "Bohemian":     1602,
    "Classic":      1598,
    "Modern":       1599,
    "Vintage":      1603,
    "Statement":    1630,
}

OCCASION_VALUE_IDS: dict[str, int] = {
    "Birthday":       117   ,
    "Anniversary":    118   ,
    "Wedding":        119   ,
    "Everyday":       120   ,
    "Religious":      540   ,
    "Pet Memorial":   541   ,
    "Graduation":     121   ,
    "Gifts for Mom":  542   ,
    "Valentine's Day": 122  ,
    "Christmas":      123   ,
}

RECIPIENT_VALUE_IDS: dict[str, int] = {
    "For Her":       1     ,
    "For Him":       2     ,
    "For Mom":       3     ,
    "For Sister":    4     ,
    "For Best Friend": 5   ,
    "For Wife":      6     ,
    "For Daughter":  7     ,
    "Unisex":        8     ,
}

# Pillars that correspond to "personalized" listings
PERSONALIZED_PILLARS = {
    CarrierPillar.NAME.value,
    CarrierPillar.BIRTHSTONE.value,
    CarrierPillar.PET.value,
}


def build_attributes(product: Product) -> list[dict]:
    """
    Return the `attributes` list for the Etsy listing create/update payload.
    Each item follows the shape:
        {"property_id": <int>, "value_ids": [<int>], "values": ["<str>"]}
    """
    attrs: list[dict] = []

    def _add(property_id: int, value_ids: list[int], values: list[str]) -> None:
        if value_ids:
            attrs.append(
                {"property_id": property_id, "value_ids": value_ids, "values": values}
            )

    # Material
    if product.material:
        vid = MATERIAL_VALUE_IDS.get(product.material)
        _add(ATTR_MATERIAL, [vid] if vid else [], [product.material])

    # Style
    if product.style:
        vid = STYLE_VALUE_IDS.get(product.style)
        _add(ATTR_STYLE, [vid] if vid else [], [product.style])

    # Occasion — may be comma-separated ("Birthday, Anniversary")
    if product.occasion:
        for occ in product.occasion.split(","):
            occ = occ.strip()
            vid = OCCASION_VALUE_IDS.get(occ)
            _add(ATTR_OCCASION, [vid] if vid else [], [occ])

    # Recipient
    if product.recipient:
        vid = RECIPIENT_VALUE_IDS.get(product.recipient)
        _add(ATTR_RECIPIENT, [vid] if vid else [], [product.recipient])

    # Color
    if product.color:
        _add(ATTR_COLOR, [], [product.color])

    return attrs


def is_personalized(product: Product) -> bool:
    return product.carrier_pillar in PERSONALIZED_PILLARS
