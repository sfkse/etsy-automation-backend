"""
Phase 6.5 — InternalLinker (Mağaza-Internal Link Inserter)

Appends 2-3 internal links to similar products at the end of the description.
Links must point to actually live / published products in the same carrier pillar.
If no similar products exist, the description is returned unchanged.

Per Section 1.3 rules:
  - Links must point to actually similar products that exist.
  - If the pillar has no other published products, skip the link.
"""
from __future__ import annotations

import structlog

from sqlalchemy.orm import Session

from src.db.models import Product, ProductStatus

_log = structlog.get_logger(__name__)

_LINK_TEMPLATE = "View our [{link_text}](https://www.etsy.com/listing/{listing_id})"

_PILLAR_LINK_LABELS: dict[str, str] = {
    "cross": "Cross Necklace Collection",
    "name": "Name Necklace Collection",
    "birthstone": "Birthstone Necklace Collection",
    "birth_flower": "Birth Flower Jewelry Collection",
    "pet": "Pet Memorial Jewelry Collection",
    "pendant": "Pendant Necklace Collection",
}


class InternalLinker:
    """Append internal Etsy links to the end of a product description."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def insert_links(self, description: str, product: Product) -> str:
        """
        Query the DB for live products in the same carrier pillar, build
        2-3 internal link strings, and append them at the end of *description*.
        Returns *description* unchanged if no eligible products exist.
        """
        similar = self._fetch_similar(product)
        if not similar:
            _log.info("internal_linker_no_similar", sku=product.sku, pillar=product.carrier_pillar)
            return description

        links = self._build_links(similar[:3], product.carrier_pillar)
        if not links:
            return description

        separator = "\n\n" if not description.endswith("\n") else "\n"
        return description + separator + "\n".join(links)

    def _fetch_similar(self, product: Product) -> list[Product]:
        """
        Return up to 3 published products in the same carrier pillar,
        excluding the current product.
        """
        return (
            self._session.query(Product)
            .filter(
                Product.carrier_pillar == product.carrier_pillar,
                Product.sku != product.sku,
                Product.status == ProductStatus.PUBLISHED.value,
                Product.etsy_listing_id.isnot(None),
            )
            .order_by(Product.published_at.desc())
            .limit(3)
            .all()
        )

    @staticmethod
    def _build_links(products: list[Product], pillar: str) -> list[str]:
        """Build 2-3 formatted internal link strings."""
        links = []
        for p in products:
            if not p.etsy_listing_id:
                continue
            label = _PILLAR_LINK_LABELS.get(pillar, f"{pillar.replace('_', ' ').title()} Collection")
            if p.final_title:
                # Use the product's title words as a more specific label
                words = p.final_title.split(",")[0].strip()
                link_text = words if len(words) <= 40 else label
            else:
                link_text = label

            links.append(_LINK_TEMPLATE.format(
                link_text=link_text,
                listing_id=p.etsy_listing_id,
            ))
        return links
