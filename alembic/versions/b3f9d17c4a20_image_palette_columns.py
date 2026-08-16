"""shop_settings.image_palette + product_images.palette_used columns

Adds the shop-level default colour palette (ShopSettings.image_palette) and a
per-image record of the palette used on the last (re)generation
(ProductImage.palette_used), so the palette can be chosen from the settings web
UI and overridden per image on the regeneration page.

Revision ID: b3f9d17c4a20
Revises: a2f4c8b1e6d9
Create Date: 2026-08-15 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3f9d17c4a20"
down_revision: Union[str, None] = "a2f4c8b1e6d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shop_settings",
        sa.Column(
            "image_palette",
            sa.String(length=40),
            nullable=True,
            server_default="soft_blush_neutral",
        ),
    )
    op.add_column(
        "product_images",
        sa.Column("palette_used", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("product_images", "palette_used")
    op.drop_column("shop_settings", "image_palette")
