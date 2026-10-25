"""Generic variant-axes scheme: products.variant_axes + variation_rows.axis_values.

Replaces the fixed Finish/Length/MultiCount-only variation model for new
products with arbitrary named axes (e.g. Color, Chain Style), seeded from
the supplier options already captured in products.supplier_options.
variation_rows.finish is relaxed to nullable since axis_values-based rows
don't populate it; existing legacy rows are untouched.

Revision ID: c91f5a2e4d03
Revises: b4e2d9f3a718
Create Date: 2026-10-23 16:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "c91f5a2e4d03"
down_revision: Union[str, None] = "b4e2d9f3a718"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("variant_axes", JSONB, nullable=False, server_default="[]"),
    )
    op.add_column(
        "variation_rows",
        sa.Column("axis_values", JSONB, nullable=True),
    )
    op.alter_column(
        "variation_rows",
        "finish",
        existing_type=sa.String(length=20),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "variation_rows",
        "finish",
        existing_type=sa.String(length=20),
        nullable=False,
    )
    op.drop_column("variation_rows", "axis_values")
    op.drop_column("products", "variant_axes")
