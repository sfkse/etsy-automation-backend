"""Add pricing_strategy.region_price_adjustments_pct.

Per-shipping-profile price adjustment (%) applied on top of every variant's
price when publishing that product's region-specific listing, e.g.
{"US": 0, "UK": 5, "DE": 10}.

Revision ID: e5f7c2a9b134
Revises: d84e6b1f0a92
Create Date: 2026-10-24 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "e5f7c2a9b134"
down_revision: Union[str, None] = "d84e6b1f0a92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pricing_strategy",
        sa.Column("region_price_adjustments_pct", JSONB, nullable=True, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("pricing_strategy", "region_price_adjustments_pct")
