"""description_template.section_finish column

Adds a dedicated Finish section (Gold / Silver / Rose Gold) to the per-category
description scaffold, split out from the Materials section per the Christmas 3
listing training. Nullable Text with no server default (server_default=None).

Revision ID: d4e7a1c9f2b6
Revises: c1d2e3f4a5b6
Create Date: 2026-08-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e7a1c9f2b6"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "description_templates",
        sa.Column("section_finish", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("description_templates", "section_finish")
