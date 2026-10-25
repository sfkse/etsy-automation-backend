"""
Product Input Module Routes (Phase 4)

GET  /products              — list all products
GET  /products/{sku}        — product detail
POST /products/{sku}/process — trigger pipeline (stub → Phase 5 fills in real logic)
GET  /products/{sku}/progress — polling progress page
GET  /products/{sku}/status  — JSON status endpoint for JS polling
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path as _DeletePath

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, selectinload

from src.config.settings import Settings
from src.db.dependencies import get_session
from src.db.models import (
    ApprovalOverride,
    PricingStrategy,
    Product,
    ProductImage,
    ProductStats,
    ProductStatus,
    RenewLog,
    ShopSettings,
    VariationRow,
)
from src.modules.images import regen_jobs
from src.modules.listings.variant_axes import STANDARD_AXES, price_groups
from src.modules.images.comparison import run_comparison
from src.modules.images.jewelry_set import DEFAULT_PALETTE, palette_choices
from src.modules.images.pipeline import run_image_pipeline
from src.modules.images.static_assets import (
    asset_stem,
    attach_asset,
    attached_assets,
    detach_asset,
    list_assets,
    remove_from_library,
    save_uploaded_asset,
)
from src.modules.images.regenerate import (
    SLOT_ORDER,
    _slot_path,
    generate_slot_candidates,
    regenerate_slot,
    select_candidate,
    valid_slot,
)
from src.modules.video import video_jobs
from src.modules.video.factory import DURATION_OPTIONS, VideoWorkflowFactory
from src.modules.video.generate import (
    default_motion_prompt_for_slot,
    generate_slot_video,
    video_path,
)
from src.modules.products.service import (
    EDITABLE_PRODUCT_FIELDS,
    update_product_field,
    validate_product_field,
)
from src.modules.sheets.sync import upsert_product_row

router = APIRouter(prefix="/products", tags=["products"])
templates: Jinja2Templates | None = None


def set_templates(t: Jinja2Templates) -> None:
    global templates
    templates = t


def _tmpl(name: str, request: Request, context: dict, **kwargs) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context, **kwargs)


_settings = Settings()

# ── Dropdown option lists ──────────────────────────────────────────────────────

WORKFLOW_OPTIONS = ["gemini", "openai"]

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


def _currency_context(session: Session) -> dict:
    """Display-only currency symbol/position (PricingStrategy.currency_symbol)
    — Etsy prices by the shop's own currency regardless; this just controls
    how this app's own admin pages show prices (e.g. "kr" suffix for SEK)."""
    pricing = session.query(PricingStrategy).filter_by(id=1).first()
    return {
        "currency_symbol": (pricing.currency_symbol if pricing else None) or "$",
        "currency_position": (pricing.currency_symbol_position if pricing else None) or "prefix",
    }


def _variant_row_label(row: VariationRow) -> str:
    """Human-readable combination label, matching the template's own display
    logic (generic axis_values dict, or legacy finish/length/multi_count)."""
    if row.axis_values:
        return " / ".join(str(v) for v in row.axis_values.values())
    parts = [row.finish or ""]
    if row.length_inches:
        parts.append(f'{row.length_inches}"')
    if row.multi_count:
        parts.append(str(row.multi_count))
    return " / ".join(p for p in parts if p)


def _region_price_preview(session: Session, variation_rows: list[VariationRow]) -> dict:
    """Preview what each variant row would cost per shipping-profile region,
    using today's PricingStrategy.region_price_adjustments_pct — read-only,
    doesn't publish or change anything. Powers the "Preview by region" modal.
    """
    regions = list(_settings.SHIPPING_PROFILES.keys())
    if not regions or not variation_rows:
        return {"regions": [], "rows": []}

    pricing = session.query(PricingStrategy).filter_by(id=1).first()
    adjustments = (pricing.region_price_adjustments_pct if pricing else None) or {}
    multipliers = {r: 1.0 + (adjustments.get(r, 0.0) or 0.0) / 100.0 for r in regions}

    rows = []
    for row in variation_rows:
        base = row.price_cents / 100.0
        rows.append({
            "label": _variant_row_label(row),
            "prices": {r: round(base * multipliers[r], 2) for r in regions},
        })
    return {"regions": regions, "rows": rows}


