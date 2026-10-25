"""Add products.etsy_listing_ids_by_profile for multi-shipping-profile publish.

Each configured shipping profile (US/UK/DE) becomes its own Etsy listing for
a product; this JSONB column tracks the listing id created per region label,
e.g. {"US": "listing_id", "UK": "...", "DE": "..."}.

Revision ID: a3f1c8d2e657
Revises: c7f4a8e2d916
Create Date: 2026-10-23 15:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "a3f1c8d2e657"
down_revision: Union[str, None] = "c7f4a8e2d916"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "etsy_listing_ids_by_profile",
            JSONB,
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("products", "etsy_listing_ids_by_profile")
