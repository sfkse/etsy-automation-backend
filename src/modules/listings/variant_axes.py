"""
Generic variant-axes model (Product.variant_axes / VariationRow.axis_values).

Replaces the fixed Finish x Length x MultiCount matrix for products whose
supplier_options (captured by the Chrome extension off the Rexven product
page) actually describe what's offered — the known failure mode this fixes:
a VariationPreset can offer a finish the supplier doesn't stock (REX-922
offers Gold only; the matching preset seeds Gold *and* Silver), producing a
listing with a variation nobody can fulfil. See
orchestrator.py's _log_preset_mismatch for where that was first noticed.

Axes are freely editable afterward (add/rename/add-value) — this module only
does the initial seed and the cartesian expansion into rows.
"""
from __future__ import annotations

import itertools
from typing import Any, Optional

from src.sourcing.rexven_normalizer import classify_option

# Etsy's own reserved scale/property ids, confirmed live against the real
# Etsy API and by inspecting this shop's own active listings (not guessed):
# 200 = Primary color (established convention for metal Finish in this shop).
# 47626759838 = Necklace length (this taxonomy's real length property) — a
#       *scaled* property: Etsy 400s ("invalid ott_value_qualifier") without
#       an explicit scale_id. 5 = Inches, confirmed via both a real listing's
#       own property_values and a live create+delete test.
# 513 = the generic "Custom 1" slot; this shop already uses it, labeled
#       "Chain Style", for chain-pattern variants.
# 514 = the generic "Custom 2" slot; seen reused for "Enamel Color" and
#       "Number of Charms" in this shop's real listings — used here as the
#       catch-all for count-style and otherwise-unrecognized axes.
#
# affects_price default: confirmed live on a real listing (4593295765, 7
# lengths x 3 colors) that Etsy's own price_on_property there is [200] only
# — price varies by color, not by length, even though every length/color
# combination still exists as its own orderable option. (finish, chain_type)
# default True since a real listing was seen varying price by Chain Style
# too; length defaults False.
_DIMENSION_TO_AXIS: dict[str, tuple[str, int, bool, Optional[int]]] = {
    "finish": ("Color", 200, True, None),
    "length": ("Length", 47_626_759_838, False, 5),
    "chain_type": ("Chain Style", 513, True, None),
}
_CUSTOM_PROPERTY_IDS = [513, 514]

# Standard axes offered as one-click "quick add" buttons on the product page
# (src/web/templates/products/detail.html) — chain length and metal color
# are the same across most of this shop's products, so these save retyping
# the same 7/3 values every time. Still fully editable/removable afterward
# like any other axis.
STANDARD_AXES: list[dict] = [
    {
        "name": "Primary color",
        "values": ["Gold", "Silver", "Rose Gold"],
        "etsy_property_id": 200,
        "affects_price": True,
    },
    {
        "name": "Necklace length",
        "values": ["12", "14", "16", "18", "20", "22", "24"],
        "etsy_property_id": 47_626_759_838,
        "etsy_scale_id": 5,  # Inches — required, see note above
        "affects_price": False,
    },
]

# Recognized axis names -> their real Etsy property id / scale id /
# affects_price default, keyed lowercase. Used so typing (or quick-adding)
# one of these well-known names gets its correct, previously-confirmed
# values instead of a generic Custom slot and a blind guess.
_KNOWN_AXIS_PROPERTY_IDS: dict[str, int] = {
    axis["name"].lower(): axis["etsy_property_id"] for axis in STANDARD_AXES
}
_KNOWN_AXIS_SCALE_IDS: dict[str, int] = {
    axis["name"].lower(): axis["etsy_scale_id"]
    for axis in STANDARD_AXES
    if "etsy_scale_id" in axis
}
_KNOWN_AXIS_AFFECTS_PRICE: dict[str, bool] = {
    axis["name"].lower(): axis["affects_price"] for axis in STANDARD_AXES
}


