"""
Etsy listing publisher (Steps 8.3 – 8.8).

Public API:
    create_listing()      — Step 8.3
    upload_images()       — Step 8.4
    set_attributes()      — Step 8.5
    assign_section()      — Step 8.6
    activate_listing()    — Step 8.7
    bulk_publish()        — Step 8.8
"""
from __future__ import annotations

import asyncio
import random
from datetime import date, datetime, timezone

import structlog
from sqlalchemy.orm import Session

from src.config.business_rules import QUANTITY_CONFIDENT
from src.config.settings import Settings
from src.db.models import Product, ProductImage, ProductStatus
from src.modules.etsy.attributes import (
    JEWELRY_NECKLACE_TAXONOMY_ID,
    build_attributes,
    is_personalized,
)
from src.modules.etsy.client import EtsyClient
from src.modules.sheets.sync import upsert_product_row

_log = structlog.get_logger(__name__)
_settings = Settings()

# ── Section cache ──────────────────────────────────────────────────────────────

_section_cache: dict[str, int] | None = None  # {pillar_name -> section_id}


async def _get_section_id(
    client: EtsyClient, carrier_pillar: str, shipping_profile_id: str
) -> int | None:
    """Resolve carrier_pillar to Etsy section_id, using a one-time cache."""
    global _section_cache

    if _section_cache is None:
        sections = await client.get_shop_sections()
        _section_cache = {s["title"].lower(): s["shop_section_id"] for s in sections}
        _log.debug("Loaded shop sections", sections=list(_section_cache.keys()))

    from src.domain.carrier_pillar import get_section_name, CarrierPillar

    try:
        section_name = get_section_name(CarrierPillar(carrier_pillar)).lower()
    except (ValueError, KeyError):
        _log.warning("Unknown carrier pillar — skipping section", pillar=carrier_pillar)
        return None

    return _section_cache.get(section_name)


# ── Step 8.3: Create listing ───────────────────────────────────────────────────

async def create_listing(
    client: EtsyClient,
    product: Product,
    shipping_profile_id: int,
    return_policy_id: int,
) -> str:
    """Create a draft listing on Etsy and return its listing_id."""
    tags: list[str] = product.final_tags or []

    payload: dict = {
        "quantity": QUANTITY_CONFIDENT,
        "title": product.final_title,
        "description": product.final_description,
        "price": float(product.selling_price),
        "who_made": "i_did",
        "when_made": "made_to_order",
        "taxonomy_id": JEWELRY_NECKLACE_TAXONOMY_ID,
        "shipping_profile_id": shipping_profile_id,
        "return_policy_id": return_policy_id,
        "tags": tags[:13],  # Etsy max = 13
        "is_personalizable": is_personalized(product),
        "personalization_is_required": False,
        "state": "draft",
    }

    resp = await client.post(
        f"/application/shops/{client.shop_id}/listings",
        json=payload,
    )
    listing_id = str(resp["listing_id"])
    _log.info("Draft listing created", sku=product.sku, listing_id=listing_id)
    return listing_id


# ── Step 8.4: Upload images ────────────────────────────────────────────────────

async def upload_images(
    client: EtsyClient,
    listing_id: str,
    images: list[ProductImage],
) -> None:
    """Upload images in rank order with human-like pacing."""
    endpoint = (
        f"/application/shops/{client.shop_id}/listings/{listing_id}/images"
    )

    for image in sorted(images, key=lambda x: x.rank):
        with open(image.file_path, "rb") as fh:
            await client.request(
                "POST",
                endpoint,
                files={"image": (image.file_path.split("/")[-1], fh, "image/jpeg")},
                data={
                    "rank": str(image.rank),
                    "alt_text": image.alt_text or "",
                },
            )
        _log.debug(
            "Image uploaded", listing_id=listing_id, rank=image.rank
        )
        await asyncio.sleep(random.uniform(1, 3))


# ── Step 8.5: Set attributes ───────────────────────────────────────────────────

async def set_attributes(
    client: EtsyClient,
    listing_id: str,
    product: Product,
) -> None:
    """Patch listing with taxonomy attributes."""
    attributes = build_attributes(product)
    if not attributes:
        return

    await client.patch(
        f"/application/shops/{client.shop_id}/listings/{listing_id}",
        json={"attributes": attributes},
    )
    _log.debug("Attributes set", listing_id=listing_id, count=len(attributes))


# ── Step 8.6: Section assignment ───────────────────────────────────────────────

