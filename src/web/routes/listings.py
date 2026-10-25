"""
Listing Builder JSON endpoints (Section H + I of OPERATIONAL_INTEGRATION.md).

Slim per-product entry point for the extension "Build" tab and the future
`/listings/build` page. Persists the Product + VariationRows synchronously
and kicks off the content pipeline as a background task.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.dependencies import get_session
from src.db.models import (
    Product,
    ProductImage,
    ProductStatus,
    VariationRow,
)
from src.modules.listings.orchestrator import (
    ListingBuildRequest,
    ListingBuilder,
    run_listing_content_pipeline,
)
from src.modules.listings.personalization_picker import PersonalizationPicker
from src.modules.listings.variant_axes import (
    STANDARD_AXES,
    affects_price_for_axis_name,
    generate_variant_rows,
    property_id_for_axis_name,
    scale_id_for_axis_name,
    seed_variant_axes_from_rexven,
)

_log = structlog.get_logger(__name__)
_settings = Settings()

router = APIRouter(prefix="/listings", tags=["listings"])


@router.post("/build")
async def build_listing(
    req: ListingBuildRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Create the Product row + variation matrix, then queue content generation.

    JSON-only entry point. For flows that also need to attach a supplier image
    (Chrome extension pulling bytes from an authenticated Rexven tab), use
    ``POST /listings/build-with-image`` instead.
    """
    builder = ListingBuilder(session)
    try:
        product = builder.build(req)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    background_tasks.add_task(
        run_listing_content_pipeline,
        product.sku,
        req.deepdive_pending,
        req.deepdive_wait_s,
    )

    return JSONResponse({
        "product_sku": product.sku,
        "product_id": product.id,
        "status": product.status,
        "poll_url": f"/listings/{product.sku}/status",
    })


@router.post("/build-with-image")
async def build_listing_with_image(
    background_tasks: BackgroundTasks,
    payload: str = Form(...),
    images: list[UploadFile] = File(...),
    session: Session = Depends(get_session),
):
    """Multipart variant of ``/listings/build`` — accepts the JSON payload as a
    string field alongside one or more supplier image files.

    Used by the Chrome extension's Listing Builder tab: because Rexven is an
    authenticated SPA, only the extension (running in the tab context) can
    fetch the product images. This endpoint receives those bytes, persists
    them as ``ProductImage(is_real=True, rank=1..N)`` rows so the image
    pipeline has references to feed the AI generators. Rank 1 is used as the
    primary reference (preprocessed → mannequin/concept generators); ranks
    2..N are preserved so the human can pick a better cover in approval.
    """
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        return JSONResponse(
            {"error": f"payload is not valid JSON: {exc}"}, status_code=400
        )
    try:
        req = ListingBuildRequest.model_validate(parsed)
    except ValidationError as exc:
        return JSONResponse({"error": exc.errors()}, status_code=422)

    if not images:
        return JSONResponse({"error": "at least one image is required"}, status_code=400)

    builder = ListingBuilder(session)
    try:
        product = builder.build(req)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    dest_dir = Path(_settings.IMAGES_DIR) / product.sku / "originals"
    dest_dir.mkdir(parents=True, exist_ok=True)

    total_bytes = 0
    saved_paths: list[str] = []
    for rank, upload in enumerate(images, start=1):
        if not upload.filename:
            continue
        safe_name = Path(upload.filename).name
        dest_path = dest_dir / safe_name
        if dest_path.exists():
            dest_path = dest_dir / f"{rank}_{safe_name}"
        contents = await upload.read()
        dest_path.write_bytes(contents)
        total_bytes += len(contents)
        saved_paths.append(str(dest_path))

        session.add(ProductImage(
            product_id=product.id,
            file_path=str(dest_path),
            rank=rank,
            is_real=True,
            workflow_source="rexven_extension",
        ))

    if not saved_paths:
        return JSONResponse({"error": "no valid image files received"}, status_code=400)

    product.original_image_path = saved_paths[0]
    session.commit()

    _log.info(
        "listing_build_with_image_saved",
        sku=product.sku,
        image_count=len(saved_paths),
        total_bytes=total_bytes,
    )

    background_tasks.add_task(
        run_listing_content_pipeline,
        product.sku,
        req.deepdive_pending,
        req.deepdive_wait_s,
    )

    return JSONResponse({
        "product_sku": product.sku,
        "product_id": product.id,
        "status": product.status,
        "poll_url": f"/listings/{product.sku}/status",
        "image_count": len(saved_paths),
        "total_bytes": total_bytes,
    })


