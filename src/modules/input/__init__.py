"""
Manual Input Module — SKU generation utilities.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from src.db.models import Product


def generate_sku(session: Session) -> str:
    """Return the next auto-incremented SKU in the format TAKI-NNNN."""
    last = (
        session.query(Product.sku)
        .order_by(Product.id.desc())
        .first()
    )
    if last is None:
        return "TAKI-0001"
    match = re.search(r"(\d+)$", last[0])
    next_n = (int(match.group(1)) + 1) if match else 1
    return f"TAKI-{next_n:04d}"
