"""
Phase 7 Routes — Human Approval UI

GET  /approval                         — Step 7.1: approval queue
GET  /approval/{sku}                   — Step 7.2: variant comparison & approval
POST /approval/{sku}/approve           — approve selected variant
POST /approval/{sku}/draft             — save as draft (no-op redirect)
POST /approval/{sku}/reject            — reject all & clear for regeneration
POST /approval/{sku}/hybrid            — save hybrid variant and approve
PATCH /approval/{sku}/variant/{vid}    — inline auto-save (JSON)
POST  /approval/{sku}/validate-field   — validate a single field (JSON)
"""
from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, Form, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.config.business_rules import MIN_IMAGES_PER_LISTING
from src.db.dependencies import get_session
from src.db.models import Product, ProductImage, ProductStatus
from src.modules.approval.service import (
    approve_hybrid_variant,
    approve_variant,
    get_approval_queue,
    get_variant_by_id,
    get_variation_matrix,
    reject_and_regenerate,
    update_variant_field,
    validate_field,
)
from src.modules.etsy.payload_builder import EtsyListingPayloadBuilder

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/approval", tags=["approval"])
templates: Jinja2Templates | None = None

STATUS_LABELS: dict[str, str] = {
    ProductStatus.MANUAL_INPUT.value:       "Manual Input",
    ProductStatus.IMAGE_PROCESSING.value:   "Image Processing",
    ProductStatus.CONTENT_GENERATING.value: "Content Generating",
    ProductStatus.AWAITING_APPROVAL.value:  "Awaiting Approval",
    ProductStatus.APPROVED.value:           "Approved",
    ProductStatus.PUBLISHED.value:          "Published",
    ProductStatus.FAILED.value:             "Failed",
}

STATUS_BADGE_CLASS: dict[str, str] = {
    ProductStatus.MANUAL_INPUT.value:       "secondary",
    ProductStatus.IMAGE_PROCESSING.value:   "info",
    ProductStatus.CONTENT_GENERATING.value: "primary",
    ProductStatus.AWAITING_APPROVAL.value:  "warning",
    ProductStatus.APPROVED.value:           "success",
    ProductStatus.PUBLISHED.value:          "success",
    ProductStatus.FAILED.value:             "danger",
}

CTR_BADGE: dict[str, str] = {
    "high":    "success",
    "medium":  "warning",
    "low":     "secondary",
    "unknown": "light",
}


def set_templates(t: Jinja2Templates) -> None:
    global templates
    templates = t


def _tmpl(name: str, request: Request, context: dict, **kwargs) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context, **kwargs)


# ── Step 7.1: Approval Queue ──────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def approval_queue(
    request: Request,
    sort: str = "newest",
    session: Session = Depends(get_session),
):
    products = get_approval_queue(session, sort=sort)

    queue_items = []
    for p in products:
        img_count = session.query(ProductImage).filter_by(product_id=p.id).count()
        queue_items.append({
            "product": p,
            "image_count": img_count,
            "low_images": img_count < MIN_IMAGES_PER_LISTING,
        })

    return _tmpl(
        "approval/queue.html",
        request,
        {
            "queue_items": queue_items,
            "sort": sort,
            "total": len(queue_items),
            "min_images": MIN_IMAGES_PER_LISTING,
        },
    )


# ── Step 7.2: Variant Comparison & Approval ───────────────────────────────────

@router.get("/{sku}", response_class=HTMLResponse)
async def approval_detail(
    sku: str,
    request: Request,
    session: Session = Depends(get_session),
):
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url="/approval", status_code=303)

    if not product.generated_variants:
        return RedirectResponse(url=f"/products/{sku}", status_code=303)

    images = (
        session.query(ProductImage)
        .filter_by(product_id=product.id)
        .order_by(ProductImage.rank)
        .all()
    )

    variants = product.generated_variants or []
    selected_id = product.selected_variant_id or (variants[0]["id"] if variants else "A")

    variations = (
        get_variation_matrix(session, product.id)
        if product.variation_preset_id is not None
        else []
    )

    return _tmpl(
        "approval/detail.html",
        request,
        {
            "product": product,
            "variants": variants,
            "selected_id": selected_id,
            "images": images,
            "variations": variations,
            "ctr_badge": CTR_BADGE,
            "status_labels": STATUS_LABELS,
            "status_badge_class": STATUS_BADGE_CLASS,
            "min_images": MIN_IMAGES_PER_LISTING,
            "low_images": len(images) < MIN_IMAGES_PER_LISTING,
        },
    )


# ── Variants as JSON (Chrome extension inline approval) ──────────────────────