@router.get("/{sku}/status")
async def build_status(
    sku: str,
    session: Session = Depends(get_session),
):
    """Poll endpoint used by the extension to drive its progress UI."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    redirect = None
    if product.status == ProductStatus.AWAITING_APPROVAL.value:
        redirect = f"/approval/{sku}"
    elif product.status in (
        ProductStatus.APPROVED.value,
        ProductStatus.PUBLISHED.value,
        ProductStatus.FAILED.value,
    ):
        redirect = f"/products/{sku}"

    return JSONResponse({
        "sku": sku,
        "status": product.status,
        "redirect": redirect,
    })


@router.get("/personalization-options")
async def personalization_options() -> JSONResponse:
    """Enumerate the user-facing personalization labels.

    Used by the Chrome extension's Listing Builder tab (PR 5) so the form
    stays in sync with ``PersonalizationPicker.USER_FACING_OPTIONS``.
    """
    return JSONResponse({
        "options": [
            {"label": label, "signature": signature}
            for label, signature in PersonalizationPicker.USER_FACING_OPTIONS
        ]
    })


@router.get("/{sku}/variations")
async def list_variations(
    sku: str,
    session: Session = Depends(get_session),
):
    """Return the persisted variation matrix for inspection / approval UI."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return JSONResponse({"error": "not found"}, status_code=404)

    rows = (
        session.query(VariationRow)
        .filter_by(product_id=product.id)
        .order_by(VariationRow.finish, VariationRow.length_inches, VariationRow.multi_count)
        .all()
    )
    return JSONResponse({
        "sku": sku,
        "variation_preset_id": product.variation_preset_id,
        "rows": [
            {
                "id": r.id,
                "finish": r.finish,
                "length_inches": r.length_inches,
                "multi_count": r.multi_count,
                "price_cents": r.price_cents,
                "sku_suffix": r.sku_suffix,
                "is_loss_leader": r.is_loss_leader,
            }
            for r in rows
        ],
    })


@router.post("/{sku}/variations/{row_id}/price")
async def update_variation_price(
    sku: str,
    row_id: int,
    price: float = Form(...),
    session: Session = Depends(get_session),
):
    """Edit one variant's price after the initial /build call.

    Lets a seller correct per-variant (e.g. Gold vs Silver) pricing without
    rebuilding the whole listing — picked up automatically on the next
    publish via EtsyListingPayloadBuilder._build_inventory.
    """
    row = (
        session.query(VariationRow)
        .join(Product, VariationRow.product_id == Product.id)
        .filter(Product.sku == sku, VariationRow.id == row_id)
        .first()
    )
    if row is None:
        return RedirectResponse(
            url=f"/products/{sku}?error=variation_not_found", status_code=302
        )

    row.price_cents = round(price * 100)
    session.commit()
    _log.info("variation_price_updated", sku=sku, row_id=row_id, price_cents=row.price_cents)
    return RedirectResponse(url=f"/products/{sku}?price_updated={row_id}#variants-card", status_code=302)


# ── Generic variant axes (add / rename / add-value) ────────────────────────────
# See modules/listings/variant_axes.py. These operate on Product.variant_axes
# and regenerate the axis-scheme VariationRow combinations — legacy
# (Finish/Length/MultiCount) rows are untouched and unaffected.

def _regenerate_axis_rows(session: Session, product: Product) -> None:
    """Rebuild axis-scheme VariationRows from product.variant_axes.

    A combination whose axis_values signature already existed keeps its
    (possibly manually-edited) price. Brand new combinations get a flat
    price — the lowest existing price as a base, no automatic per-value
    variance — editable per-row, or in bulk for selected rows, via
    /variations/price and /variations/bulk-price.
    """
    existing = (
        session.query(VariationRow)
        .filter(VariationRow.product_id == product.id, VariationRow.axis_values.isnot(None))
        .all()
    )
    existing_dicts = [
        {"axis_values": r.axis_values, "price_cents": r.price_cents} for r in existing
    ]
    base_price_cents = (
        min((r["price_cents"] for r in existing_dicts), default=None)
        or round(float(product.selling_price or 0) * 100)
        or 2000
    )
    for row in existing:
        session.delete(row)
    session.flush()

    new_rows = generate_variant_rows(product.variant_axes, base_price_cents, existing_dicts)
    for r in new_rows:
        session.add(VariationRow(
            product_id=product.id,
            axis_values=r["axis_values"],
            price_cents=r["price_cents"],
            sku_suffix=r["sku_suffix"],
        ))


