"""
Listing Builder JSON endpoints (Section H + I of OPERATIONAL_INTEGRATION.md).

Slim per-product entry point for the extension "Build" tab and the future
`/listings/build` page. Persists the Product + VariationRows synchronously
and kicks off the content pipeline as a background task.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.db.dependencies import get_session
from src.db.models import Product, ProductStatus, VariationRow
from src.modules.listings.orchestrator import (
    ListingBuildRequest,
    ListingBuilder,
    run_listing_content_pipeline,
)
from src.modules.listings.personalization_picker import PersonalizationPicker

_log = structlog.get_logger(__name__)

router = APIRouter(prefix="/listings", tags=["listings"])


@router.post("/build")
async def build_listing(
    req: ListingBuildRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    """Create the Product row + variation matrix, then queue content generation."""
    builder = ListingBuilder(session)
    try:
        product = builder.build(req)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    background_tasks.add_task(run_listing_content_pipeline, product.sku)

    return JSONResponse({
        "product_sku": product.sku,
        "product_id": product.id,
        "status": product.status,
        "poll_url": f"/listings/{product.sku}/status",
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
