"""product.rexven_sku column

Adds the supplier-side SKU (e.g. "REX-1664") to Product so listings built via
the Chrome extension can be traced back to the exact Rexven source item.
Populated by ListingBuilder.build from ListingBuildRequest.rexven_sku, which
the extension extracts from the Rexven product-details DOM.

Revision ID: f8d3a2c5b9e7
Revises: e5b8c2f091a4
Create Date: 2026-07-03 22:52:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8d3a2c5b9e7"
down_revision: Union[str, None] = "e5b8c2f091a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("rexven_sku", sa.String(length=50), nullable=True),
    )
    op.create_index(
        "ix_products_rexven_sku",
        "products",
        ["rexven_sku"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_products_rexven_sku", table_name="products")
    op.drop_column("products", "rexven_sku")