async def assign_section(
    client: EtsyClient,
    listing_id: str,
    product: Product,
) -> None:
    """Assign listing to the matching shop section."""
    section_id = await _get_section_id(
        client, product.carrier_pillar, shipping_profile_id=""
    )
    if section_id is None:
        _log.warning(
            "No matching section found, skipping",
            pillar=product.carrier_pillar,
        )
        return

    await client.patch(
        f"/application/shops/{client.shop_id}/listings/{listing_id}",
        json={"shop_section_id": section_id},
    )
    _log.debug("Section assigned", listing_id=listing_id, section_id=section_id)


# ── Step 8.7: Activate listing ─────────────────────────────────────────────────

async def activate_listing(
    client: EtsyClient,
    listing_id: str,
) -> None:
    """Move listing state from draft → active."""
    await client.patch(
        f"/application/shops/{client.shop_id}/listings/{listing_id}",
        json={"state": "active"},
    )
    _log.info("Listing activated", listing_id=listing_id)


# ── Full single-product publish flow ──────────────────────────────────────────

async def publish_product(
    client: EtsyClient,
    product: Product,
    session: Session,
    shipping_profile_id: int,
    return_policy_id: int,
) -> str:
    """
    Run the full publish pipeline for one product.
    Returns the Etsy listing_id on success.
    """
    images = (
        session.query(ProductImage)
        .filter_by(product_id=product.id, is_selected=True)
        .order_by(ProductImage.rank)
        .all()
    )

    listing_id = await create_listing(
        client, product, shipping_profile_id, return_policy_id
    )
    await upload_images(client, listing_id, images)
    await set_attributes(client, listing_id, product)
    await assign_section(client, listing_id, product)
    await activate_listing(client, listing_id)

    product.etsy_listing_id = listing_id
    product.status = ProductStatus.PUBLISHED.value
    product.published_at = datetime.now(timezone.utc)
    session.commit()
    upsert_product_row(product, _settings)
    return listing_id


# ── Step 8.8: Bulk publish ─────────────────────────────────────────────────────

def _get_today_publish_count(session: Session) -> int:
    today = date.today()
    return (
        session.query(Product)
        .filter(
            Product.status == ProductStatus.PUBLISHED.value,
            Product.published_at >= datetime(today.year, today.month, today.day),
        )
        .count()
    )


def _is_new_shop(shop_creation_date: str) -> bool:
    """Return True if the shop is < 6 months old."""
    if not shop_creation_date:
        return False
    try:
        created = date.fromisoformat(shop_creation_date)
        delta = date.today() - created
        return delta.days < 183  # ~6 months
    except ValueError:
        return False


async def bulk_publish(
    client: EtsyClient,
    session: Session,
    shipping_profile_id: int,
    return_policy_id: int,
    shop_creation_date: str = "",
    approved_skus: list[str] | None = None,
) -> dict:
    """
    Publish approved products with human-like pacing.

    Args:
        approved_skus: Optional list of SKUs to publish; if None, publishes
                       all APPROVED products up to the daily limit.

    Returns:
        {"published": [...], "skipped": int, "errors": [...]}
    """
    is_new = _is_new_shop(shop_creation_date)
    max_per_day = 15 if is_new else 50

    today_count = _get_today_publish_count(session)
    remaining = max_per_day - today_count

    if remaining <= 0:
        _log.info(
            "Daily publish limit already reached",
            limit=max_per_day,
            today_count=today_count,
        )
        return {"published": [], "skipped": 0, "errors": [], "limit_reached": True}

    if approved_skus is not None:
        products = [
            session.query(Product).filter_by(sku=sku).first()
            for sku in approved_skus
        ]
        products = [p for p in products if p and p.status == ProductStatus.APPROVED.value]
    else:
        products = (
            session.query(Product)
            .filter_by(status=ProductStatus.APPROVED.value)
            .order_by(Product.approved_at)
            .all()
        )

    to_publish = products[:remaining]
    published: list[str] = []
    errors: list[dict] = []

    for i, product in enumerate(to_publish):
        try:
            listing_id = await publish_product(
                client, product, session, shipping_profile_id, return_policy_id
            )
            published.append(product.sku)
            _log.info(
                "Published",
                sku=product.sku,
                listing_id=listing_id,
                progress=f"{i + 1}/{len(to_publish)}",
            )
        except Exception as exc:
            _log.error("Failed to publish", sku=product.sku, error=str(exc))
            errors.append({"sku": product.sku, "error": str(exc)})

        if i < len(to_publish) - 1:
            wait = random.uniform(30, 90)
            _log.info("Waiting before next publish", seconds=round(wait))
            await asyncio.sleep(wait)

    return {
        "published": published,
        "skipped": len(products) - len(to_publish),
        "errors": errors,
        "limit_reached": False,
    }
