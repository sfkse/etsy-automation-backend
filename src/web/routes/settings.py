"""
Shop Settings JSON API (Section B.3 of OPERATIONAL_INTEGRATION.md).

Eight tabs exposed as GET/POST pairs, backed by the singleton and
per-category rows seeded via ``seed_shop_defaults.seed_all``:

- production-partner    → ShopSettings.production_partner_*
- description-templates → DescriptionTemplate rows
- default-attributes    → DefaultAttributes rows
- variation-presets     → VariationPreset rows
- pricing-strategy      → PricingStrategy singleton
- personalization-library → PersonalizationTemplate rows
- operations            → ShopSettings (renewal, return policy, quantity)
- shop-sections         → ShopSection rows

The HTML/Jinja UI on top of this API is a follow-up. This module holds the
persistence layer only.
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.config.business_rules import CARRIER_PILLARS
from src.db.dependencies import get_session
from src.db.models import (
    DefaultAttributes,
    DescriptionTemplate,
    MaterialType,
    PersonalizationTemplate,
    PricingStrategy,
    RenewalOption,
    ShopSection,
    ShopSettings,
    VariationPreset,
)
from src.modules.listings.reprice import reprice_all_preset_products

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])
templates: Jinja2Templates | None = None


def set_templates(t: Jinja2Templates) -> None:
    global templates
    templates = t


# ── Helpers ──────────────────────────────────────────────────────────────────


def _row_to_dict(row: Any) -> dict:
    """Return a plain dict of an SQLAlchemy row's non-private columns."""
    if row is None:
        return {}
    return {
        col.name: getattr(row, col.name)
        for col in row.__table__.columns
    }


def _apply_updates(row: Any, updates: dict, allowed: set[str]) -> None:
    for key, value in updates.items():
        if key in allowed:
            setattr(row, key, value)


def _get_or_create_settings(session: Session) -> ShopSettings:
    row = session.query(ShopSettings).filter_by(id=1).first()
    if row is None:
        row = ShopSettings(id=1)
        session.add(row)
        session.commit()
    return row


def compute_preflight(session: Session) -> dict:
    """Report shop-settings gaps that would break a build or publish.

    DB-only (no Etsy API calls). The two user-required entries are the
    Etsy-account-specific IDs the seed can't fill; the rest are defensive
    checks that only trip if ``seed_shop_defaults.seed_all`` never ran.
    Returns ``{"ready": bool, "missing": [{key, label, tab, why}, ...]}``.
    """
    settings = session.query(ShopSettings).filter_by(id=1).first()
    missing: list[dict] = []

    def _blank(value) -> bool:
        return value is None or (isinstance(value, str) and not value.strip())

    if settings is None:
        missing.append({
            "key": "shop_settings",
            "label": "Shop Settings",
            "tab": "operations",
            "why": "No shop settings row — run seed_shop_defaults.seed_all.",
        })

    if settings is None or _blank(settings.production_partner_id):
        missing.append({
            "key": "production_partner_id",
            "label": "Production Partner",
            "tab": "production-partner",
            "why": "Etsy rejects new listings without a production partner ID.",
        })

    if settings is None or _blank(settings.default_shipping_profile_id):
        missing.append({
            "key": "default_shipping_profile_id",
            "label": "Shipping Profile",
            "tab": "operations",
            "why": "Listings can't publish without a shipping profile.",
        })

    if session.query(PricingStrategy).first() is None:
        missing.append({
            "key": "pricing_strategy",
            "label": "Pricing Strategy",
            "tab": "pricing-strategy",
            "why": "Missing pricing rules — run seed_shop_defaults.seed_all.",
        })

    if session.query(VariationPreset).first() is None:
        missing.append({
            "key": "variation_presets",
            "label": "Variation Presets",
            "tab": "variation-presets",
            "why": "No variation presets — run seed_shop_defaults.seed_all.",
        })

    return {"ready": len(missing) == 0, "missing": missing}


# ── 1. Production Partner ────────────────────────────────────────────────────


class ProductionPartnerPatch(BaseModel):
    production_partner_id: str | None = None
    production_partner_name: str | None = None
    production_partner_about: str | None = None
    production_partner_location: str | None = None
    production_partner_q1: str | None = None
    production_partner_q2: str | None = None
    production_partner_q3: str | None = None


