"""rexven variant + attribute capture

Adds the columns needed to record what a Rexven product page actually offers,
rather than just its currently-selected price:

  sourcing_analyses.rexven_shipping_cents  — see the scoring note below
  sourcing_analyses.rexven_options         — normalized option domains
  sourcing_analyses.rexven_attributes      — parsed Turkish spec block
  sourcing_analyses.rexven_raw_payload     — verbatim capture, for re-normalizing
  products.supplier_options                — what the supplier stocks, per product

SCORING BEHAVIOUR CHANGE
------------------------
Until now the Chrome extension forwarded the supplier's product cost but not its
shipping, so OpportunityScorer computed target_retail = product_cost x 4 while
ListingBuilder priced the listing off landed_cost x 4. Shipping is near-flat
(~$7.42) while product cost varies several-fold, so the two disagreed by +48% on
a $15.40 silver item and +112% on a $6.60 brass one.

With rexven_shipping_cents populated, the scorer switches to landed cost and the
two agree. **Opportunity scores computed after this migration are therefore not
comparable with ones computed before it.** Rows written before this migration
have rexven_shipping_cents NULL and keep the old behaviour, so historical rows
stay self-consistent rather than silently shifting.

Revision ID: c4b7e1a9d206
Revises: b3f9d17c4a20
Create Date: 2026-08-20 10:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c4b7e1a9d206"
down_revision: Union[str, None] = "b3f9d17c4a20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sourcing_analyses",
        sa.Column("rexven_shipping_cents", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sourcing_analyses",
        sa.Column("rexven_options", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "sourcing_analyses",
        sa.Column("rexven_attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "sourcing_analyses",
        sa.Column("rexven_raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("supplier_options", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("products", "supplier_options")
    op.drop_column("sourcing_analyses", "rexven_raw_payload")
    op.drop_column("sourcing_analyses", "rexven_attributes")
    op.drop_column("sourcing_analyses", "rexven_options")
    op.drop_column("sourcing_analyses", "rexven_shipping_cents")