def affects_price_for_axis_name(name: str) -> bool:
    """Default affects_price for a newly-added axis. Recognized names (e.g.
    "Necklace length") get their confirmed default; anything else defaults
    True — most axes genuinely do vary price, length is the known exception.
    """
    return _KNOWN_AXIS_AFFECTS_PRICE.get(name.strip().lower(), True)


def scale_id_for_axis_name(name: str) -> Optional[int]:
    """Resolve the etsy_scale_id for a newly-added axis, or None when the
    property isn't a scaled one (most aren't — only recognized scaled
    properties like "Necklace length" need this)."""
    return _KNOWN_AXIS_SCALE_IDS.get(name.strip().lower())


def property_id_for_axis_name(name: str, existing_axes: list[dict]) -> int:
    """Resolve the etsy_property_id for a newly-added axis.

    A recognized standard name (e.g. "Primary color") gets its real,
    previously-confirmed Etsy property id; anything else falls back to the
    next free Custom slot. Falls back too if the known id somehow collides
    with one an existing axis on this product already uses.
    """
    known_id = _KNOWN_AXIS_PROPERTY_IDS.get(name.strip().lower())
    used = {a.get("etsy_property_id") for a in existing_axes}
    if known_id is not None and known_id not in used:
        return known_id
    return next_custom_property_id(existing_axes)


def seed_variant_axes_from_rexven(options: Optional[list[dict[str, Any]]]) -> list[dict]:
    """Build Product.variant_axes from raw supplier_options.

    An option only becomes an axis when the supplier stated a real domain of
    2+ values — a single value or values=None (domain unknown) isn't a buyer
    choice, it's a fact about the one thing in stock. "material"-classified
    options are skipped: material is already sent to Etsy as a listing
    attribute (see payload_builder._materials_list), not a variant.
    """
    axes: list[dict] = []
    used_ids: set[int] = set()
    custom_idx = 0

    for opt in options or []:
        values = opt.get("values")
        if not values or len(values) < 2:
            continue
        raw_name = (opt.get("name") or "").strip()
        if not raw_name:
            continue

        dimension = classify_option(raw_name)
        if dimension == "material":
            continue

        if dimension in _DIMENSION_TO_AXIS:
            axis_name, property_id, affects_price, scale_id = _DIMENSION_TO_AXIS[dimension]
        elif dimension == "count":
            axis_name, property_id, affects_price, scale_id = raw_name.title(), _CUSTOM_PROPERTY_IDS[0], True, None
        else:
            axis_name, property_id, affects_price, scale_id = raw_name.title(), _CUSTOM_PROPERTY_IDS[0], True, None

        if property_id in used_ids:
            # Preferred id already taken by an earlier axis on this same
            # product — fall back to the other custom slot, then just reuse
            # (jewelry products realistically have at most 2-3 axes; a third
            # collision is an edge case the user can rename around).
            remaining = [pid for pid in _CUSTOM_PROPERTY_IDS if pid not in used_ids]
            property_id = remaining[0] if remaining else _CUSTOM_PROPERTY_IDS[custom_idx % 2]
            scale_id = None  # Custom slots aren't scaled properties
            custom_idx += 1
        used_ids.add(property_id)

        axis: dict = {
            "name": axis_name,
            "values": [str(v) for v in values],
            "etsy_property_id": property_id,
            "affects_price": affects_price,
        }
        if scale_id is not None:
            axis["etsy_scale_id"] = scale_id
        axes.append(axis)

    return axes


def next_custom_property_id(existing_axes: list[dict]) -> int:
    """Pick a property_id for a manually-added axis, avoiding collisions."""
    used = {a.get("etsy_property_id") for a in existing_axes}
    for pid in _CUSTOM_PROPERTY_IDS:
        if pid not in used:
            return pid
    return _CUSTOM_PROPERTY_IDS[0]


