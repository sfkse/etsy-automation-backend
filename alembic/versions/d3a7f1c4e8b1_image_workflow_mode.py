"""image_workflow_mode on shop_settings

Adds the ``image_workflow_mode`` column so the 9-image jewelry pipeline
can be toggled per shop alongside the legacy 5-lifestyle pipeline.

Revision ID: d3a7f1c4e8b1
Revises: c8d1a4e6b2f0
Create Date: 2026-07-03 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d3a7f1c4e8b1"
down_revision: Union[str, None] = "c8d1a4e6b2f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shop_settings",
        sa.Column(
            "image_workflow_mode",
            sa.String(length=20),
            nullable=True,
            server_default="jewelry_9",
        ),
    )
    op.execute(
        "UPDATE shop_settings SET image_workflow_mode = 'jewelry_9' "
        "WHERE image_workflow_mode IS NULL"
    )


def downgrade() -> None:
    op.drop_column("shop_settings", "image_workflow_mode")
