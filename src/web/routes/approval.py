"""
Phase 7 Routes — Human Approval UI

GET  /approval                         — Step 7.1: approval queue (?skus= scopes it to one build batch)
GET  /approval/{sku}                   — Step 7.2: variant comparison & approval
POST /approval/{sku}/approve           — approve selected variant
POST /approval/{sku}/draft             — save as draft (no-op redirect)
POST /approval/{sku}/reject            — reject all & clear for regeneration
POST /approval/{sku}/hybrid            — save hybrid variant and approve
PATCH /approval/{sku}/variant/{vid}    — inline auto-save (JSON)
POST  /approval/{sku}/validate-field   — validate a single field (JSON)
POST  /approval/{sku}/variant/{vid}/regenerate — redo ONE field of ONE variant (JSON)
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, Form, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.config.business_rules import MIN_IMAGES_PER_LISTING
from src.db.dependencies import get_session
from src.db.models import Product, ProductImage, ProductStatus
from src.modules.approval.service import (
    COPY_PASTE_FIELDS,
    QUEUE_STATUS_FILTERS,
    approve_hybrid_variant,
    approve_variant,
    get_approval_queue,
    get_copy_progress,
    get_variant_by_id,
    get_variation_matrix,
    publish_variants,
    reject_and_regenerate,
    set_etsy_url,
    toggle_copy_progress,
    update_variant_field,
    validate_field,
)
from src.modules.content.regenerate import (
    REGENERABLE_FIELDS,
    RegenerationError,
    regenerate_variant_field,
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

# (value, label) for the queue's filter tabs — ordered as they render.
QUEUE_STATUS_TABS: tuple[tuple[str, str], ...] = (
    ("pending",   "Pending"),
    ("approved",  "Approved"),
    ("published", "Published"),
    ("all",       "All"),
)

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
    status: str = "",
    skus: str = "",
    session: Session = Depends(get_session),
):
    # skus= scopes the queue to one build batch (the Chrome extension's hand-off
    # link). A batch is routinely a mix of awaiting-approval and already-approved
    # rows, so it defaults to "all" — the usual "pending" default would hide half
    # of what the user just built.
    sku_filter = [s.strip() for s in skus.split(",") if s.strip()]

    if not status:
        status = "all" if sku_filter else "pending"
    if status not in QUEUE_STATUS_FILTERS:
        status = "pending"

    products = get_approval_queue(
        session, sort=sort, status_filter=status, skus=sku_filter
    )

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
            "status_filter": status,
            "sku_filter": sku_filter,
            "skus_param": ",".join(sku_filter),
            "status_tabs": QUEUE_STATUS_TABS,
            "total": len(queue_items),
            "min_images": MIN_IMAGES_PER_LISTING,
            "status_labels": STATUS_LABELS,
            "status_badge_class": STATUS_BADGE_CLASS,
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
    # Attach a cache-busted URL per image so a regenerated (overwritten-in-place)
    # photo shows the latest version instead of the browser's cached copy of the
    # same URL. Mirrors the ?v=<mtime> pattern used by the per-slot images page.
    for img in images:
        if not img.file_path:
            img.cache_url = None
            continue
        url = "/images/" + img.file_path.split("data/images/")[-1]
        try:
            url += f"?v={int(Path(img.file_path).stat().st_mtime)}"
        except OSError:
            pass
        img.cache_url = url

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
            "published_variant_ids": product.published_variant_ids or [],
            "images": images,
            "variations": variations,
            "ctr_badge": CTR_BADGE,
            "status_labels": STATUS_LABELS,
            "status_badge_class": STATUS_BADGE_CLASS,
            "min_images": MIN_IMAGES_PER_LISTING,
            "low_images": len(images) < MIN_IMAGES_PER_LISTING,
        },
    )


# ── Bulk image download (ZIP) ─────────────────────────────────────────────────

@router.get("/{sku}/images.zip")
async def approval_images_zip(
    sku: str,
    session: Session = Depends(get_session),
):
    """Stream all of a product's images as a single ZIP so the user can grab
    every photo in one click (from the Chrome extension's approved step and the
    web approval detail page) instead of right-click-saving each thumbnail."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    images = (
        session.query(ProductImage)
        .filter_by(product_id=product.id)
        .order_by(ProductImage.rank)
        .all()
    )

    buffer = io.BytesIO()
    written = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, img in enumerate(images, start=1):
            if not img.file_path:
                continue
            path = Path(img.file_path)
            if not path.is_file():
                continue
            # Rank-prefix keeps a stable, human-readable order in the archive.
            arcname = f"{idx:02d}-{path.name}"
            zf.write(path, arcname=arcname)
            written += 1

    if written == 0:
        return JSONResponse({"error": "no images"}, status_code=404)

    buffer.seek(0)
    filename = f"etsy-{sku}-images.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
    payload = EtsyListingPayloadBuilder(session).build(product, chosen_variant=chosen)
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

    approve_variant(session, product, variant_id, overrides=overrides)

    # Stay on the variants page — the other variants remain useful (and
    # publishable) after one is approved, so approving must not navigate away
    # from them. The page renders for any status.
    return RedirectResponse(url=f"/approval/{sku}", status_code=303)


