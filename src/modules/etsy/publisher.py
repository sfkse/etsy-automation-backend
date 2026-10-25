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

import httpx
import structlog
from sqlalchemy.orm import Session

from src.config.business_rules import QUANTITY_CONFIDENT
from src.config.settings import Settings
from src.db.models import PricingStrategy, Product, ProductImage, ProductStatus
from src.modules.etsy.attributes import (
    JEWELRY_NECKLACE_TAXONOMY_ID,
    build_attributes,
    is_personalized,
)
from src.modules.etsy.client import EtsyClient
from src.modules.sheets.sync import upsert_product_row
from src.utils.exceptions import EtsyPartialListingError

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


# ── Readiness-state cache ───────────────────────────────────────────────────────
# Etsy added a required readiness_state_id on physical listings (processing-time
# profile) after this pipeline was first built; create_listing 400s without it.

_readiness_state_id_cache: int | None = None


async def _get_readiness_state_id(client: EtsyClient) -> int | None:
    """Resolve the shop's readiness_state_id, using a one-time cache."""
    global _readiness_state_id_cache

    if _readiness_state_id_cache is None:
        definitions = await client.get_readiness_state_definitions()
        if definitions:
            _readiness_state_id_cache = definitions[0]["readiness_state_id"]
            _log.info(
                "Loaded shop readiness state",
                readiness_state_id=_readiness_state_id_cache,
                readiness_state=definitions[0].get("readiness_state"),
            )
        else:
            _log.warning("No readiness-state definitions found for shop")

    return _readiness_state_id_cache


def _region_price_multiplier(session: "Session | None", region: "str | None") -> float:
    """1.0 + PricingStrategy.region_price_adjustments_pct[region]/100.

    Used by the legacy flat-price payload (create_listing's non-variation
    branch) — the variation-aware path applies the same logic itself via
    EtsyListingPayloadBuilder._region_price_multiplier.
    """
    if not region or session is None:
        return 1.0
    pricing = session.query(PricingStrategy).filter_by(id=1).first()
    adjustments = (pricing.region_price_adjustments_pct if pricing else None) or {}
    pct = adjustments.get(region, 0.0) or 0.0
    return 1.0 + pct / 100.0


# ── Step 8.3: Create listing ───────────────────────────────────────────────────