@router.post("/{sku}/axes")
async def add_variant_axis(
    sku: str,
    name: str = Form(...),
    values: str = Form(...),
    session: Session = Depends(get_session),
):
    """Add a new variant axis, e.g. name='Birthstone', values='Ruby,Sapphire,Emerald'."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url=f"/products/{sku}?error=not_found#variants-card", status_code=302)

    value_list = [v.strip() for v in values.split(",") if v.strip()]
    if not value_list:
        return RedirectResponse(url=f"/products/{sku}?error=no_values#variants-card", status_code=302)

    axes = copy.deepcopy(product.variant_axes or [])
    if any(a["name"].lower() == name.strip().lower() for a in axes):
        return RedirectResponse(url=f"/products/{sku}?error=axis_exists#variants-card", status_code=302)

    new_axis: dict = {
        "name": name.strip(),
        "values": value_list,
        "etsy_property_id": property_id_for_axis_name(name.strip(), axes),
        "affects_price": affects_price_for_axis_name(name.strip()),
    }
    scale_id = scale_id_for_axis_name(name.strip())
    if scale_id is not None:
        new_axis["etsy_scale_id"] = scale_id
    axes.append(new_axis)
    product.variant_axes = axes
    session.flush()
    _regenerate_axis_rows(session, product)
    session.commit()
    _log.info("variant_axis_added", sku=sku, axis=name, values=value_list)
    return RedirectResponse(url=f"/products/{sku}?axis_added={name}#variants-card", status_code=302)


@router.post("/{sku}/axes/{axis_name}/rename")
async def rename_variant_axis(
    sku: str,
    axis_name: str,
    new_name: str = Form(...),
    session: Session = Depends(get_session),
):
    """Rename an axis — relabels it in variant_axes and in every row's axis_values."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url=f"/products/{sku}?error=not_found#variants-card", status_code=302)

    new_name = new_name.strip()
    axes = copy.deepcopy(product.variant_axes or [])
    axis = next((a for a in axes if a["name"] == axis_name), None)
    if axis is None or not new_name:
        return RedirectResponse(url=f"/products/{sku}?error=axis_not_found#variants-card", status_code=302)

    axis["name"] = new_name
    product.variant_axes = axes

    rows = (
        session.query(VariationRow)
        .filter(VariationRow.product_id == product.id, VariationRow.axis_values.isnot(None))
        .all()
    )
    for row in rows:
        av = dict(row.axis_values or {})
        if axis_name in av:
            av[new_name] = av.pop(axis_name)
            row.axis_values = av

    session.commit()
    _log.info("variant_axis_renamed", sku=sku, old_name=axis_name, new_name=new_name)
    return RedirectResponse(url=f"/products/{sku}?axis_renamed={new_name}#variants-card", status_code=302)


@router.post("/{sku}/axes/{axis_name}/affects-price")
async def toggle_axis_affects_price(
    sku: str,
    axis_name: str,
    session: Session = Depends(get_session),
):
    """Flip whether this axis affects price — e.g. mark Necklace length as
    not price-affecting (like a real listing's own price_on_property does),
    so its values can be bulk-priced as one group instead of per-length.
    Doesn't change existing row prices, only how they're grouped/declared.
    """
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url=f"/products/{sku}?error=not_found#variants-card", status_code=302)

    axes = copy.deepcopy(product.variant_axes or [])
    axis = next((a for a in axes if a["name"] == axis_name), None)
    if axis is None:
        return RedirectResponse(url=f"/products/{sku}?error=axis_not_found#variants-card", status_code=302)

    axis["affects_price"] = not axis.get("affects_price", True)
    product.variant_axes = axes
    session.commit()
    _log.info("variant_axis_affects_price_toggled", sku=sku, axis=axis_name, affects_price=axis["affects_price"])
    return RedirectResponse(url=f"/products/{sku}?axis_renamed={axis_name}#variants-card", status_code=302)


