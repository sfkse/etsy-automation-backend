"""multi-listing publish: published_variant_ids, etsy_urls, copy_paste_progress

Adds support for publishing a single product as multiple separate Etsy listings
(Christmas-2 strategy — one listing per selected variant). Introduces:

- products.published_variant_ids (JSONB list) — the variant ids the user elected
  to publish, e.g. ["A", "B", "C"] or ["B"] or ["A", "HYBRID"].
- products.etsy_urls (JSONB dict) — per-variant Etsy listing URLs pasted back
  after manual publishing.
- copy_paste_progress table — per (product, variant, field) checklist state for
  the copy-paste helper page.

The legacy selected_variant_id / final_* columns are intentionally KEPT (they are
still read by the description-originality corpus, Sheets sync, the Etsy publisher,
the internal linker, and the dashboard); on publish they mirror the first published
variant. Existing selected_variant_id values are wrapped into a one-element
published_variant_ids list so already-approved products render correctly.

Revision ID: a2f4c8b1e6d9
Revises: e1f4b7c2a9d3
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a2f4c8b1e6d9"
down_revision: Union[str, None] = "e1f4b7c2a9d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "published_variant_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "etsy_urls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # Backfill: wrap any existing single selection into a one-element list.
    op.execute(
        "UPDATE products "
        "SET published_variant_ids = jsonb_build_array(selected_variant_id) "
        "WHERE selected_variant_id IS NOT NULL"
    )

    op.create_table(
        "copy_paste_progress",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("variant_id", sa.String(length=10), nullable=False),
        sa.Column("field", sa.String(length=20), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id", "variant_id", "field", name="uq_copy_progress_field"
        ),
    )


def downgrade() -> None:
    op.drop_table("copy_paste_progress")
    op.drop_column("products", "etsy_urls")
    op.drop_column("products", "published_variant_ids")
