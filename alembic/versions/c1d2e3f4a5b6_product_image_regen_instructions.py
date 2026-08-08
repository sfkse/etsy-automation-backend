"""product_image.regen_instructions column

Adds per-image art-direction text appended to the slot's built-in prompt on the
last regenerate, persisted so the per-slot images page can pre-fill it and the
user can iterate on instructions.

Revision ID: c1d2e3f4a5b6
Revises: b7c4e9d1f2a3
Create Date: 2026-07-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b7c4e9d1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "product_images",
        sa.Column("regen_instructions", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("product_images", "regen_instructions")
