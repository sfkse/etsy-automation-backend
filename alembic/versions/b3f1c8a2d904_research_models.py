"""research models

Revision ID: b3f1c8a2d904
Revises: ea9c2eee784d
Create Date: 2026-06-27 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b3f1c8a2d904'
down_revision: Union[str, None] = 'ea9c2eee784d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'competitor_listings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('listing_id', sa.String(length=20), nullable=False),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('keyword_searched', sa.String(length=100), nullable=True),
        sa.Column('rank_in_search', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('image_url', sa.String(length=1000), nullable=True),
        sa.Column('shop_name', sa.String(length=100), nullable=True),
        sa.Column('shop_id', sa.String(length=20), nullable=True),
        sa.Column('shop_url', sa.String(length=500), nullable=True),
        sa.Column('shop_age_years', sa.Float(), nullable=True),
        sa.Column('price_cents', sa.Integer(), nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=True),
        sa.Column('original_price_cents', sa.Integer(), nullable=True),
        sa.Column('discount_pct', sa.Integer(), nullable=True),
        sa.Column('rating', sa.Float(), nullable=True),
        sa.Column('review_count', sa.Integer(), nullable=True),
        sa.Column('is_bestseller', sa.Boolean(), nullable=True),
        sa.Column('is_star_seller', sa.Boolean(), nullable=True),
        sa.Column('is_popular_now', sa.Boolean(), nullable=True),
        sa.Column('is_etsys_pick', sa.Boolean(), nullable=True),
        sa.Column('is_ad', sa.Boolean(), nullable=True),
        sa.Column('has_video', sa.Boolean(), nullable=True),
        sa.Column('keyword_total_results', sa.Integer(), nullable=True),
        # EHunt Phase 1
        sa.Column('eh_sales_total', sa.Integer(), nullable=True),
        sa.Column('eh_sales_recent', sa.Integer(), nullable=True),
        sa.Column('eh_favorites', sa.Integer(), nullable=True),
        sa.Column('eh_shop_weekly_sales', sa.Integer(), nullable=True),
        sa.Column('eh_listed_date', sa.Date(), nullable=True),
        # Listing detail (Phase 2)
        sa.Column('views_24h_count', sa.String(length=20), nullable=True),
        sa.Column('cart_count', sa.Integer(), nullable=True),
        sa.Column('stock_warning', sa.String(length=100), nullable=True),
        sa.Column('shop_total_sales', sa.Integer(), nullable=True),
        sa.Column('has_sale_countdown', sa.Boolean(), nullable=True),
        sa.Column('personalization_required', sa.Boolean(), nullable=True),
        # LLM enrichment
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('tag_volumes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('description_text', sa.Text(), nullable=True),
        sa.Column('description_length', sa.Integer(), nullable=True),
        sa.Column('image_count', sa.Integer(), nullable=True),
        # EHunt detail panel (Phase 2)
        sa.Column('eh_detail_release_date', sa.Date(), nullable=True),
        sa.Column('eh_detail_total_sales', sa.Integer(), nullable=True),
        sa.Column('eh_detail_total_reviews', sa.Integer(), nullable=True),
        sa.Column('eh_detail_total_favorites', sa.Integer(), nullable=True),
        sa.Column('eh_detail_review_ratio', sa.String(length=20), nullable=True),
        sa.Column('eh_detail_category', sa.String(length=255), nullable=True),
        sa.Column('eh_detail_stocks', sa.Integer(), nullable=True),
        sa.Column('eh_detail_conv_rate', sa.String(length=20), nullable=True),
        # Computed
        sa.Column('sales_signal_score', sa.Float(), nullable=True),
        sa.Column('scraped_at', sa.DateTime(), nullable=True),
        sa.Column('imported_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('listing_id'),
    )
    op.create_index('ix_competitor_listings_listing_id', 'competitor_listings', ['listing_id'])
    op.create_index('ix_competitor_listings_keyword_searched', 'competitor_listings', ['keyword_searched'])
    op.create_index('ix_competitor_listings_shop_name', 'competitor_listings', ['shop_name'])
    op.create_index('ix_competitor_listings_sales_signal_score', 'competitor_listings', ['sales_signal_score'])

    op.create_table(
        'keyword_research',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('keyword', sa.String(length=100), nullable=False),
        sa.Column('total_listings_scraped', sa.Integer(), nullable=True),
        sa.Column('bestseller_count', sa.Integer(), nullable=True),
        sa.Column('star_seller_count', sa.Integer(), nullable=True),
        sa.Column('avg_title_length', sa.Float(), nullable=True),
        sa.Column('avg_review_count', sa.Float(), nullable=True),
        sa.Column('avg_price_cents', sa.Float(), nullable=True),
        sa.Column('avg_image_count', sa.Float(), nullable=True),
        sa.Column('title_patterns', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('top_tags_by_frequency', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('common_cliches', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('underused_keywords', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('volume_stratified_tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('avg_volume_by_position', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('last_analyzed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('keyword'),
    )
    op.create_index('ix_keyword_research_keyword', 'keyword_research', ['keyword'])

    op.create_table(
        'competitor_shops',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('shop_id', sa.String(length=20), nullable=False),
        sa.Column('shop_name', sa.String(length=100), nullable=True),
        sa.Column('shop_url', sa.String(length=500), nullable=True),
        sa.Column('total_sales', sa.Integer(), nullable=True),
        sa.Column('listings_in_research', sa.Integer(), nullable=True),
        sa.Column('bestseller_listings', sa.Integer(), nullable=True),
        sa.Column('avg_rating', sa.Float(), nullable=True),
        sa.Column('classification', sa.String(length=20), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shop_id'),
    )
    op.create_index('ix_competitor_shops_shop_id', 'competitor_shops', ['shop_id'])
    op.create_index('ix_competitor_shops_shop_name', 'competitor_shops', ['shop_name'])


def downgrade() -> None:
    op.drop_index('ix_competitor_shops_shop_name', table_name='competitor_shops')
    op.drop_index('ix_competitor_shops_shop_id', table_name='competitor_shops')
    op.drop_table('competitor_shops')

    op.drop_index('ix_keyword_research_keyword', table_name='keyword_research')
    op.drop_table('keyword_research')

    op.drop_index('ix_competitor_listings_sales_signal_score', table_name='competitor_listings')
    op.drop_index('ix_competitor_listings_shop_name', table_name='competitor_listings')
    op.drop_index('ix_competitor_listings_keyword_searched', table_name='competitor_listings')
    op.drop_index('ix_competitor_listings_listing_id', table_name='competitor_listings')
    op.drop_table('competitor_listings')