# ── Publish selected variants as separate listings ────────────────────────────

@router.post("/{sku}/publish")
async def publish_selected(
    sku: str,
    variant_ids: list[str] = Form(default=[]),
    session: Session = Depends(get_session),
):
    """Mark the checked variants as published (each is its own Etsy listing) and
    redirect to the copy-paste helper. No Etsy API call — the user pastes manually.

    Both approval-detail submit buttons post here: "Publish Selected as Separate
    Listings" sends the checkbox group; "Publish Only Best" sends a single id."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url="/approval", status_code=303)

    if not publish_variants(session, product, variant_ids):
        # Nothing valid selected — bounce back to the comparison view.
        return RedirectResponse(url=f"/approval/{sku}", status_code=303)

    return RedirectResponse(
        url=f"/approval/{sku}/copy-paste-helper", status_code=303
    )


# ── Copy-paste helper (per-variant manual publish workflow) ────────────────────

@router.get("/{sku}/copy-paste-helper", response_class=HTMLResponse)
async def copy_paste_helper(
    sku: str,
    request: Request,
    session: Session = Depends(get_session),
):
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url="/approval", status_code=303)

    published = product.published_variant_ids or []
    if not published:
        return RedirectResponse(url=f"/approval/{sku}", status_code=303)

    builder = EtsyListingPayloadBuilder(session)
    progress = get_copy_progress(session, product.id)
    etsy_urls = product.etsy_urls or {}

    panels = []
    for vid in published:
        variant = get_variant_by_id(product, vid) or {}
        payload = builder.build(product, variant_id=vid)
        tags = payload.get("tags", []) or []
        panels.append({
            "variant_id": vid,
            "strategy_label": variant.get("strategy_label", ""),
            "title": payload.get("title", ""),
            "tags": tags,
            "tags_csv": ", ".join(tags),
            "description": payload.get("description", ""),
            "checked_fields": progress.get(vid, []),
            "all_checked": len(progress.get(vid, [])) >= len(COPY_PASTE_FIELDS),
            "etsy_url": etsy_urls.get(vid, ""),
        })

    return _tmpl(
        "approval/copy_paste_helper.html",
        request,
        {
            "product": product,
            "panels": panels,
            "copy_fields": COPY_PASTE_FIELDS,
            "status_labels": STATUS_LABELS,
            "status_badge_class": STATUS_BADGE_CLASS,
        },
    )


@router.post("/{sku}/copy-progress")
async def update_copy_progress(
    sku: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Persist one checklist toggle. Returns whether the variant is now fully
    checked so the client can reveal the Etsy-URL input."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    body = await request.json()
    variant_id = body.get("variant_id", "")
    field = body.get("field", "")
    checked = bool(body.get("checked", False))

    if not variant_id or field not in COPY_PASTE_FIELDS:
        return JSONResponse({"error": "variant_id and valid field required"}, status_code=422)

    all_checked = toggle_copy_progress(session, product.id, variant_id, field, checked)
    return JSONResponse({"ok": True, "all_checked": all_checked})


@router.post("/{sku}/etsy-url")
async def save_etsy_url(
    sku: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Save the Etsy listing URL the user pasted back for a published variant."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    body = await request.json()
    variant_id = body.get("variant_id", "")
    url = (body.get("url") or "").strip()
    if not variant_id:
        return JSONResponse({"error": "variant_id required"}, status_code=422)

    set_etsy_url(session, product, variant_id, url)
    return JSONResponse({"saved": True})


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
    return RedirectResponse(url=f"/approval/{sku}", status_code=303)


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

    # Tag rules compare against the paired title (wasted slots, material
    # coherence), so hand the stored title through.
    variant = get_variant_by_id(product, variant_id) or {}
    ok, violations = validate_field(field, value, paired_title=variant.get("title", ""))

    updated = update_variant_field(session, product, variant_id, field, value)
    if not updated:
        return JSONResponse({"error": "variant or field not found"}, status_code=404)

    return JSONResponse({"saved": True, "valid": ok, "violations": violations})


# ── Per-field regeneration (JSON POST) ────────────────────────────────────────

@router.post("/{sku}/variant/{variant_id}/regenerate")
async def regenerate_variant_field_endpoint(
    sku: str,
    variant_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Redo ONE field of ONE variant. Costs a single LLM call; no re-scrape.

    Runs inline rather than as a background task: one field is one call, so the
    caller can hold a spinner instead of polling a progress page.
    """
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    body = await request.json()
    field = body.get("field", "")
    if field not in REGENERABLE_FIELDS:
        return JSONResponse(
            {"error": f"field must be one of {sorted(REGENERABLE_FIELDS)}"},
            status_code=422,
        )

    variant = get_variant_by_id(product, variant_id)
    if variant is None:
        return JSONResponse({"error": "variant not found"}, status_code=404)

    # Built here rather than at import time — it opens an LLM client.
    from src.web.routes.content import _build_orchestrator

    try:
        result = await regenerate_variant_field(
            product, variant, field, _build_orchestrator(session), session=session
        )
    except RegenerationError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except Exception as exc:  # noqa: BLE001 — surface the reason to the UI
        _log.exception("variant_regen_failed", sku=sku, variant=variant_id, field=field)
        return JSONResponse({"error": f"Regeneration failed: {exc}"}, status_code=500)

    # Persist field by field so a regen never clobbers an unsaved inline edit to
    # a field it did not touch.
    for name, value in result["updates"].items():
        update_variant_field(session, product, variant_id, name, value)

    updated = result["updates"]
    ok, violations = validate_field(
        field,
        updated.get(field),
        paired_title=updated.get("title", variant.get("title", "")),
    )
    return JSONResponse({
        "regenerated": True,
        "field": field,
        "updates": updated,
        "notes": result["notes"],
        "valid": ok,
        "violations": violations,
    })


# ── Real-time field validation (JSON POST) ────────────────────────────────────

@router.post("/{sku}/validate-field")
async def validate_field_endpoint(
    sku: str,
    request: Request,
    session: Session = Depends(get_session),
):
    body = await request.json()
    field = body.get("field", "")
    value = body.get("value", "")

    # The caller may send the in-progress title alongside (hybrid editor); fall
    # back to the stored variant's title so tag rules stay title-aware.
    paired_title = body.get("paired_title", "")
    if not paired_title and (variant_id := body.get("variant_id", "")):
        product = session.query(Product).filter_by(sku=sku).first()
        if product is not None:
            paired_title = (get_variant_by_id(product, variant_id) or {}).get("title", "")

    ok, violations = validate_field(field, value, paired_title=paired_title)
    return JSONResponse({"valid": ok, "violations": violations})