async def build_full_listing_payload(
    client: EtsyClient,
    product: Product,
    shipping_profile_id: int,
    return_policy_id: int,
    session: "Session | None" = None,
    region: "str | None" = None,
) -> dict:
    """Build the exact request payload(s) create_listing would send, without
    sending them — the single source of truth both the real publish path
    and the read-only "preview payload" page build from, so a preview can
    never drift from what actually gets sent.

    Returns {"listing": <POST .../listings body>,
             "inventory": <PUT .../inventory body> | None}.
    """
    if product.variation_preset_id and session is not None:
        from src.modules.etsy.payload_builder import EtsyListingPayloadBuilder

        builder = EtsyListingPayloadBuilder(session)
        payload = builder.build(product, region=region)

        # Etsy split: variation inventory travels through the separate
        # inventory endpoint, so pop it before the create-listing call.
        inventory = payload.pop("inventory", None)
        payload.setdefault("shipping_profile_id", shipping_profile_id)
        payload["return_policy_id"] = return_policy_id
        payload["taxonomy_id"] = JEWELRY_NECKLACE_TAXONOMY_ID
        readiness_state_id = await _get_readiness_state_id(client)
        if readiness_state_id is not None:
            payload.setdefault("readiness_state_id", readiness_state_id)
        if inventory and inventory.get("products"):
            first_price = inventory["products"][0]["offerings"][0]["price"]
            payload.setdefault("price", first_price)
            payload.setdefault("quantity", inventory["products"][0]["offerings"][0]["quantity"])
            if readiness_state_id is not None:
                for inv_product in inventory["products"]:
                    for offering in inv_product.get("offerings", []):
                        offering.setdefault("readiness_state_id", readiness_state_id)
        return {"listing": payload, "inventory": inventory}

    tags: list[str] = product.final_tags or []
    region_multiplier = _region_price_multiplier(session, region) if session is not None else 1.0

    payload = {
        "quantity": QUANTITY_CONFIDENT,
        "title": product.final_title,
        "description": product.final_description,
        "price": round(float(product.selling_price) * region_multiplier, 2),
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
    readiness_state_id = await _get_readiness_state_id(client)
    if readiness_state_id is not None:
        payload["readiness_state_id"] = readiness_state_id
    return {"listing": payload, "inventory": None}


async def create_listing(
    client: EtsyClient,
    product: Product,
    shipping_profile_id: int,
    return_policy_id: int,
    session: "Session | None" = None,
    region: "str | None" = None,
) -> str:
    """Create a draft listing on Etsy and return its listing_id.

    When the product carries a `variation_preset_id` (Listing Builder flow),
    delegates payload assembly to ``EtsyListingPayloadBuilder`` and, after
    creation, uploads the variation matrix via ``update_inventory``. Legacy
    manual-input products keep the pre-existing single-price payload.

    region: see publish_product_multi_profile — applies that region's
    PricingStrategy.region_price_adjustments_pct on top of the price(s).
    """
    if product.variation_preset_id and session is not None:
        return await _create_listing_with_variations(
            client, product, session, shipping_profile_id, return_policy_id, region
        )

    payloads = await build_full_listing_payload(
        client, product, shipping_profile_id, return_policy_id, session, region
    )
    resp = await client.post(
        f"/application/shops/{client.shop_id}/listings",
        json=payloads["listing"],
    )
    listing_id = str(resp["listing_id"])
    _log.info("Draft listing created", sku=product.sku, listing_id=listing_id)
    return listing_id


async def _create_listing_with_variations(
    client: EtsyClient,
    product: Product,
    session: "Session",
    shipping_profile_id: int,
    return_policy_id: int,
    region: "str | None" = None,
) -> str:
    """Create the listing using the operational-integration payload builder."""
    payloads = await build_full_listing_payload(
        client, product, shipping_profile_id, return_policy_id, session, region
    )
    payload = payloads["listing"]
    inventory = payloads["inventory"]

    resp = await client.post(
        f"/application/shops/{client.shop_id}/listings",
        json=payload,
    )
    listing_id = str(resp["listing_id"])
    _log.info(
        "Draft listing (variation) created",
        sku=product.sku,
        listing_id=listing_id,
        variation_count=len(inventory.get("products", [])) if inventory else 0,
    )

    if inventory and inventory.get("products"):
        # Deliberately not swallowed: the draft above has no real variants,
        # SKU, or per-variant price without this call succeeding. Raised as
        # EtsyPartialListingError (not a bare exception) because this runs
        # before _create_draft_listing's own try block, so a plain
        # raise here would otherwise reach the caller unwrapped and lose
        # track of this orphaned draft's listing_id.
        try:
            await client.update_inventory(listing_id, inventory)
        except Exception as exc:
            raise EtsyPartialListingError(listing_id, str(exc)) from exc

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


async def activate_listing_for_region(
    client: EtsyClient,
    product: Product,
    region: str,
) -> str:
    """Manually activate the draft already created for *region*.

    Deliberate, explicit action — publish_product/publish_product_multi_profile
    never call this automatically; the user reviews the draft on Etsy first.
    Raises KeyError if no listing exists yet for that region.
    """
    listing_id = (product.etsy_listing_ids_by_profile or {})[region]
    await activate_listing(client, listing_id)
    return listing_id


# ── Full single-listing publish flow (create → image → attrs → section, draft only)

async def _create_draft_listing(
    client: EtsyClient,
    product: Product,
    session: Session,
    shipping_profile_id: int,
    return_policy_id: int,
    region: "str | None" = None,
) -> str:
    """Run create→image→attributes→section for ONE Etsy listing and leave it
    as a draft — activation is a separate, deliberate step
    (`activate_listing_for_region`), never automatic.

    Shared by the single-profile (`publish_product`) and multi-profile
    (`publish_product_multi_profile`) entry points below. Returns listing_id.
    """
    images = (
        session.query(ProductImage)
        .filter_by(product_id=product.id, is_real=False)
        .order_by(ProductImage.rank)
        .all()
    )

    listing_id = await create_listing(
        client, product, shipping_profile_id, return_policy_id, session=session, region=region
    )
    try:
        await upload_images(client, listing_id, images)
        await set_attributes(client, listing_id, product)
        await assign_section(client, listing_id, product)
    except Exception as exc:
        # The draft above was already created on Etsy — surface its id rather
        # than letting the caller lose track of an orphaned draft.
        raise EtsyPartialListingError(listing_id, str(exc)) from exc
    return listing_id


async def publish_product(
    client: EtsyClient,
    product: Product,
    session: Session,
    shipping_profile_id: int,
    return_policy_id: int,
) -> str:
    """
    Run the full publish pipeline for one product, as a single DRAFT listing.
    Returns the Etsy listing_id on success.
    """
    listing_id = await _create_draft_listing(
        client, product, session, shipping_profile_id, return_policy_id
    )

    product.etsy_listing_id = listing_id
    product.status = ProductStatus.PUBLISHED.value
    product.published_at = datetime.now(timezone.utc)
    session.commit()
    upsert_product_row(product, _settings)
    return listing_id


# ── Multi-shipping-profile publish ─────────────────────────────────────────────

async def _listing_exists(client: EtsyClient, listing_id: str) -> bool:
    """True if *listing_id* still exists on Etsy.

    Catches the case where the user deletes a listing directly on Etsy —
    without this, a region recorded as "published" locally stays skipped
    forever, since nothing ever tells the pipeline it's actually gone.
    A non-404 error (network blip, auth hiccup) is re-raised rather than
    silently treated as "deleted", so a transient failure can't trigger an
    unwanted republish of a listing that's still live.
    """
    try:
        await client.get(f"/application/listings/{listing_id}")
        return True
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return False
        raise


async def publish_product_multi_profile(
    client: EtsyClient,
    product: Product,
    session: Session,
    shipping_profiles: dict[str, int],
    return_policy_id: int,
) -> dict:
    """
    Publish *product* as one separate Etsy listing per shipping profile, e.g.
    {"US": 315790228947, "UK": 315791560277, "DE": 315791900979}, so buyers in
    each region see that region's shipping rates. A failure on one profile
    doesn't block the others — each is attempted independently, and a profile
    that already has a listing (e.g. from an earlier partial run) is skipped,
    unless that listing was deleted directly on Etsy since, in which case it's
    republished instead of skipped forever.

    Returns {"published": {region: listing_id}, "failed": {region: error}}.
    """
    published: dict[str, str] = dict(product.etsy_listing_ids_by_profile or {})
    drafts: dict[str, str] = dict(product.etsy_draft_listing_ids_by_profile or {})
    failed: dict[str, str] = {}

    for region in list(published):
        if not await _listing_exists(client, published[region]):
            stale_id = published.pop(region)
            if product.etsy_listing_id == stale_id:
                product.etsy_listing_id = None
            _log.warning(
                "Recorded listing no longer exists on Etsy — republishing",
                sku=product.sku, region=region, listing_id=stale_id,
            )

    pending = [
        (region, pid) for region, pid in shipping_profiles.items() if region not in published
    ]

    for i, (region, shipping_profile_id) in enumerate(pending):
        try:
            listing_id = await _create_draft_listing(
                client, product, session, shipping_profile_id, return_policy_id, region=region
            )
            published[region] = listing_id
            drafts.pop(region, None)
            _log.info(
                "Published to profile", sku=product.sku, region=region, listing_id=listing_id
            )
        except EtsyPartialListingError as exc:
            # Draft exists on Etsy (orphaned) but never reached active — keep
            # its id so it's visible for manual review instead of silently lost.
            drafts[region] = exc.listing_id
            failed[region] = str(exc)
            _log.error(
                "Partial publish — orphaned draft left on Etsy",
                sku=product.sku,
                region=region,
                draft_listing_id=exc.listing_id,
                error=str(exc),
            )
        except Exception as exc:
            failed[region] = str(exc)
            _log.error(
                "Failed to publish to profile", sku=product.sku, region=region, error=str(exc)
            )

        if i < len(pending) - 1:
            await asyncio.sleep(random.uniform(5, 15))

    product.etsy_listing_ids_by_profile = published
    product.etsy_draft_listing_ids_by_profile = drafts
    if published:
        if not product.etsy_listing_id:
            product.etsy_listing_id = next(iter(published.values()))
        product.status = ProductStatus.PUBLISHED.value
        product.published_at = datetime.now(timezone.utc)
    session.commit()
    if published:
        upsert_product_row(product, _settings)

    return {"published": published, "failed": failed, "drafts": drafts}


# ── Step 8.8: Bulk publish ─────────────────────────────────────────────────────

def _get_today_listing_count(session: Session) -> int:
    """Count actual Etsy listings created today, not products.

    Etsy's daily new-listing cap is per listing, and one product can now
    produce up to len(shipping_profiles) listings — so that's what has to be
    weighed against the limit, not the number of Product rows.
    """
    today = date.today()
    products_today = (
        session.query(Product)
        .filter(
            Product.status == ProductStatus.PUBLISHED.value,
            Product.published_at >= datetime(today.year, today.month, today.day),
        )
        .all()
    )
    return sum(len(p.etsy_listing_ids_by_profile or {}) for p in products_today)


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
    shipping_profiles: dict[str, int],
    return_policy_id: int,
    shop_creation_date: str = "",
    approved_skus: list[str] | None = None,
) -> dict:
    """
    Publish approved products with human-like pacing. Each product becomes
    one Etsy listing per entry in *shipping_profiles* (see
    publish_product_multi_profile).

    Args:
        approved_skus: Optional list of SKUs to publish; if None, publishes
                       all APPROVED products up to the daily limit.

    Returns:
        {"published": [...], "skipped": int, "errors": [...]}
    """
    is_new = _is_new_shop(shop_creation_date)
    max_per_day = 15 if is_new else 50

    today_count = _get_today_listing_count(session)
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

    # Each product can create up to len(shipping_profiles) listings — stay
    # conservative and budget for the full set per product rather than
    # overrunning Etsy's daily cap on a partial-failure undercount.
    profiles_per_product = max(len(shipping_profiles), 1)
    products_capacity = max(remaining // profiles_per_product, 0)
    to_publish = products[:products_capacity]
    published: list[str] = []
    errors: list[dict] = []

    for i, product in enumerate(to_publish):
        try:
            result = await publish_product_multi_profile(
                client, product, session, shipping_profiles, return_policy_id
            )
            if result["published"]:
                published.append(product.sku)
            for region, err in result["failed"].items():
                entry = {"sku": product.sku, "region": region, "error": err}
                if region in result.get("drafts", {}):
                    entry["draft_listing_id"] = result["drafts"][region]
                errors.append(entry)
            _log.info(
                "Published",
                sku=product.sku,
                listings=result["published"],
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
