"""competitor_listings: one row per (listing, keyword), not per listing

`competitor_listings.listing_id` was UNIQUE while `keyword_searched` was a plain
scalar on the same row, so the table could not represent one Etsy listing ranking
for two keywords.

`ingest_and_score` deduped on `filter_by(listing_id=...)` unscoped — across every
analysis and all history — and skipped the card without recording the new
keyword. The first keyword ever to see a listing owned it permanently, so any
later keyword whose Etsy results overlapped an already-scraped one retained
almost nothing, fell under OpportunityScorer's 5-row floor in `_fetch_top20`, and
was dropped as `scorer_skip_insufficient_data`. Niche keywords lose that race by
construction: their results overlap the generic terms already in the table.

SCORING BEHAVIOUR CHANGE
------------------------
Until now `_fetch_top20` returned only the listings a keyword managed to claim,
not its actual top-20, so avg_price / activity / new_shop_share / diversity were
all computed on a biased partial sample. After this migration keywords are scored
against their full ingested top-20. **Opportunity scores computed after this
migration are not comparable with ones computed before it**, and re-running an
old analysis will not reproduce its old numbers.

Existing rows are already unique under the composite key, so nothing is rewritten
or backfilled here — historical rows keep whichever single keyword first claimed
them. Re-scraping is what repopulates the missing (listing, keyword) pairs.

Also adds `sourcing_analyses.unscored_candidates`, so a candidate Layer B could
not score is recorded with its reason instead of vanishing into a log line.

Revision ID: a7d2f6c31b95
Revises: c4b7e1a9d206
Create Date: 2026-08-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a7d2f6c31b95"
down_revision: Union[str, None] = "c4b7e1a9d206"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# `unique=True` on a Column emits a UNIQUE *index* under postgres, named by
# alembic's default convention. It is dropped and replaced by a plain (non-unique)
# index so lookups by listing_id — the Phase 2 detail merges — stay indexed.
_OLD_UNIQUE_INDEX = "ix_competitor_listings_listing_id"
_NEW_INDEX = "ix_competitor_listings_listing_id"


def upgrade() -> None:
    op.drop_index(_OLD_UNIQUE_INDEX, table_name="competitor_listings")
    op.create_index(
        _NEW_INDEX, "competitor_listings", ["listing_id"], unique=False
    )
    op.create_unique_constraint(
        "uq_listing_keyword",
        "competitor_listings",
        ["listing_id", "keyword_searched"],
    )
    op.add_column(
        "sourcing_analyses",
        sa.Column(
            "unscored_candidates",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("sourcing_analyses", "unscored_candidates")
    # Reinstating the old UNIQUE(listing_id) fails if any listing has since been
    # ingested under more than one keyword — which is the entire point of the
    # upgrade. Drop the surplus rows first, keeping the lowest id per listing.
    op.execute(
        sa.text(
            """
            DELETE FROM competitor_listings
            WHERE id NOT IN (
                SELECT MIN(id) FROM competitor_listings GROUP BY listing_id
            )
            """
        )
    )
    op.drop_constraint(
        "uq_listing_keyword", "competitor_listings", type_="unique"
    )
    op.drop_index(_NEW_INDEX, table_name="competitor_listings")
    op.create_index(
        _OLD_UNIQUE_INDEX, "competitor_listings", ["listing_id"], unique=True
    )