@router.get("/production-partner")
def get_production_partner(session: Session = Depends(get_session)):
    row = _get_or_create_settings(session)
    fields = {
        "production_partner_id",
        "production_partner_name",
        "production_partner_about",
        "production_partner_location",
        "production_partner_q1",
        "production_partner_q2",
        "production_partner_q3",
    }
    return {k: getattr(row, k) for k in fields}


@router.post("/production-partner")
def save_production_partner(
    patch: ProductionPartnerPatch,
    session: Session = Depends(get_session),
):
    row = _get_or_create_settings(session)
    _apply_updates(row, patch.model_dump(exclude_none=True), {
        "production_partner_id",
        "production_partner_name",
        "production_partner_about",
        "production_partner_location",
        "production_partner_q1",
        "production_partner_q2",
        "production_partner_q3",
    })
    session.commit()
    return get_production_partner(session)


@router.post("/production-partner/sync")
def sync_production_partner(session: Session = Depends(get_session)):
    """
    Persist the partner id supplied via the /production-partner endpoint.

    Real Etsy-side creation is deferred (Etsy Open API v3 does not expose a
    public production-partner create endpoint at the time of writing). This
    route is a no-op that acknowledges the current stored partner id — the
    frontend can wire it to a "Confirm partner" UX today.
    """
    row = _get_or_create_settings(session)
    if not row.production_partner_id:
        raise HTTPException(status_code=400, detail="production_partner_id not set")
    return {"status": "ok", "production_partner_id": row.production_partner_id}


# ── 2. Description Templates ─────────────────────────────────────────────────


_DESC_TEMPLATE_FIELDS = {
    "section_intro", "section_how_to_order", "section_materials",
    "section_packaging", "section_gift_note", "section_best_gifts_for",
    "section_have_a_question", "brass_overrides", "silver_overrides",
    "default_chain_text",
}


@router.get("/description-templates")
def list_description_templates(session: Session = Depends(get_session)):
    rows = session.query(DescriptionTemplate).all()
    return [_row_to_dict(r) for r in rows]


@router.get("/description-templates/{category}")
def get_description_template(category: str, session: Session = Depends(get_session)):
    row = session.query(DescriptionTemplate).filter_by(category=category).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"template for {category!r} not found")
    return _row_to_dict(row)


@router.post("/description-templates/{category}")
def save_description_template(
    category: str,
    payload: dict,
    session: Session = Depends(get_session),
):
    row = session.query(DescriptionTemplate).filter_by(category=category).first()
    if row is None:
        row = DescriptionTemplate(category=category)
        session.add(row)
    _apply_updates(row, payload, _DESC_TEMPLATE_FIELDS)
    session.commit()
    return _row_to_dict(row)


# ── 3. Default Attributes ────────────────────────────────────────────────────


_DEFAULT_ATTR_FIELDS = {
    "style", "theme", "holiday_default", "sustainability",
    "chain_style", "adjustable", "convertible",
    "default_occasion", "default_recipients",
}


@router.get("/default-attributes")
def list_default_attributes(session: Session = Depends(get_session)):
    rows = session.query(DefaultAttributes).all()
    return [_row_to_dict(r) for r in rows]


@router.post("/default-attributes/{category}")
def save_default_attributes(
    category: str,
    payload: dict,
    session: Session = Depends(get_session),
):
    row = session.query(DefaultAttributes).filter_by(category=category).first()
    if row is None:
        row = DefaultAttributes(category=category)
        session.add(row)
    _apply_updates(row, payload, _DEFAULT_ATTR_FIELDS)
    session.commit()
    return _row_to_dict(row)


# ── 4. Variation Presets ─────────────────────────────────────────────────────


_VARIATION_FIELDS = {
    "category", "material_type", "finishes", "lengths_inches",
    "multi_count_label", "multi_count_range", "has_length_variation",
}


@router.get("/variation-presets")
def list_variation_presets(session: Session = Depends(get_session)):
    rows = session.query(VariationPreset).order_by(VariationPreset.name).all()
    return [_row_to_dict(r) for r in rows]