# ── Product List ───────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def product_list(
    request: Request,
    sort: str = "newest",
    session: Session = Depends(get_session),
):
    # Images are eager-loaded for the row thumbnails — the relationship is lazy,
    # so without this the list fires one extra query per product.
    q = session.query(Product).options(selectinload(Product.images))
    if sort == "oldest":
        q = q.order_by(Product.created_at.asc())
    elif sort == "sku":
        q = q.order_by(Product.sku.asc())
    elif sort == "status":
        q = q.order_by(Product.status.asc(), Product.created_at.desc())
    else:
        q = q.order_by(Product.created_at.desc())

    products = q.all()
    return _tmpl(
        "products/list.html", request,
        {
            "products": products,
            "thumbs": {p.sku: _thumb_url(p) for p in products},
            "sort": sort,
            "status_labels": STATUS_LABELS,
            "status_badge_class": STATUS_BADGE_CLASS,
            **_currency_context(session),
        },
    )


# ── Product Detail ─────────────────────────────────────────────────────────────

@router.get("/{sku}", response_class=HTMLResponse)
async def product_detail(
    sku: str,
    request: Request,
    session: Session = Depends(get_session),
):
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return _tmpl(
            "products/list.html", request,
            {
                "products": [],
                "thumbs": {},
                "sort": "newest",
                "status_labels": STATUS_LABELS,
                "status_badge_class": STATUS_BADGE_CLASS,
                **_currency_context(session),
                "error": f"Product {sku} not found.",
            },
            status_code=404,
        )

    images = (
        session.query(ProductImage)
        .filter_by(product_id=product.id)
        .order_by(ProductImage.rank)
        .all()
    )
    # Cache-bust each URL by file mtime so a regenerated (overwritten-in-place)
    # photo shows the latest version instead of the browser's cached copy.
    for img in images:
        if not img.file_path:
            img.cache_url = None
            continue
        url = "/images/" + img.file_path.split("data/images/")[-1]
        try:
            url += f"?v={int(_DeletePath(img.file_path).stat().st_mtime)}"
        except OSError:
            pass
        img.cache_url = url

    variation_rows = (
        session.query(VariationRow)
        .filter_by(product_id=product.id)
        .order_by(VariationRow.finish, VariationRow.length_inches, VariationRow.multi_count)
        .all()
    )

    region_price_preview = _region_price_preview(session, variation_rows)

    return _tmpl(
        "products/detail.html", request,
        {
            "product": product,
            "images": images,
            "variation_rows": variation_rows,
            "standard_axes": STANDARD_AXES,
            "price_groups": price_groups(variation_rows, product.variant_axes or []),
            "region_price_preview": region_price_preview,
            "status_labels": STATUS_LABELS,
            "status_badge_class": STATUS_BADGE_CLASS,
            "workflow_options": WORKFLOW_OPTIONS,
            "default_workflow": _settings.DEFAULT_IMAGE_WORKFLOW,
            **_currency_context(session),
        },
    )


# ── Inline field auto-save (post-approval editing) ─────────────────────────────

@router.patch("/{sku}/field")
async def autosave_product_field(
    sku: str,
    request: Request,
    session: Session = Depends(get_session),
):
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    if product.status not in (ProductStatus.APPROVED.value, ProductStatus.PUBLISHED.value):
        return JSONResponse(
            {"error": f"editing not allowed in status '{product.status}'"},
            status_code=409,
        )

    body = await request.json()
    field = body.get("field")
    value = body.get("value")

    if not field or value is None:
        return JSONResponse({"error": "field and value required"}, status_code=422)
    if field not in EDITABLE_PRODUCT_FIELDS:
        return JSONResponse({"error": f"field '{field}' is not editable"}, status_code=422)

    ok, violations = validate_product_field(field, value)
    updated, coerced, err = update_product_field(session, product, field, value)
    if not updated:
        return JSONResponse({"saved": False, "error": err}, status_code=422)

    return JSONResponse({"saved": True, "valid": ok, "violations": violations})


# ── Process Product ────────────────────────────────────────────────────────────

@router.post("/{sku}/process")
async def process_product(
    sku: str,
    background_tasks: BackgroundTasks,
    workflow: str = Form(_settings.DEFAULT_IMAGE_WORKFLOW),
    session: Session = Depends(get_session),
):
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url="/products", status_code=303)

    product.image_workflow_used = workflow
    product.status = ProductStatus.IMAGE_PROCESSING.value
    session.commit()
    upsert_product_row(product, _settings)

    background_tasks.add_task(_run_pipeline_bg, sku, workflow)

    return RedirectResponse(url=f"/products/{sku}/progress", status_code=303)


