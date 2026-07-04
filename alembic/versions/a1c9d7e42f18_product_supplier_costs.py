"""product supplier cost breakdown

Adds Rexven "Product / Shipping / Total" price snapshot columns on Product so
downstream analytics can compute real margin (sold_price − landed_cost). These
are captured by the Chrome extension from the authenticated Rexven DOM at build
time; cost_cents itself now represents landed cost (product + shipping) when
use_landed_cost was true.

Revision ID: a1c9d7e42f18
Revises: f8d3a2c5b9e7
Create Date: 2026-07-03 23:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c9d7e42f18"
down_revision: Union[str, None] = "f8d3a2c5b9e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("supplier_product_cents", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("supplier_shipping_cents", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("supplier_total_cents", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "supplier_total_cents")
    op.drop_column("products", "supplier_shipping_cents")
    op.drop_column("products", "supplier_product_cents")
