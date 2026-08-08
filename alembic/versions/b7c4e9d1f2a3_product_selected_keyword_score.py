"""product selected keyword score

Adds ``selected_keyword_score_id`` on Product so a Phase 4 sourcing keyword
chosen in the Chrome extension can be persisted at build time and used to
ground content generation (and any later regeneration) in that keyword's
empirical market data — no manual ID re-entry in the backend.

Revision ID: b7c4e9d1f2a3
Revises: a1c9d7e42f18
Create Date: 2026-07-16 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c4e9d1f2a3"
down_revision: Union[str, None] = "a1c9d7e42f18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("selected_keyword_score_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "selected_keyword_score_id")
