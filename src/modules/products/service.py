"""
Post-approval product field editing.

Lets an `approved`/`published` product's final content and manual-input
fields be edited in place (DB-only — no Etsy sync; publish is disabled).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import structlog
from sqlalchemy.orm import Session

from src.db.models import Product
from src.modules.approval.service import validate_field

_log = structlog.get_logger(__name__)

EDITABLE_PRODUCT_FIELDS: dict[str, dict] = {
    "title":         {"column": "final_title",       "kind": "content"},
    "tags":          {"column": "final_tags",         "kind": "content"},
    "description":   {"column": "final_description",  "kind": "content"},
    # The fields below only ever fed the one-time content-generation prompt
    # (ResearchContextBuilder.build_for_product) earlier in the pipeline —
    # they have no counterpart on a live Etsy listing, so editing them here
    # is DB-only record-keeping, never synced anywhere.
    "material":      {"column": "material",      "kind": "str", "max_len": 100},
    "color":         {"column": "color",         "kind": "str", "max_len": 50},
    "has_stone":     {"column": "has_stone",     "kind": "bool"},
    "stone_type":    {"column": "stone_type",    "kind": "str", "max_len": 100},
    "shape":         {"column": "shape",         "kind": "str", "max_len": 50},
    "style":         {"column": "style",         "kind": "str", "max_len": 50},
    "occasion":      {"column": "occasion",      "kind": "str", "max_len": 100},
    "recipient":     {"column": "recipient",     "kind": "str", "max_len": 50},
    "size_info":     {"column": "size_info",     "kind": "str"},
    "cost":          {"column": "cost",          "kind": "money", "min": 0},
    "selling_price": {"column": "selling_price", "kind": "money", "min": 0.01},
}


def validate_product_field(field: str, value: Any) -> tuple[bool, list[str]]:
    """Soft validation — violations are reported but never block the save,
    matching the approval page's override-friendly UX for content fields."""
    spec = EDITABLE_PRODUCT_FIELDS[field]
    if spec["kind"] == "content":
        return validate_field(field, value)
    return (True, [])


def update_product_field(
    session: Session,
    product: Product,
    field: str,
    value: Any,
) -> tuple[bool, Any, str | None]:
    """
    Coerce + persist one field. Returns (success, coerced_value, error).

    Numeric/length fields are hard-rejected on bad input (DB/consistency
    constraints, not stylistic choices) — unlike content fields, which are
    never hard-rejected here (soft violations from validate_product_field
    already cover that UX).
    """
    spec = EDITABLE_PRODUCT_FIELDS.get(field)
    if spec is None:
        return False, None, "unknown field"

    kind = spec["kind"]
    if kind == "content":
        if field == "tags":
            coerced = value if isinstance(value, list) else [
                t.strip() for t in str(value).split(",") if t.strip()
            ]
            coerced = coerced[:13]
        else:
            coerced = value
    elif kind == "bool":
        coerced = bool(value)
    elif kind == "money":
        try:
            coerced = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return False, None, "must be a number"
        if coerced < Decimal(str(spec["min"])):
            return False, None, f"must be >= {spec['min']}"
    else:  # str
        coerced = (str(value).strip() or None) if value is not None else None
        if coerced and spec.get("max_len") and len(coerced) > spec["max_len"]:
            return False, None, f"must be {spec['max_len']} characters or fewer"

    setattr(product, spec["column"], coerced)
    session.commit()
    _log.info("product_field_updated", sku=product.sku, field=field)
    return True, coerced, None
