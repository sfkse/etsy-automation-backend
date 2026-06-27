"""
Product Input Module Routes (Phase 4)

GET  /products              — list all products
GET  /products/new          — manual input form
POST /products/new          — create product from form
GET  /products/{sku}        — product detail
POST /products/{sku}/process — trigger pipeline (stub → Phase 5 fills in real logic)
GET  /products/{sku}/progress — polling progress page
GET  /products/{sku}/status  — JSON status endpoint for JS polling
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.dependencies import get_session
from src.db.models import Product, ProductImage, ProductStatus
from src.domain.carrier_pillar import CarrierPillar
from src.modules.images.comparison import run_comparison
from src.modules.images.pipeline import run_image_pipeline
from src.modules.input import generate_sku, save_product_images

router = APIRouter(prefix="/products", tags=["products"])
templates: Jinja2Templates | None = None


def set_templates(t: Jinja2Templates) -> None:
    global templates
    templates = t


def _tmpl(name: str, request: Request, context: dict, **kwargs) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context, **kwargs)


_settings = Settings()

# ── Dropdown option lists ──────────────────────────────────────────────────────

PILLAR_OPTIONS = [p.value for p in CarrierPillar]

MATERIAL_OPTIONS = ["Gold Plated", "Brass", "925 Sterling Silver"]

SHAPE_OPTIONS = [
    "Round", "Oval", "Square", "Heart", "Star", "Cross",
    "Leaf", "Moon", "Flower", "Teardrop", "Rectangle", "Custom",
]

STYLE_OPTIONS = [
    "Minimalist", "Personalized", "Floral", "Bohemian",
    "Classic", "Modern", "Vintage", "Statement",
]

OCCASION_OPTIONS = [
    "Birthday", "Anniversary", "Wedding", "Everyday",
    "Religious", "Pet Memorial", "Graduation", "Gifts for Mom",
    "Valentine's Day", "Christmas",
]

RECIPIENT_OPTIONS = [
    "For Her", "For Him", "For Mom", "For Sister",
    "For Best Friend", "For Wife", "For Daughter", "Unisex",
]

WORKFLOW_OPTIONS = ["gemini", "openai", "flux"]

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


# ── Product List ───────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def product_list(
    request: Request,
    sort: str = "newest",
    session: Session = Depends(get_session),
):
    q = session.query(Product)
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
            "sort": sort,
            "status_labels": STATUS_LABELS,
            "status_badge_class": STATUS_BADGE_CLASS,
        },
    )


# ── New Product Form ───────────────────────────────────────────────────────────

@router.get("/new", response_class=HTMLResponse)
async def new_product_form(request: Request):
    return _tmpl(
        "products/new.html", request,
        {
            "error": None,
            "pillar_options": PILLAR_OPTIONS,
            "material_options": MATERIAL_OPTIONS,
            "shape_options": SHAPE_OPTIONS,
            "style_options": STYLE_OPTIONS,
            "occasion_options": OCCASION_OPTIONS,
            "recipient_options": RECIPIENT_OPTIONS,
        },
    )


@router.post("/new", response_class=HTMLResponse)
async def create_product(
    request: Request,
    carrier_pillar: str = Form(...),
    material: str = Form(...),
    color: str = Form(""),
    has_stone: bool = Form(False),
    stone_type: str = Form(""),
    shape: str = Form(""),
    style: str = Form(""),
    occasion: list[str] = Form(default=[]),
    recipient: str = Form(""),
    size_info: str = Form(""),
    cost: float = Form(...),
    selling_price: float = Form(...),
    primary_image: UploadFile = File(...),
    extra_images: list[UploadFile] = File(default=[]),
    session: Session = Depends(get_session),
):
    # Validate primary image
    if not primary_image.filename:
        return _tmpl(
            "products/new.html", request,
            {
                "error": "At least one product image is required.",
                "pillar_options": PILLAR_OPTIONS,
                "material_options": MATERIAL_OPTIONS,
                "shape_options": SHAPE_OPTIONS,
                "style_options": STYLE_OPTIONS,
                "occasion_options": OCCASION_OPTIONS,
                "recipient_options": RECIPIENT_OPTIONS,
            },
            status_code=422,
        )

    sku = generate_sku(session)

    saved = await save_product_images(
        sku=sku,
        primary_file=primary_image,
        extra_files=extra_images,
        images_dir=_settings.IMAGES_DIR,
    )

    product = Product(
        sku=sku,
        carrier_pillar=carrier_pillar,
        material=material,
        color=color or None,
        has_stone=has_stone,
        stone_type=stone_type or None,
        shape=shape or None,
        style=style or None,
        occasion=", ".join(occasion) if occasion else None,
        recipient=recipient or None,
        size_info=size_info or None,
        cost=cost,
        selling_price=selling_price,
        status=ProductStatus.MANUAL_INPUT.value,
    )
    session.add(product)
    session.flush()  # get product.id

    for img_data in saved:
        session.add(ProductImage(
            product_id=product.id,
            file_path=img_data["file_path"],
            rank=img_data["rank"],
            is_real=img_data["is_real"],
            is_selected=img_data["rank"] == 1,
        ))

    session.commit()
    return RedirectResponse(url=f"/products/{sku}", status_code=303)


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
                "sort": "newest",
                "status_labels": STATUS_LABELS,
                "status_badge_class": STATUS_BADGE_CLASS,
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

    return _tmpl(
        "products/detail.html", request,
        {
            "product": product,
            "images": images,
            "status_labels": STATUS_LABELS,
            "status_badge_class": STATUS_BADGE_CLASS,
            "workflow_options": WORKFLOW_OPTIONS,
            "default_workflow": _settings.DEFAULT_IMAGE_WORKFLOW,
        },
    )


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
    for wf in ["gemini", "openai", "flux"]:
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
