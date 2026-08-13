"""
Listing Builder JSON endpoints (Section H + I of OPERATIONAL_INTEGRATION.md).

Slim per-product entry point for the extension "Build" tab and the future
`/listings/build` page. Persists the Product + VariationRows synchronously
and kicks off the content pipeline as a background task.
"""
from __future__ import annotations

import json
from pathlib import Path

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.dependencies import get_session
from src.db.models import Product, ProductImage, ProductStatus, VariationRow
from src.modules.listings.orchestrator import (
    ListingBuildRequest,
    ListingBuilder,
    run_listing_content_pipeline,
)
from src.modules.listings.personalization_picker import PersonalizationPicker

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
        run_listing_content_pipeline, product.sku, req.deepdive_pending
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
        run_listing_content_pipeline, product.sku, req.deepdive_pending
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