async def _run_pipeline_bg(sku: str, workflow: str) -> None:
    """Background task: run image pipeline and handle failures gracefully."""
    from src.db.session import SessionLocal

    with SessionLocal() as bg_session:
        product = bg_session.query(Product).filter_by(sku=sku).first()
        if product is None:
            return
        try:
            await run_image_pipeline(product, bg_session, _settings)
        except Exception:
            product.status = ProductStatus.FAILED.value
            bg_session.commit()
            upsert_product_row(product, _settings)


# ── Progress Polling Page ──────────────────────────────────────────────────────

@router.get("/{sku}/progress", response_class=HTMLResponse)
async def product_progress(
    sku: str,
    request: Request,
    session: Session = Depends(get_session),
):
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url="/products", status_code=303)

    return _tmpl(
        "products/progress.html", request,
        {
            "product": product,
            "status_labels": STATUS_LABELS,
            "status_badge_class": STATUS_BADGE_CLASS,
        },
    )


# ── Comparison Workflow ────────────────────────────────────────────────────────

@router.post("/{sku}/generate-comparison")
async def generate_comparison(
    sku: str,
    session: Session = Depends(get_session),
):
    """Run all 3 AI workflows on the same prompt and redirect to comparison view."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    results = await run_comparison(product, session, _settings)
    comparison_data = [
        {
            "workflow": r.workflow_name,
            "file_path": r.file_path,
            "elapsed_seconds": r.elapsed_seconds,
            "cost_estimate": r.cost_estimate,
            "success": r.success,
            "error": r.error,
        }
        for r in results
    ]
    return JSONResponse({"sku": sku, "results": comparison_data})


@router.get("/{sku}/comparison", response_class=HTMLResponse)
async def comparison_page(
    sku: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Show comparison UI for the 3 AI workflow outputs."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url="/products", status_code=303)

    from pathlib import Path as _Path

    comp_dir = _Path(_settings.IMAGES_DIR) / sku / "comparison"
    workflow_results = []
    for wf in ["gemini", "openai"]:
        img_path = comp_dir / f"{wf}.png"
        workflow_results.append({
            "workflow": wf,
            "exists": img_path.exists(),
            "url": f"/images/{sku}/comparison/{wf}.png" if img_path.exists() else None,
        })

    return _tmpl(
        "products/comparison.html", request,
        {
            "product": product,
            "workflow_results": workflow_results,
            "status_labels": STATUS_LABELS,
            "status_badge_class": STATUS_BADGE_CLASS,
        },
    )


@router.post("/{sku}/select-workflow")
async def select_workflow(
    sku: str,
    workflow: str = Form(...),
    session: Session = Depends(get_session),
):
    """Save the user's preferred workflow selection for this product."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url="/products", status_code=303)

    product.image_workflow_used = workflow
    session.commit()
    return RedirectResponse(url=f"/products/{sku}", status_code=303)


# ── Status JSON (for JS polling) ───────────────────────────────────────────────

@router.get("/{sku}/status")
async def product_status(
    sku: str,
    session: Session = Depends(get_session),
):
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    status = product.status
    redirect = None
    if status == ProductStatus.AWAITING_APPROVAL.value:
        redirect = f"/approval/{sku}"
    elif status in (ProductStatus.APPROVED.value, ProductStatus.PUBLISHED.value, ProductStatus.FAILED.value):
        redirect = f"/products/{sku}"

    return JSONResponse({
        "status": status,
        "label": STATUS_LABELS.get(status, status),
        "redirect": redirect,
    })


# ── Per-slot image management (regenerate / compare backends) ──────────────────


def _slot_of(file_path: str) -> str | None:
    """Derive the slot id (e.g. 'mannequin-1') from an AI image filename."""
    name = file_path.rsplit("/", 1)[-1]
    for slot in SLOT_ORDER:
        if name.endswith(f"-{slot}.jpg"):
            return slot
    return None


def _slot_public_url(file_path: str | None) -> str | None:
    """Public ``/images/...`` URL for a slot photo, cache-busted by file mtime.

    The ``?v=<mtime>`` suffix makes a regenerated (overwritten-in-place) photo
    show on refresh instead of the browser's cached copy of the same URL.
    """
    if not file_path:
        return None
    url = "/images/" + file_path.split("data/images/")[-1]
    try:
        url += f"?v={int(_DeletePath(file_path).stat().st_mtime)}"
    except OSError:
        pass
    return url


