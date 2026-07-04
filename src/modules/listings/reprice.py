"""Re-price existing products from the *current* preset + PricingStrategy.

Prices are snapshotted onto ``VariationRow`` / ``Product.selling_price`` when a
product is first built (see ``orchestrator``). Editing the PricingStrategy or a
VariationPreset afterward does not retro-update those snapshots — this module
does, so the two stay in sync.

Only products linked to a ``variation_preset_id`` are touched; manually-created
products (no preset) keep their typed ``selling_price``.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from src.db.models import Product, VariationPreset, VariationRow
from src.modules.listings.variation_builder import VariationMatrixBuilder
from src.utils.logger import get_logger

logger = get_logger(__name__)


def reprice_product(product: Product, session: Session) -> bool:
    """Rebuild a product's VariationRows + selling_price from current settings.

    Returns True if the product was re-priced, False if skipped (no preset,
    missing preset, or no cost to price from).
    """
    if product.variation_preset_id is None:
        return False
    preset = session.get(VariationPreset, product.variation_preset_id)
    if preset is None:
        return False

    cost_cents = product.cost_cents or int(float(product.cost or 0) * 100)
    if not cost_cents:
        return False

    cells = VariationMatrixBuilder(session).build(preset.name, cost_cents)
    if not cells:
        return False

    # Replace the stored variation matrix with the freshly-computed one.
    session.query(VariationRow).filter_by(product_id=product.id).delete(
        synchronize_session=False
    )
    for cell in cells:
        session.add(VariationRow(
            product_id=product.id,
            finish=cell.finish,
            length_inches=cell.length,
            multi_count=cell.multi_count,
            price_cents=cell.price_cents,
            sku_suffix=cell.sku_suffix,
            is_loss_leader=cell.is_loss_leader,
        ))

    product.selling_price = Decimal(min(c.price_cents for c in cells)) / Decimal(100)
    return True


def reprice_all_preset_products(
    session: Session,
    preset_id: int | None = None,
) -> dict[str, int]:
    """Re-price every preset-linked product (optionally only one preset's).

    Commits the session. Returns ``{"repriced": n, "total": m}``.
    """
    q = session.query(Product).filter(Product.variation_preset_id.isnot(None))
    if preset_id is not None:
        q = q.filter(Product.variation_preset_id == preset_id)
    products = q.all()

    repriced = 0
    for p in products:
        try:
            if reprice_product(p, session):
                repriced += 1
        except Exception:  # noqa: BLE001 — one bad product shouldn't block the rest
            logger.exception("reprice_failed", sku=p.sku)
    session.commit()
    logger.info("reprice_all_done", repriced=repriced, total=len(products), preset_id=preset_id)
    return {"repriced": repriced, "total": len(products)}


__all__ = ["reprice_product", "reprice_all_preset_products"]