@router.post("/{sku}/axes/{axis_name}/values")
async def add_variant_axis_value(
    sku: str,
    axis_name: str,
    value: str = Form(...),
    session: Session = Depends(get_session),
):
    """Add one new value to an existing axis, e.g. a new color option."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url=f"/products/{sku}?error=not_found#variants-card", status_code=302)

    value = value.strip()
    axes = copy.deepcopy(product.variant_axes or [])
    axis = next((a for a in axes if a["name"] == axis_name), None)
    if axis is None or not value:
        return RedirectResponse(url=f"/products/{sku}?error=axis_not_found#variants-card", status_code=302)
    if value in axis["values"]:
        return RedirectResponse(url=f"/products/{sku}?error=value_exists#variants-card", status_code=302)

    axis["values"] = [*axis["values"], value]
    product.variant_axes = axes
    session.flush()
    _regenerate_axis_rows(session, product)
    session.commit()
    _log.info("variant_axis_value_added", sku=sku, axis=axis_name, value=value)
    return RedirectResponse(url=f"/products/{sku}?value_added={value}#variants-card", status_code=302)


@router.post("/{sku}/regenerate-from-rexven")
async def regenerate_variants_from_rexven(
    sku: str,
    session: Session = Depends(get_session),
):
    """Reset variant_axes from the product's already-captured supplier_options.

    No new network scraping — Rexven's option dropdowns only render for a
    live browser (that's what the Chrome extension's page reader is for),
    so this re-derives from whatever was captured when the product was
    built, not a fresh fetch. Destructive: replaces variant_axes entirely.
    """
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url=f"/products/{sku}?error=not_found#variants-card", status_code=302)

    axes = seed_variant_axes_from_rexven(product.supplier_options)
    if not axes:
        return RedirectResponse(url=f"/products/{sku}?error=no_supplier_options#variants-card", status_code=302)

    product.variant_axes = axes
    session.flush()
    _regenerate_axis_rows(session, product)
    session.commit()
    _log.info("variant_axes_regenerated_from_rexven", sku=sku, axes=[a["name"] for a in axes])
    return RedirectResponse(url=f"/products/{sku}?axes_regenerated=1#variants-card", status_code=302)


@router.post("/{sku}/variations/reset")
async def reset_variants(
    sku: str,
    session: Session = Depends(get_session),
):
    """Clear every variation type and pricing row — same end result as
    deleting each axis one by one, in a single action. Wipes both the
    generic axis scheme (variant_axes + axis_values rows) and any legacy
    (Finish/Length/MultiCount) rows, back to a clean slate.
    """
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url=f"/products/{sku}?error=not_found#variants-card", status_code=302)

    session.query(VariationRow).filter_by(product_id=product.id).delete()
    product.variant_axes = []
    session.commit()
    _log.info("variants_reset", sku=sku)
    return RedirectResponse(url=f"/products/{sku}?variants_reset=1#variants-card", status_code=302)


@router.post("/{sku}/axes/{axis_name}/delete")
async def delete_variant_axis(
    sku: str,
    axis_name: str,
    session: Session = Depends(get_session),
):
    """Remove a whole variation type. Regenerates rows from the remaining
    axes — if this was the last axis, that correctly leaves zero rows."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url=f"/products/{sku}?error=not_found#variants-card", status_code=302)

    axes = copy.deepcopy(product.variant_axes or [])
    remaining = [a for a in axes if a["name"] != axis_name]
    if len(remaining) == len(axes):
        return RedirectResponse(url=f"/products/{sku}?error=axis_not_found#variants-card", status_code=302)

    product.variant_axes = remaining
    session.flush()
    _regenerate_axis_rows(session, product)
    session.commit()
    _log.info("variant_axis_deleted", sku=sku, axis=axis_name)
    return RedirectResponse(url=f"/products/{sku}?axis_deleted={axis_name}#variants-card", status_code=302)


