"""Add products.etsy_draft_listing_ids_by_profile for orphaned-draft tracking.

When a publish run creates a draft listing on Etsy but a later step
(image upload, attributes, section, activate) fails, the draft is left
live on Etsy's side with no local record. This column tracks those by
region label so they're visible for manual review instead of silently
lost, e.g. {"US": "listing_id", "DE": "..."}.

Revision ID: b4e2d9f3a718
Revises: a3f1c8d2e657
Create Date: 2026-10-23 16:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "b4e2d9f3a718"
down_revision: Union[str, None] = "a3f1c8d2e657"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "etsy_draft_listing_ids_by_profile",
            JSONB,
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("products", "etsy_draft_listing_ids_by_profile")