def _auto_price_cents(
    base_price_cents: int,
    combo: tuple[str, ...],
    value_offsets_pct: Optional[dict[str, float]],
) -> int:
    """Apply any configured per-value % offset (e.g. Silver -3%) to the base
    price, like Etsy's own "price per option" — each offset that matches a
    value in this combo compounds. A value with no configured offset (e.g. a
    custom Birthstone option) just gets the base price."""
    price = float(base_price_cents)
    for value in combo:
        offset_pct = (value_offsets_pct or {}).get(value)
        if offset_pct:
            price *= 1.0 + offset_pct / 100.0
    return round(price)


def generate_variant_rows(
    axes: list[dict],
    base_price_cents: int,
    existing_rows: Optional[list[dict]] = None,
    value_offsets_pct: Optional[dict[str, float]] = None,
) -> list[dict]:
    """Cartesian product of axis values -> row dicts for VariationRow.

    Each new combination's starting price is auto-calculated from
    base_price_cents plus any configured per-value offset (PricingStrategy.
    finish_offsets_pct, e.g. {"Gold": 0.0, "Silver": -3.0, "Rose": -5.0}) —
    options aren't all identically priced by default, matching how Etsy
    sellers actually price variants (Gold vs Silver typically differ).
    Freely editable afterward regardless.

    Args:
        existing_rows: prior [{"axis_values": {...}, "price_cents": int}, ...]
            — a combination whose axis_values signature already existed keeps
            its (possibly manually-edited) price; only brand new combinations
            get the auto-calculated one.

    Returns [{"axis_values": {...}, "price_cents": int, "sku_suffix": str}].
    """
    if not axes:
        return []

    names = [a["name"] for a in axes]
    value_lists = [a["values"] for a in axes]

    price_by_signature: dict[tuple, int] = {}
    for row in existing_rows or []:
        av = row.get("axis_values") or {}
        signature = tuple(av.get(n) for n in names)
        if all(v is not None for v in signature):
            price_by_signature[signature] = row["price_cents"]

    rows: list[dict] = []
    for combo in itertools.product(*value_lists):
        axis_values = dict(zip(names, combo))
        if combo in price_by_signature:
            price_cents = price_by_signature[combo]
        else:
            price_cents = _auto_price_cents(base_price_cents, combo, value_offsets_pct)
        suffix = "-".join(v[:2].upper() for v in combo)
        rows.append({
            "axis_values": axis_values,
            "price_cents": price_cents,
            "sku_suffix": suffix,
        })

    return rows


def price_groups(variation_rows: list[Any], axes: list[dict]) -> list[dict]:
    """Group axis-scheme rows by their price-affecting axis values only.

    E.g. with Color (affects_price=True) and Length (affects_price=False),
    21 rows (3 colors x 7 lengths) collapse into 3 groups — one per color —
    each listing which row ids share that color so a single price can be
    applied to all of them at once (src/web/routes/listings.py's
    price_variant_group route). Rows sharing identical price_cents already
    report that as the group's current price; otherwise it's shown blank
    (mixed) rather than guessing which one is "the" price.

    Returns [] when every axis affects price (grouping would just be the
    same rows one-for-one — no point showing it) or there are no axis-scheme
    rows at all.
    """
    price_axis_names = [a["name"] for a in axes if a.get("affects_price", True)]
    if not price_axis_names or len(price_axis_names) == len(axes):
        return []

    groups: dict[tuple, dict] = {}
    for row in variation_rows:
        av = row.axis_values
        if not av:
            continue
        signature = tuple(av.get(n) for n in price_axis_names)
        if any(v is None for v in signature):
            continue
        group = groups.setdefault(signature, {
            "values": {n: av.get(n) for n in price_axis_names},
            "row_ids": [],
            "prices": set(),
        })
        group["row_ids"].append(row.id)
        group["prices"].add(row.price_cents)

    result = []
    for group in groups.values():
        prices = group.pop("prices")
        group["price_cents"] = next(iter(prices)) if len(prices) == 1 else None
        result.append(group)
    return result