@router.post("/{sku}/axes/{axis_name}/values/{value}/delete")
async def delete_variant_axis_value(
    sku: str,
    axis_name: str,
    value: str,
    session: Session = Depends(get_session),
):
    """Remove one option value from an axis. Rejects removing the last
    value — a zero-option variation is meaningless; delete the whole axis
    instead."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url=f"/products/{sku}?error=not_found#variants-card", status_code=302)

    axes = copy.deepcopy(product.variant_axes or [])
    axis = next((a for a in axes if a["name"] == axis_name), None)
    if axis is None or value not in axis["values"]:
        return RedirectResponse(url=f"/products/{sku}?error=value_not_found#variants-card", status_code=302)
    if len(axis["values"]) <= 1:
        return RedirectResponse(url=f"/products/{sku}?error=last_value#variants-card", status_code=302)

    axis["values"] = [v for v in axis["values"] if v != value]
    product.variant_axes = axes
    session.flush()
    _regenerate_axis_rows(session, product)
    session.commit()
    _log.info("variant_axis_value_deleted", sku=sku, axis=axis_name, value=value)
    return RedirectResponse(url=f"/products/{sku}?value_deleted={value}#variants-card", status_code=302)


@router.post("/{sku}/variations/{row_id}/delete")
async def delete_variation_row(
    sku: str,
    row_id: int,
    session: Session = Depends(get_session),
):
    """Remove one specific pricing-table combination without touching the
    axis/value it's made of (e.g. disable just Gold+Twist while keeping
    every other Gold and every other Twist combination)."""
    row = (
        session.query(VariationRow)
        .join(Product, VariationRow.product_id == Product.id)
        .filter(Product.sku == sku, VariationRow.id == row_id)
        .first()
    )
    if row is None:
        return RedirectResponse(url=f"/products/{sku}?error=variation_not_found#variants-card", status_code=302)

    session.delete(row)
    session.commit()
    _log.info("variation_row_deleted", sku=sku, row_id=row_id)
    return RedirectResponse(url=f"/products/{sku}?row_deleted=1#variants-card", status_code=302)


@router.post("/{sku}/variations/restore-missing")
async def restore_missing_variations(
    sku: str,
    session: Session = Depends(get_session),
):
    """Refill any combination missing from the current axes — including one
    removed via delete_variation_row, which otherwise has no way back.
    Re-runs the same regeneration add_variant_axis/etc. already trigger, but
    without changing any axis, so every row still present keeps its price and
    only the missing ones reappear (auto-priced)."""
    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url=f"/products/{sku}?error=not_found#variants-card", status_code=302)
    if not product.variant_axes:
        return RedirectResponse(url=f"/products/{sku}?error=no_axes#variants-card", status_code=302)

    _regenerate_axis_rows(session, product)
    session.commit()
    _log.info("variations_restored_missing", sku=sku)
    return RedirectResponse(url=f"/products/{sku}?variations_restored=1#variants-card", status_code=302)


@router.post("/{sku}/variations/bulk-price")
async def bulk_update_variation_price(
    sku: str,
    price: float = Form(...),
    row_ids: list[int] = Form(default=[]),
    session: Session = Depends(get_session),
):
    """Set one price across several checked pricing-table rows at once —
    type a price, check the rows it applies to, apply; repeat for other
    price tiers. Rows left unchecked keep their current price."""
    if not row_ids:
        return RedirectResponse(url=f"/products/{sku}?error=no_rows_selected#variants-card", status_code=302)

    product = session.query(Product).filter_by(sku=sku).first()
    if product is None:
        return RedirectResponse(url=f"/products/{sku}?error=not_found#variants-card", status_code=302)

    price_cents = round(price * 100)
    # Scoped to this product's own rows (not just the posted ids) — row_ids
    # come from client form input, so this also guards against an id for a
    # different product's row ever being touched.
    updated = (
        session.query(VariationRow)
        .filter(VariationRow.product_id == product.id, VariationRow.id.in_(row_ids))
        .update({VariationRow.price_cents: price_cents}, synchronize_session=False)
    )
    session.commit()
    _log.info("variation_bulk_price_applied", sku=sku, row_ids=row_ids, price_cents=price_cents, updated=updated)
    return RedirectResponse(url=f"/products/{sku}?bulk_price_applied={updated}#variants-card", status_code=302)
