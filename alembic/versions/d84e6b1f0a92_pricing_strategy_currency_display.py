"""Add pricing_strategy.currency_symbol / currency_symbol_position.

Display-only settings for how prices show in this app's own admin UI
(e.g. "kr" as a suffix for a Swedish-currency shop). Etsy's API never
receives an explicit currency from this app — currency is entirely
implicit from the shop's own Etsy-side setting.

Revision ID: d84e6b1f0a92
Revises: c91f5a2e4d03
Create Date: 2026-10-24 11:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d84e6b1f0a92"
down_revision: Union[str, None] = "c91f5a2e4d03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pricing_strategy",
        sa.Column("currency_symbol", sa.String(length=5), nullable=True, server_default="$"),
    )
    op.add_column(
        "pricing_strategy",
        sa.Column(
            "currency_symbol_position", sa.String(length=10), nullable=True, server_default="prefix"
        ),
    )


def downgrade() -> None:
    op.drop_column("pricing_strategy", "currency_symbol_position")
    op.drop_column("pricing_strategy", "currency_symbol")