@router.get("/{sku}/variants")
async def approval_variants_json(
    sku: str,
    session: Session = Depends(get_session),
):
    """JSON mirror of the approval detail page, consumed by the Chrome
    extension's inline approval step so the user can approve without leaving
    the side panel."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    variants = product.generated_variants or []
    image_count = (
        session.query(ProductImage).filter_by(product_id=product.id).count()
    )
    return JSONResponse({
        "sku": sku,
        "status": product.status,
        "status_label": STATUS_LABELS.get(product.status, product.status),
        "target_keyword": product.target_keyword,
        "selected_id": product.selected_variant_id
        or (variants[0]["id"] if variants else None),
        "image_count": image_count,
        "min_images": MIN_IMAGES_PER_LISTING,
        "variants": variants,
    })


# ── Etsy payload preview (JSON) ───────────────────────────────────────────────

@router.get("/{sku}/payload-preview")
async def payload_preview(
    sku: str,
    variant_id: str = "",
    session: Session = Depends(get_session),
):
    """Return the Etsy v3 payload that would be sent for this product / variant.

    Lazy-loaded by the approval detail page's <details> block.
    """
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    chosen = get_variant_by_id(product, variant_id) if variant_id else None
    payload = EtsyListingPayloadBuilder(session).build(product, chosen)
    return JSONResponse(jsonable_encoder(payload))


# ── Approve selected variant ──────────────────────────────────────────────────

@router.post("/{sku}/approve")
async def approve_selected(
    sku: str,
    variant_id: str = Form(...),
    overrides_json: str = Form(default="[]"),
    session: Session = Depends(get_session),
):
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url="/approval", status_code=303)

    try:
        overrides = json.loads(overrides_json)
    except Exception:
        overrides = []

    ok = approve_variant(session, product, variant_id, overrides=overrides)
    if not ok:
        return RedirectResponse(url=f"/approval/{sku}", status_code=303)

    return RedirectResponse(url=f"/products/{sku}", status_code=303)


# ── Save as draft (stay on page) ──────────────────────────────────────────────

@router.post("/{sku}/draft")
async def save_draft(
    sku: str,
    variant_id: str = Form(default=""),
    session: Session = Depends(get_session),
):
    product = session.query(Product).filter_by(sku=sku).first()
    if product and variant_id:
        product.selected_variant_id = variant_id
        session.commit()
    return RedirectResponse(url=f"/approval/{sku}", status_code=303)


# ── Reject all & clear for regeneration ──────────────────────────────────────

@router.post("/{sku}/reject")
async def reject_all(
    sku: str,
    session: Session = Depends(get_session),
):
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url="/approval", status_code=303)

    reject_and_regenerate(session, product)
    return RedirectResponse(url=f"/products/{sku}", status_code=303)


# ── Hybrid variant approval ───────────────────────────────────────────────────

@router.post("/{sku}/hybrid")
async def approve_hybrid(
    sku: str,
    title: str = Form(...),
    tags_json: str = Form(...),
    description: str = Form(...),
    source_angles_json: str = Form(default="{}"),
    overrides_json: str = Form(default="[]"),
    session: Session = Depends(get_session),
):
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url="/approval", status_code=303)

    try:
        tags = json.loads(tags_json)
    except Exception:
        tags = [t.strip() for t in tags_json.split(",") if t.strip()]

    try:
        source_angles = json.loads(source_angles_json)
    except Exception:
        source_angles = {}

    try:
        overrides = json.loads(overrides_json)
    except Exception:
        overrides = []

    approve_hybrid_variant(
        session, product, title, tags, description, source_angles, overrides=overrides
    )
    return RedirectResponse(url=f"/products/{sku}", status_code=303)


# ── Inline auto-save (JSON PATCH) ─────────────────────────────────────────────

@router.patch("/{sku}/variant/{variant_id}")
async def autosave_variant_field(
    sku: str,
    variant_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    body = await request.json()
    field = body.get("field")
    value = body.get("value")

    if not field or value is None:
        return JSONResponse({"error": "field and value required"}, status_code=422)

    ok, violations = validate_field(field, value)

    updated = update_variant_field(session, product, variant_id, field, value)
    if not updated:
        return JSONResponse({"error": "variant or field not found"}, status_code=404)

    return JSONResponse({"saved": True, "valid": ok, "violations": violations})


# ── Real-time field validation (JSON POST) ────────────────────────────────────

@router.post("/{sku}/validate-field")
async def validate_field_endpoint(
    sku: str,
    request: Request,
):
    body = await request.json()
    field = body.get("field", "")
    value = body.get("value", "")

    ok, violations = validate_field(field, value)
    return JSONResponse({"valid": ok, "violations": violations})