def _thumb_url(product: Product) -> str | None:
    """Best available preview photo for a products-list row.

    Prefers the primary photo, then the lowest-ranked one, and falls back to the
    supplier's original capture — so a row shows something from the moment the
    extension uploads the Rexven image, long before the AI set exists.
    """
    candidates = [i for i in (product.images or []) if i.file_path]
    chosen = next((i for i in candidates if i.is_selected), None)
    if chosen is None and candidates:
        chosen = min(candidates, key=lambda i: (i.rank is None, i.rank or 0))
    return _slot_public_url(
        chosen.file_path if chosen else product.original_image_path
    )


@router.get("/{sku}/images", response_class=HTMLResponse)
async def images_page(
    sku: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Per-slot image manager: 6 photos, each regenerable / comparable."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url="/products", status_code=303)

    rows = (
        session.query(ProductImage)
        .filter_by(product_id=product.id, is_real=False)
        .all()
    )
    by_slot = {}
    for r in rows:
        slot = _slot_of(r.file_path or "")
        if slot:
            by_slot[slot] = r

    shop_settings = session.query(ShopSettings).filter_by(id=1).first()
    default_palette = getattr(shop_settings, "image_palette", None) or DEFAULT_PALETTE

    slots = []
    for slot in SLOT_ORDER:
        row = by_slot.get(slot)
        url = _slot_public_url(row.file_path if row else None)
        vpath = video_path(product, _settings, slot)
        slots.append({
            "slot": slot,
            "label": slot.replace("-", " ").title(),
            "url": url,
            "video_url": _slot_public_url(str(vpath)) if vpath.exists() else None,
            "workflow": row.workflow_source if row else None,
            "instructions": (row.regen_instructions if row else "") or "",
            "palette": (row.palette_used if row else None) or default_palette,
            "default_motion_prompt": default_motion_prompt_for_slot(slot),
        })

    return _tmpl(
        "products/images.html", request,
        {
            "product": product,
            "slots": slots,
            "workflows": ["gemini", "openai"],
            "palettes": palette_choices(),
            "default_palette": default_palette,
            "attached_assets": _attached_asset_items(product, session),
            "video_models": VideoWorkflowFactory.available_workflows(),
            "video_duration_options": DURATION_OPTIONS,
            "status_labels": STATUS_LABELS,
            "status_badge_class": STATUS_BADGE_CLASS,
        },
    )


@router.post("/{sku}/images/regenerate")
async def images_regenerate(
    sku: str,
    background_tasks: BackgroundTasks,
    slot: str = Form(...),
    workflow: str = Form(...),
    instructions: str = Form(""),
    palette: str = Form(""),
    session: Session = Depends(get_session),
):
    """Kick off a per-slot regeneration as a background task.

    Returns immediately with ``{"status": "started"}`` — the work outlives this
    request, and its progress is tracked in ``regen_jobs`` so the images page can
    show a spinner (even after a reload) and swap in the finished photo by polling
    ``/images/status``.
    """
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not valid_slot(slot):
        return JSONResponse({"error": f"invalid slot {slot}"}, status_code=400)
    if regen_jobs.is_running(sku, slot):
        return JSONResponse(
            {"error": f"slot {slot} is already regenerating"}, status_code=409
        )

    regen_jobs.mark_running(sku, slot)
    background_tasks.add_task(
        _regenerate_bg, sku, slot, workflow, instructions, palette
    )
    return JSONResponse({"status": "started", "slot": slot, "workflow": workflow})


async def _regenerate_bg(
    sku: str, slot: str, workflow: str, instructions: str, palette: str
) -> None:
    """Background worker: regenerate one slot with its own DB session.

    Always clears the ``regen_jobs`` running flag (recording the error on
    failure) so a stuck slot can never spin forever.
    """
    from src.db.session import SessionLocal

    error: str | None = None
    try:
        with SessionLocal() as bg_session:
            product = bg_session.query(Product).filter_by(sku=sku).first()
            if product is None:
                return
            await regenerate_slot(
                product, bg_session, _settings, slot, workflow, instructions, palette
            )
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    finally:
        regen_jobs.mark_done(sku, slot, error=error)


@router.get("/{sku}/images/status")
async def images_status(
    sku: str,
    session: Session = Depends(get_session),
):
    """Per-slot regeneration status for JS polling on the images page."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    rows = (
        session.query(ProductImage)
        .filter_by(product_id=product.id, is_real=False)
        .all()
    )
    by_slot = {}
    for r in rows:
        s = _slot_of(r.file_path or "")
        if s:
            by_slot[s] = r

    running = regen_jobs.running_slots(sku)
    slots = {}
    for slot in SLOT_ORDER:
        row = by_slot.get(slot)
        slots[slot] = {
            "running": slot in running,
            "url": _slot_public_url(row.file_path if row else None),
            "workflow": row.workflow_source if row else None,
            "error": regen_jobs.error_of(sku, slot),
        }

    return JSONResponse({"slots": slots, "any_running": bool(running)})


# ── Common images (asset library) ────────────────────────────────────────────


def _attached_asset_items(product: Product, session: Session) -> list[dict]:
    return [
        {
            "image_id": row.id,
            "stem": asset_stem(row),
            "label": asset_stem(row).replace("_", " ").replace("-", " ").title(),
            "url": _slot_public_url(row.file_path),
        }
        for row in attached_assets(product, session)
    ]


@router.get("/{sku}/assets")
async def assets_list(sku: str, session: Session = Depends(get_session)):
    """The asset library plus what this product already has attached."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({
        "library": list_assets(_settings),
        "attached": _attached_asset_items(product, session),
    })


