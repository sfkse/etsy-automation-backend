"""phase4 sourcing intelligence

Revision ID: f7e2c9a1b3d5
Revises: b3f1c8a2d904
Create Date: 2026-06-27 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'f7e2c9a1b3d5'
down_revision: Union[str, None] = '59fe59a50ae0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── sourcing_analyses ────────────────────────────────────────────────────
    op.create_table(
        'sourcing_analyses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('rexven_url', sa.String(length=500), nullable=True),
        sa.Column('rexven_sku', sa.String(length=50), nullable=True),
        sa.Column('image_path', sa.String(length=500), nullable=True),
        sa.Column('image_url', sa.String(length=500), nullable=True),
        sa.Column('rexven_title_tr', sa.String(length=255), nullable=True),
        sa.Column('rexven_title_en', sa.String(length=255), nullable=True),
        sa.Column('rexven_cost_usd_cents', sa.Integer(), nullable=True),
        sa.Column('rexven_premium_cost_usd_cents', sa.Integer(), nullable=True),
        sa.Column('rexven_category', sa.String(length=50), nullable=True),
        sa.Column('rexven_has_satisa_uygun_badge', sa.Boolean(), nullable=True),
        sa.Column('rexven_has_yeni_badge', sa.Boolean(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=True),
        sa.Column('layer_a_completed', sa.Boolean(), nullable=True),
        sa.Column('layer_b_completed', sa.Boolean(), nullable=True),
        sa.Column('layer_c_completed', sa.Boolean(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('vision_tokens_used', sa.Integer(), nullable=True),
        sa.Column('vision_cost_usd_cents', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sourcing_analyses_rexven_url', 'sourcing_analyses', ['rexven_url'])
    op.create_index('ix_sourcing_analyses_rexven_sku', 'sourcing_analyses', ['rexven_sku'])

    # ── keyword_candidates ───────────────────────────────────────────────────
    op.create_table(
        'keyword_candidates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('analysis_id', sa.Integer(), nullable=False),
        sa.Column('keyword', sa.String(length=100), nullable=False),
        sa.Column('tier', sa.String(length=10), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=True),
        sa.Column('detected_attributes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('source_layer', sa.String(length=10), nullable=True),
        sa.ForeignKeyConstraint(['analysis_id'], ['sourcing_analyses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_keyword_candidates_keyword', 'keyword_candidates', ['keyword'])
    op.create_index('ix_keyword_candidates_analysis_id', 'keyword_candidates', ['analysis_id'])

    # ── keyword_scores ───────────────────────────────────────────────────────
    op.create_table(
        'keyword_scores',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('analysis_id', sa.Integer(), nullable=False),
        sa.Column('candidate_id', sa.Integer(), nullable=False),
        sa.Column('keyword', sa.String(length=100), nullable=False),
        sa.Column('score_new_shop_share', sa.Float(), nullable=True),
        sa.Column('score_price_alignment', sa.Float(), nullable=True),
        sa.Column('score_activity', sa.Float(), nullable=True),
        sa.Column('score_competition', sa.Float(), nullable=True),
        sa.Column('score_diversity', sa.Float(), nullable=True),
        sa.Column('opportunity_score', sa.Float(), nullable=True),
        sa.Column('top20_avg_price_cents', sa.Integer(), nullable=True),
        sa.Column('top20_avg_shop_age', sa.Float(), nullable=True),
        sa.Column('top20_keyword_total_results', sa.Integer(), nullable=True),
        sa.Column('top20_unique_shops', sa.Integer(), nullable=True),
        sa.Column('top20_with_recent_sales', sa.Integer(), nullable=True),
        sa.Column('estimated_rank', sa.Integer(), nullable=True),
        sa.Column('estimated_page', sa.Integer(), nullable=True),
        sa.Column('visual_similarity_support', sa.Integer(), nullable=True),
        sa.Column('rank_in_recommendation', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['analysis_id'], ['sourcing_analyses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['candidate_id'], ['keyword_candidates.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_keyword_scores_opportunity_score', 'keyword_scores', ['opportunity_score'])
    op.create_index('ix_keyword_scores_analysis_id', 'keyword_scores', ['analysis_id'])

    # ── rexven_product_embeddings ────────────────────────────────────────────
    op.create_table(
        'rexven_product_embeddings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('image_hash', sa.String(length=64), nullable=False),
        sa.Column('image_path', sa.String(length=500), nullable=True),
        sa.Column('embedding', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('model_name', sa.String(length=50), nullable=True),
        sa.Column('computed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('image_hash'),
    )
    op.create_index('ix_rexven_product_embeddings_image_hash', 'rexven_product_embeddings', ['image_hash'])

    # ── competitor_listings — Phase 4 columns ────────────────────────────────
    op.add_column('competitor_listings',
        sa.Column('scraped_for_sourcing', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('competitor_listings',
        sa.Column('sourcing_analysis_id', sa.Integer(), nullable=True))
    op.add_column('competitor_listings',
        sa.Column('image_embedding', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('competitor_listings',
        sa.Column('image_embedding_model', sa.String(length=50), nullable=True))
    op.add_column('competitor_listings',
        sa.Column('image_embedding_computed_at', sa.DateTime(), nullable=True))

    op.create_index(
        'ix_competitor_listings_scraped_for_sourcing',
        'competitor_listings',
        ['scraped_for_sourcing'],
    )
    op.create_index(
        'ix_competitor_listings_image_embedding_computed_at',
        'competitor_listings',
        ['image_embedding_computed_at'],
    )
    op.create_foreign_key(
        'fk_competitor_listings_sourcing_analysis_id',
        'competitor_listings', 'sourcing_analyses',
        ['sourcing_analysis_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_competitor_listings_sourcing_analysis_id',
        'competitor_listings', type_='foreignkey',
    )
    op.drop_index('ix_competitor_listings_image_embedding_computed_at', table_name='competitor_listings')
    op.drop_index('ix_competitor_listings_scraped_for_sourcing', table_name='competitor_listings')
    op.drop_column('competitor_listings', 'image_embedding_computed_at')
    op.drop_column('competitor_listings', 'image_embedding_model')
    op.drop_column('competitor_listings', 'image_embedding')
    op.drop_column('competitor_listings', 'sourcing_analysis_id')
    op.drop_column('competitor_listings', 'scraped_for_sourcing')

    op.drop_index('ix_rexven_product_embeddings_image_hash', table_name='rexven_product_embeddings')
    op.drop_table('rexven_product_embeddings')

    op.drop_index('ix_keyword_scores_analysis_id', table_name='keyword_scores')
    op.drop_index('ix_keyword_scores_opportunity_score', table_name='keyword_scores')
    op.drop_table('keyword_scores')

    op.drop_index('ix_keyword_candidates_analysis_id', table_name='keyword_candidates')
    op.drop_index('ix_keyword_candidates_keyword', table_name='keyword_candidates')
    op.drop_table('keyword_candidates')

    op.drop_index('ix_sourcing_analyses_rexven_sku', table_name='sourcing_analyses')
    op.drop_index('ix_sourcing_analyses_rexven_url', table_name='sourcing_analyses')
    op.drop_table('sourcing_analyses')
