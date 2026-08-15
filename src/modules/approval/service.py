"""
Phase 7 — Approval Service

Business logic for the human approval flow:
- Fetching approval queue
- Applying variant selection
- Inline field auto-save
- Hybrid variant composition
- Validator-with-override logging
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.models import (
    ApprovalOverride,
    CopyPasteProgress,
    Product,
    ProductStatus,
    VariationRow,
)
from src.domain.validators import validate_tags, validate_title
from src.modules.sheets.sync import upsert_product_row

_settings = Settings()

_log = structlog.get_logger(__name__)


# ── Queue ─────────────────────────────────────────────────────────────────────


def get_approval_queue(session: Session, sort: str = "newest") -> list[Product]:
    """Return all products in AWAITING_APPROVAL with generated variants."""
    q = session.query(Product).filter(
        Product.status == ProductStatus.AWAITING_APPROVAL.value,
        Product.generated_variants.isnot(None),
    )
    if sort == "oldest":
        q = q.order_by(Product.created_at.asc())
    else:
        q = q.order_by(Product.created_at.desc())
    return q.all()


# ── Variation matrix (for approval UI) ────────────────────────────────────────


def get_variation_matrix(session: Session, product_id: int) -> list[dict]:
    """Flattened Finish x Length x MultiCount rows for the approval detail UI."""
    rows = (
        session.query(VariationRow)
        .filter_by(product_id=product_id)
        .order_by(
            VariationRow.finish,
            VariationRow.length_inches,
            VariationRow.multi_count,
        )
        .all()
    )
    return [
        {
            "finish": r.finish,
            "length_inches": r.length_inches,
            "multi_count": r.multi_count,
            "price_cents": r.price_cents,
            "sku_suffix": r.sku_suffix,
            "is_loss_leader": r.is_loss_leader,
        }
        for r in rows
    ]


# ── Variant helpers ───────────────────────────────────────────────────────────


def get_variant_by_id(product: Product, variant_id: str) -> dict | None:
    if not product.generated_variants:
        return None
    for v in product.generated_variants:
        if v.get("id") == variant_id:
            return v
    return None


def update_variant_field(
    session: Session,
    product: Product,
    variant_id: str,
    field: str,
    value: Any,
) -> bool:
    """
    Mutate a single field inside product.generated_variants and persist.
    Returns True if the variant was found and updated.
    """
    if not product.generated_variants:
        return False

    allowed_fields = {"title", "tags", "description"}
    if field not in allowed_fields:
        return False

    variants: list[dict] = copy.deepcopy(product.generated_variants)
    updated = False
    for v in variants:
        if v.get("id") == variant_id:
            v[field] = value
            updated = True
            break

    if updated:
        product.generated_variants = variants
        session.commit()
        _log.info("variant_field_updated", sku=product.sku, variant=variant_id, field=field)
    return updated


# ── Approval ──────────────────────────────────────────────────────────────────


def approve_variant(
    session: Session,
    product: Product,
    variant_id: str,
    overrides: list[dict] | None = None,
) -> bool:
    """
    Finalise approval: copy the selected variant into final_* fields,
    advance status to APPROVED, record any validator overrides.

    overrides: list of {"field": str, "violation": str} dicts supplied by the user.
    """
    variant = get_variant_by_id(product, variant_id)
    if variant is None:
        return False

    product.final_title = variant.get("title", "")
    product.final_tags = variant.get("tags", [])
    product.final_description = variant.get("description", "")
    product.selected_variant_id = variant_id
    product.approved_at = datetime.utcnow()
    product.status = ProductStatus.APPROVED.value

    if overrides:
        for ov in overrides:
            session.add(ApprovalOverride(
                product_id=product.id,
                field_name=ov.get("field", ""),
                violation=ov.get("violation", ""),
                overridden_value=ov.get("value", ""),
            ))

    session.commit()
    upsert_product_row(product, _settings)
    _log.info("product_approved", sku=product.sku, variant=variant_id)
    return True


def approve_hybrid_variant(
    session: Session,
    product: Product,
    title: str,
    tags: list[str],
    description: str,
    source_angles: dict[str, str],
    overrides: list[dict] | None = None,
) -> None:
    """
    Create a HYBRID variant from mixed fields and approve it immediately.

    source_angles: {"title": "A", "tags": "B", "description": "C"} — which
                   variant each field came from.
    """
    hybrid: dict = {
        "id": "HYBRID",
        "strategy_label": "Hybrid (user composed)",
        "strategy_rationale": _build_hybrid_rationale(source_angles),
        "title": title,
        "tags": tags,
        "description": description,
        "estimated_ctr_signal": "unknown",
    }

    variants: list[dict] = copy.deepcopy(product.generated_variants or [])
    existing_hybrid = next((i for i, v in enumerate(variants) if v.get("id") == "HYBRID"), None)
    if existing_hybrid is not None:
        variants[existing_hybrid] = hybrid
    else:
        variants.append(hybrid)

    product.generated_variants = variants
    product.final_title = title
    product.final_tags = tags
    product.final_description = description
    product.selected_variant_id = "HYBRID"
    product.approved_at = datetime.utcnow()
    product.status = ProductStatus.APPROVED.value

    if overrides:
        for ov in overrides:
            session.add(ApprovalOverride(
                product_id=product.id,
                field_name=ov.get("field", ""),
                violation=ov.get("violation", ""),
                overridden_value=ov.get("value", ""),
            ))

    session.commit()
    upsert_product_row(product, _settings)
    _log.info("product_hybrid_approved", sku=product.sku)


def _build_hybrid_rationale(source_angles: dict[str, str]) -> str:
    parts = [f"{field} from Variant {src}" for field, src in source_angles.items()]
    return "User hybrid: " + ", ".join(parts)


def reject_and_regenerate(session: Session, product: Product) -> None:
    """
    Clear generated variants and send back to content_generating so the user
    can retrigger the pipeline from the product detail page.
    """
    product.generated_variants = None
    product.selected_variant_id = None
    product.final_title = None
    product.final_tags = None
    product.final_description = None
    product.status = ProductStatus.AWAITING_APPROVAL.value
    session.commit()
    upsert_product_row(product, _settings)
    _log.info("product_rejected_for_regen", sku=product.sku)


# ── Multi-listing publish ─────────────────────────────────────────────────────

# The six things the user must copy into each Etsy listing. The copy-paste helper
# reveals the "Etsy listing URL" input once all six are ticked for a variant.
COPY_PASTE_FIELDS: tuple[str, ...] = (
    "title",
    "tags",
    "description",
    "photos",
    "variations",
    "attributes",
)


def publish_variants(
    session: Session,
    product: Product,
    variant_ids: list[str],
) -> bool:
    """
    Mark the selected variants as published — each becomes its own Etsy listing.

    No Etsy API call happens; the user copy-pastes manually via the helper page.
    Sets ``published_variant_ids`` to the (validated, order-preserved) selection and
    mirrors the FIRST published variant into the legacy ``final_*`` /
    ``selected_variant_id`` fields for the originality corpus, Sheets sync, publisher,
    internal linker, and dashboard. Returns False if none of the ids are valid.
    """
    valid = [vid for vid in variant_ids if get_variant_by_id(product, vid)]
    if not valid:
        return False

    product.published_variant_ids = valid

    primary = get_variant_by_id(product, valid[0]) or {}
    product.final_title = primary.get("title", "")
    product.final_tags = primary.get("tags", [])
    product.final_description = primary.get("description", "")
    product.selected_variant_id = valid[0]

    product.status = ProductStatus.PUBLISHED.value
    product.published_at = datetime.utcnow()

    session.commit()
    upsert_product_row(product, _settings)
    _log.info("product_published", sku=product.sku, variants=valid)
    return True


def get_copy_progress(session: Session, product_id: int) -> dict[str, list[str]]:
    """Return {variant_id: [checked fields]} for the copy-paste helper."""
    rows = (
        session.query(CopyPasteProgress)
        .filter_by(product_id=product_id)
        .all()
    )
    progress: dict[str, list[str]] = {}
    for r in rows:
        progress.setdefault(r.variant_id, []).append(r.field)
    return progress


def toggle_copy_progress(
    session: Session,
    product_id: int,
    variant_id: str,
    field: str,
    checked: bool,
) -> bool:
    """Tick/untick one checklist field. Returns True when all six fields are checked
    for the variant (the helper then reveals the Etsy-URL input)."""
    if field not in COPY_PASTE_FIELDS:
        return False

    row = (
        session.query(CopyPasteProgress)
        .filter_by(product_id=product_id, variant_id=variant_id, field=field)
        .first()
    )
    if checked and row is None:
        session.add(
            CopyPasteProgress(
                product_id=product_id, variant_id=variant_id, field=field
            )
        )
    elif not checked and row is not None:
        session.delete(row)
    session.commit()

    checked_count = (
        session.query(CopyPasteProgress)
        .filter_by(product_id=product_id, variant_id=variant_id)
        .count()
    )
    return checked_count >= len(COPY_PASTE_FIELDS)


def set_etsy_url(
    session: Session,
    product: Product,
    variant_id: str,
    url: str,
) -> None:
    """Persist the Etsy listing URL pasted back for a published variant."""
    urls: dict = copy.deepcopy(product.etsy_urls or {})
    if url:
        urls[variant_id] = url
    else:
        urls.pop(variant_id, None)
    product.etsy_urls = urls
    session.commit()
    _log.info("etsy_url_saved", sku=product.sku, variant=variant_id)


# ── Validation helpers ────────────────────────────────────────────────────────


def validate_field(field: str, value: Any) -> tuple[bool, list[str]]:
    """Run the business-rule validator for a single field. Returns (ok, violations)."""
    if field == "title":
        return validate_title(value)
    if field == "tags":
        tags = value if isinstance(value, list) else [t.strip() for t in value.split(",") if t.strip()]
        return validate_tags(tags)
    if field == "description":
        word_count = len(value.split())
        from src.config.business_rules import DESCRIPTION_MAX_WORDS, DESCRIPTION_MIN_WORDS, CLICHE_DESCRIPTION_PHRASES
        violations = []
        if not (DESCRIPTION_MIN_WORDS <= word_count <= DESCRIPTION_MAX_WORDS):
            violations.append(
                f"Word count {word_count} not in [{DESCRIPTION_MIN_WORDS}, {DESCRIPTION_MAX_WORDS}]"
            )
        for phrase in CLICHE_DESCRIPTION_PHRASES:
            if phrase.lower() in value.lower():
                violations.append(f"Cliché phrase found: '{phrase}'")
        return (len(violations) == 0, violations)
    return (True, [])