@router.post("/variation-presets/{name}")
def save_variation_preset(
    name: str,
    payload: dict,
    session: Session = Depends(get_session),
):
    row = session.query(VariationPreset).filter_by(name=name).first()
    is_new = row is None
    if is_new:
        row = VariationPreset(name=name)
        session.add(row)
    _apply_updates(row, payload, _VARIATION_FIELDS)

    # `finishes` is required (NOT NULL) — a preset with no finishes builds an empty
    # variation matrix. Reject clearly instead of letting the DB raise a 500.
    if not row.finishes:
        session.rollback()
        raise HTTPException(
            status_code=400,
            detail="At least one finish is required (e.g. \"Gold, Silver, Rose\").",
        )
    if is_new and not row.category:
        session.rollback()
        raise HTTPException(status_code=400, detail="A category is required (e.g. \"necklace\").")

    session.commit()
    # Re-price products that use this preset so finish/length/multi-count edits
    # propagate to their stored variation matrix + selling_price.
    reprice = reprice_all_preset_products(session, preset_id=row.id)
    result = _row_to_dict(row)
    result["repriced"] = reprice
    return result


# ── 5. Pricing Strategy ──────────────────────────────────────────────────────


_PRICING_FIELDS = {
    "base_multiplier", "finish_offsets_pct",
    "length_base_inches", "length_price_per_extra_inch_pct",
    "loss_leader_enabled", "loss_leader_finish", "loss_leader_length",
    "loss_leader_margin_pct", "multi_count_extra_pct",
}


def _get_or_create_pricing(session: Session) -> PricingStrategy:
    row = session.query(PricingStrategy).filter_by(id=1).first()
    if row is None:
        row = PricingStrategy(id=1)
        session.add(row)
        session.commit()
    return row


@router.get("/pricing-strategy")
def get_pricing_strategy(session: Session = Depends(get_session)):
    return _row_to_dict(_get_or_create_pricing(session))


@router.post("/pricing-strategy")
def save_pricing_strategy(payload: dict, session: Session = Depends(get_session)):
    row = _get_or_create_pricing(session)
    _apply_updates(row, payload, _PRICING_FIELDS)
    session.commit()
    # Re-price all preset-linked products so existing listings reflect the new
    # strategy (manual products without a preset are left untouched).
    reprice = reprice_all_preset_products(session)
    result = _row_to_dict(row)
    result["repriced"] = reprice
    return result


# ── 6. Personalization Library ───────────────────────────────────────────────


_PERSONALIZATION_FIELDS = {
    "instruction_text", "example_text", "reference_note",
    "max_characters", "is_optional",
    "applicable_categories", "type_signature",
}


@router.get("/personalization-library")
def list_personalization_templates(session: Session = Depends(get_session)):
    rows = session.query(PersonalizationTemplate).order_by(PersonalizationTemplate.name).all()
    return [_row_to_dict(r) for r in rows]


@router.post("/personalization-library/{name}")
def save_personalization_template(
    name: str,
    payload: dict,
    session: Session = Depends(get_session),
):
    row = session.query(PersonalizationTemplate).filter_by(name=name).first()
    if row is None:
        row = PersonalizationTemplate(name=name)
        session.add(row)
    _apply_updates(row, payload, _PERSONALIZATION_FIELDS)
    session.commit()
    return _row_to_dict(row)


# ── 7. Operations (renewal, return policy, quantity, active pillars) ─────────


class OperationsPatch(BaseModel):
    renewal_option: str | None = None
    return_policy_days: int | None = None
    feature_listing_default: bool | None = None
    default_quantity: int | None = None
    omit_karat_in_title: bool | None = None
    active_pillars: list[str] | None = None
    default_shipping_profile_id: str | None = None
    image_workflow_mode: str | None = None
    auto_create_sections: bool | None = None


_OPERATIONS_FIELDS = {
    "renewal_option", "return_policy_days", "feature_listing_default",
    "default_quantity", "omit_karat_in_title", "active_pillars",
    "default_shipping_profile_id", "image_workflow_mode",
    "auto_create_sections",
}


@router.get("/operations")
def get_operations(session: Session = Depends(get_session)):
    row = _get_or_create_settings(session)
    return {k: getattr(row, k) for k in _OPERATIONS_FIELDS}


@router.post("/operations")
def save_operations(patch: OperationsPatch, session: Session = Depends(get_session)):
    row = _get_or_create_settings(session)
    _apply_updates(row, patch.model_dump(exclude_none=True), _OPERATIONS_FIELDS)
    session.commit()
    return get_operations(session)


# ── Preflight (required-settings check for the extension build gate) ──────────


@router.get("/preflight")
def get_preflight(session: Session = Depends(get_session)):
    """Report whether required shop settings are in place before a build."""
    return compute_preflight(session)


# ── 8. Shop Sections ─────────────────────────────────────────────────────────


