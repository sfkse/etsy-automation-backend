"""
Alt text generator (Step 5.9).
SEO alt text based on image rank and product attributes.
"""
from __future__ import annotations

from src.db.models import Product, ProductImage


def build_main_keyword(product: Product) -> str:
    """
    Build the main keyword phrase for a product.
    e.g. "gold plated cross necklace"
    """
    parts: list[str] = []
    if product.color:
        parts.append(product.color.lower())
    if product.material:
        parts.append(product.material.lower())
    pillar = (product.carrier_pillar or "").replace("_", " ").lower()
    if pillar:
        parts.append(pillar)
    parts.append("necklace")
    return " ".join(dict.fromkeys(parts))  # deduplicate while preserving order


def generate_alt_text(product: Product, image: ProductImage) -> str:
    """Generate SEO alt text based on image rank and product attributes."""
    main_keyword = build_main_keyword(product)
    rank = image.rank or 0

    if rank == 1:
        return f"{main_keyword} - main view"
    elif rank in (2, 3):
        return f"{main_keyword} - color variation {rank}"
    elif rank in (4, 5):
        return f"{main_keyword} - size and material details"
    elif rank in (6, 7):
        recipient = (product.recipient or "").lower().strip()
        label = f"gift for {recipient}" if recipient else "gift"
        return f"{main_keyword} - {label}"
    elif rank == 8:
        # jewelry_9 layout: ranks 5-7 are the concept shots, so the first chart
        # (size) lands here. The old "gift box presentation" text predates that
        # layout and no gift box shot exists any more.
        return f"{main_keyword} - size chart"
    else:
        return main_keyword
