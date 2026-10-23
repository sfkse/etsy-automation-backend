"""product_images.workflow_source: widen varchar(20) -> varchar(64)

Common-image assets are tagged ``"asset:<filename stem>"`` (e.g.
``"asset:birthstone_chart"``, 22 chars; ``"asset:care_instructions"``, 23
chars). The library accepts any image file the user drops into
``data/assets/``, so the stem length isn't bounded by this app's own naming —
20 chars was sized for the short built-in tags ("gemini", "chart:birthstone")
and silently truncated/rejected longer asset tags
(``psycopg.errors.StringDataRightTruncation``) when attaching from the gallery.

Revision ID: c7f4a8e2d916
Revises: b3e9d5a7c104
Create Date: 2026-10-04 19:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7f4a8e2d916"
down_revision: Union[str, None] = "b3e9d5a7c104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "product_images",
        "workflow_source",
        type_=sa.String(length=64),
        existing_type=sa.String(length=20),
    )


def downgrade() -> None:
    op.alter_column(
        "product_images",
        "workflow_source",
        type_=sa.String(length=20),
        existing_type=sa.String(length=64),
    )