@router.post("/{sku}/assets")
async def assets_attach(
    sku: str,
    name: str = Form(...),
    session: Session = Depends(get_session),
):
    """Add one library image to the product (idempotent)."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    # Off the event loop: decoding + re-encoding a multi-MB PNG takes a moment.
    row = await asyncio.to_thread(attach_asset, product, session, _settings, name)
    if row is None:
        return JSONResponse({"error": f"{name!r} is not in the asset library"}, status_code=404)
    session.commit()
    return JSONResponse({"attached": _attached_asset_items(product, session)})


@router.delete("/{sku}/assets/{image_id}")
async def assets_detach(
    sku: str,
    image_id: int,
    session: Session = Depends(get_session),
):
    """Remove an attached library image from the product."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not detach_asset(product, session, image_id):
        return JSONResponse({"error": "not an attached asset"}, status_code=404)
    session.commit()
    return JSONResponse({"attached": _attached_asset_items(product, session)})


@router.post("/{sku}/assets/library")
async def assets_upload(
    sku: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """Add a new image to the shared library (not product-specific — ``sku``
    is only used to shape the response like the other asset endpoints)."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    data = await file.read()
    try:
        # Off the event loop: decoding + re-encoding the upload takes a moment.
        await asyncio.to_thread(save_uploaded_asset, _settings, file.filename or "asset", data)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    return JSONResponse({
        "library": list_assets(_settings),
        "attached": _attached_asset_items(product, session),
    })


@router.delete("/{sku}/assets/library/{name}")
async def assets_remove_from_library(
    sku: str,
    name: str,
    session: Session = Depends(get_session),
):
    """Remove an image from the shared library.

    Leaves any product's already-attached copy alone (``attach_asset`` copies
    the file into that product's own folder) — this only affects what future
    attaches can choose from.
    """
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not remove_from_library(_settings, name):
        return JSONResponse({"error": f"{name!r} is not in the asset library"}, status_code=404)
    return JSONResponse({
        "library": list_assets(_settings),
        "attached": _attached_asset_items(product, session),
    })


@router.post("/{sku}/images/compare")
async def images_compare(
    sku: str,
    slot: str = Form(...),
    instructions: str = Form(""),
    palette: str = Form(""),
    session: Session = Depends(get_session),
):
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not valid_slot(slot):
        return JSONResponse({"error": f"invalid slot {slot}"}, status_code=400)
    candidates = await generate_slot_candidates(
        product, session, _settings, slot, instructions=instructions, palette=palette
    )
    return JSONResponse({
        "slot": slot,
        "candidates": [
            {
                "workflow": c.workflow,
                "model_name": c.model_name,
                "url": c.url,
                "success": c.success,
                "elapsed_seconds": c.elapsed_seconds,
                "cost_estimate": c.cost_estimate,
                "error": c.error,
            }
            for c in candidates
        ],
    })


@router.post("/{sku}/images/select")
async def images_select(
    sku: str,
    slot: str = Form(...),
    workflow: str = Form(...),
    instructions: str = Form(""),
    palette: str = Form(""),
    session: Session = Depends(get_session),
):
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not valid_slot(slot):
        return JSONResponse({"error": f"invalid slot {slot}"}, status_code=400)
    try:
        row = select_candidate(
            product, session, _settings, slot, workflow, instructions, palette
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=500)
    url = "/images/" + row.file_path.split("data/images/")[-1]
    return JSONResponse({
        "slot": slot, "workflow": workflow, "url": url,
        "cache_url": f"{url}?t={int(__import__('time').time())}",
    })


# ── Per-slot short video clips (image-to-video) ────────────────────────────────


@router.post("/{sku}/images/video")
async def images_video(
    sku: str,
    background_tasks: BackgroundTasks,
    slot: str = Form(...),
    prompt: str = Form(""),
    duration: str = Form(""),
    model: str = Form("dop"),
    session: Session = Depends(get_session),
):
    """Kick off a per-slot video-clip generation as a background task.

    Mirrors ``images_regenerate``: the work outlives this request and its
    progress is tracked in ``video_jobs`` so the page can restore a spinner after
    a reload and swap in the finished clip by polling ``/images/video/status``.
    """
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not valid_slot(slot):
        return JSONResponse({"error": f"invalid slot {slot}"}, status_code=400)
    if model not in VideoWorkflowFactory.available_workflows():
        return JSONResponse({"error": f"invalid model {model}"}, status_code=400)
    if not _slot_path(product, _settings, slot).exists():
        return JSONResponse(
            {"error": f"slot {slot} has no image to animate yet"}, status_code=400
        )
    if video_jobs.is_running(sku, slot):
        return JSONResponse(
            {"error": f"slot {slot} video is already generating"}, status_code=409
        )

    duration_int = int(duration) if duration.strip().isdigit() else None
    video_jobs.mark_running(sku, slot)
    background_tasks.add_task(
        _generate_video_bg, sku, slot, prompt, duration_int, model
    )
    return JSONResponse({"status": "started", "slot": slot})


async def _generate_video_bg(
    sku: str, slot: str, prompt: str, duration: int | None, model: str
) -> None:
    """Background worker: generate one slot's clip with its own DB session.

    Always clears the ``video_jobs`` running flag (recording the error on
    failure) so a stuck slot can never spin forever.
    """
    from src.db.session import SessionLocal

    error: str | None = None
    try:
        with SessionLocal() as bg_session:
            product = bg_session.query(Product).filter_by(sku=sku).first()
            if product is None:
                return
            await generate_slot_video(
                product, bg_session, _settings, slot, prompt, duration, workflow=model
            )
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    finally:
        video_jobs.mark_done(sku, slot, error=error)


@router.get("/{sku}/images/video/status")
async def images_video_status(
    sku: str,
    session: Session = Depends(get_session),
):
    """Per-slot video-generation status for JS polling on the images page."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    running = video_jobs.running_slots(sku)
    slots = {}
    for slot in SLOT_ORDER:
        vpath = video_path(product, _settings, slot)
        slots[slot] = {
            "running": slot in running,
            "url": _slot_public_url(str(vpath)) if vpath.exists() else None,
            "error": video_jobs.error_of(sku, slot),
        }

    return JSONResponse({"slots": slots, "any_running": bool(running)})


# ── Delete a product and all connected assets ──────────────────────────────────

@router.post("/{sku}/delete")
async def delete_product(
    sku: str,
    session: Session = Depends(get_session),
):
    """Permanently delete a product, its DB child rows, and its image files.

    Removes: ProductImage, ProductStats, ApprovalOverride, RenewLog and
    VariationRow rows, the Product itself, and the entire on-disk image
    directory ``{IMAGES_DIR}/{sku}/`` (originals, preprocessed, ai_generated,
    candidates, comparison, charts).
    """
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url="/products", status_code=303)

    pid = product.id
    for model in (ProductImage, ProductStats, ApprovalOverride, RenewLog, VariationRow):
        session.query(model).filter_by(product_id=pid).delete(synchronize_session=False)
    session.delete(product)
    session.commit()

    # Remove image files on disk (best-effort — DB delete already committed).
    img_dir = _DeletePath(_settings.IMAGES_DIR) / sku
    if img_dir.exists():
        shutil.rmtree(img_dir, ignore_errors=True)

    return RedirectResponse(url="/products", status_code=303)
