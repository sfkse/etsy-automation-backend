"""keyword_pool.is_universal column

Adds an ``is_universal`` flag to the keyword pool so a keyword can apply across
all carrier pillars rather than being scoped to one. Used to seed the 9 universal
jewelry SEO staples from the Christmas 2 tag training (Custom, Personalized,
Gold, 14K Gold, 14K Gold Plated, 925 Silver, Sterling Silver, Dainty,
Minimalist), which are offered to every listing's tag generation as candidates.

Revision ID: e1f4b7c2a9d3
Revises: d4e7a1c9f2b6
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1f4b7c2a9d3"
down_revision: Union[str, None] = "d4e7a1c9f2b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "keyword_pool",
        sa.Column(
            "is_universal",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_keyword_pool_is_universal", "keyword_pool", ["is_universal"]
    )


def downgrade() -> None:
    op.drop_index("ix_keyword_pool_is_universal", table_name="keyword_pool")
    op.drop_column("keyword_pool", "is_universal")
