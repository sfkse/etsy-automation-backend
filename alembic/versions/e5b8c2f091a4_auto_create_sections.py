"""auto_create_sections on shop_settings

Toggles whether ListingBuilder.build should auto-create a matching
ShopSection row for a newly-seen carrier pillar (PR 6).

Revision ID: e5b8c2f091a4
Revises: d3a7f1c4e8b1
Create Date: 2026-07-03 20:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5b8c2f091a4"
down_revision: Union[str, None] = "d3a7f1c4e8b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shop_settings",
        sa.Column(
            "auto_create_sections",
            sa.Boolean(),
            nullable=True,
            server_default=sa.true(),
        ),
    )
    op.execute(
        "UPDATE shop_settings SET auto_create_sections = TRUE "
        "WHERE auto_create_sections IS NULL"
    )


def downgrade() -> None:
    op.drop_column("shop_settings", "auto_create_sections")