_SECTION_FIELDS = {"etsy_section_id", "name", "carrier_pillar", "display_order"}


@router.get("/shop-sections")
def list_shop_sections(session: Session = Depends(get_session)):
    rows = (
        session.query(ShopSection)
        .order_by(ShopSection.display_order, ShopSection.name)
        .all()
    )
    return [_row_to_dict(r) for r in rows]


@router.post("/shop-sections/sync")
async def sync_shop_sections(session: Session = Depends(get_session)) -> dict:
    """Push local ShopSection rows with etsy_section_id IS NULL to Etsy.

    Idempotent: rows already synced (etsy_section_id set) are skipped by the
    query filter, so re-running is safe. Errors on individual rows are
    captured per-row so a single failure does not abort the whole sync.
    """
    from src.web.routes.etsy import _get_etsy_client

    client = _get_etsy_client()
    unsynced = (
        session.query(ShopSection)
        .filter(ShopSection.etsy_section_id.is_(None))
        .order_by(ShopSection.display_order, ShopSection.name)
        .all()
    )
    created: list[dict] = []
    errors: list[dict] = []
    for row in unsynced:
        try:
            resp = await client.create_shop_section(row.name)
            row.etsy_section_id = str(resp.get("shop_section_id"))
            created.append(
                {"name": row.name, "etsy_section_id": row.etsy_section_id}
            )
        except Exception as exc:
            _log.warning(
                "shop_section_sync_failed", name=row.name, error=str(exc)
            )
            errors.append({"name": row.name, "error": str(exc)})
    session.commit()
    return {"created": created, "errors": errors}


@router.post("/shop-sections/{name}")
def save_shop_section(
    name: str,
    payload: dict,
    session: Session = Depends(get_session),
):
    row = session.query(ShopSection).filter_by(name=name).first()
    if row is None:
        row = ShopSection(name=name)
        session.add(row)
    _apply_updates(row, payload, _SECTION_FIELDS)
    session.commit()
    return _row_to_dict(row)


@router.delete("/shop-sections/{name}")
def delete_shop_section(name: str, session: Session = Depends(get_session)):
    row = session.query(ShopSection).filter_by(name=name).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"section {name!r} not found")
    session.delete(row)
    session.commit()
    return JSONResponse({"status": "deleted"})


# ── HTML tabbed editor ───────────────────────────────────────────────────────


def _load_all_tabs(session: Session) -> dict:
    """Pre-fetch every tab's data in a single request so /settings is one round-trip."""
    settings_row = _get_or_create_settings(session)
    pricing_row = _get_or_create_pricing(session)

    partner_fields = {
        "production_partner_id",
        "production_partner_name",
        "production_partner_about",
        "production_partner_location",
        "production_partner_q1",
        "production_partner_q2",
        "production_partner_q3",
    }
    return {
        "production_partner": {k: getattr(settings_row, k) for k in partner_fields},
        "description_templates": [
            _row_to_dict(r) for r in session.query(DescriptionTemplate).all()
        ],
        "default_attributes": [
            _row_to_dict(r) for r in session.query(DefaultAttributes).all()
        ],
        "variation_presets": [
            _row_to_dict(r)
            for r in session.query(VariationPreset).order_by(VariationPreset.name).all()
        ],
        "pricing_strategy": _row_to_dict(pricing_row),
        "personalization_library": [
            _row_to_dict(r)
            for r in session.query(PersonalizationTemplate)
            .order_by(PersonalizationTemplate.name)
            .all()
        ],
        "operations": {k: getattr(settings_row, k) for k in _OPERATIONS_FIELDS},
        "shop_sections": [
            _row_to_dict(r)
            for r in session.query(ShopSection)
            .order_by(ShopSection.display_order, ShopSection.name)
            .all()
        ],
    }


@router.get("", response_class=HTMLResponse)
def settings_index(request: Request, session: Session = Depends(get_session)):
    """Tabbed HTML editor over the 8 JSON tabs (PR 3)."""
    if templates is None:
        raise HTTPException(status_code=500, detail="templates not configured")
    tabs = _load_all_tabs(session)
    return templates.TemplateResponse(
        request,
        "settings/index.html",
        {
            "tabs": tabs,
            "carrier_pillars": CARRIER_PILLARS,
            "material_types": [e.value for e in MaterialType],
            "renewal_options": [e.value for e in RenewalOption],
        },
    )
