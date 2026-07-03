"""operational integration v2.5

Adds Shop Settings, Description Templates, Default Attributes, Variation
Presets, Pricing Strategy, Personalization Library, Shop Sections, and
Variation Rows. Also adds nullable columns to products for the Listing
Builder flow.

Revision ID: c8d1a4e6b2f0
Revises: f7e2c9a1b3d5
Create Date: 2026-07-03 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c8d1a4e6b2f0'
down_revision: Union[str, None] = 'f7e2c9a1b3d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── shop_settings ────────────────────────────────────────────────────────
    op.create_table(
        'shop_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('shop_name', sa.String(length=100), nullable=True),
        sa.Column('shop_id', sa.String(length=20), nullable=True),
        sa.Column('production_partner_id', sa.String(length=50), nullable=True),
        sa.Column('production_partner_name', sa.String(length=100), nullable=True),
        sa.Column('production_partner_about', sa.String(length=255), nullable=True),
        sa.Column('production_partner_location', sa.String(length=100), nullable=True),
        sa.Column('production_partner_q1', sa.String(length=50), nullable=True),
        sa.Column('production_partner_q2', sa.String(length=50), nullable=True),
        sa.Column('production_partner_q3', sa.String(length=50), nullable=True),
        sa.Column('renewal_option', sa.String(length=20), nullable=True),
        sa.Column('return_policy_days', sa.Integer(), nullable=True),
        sa.Column('feature_listing_default', sa.Boolean(), nullable=True),
        sa.Column('default_quantity', sa.Integer(), nullable=True),
        sa.Column('omit_karat_in_title', sa.Boolean(), nullable=True),
        sa.Column('active_pillars', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('default_shipping_profile_id', sa.String(length=50), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── description_templates ────────────────────────────────────────────────
    op.create_table(
        'description_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('section_intro', sa.Text(), nullable=True),
        sa.Column('section_how_to_order', sa.Text(), nullable=True),
        sa.Column('section_materials', sa.Text(), nullable=True),
        sa.Column('section_packaging', sa.Text(), nullable=True),
        sa.Column('section_gift_note', sa.Text(), nullable=True),
        sa.Column('section_best_gifts_for', sa.Text(), nullable=True),
        sa.Column('section_have_a_question', sa.Text(), nullable=True),
        sa.Column('brass_overrides', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('silver_overrides', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('default_chain_text', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('category'),
    )

    # ── default_attributes ───────────────────────────────────────────────────
    op.create_table(
        'default_attributes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('style', sa.String(length=50), nullable=True),
        sa.Column('theme', sa.String(length=50), nullable=True),
        sa.Column('holiday_default', sa.String(length=50), nullable=True),
        sa.Column('sustainability', sa.String(length=50), nullable=True),
        sa.Column('chain_style', sa.String(length=50), nullable=True),
        sa.Column('adjustable', sa.Boolean(), nullable=True),
        sa.Column('convertible', sa.Boolean(), nullable=True),
        sa.Column('default_occasion', sa.String(length=50), nullable=True),
        sa.Column('default_recipients', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('category'),
    )

    # ── variation_presets ────────────────────────────────────────────────────
    op.create_table(
        'variation_presets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('material_type', sa.String(length=30), nullable=False),
        sa.Column('finishes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('lengths_inches', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('multi_count_label', sa.String(length=50), nullable=True),
        sa.Column('multi_count_range', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('has_length_variation', sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # ── pricing_strategy ─────────────────────────────────────────────────────
    op.create_table(
        'pricing_strategy',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('base_multiplier', sa.Float(), nullable=True),
        sa.Column('finish_offsets_pct', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('length_base_inches', sa.Integer(), nullable=True),
        sa.Column('length_price_per_extra_inch_pct', sa.Float(), nullable=True),
        sa.Column('loss_leader_enabled', sa.Boolean(), nullable=True),
        sa.Column('loss_leader_finish', sa.String(length=20), nullable=True),
        sa.Column('loss_leader_length', sa.Integer(), nullable=True),
        sa.Column('loss_leader_margin_pct', sa.Float(), nullable=True),
        sa.Column('multi_count_extra_pct', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── personalization_templates ────────────────────────────────────────────
    op.create_table(
        'personalization_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('instruction_text', sa.Text(), nullable=True),
        sa.Column('example_text', sa.Text(), nullable=True),
        sa.Column('reference_note', sa.Text(), nullable=True),
        sa.Column('max_characters', sa.Integer(), nullable=True),
        sa.Column('is_optional', sa.Boolean(), nullable=True),
        sa.Column('applicable_categories', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('type_signature', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # ── shop_sections ────────────────────────────────────────────────────────
    op.create_table(
        'shop_sections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('etsy_section_id', sa.String(length=50), nullable=True),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('carrier_pillar', sa.String(length=50), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # ── variation_rows ───────────────────────────────────────────────────────
    op.create_table(
        'variation_rows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('finish', sa.String(length=20), nullable=False),
        sa.Column('length_inches', sa.Integer(), nullable=True),
        sa.Column('multi_count', sa.Integer(), nullable=True),
        sa.Column('price_cents', sa.Integer(), nullable=False),
        sa.Column('sku_suffix', sa.String(length=40), nullable=False),
        sa.Column('is_loss_leader', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_variation_rows_product_id', 'variation_rows', ['product_id'])

    # ── products additive columns ────────────────────────────────────────────
    with op.batch_alter_table('products') as batch:
        batch.add_column(sa.Column('variation_preset_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('personalization_template_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('target_keyword', sa.String(length=100), nullable=True))
        batch.add_column(sa.Column('material_type', sa.String(length=30), nullable=True))
        batch.add_column(sa.Column('stone_shape', sa.String(length=50), nullable=True))
        batch.add_column(sa.Column('holiday_override', sa.String(length=50), nullable=True))
        batch.add_column(sa.Column('is_featured', sa.Boolean(), nullable=True))
        batch.add_column(sa.Column('theme', sa.String(length=100), nullable=True))
        batch.add_column(sa.Column('chain_style', sa.String(length=50), nullable=True))
        batch.add_column(sa.Column('recipients_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        batch.add_column(sa.Column('occasions_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        batch.add_column(sa.Column('rexven_url', sa.String(length=500), nullable=True))
        batch.add_column(sa.Column('original_image_path', sa.String(length=500), nullable=True))
        batch.add_column(sa.Column('cost_cents', sa.Integer(), nullable=True))
        batch.create_foreign_key(
            'fk_products_variation_preset',
            'variation_presets', ['variation_preset_id'], ['id'],
        )
        batch.create_foreign_key(
            'fk_products_personalization_template',
            'personalization_templates', ['personalization_template_id'], ['id'],
        )


def downgrade() -> None:
    with op.batch_alter_table('products') as batch:
        batch.drop_constraint('fk_products_personalization_template', type_='foreignkey')
        batch.drop_constraint('fk_products_variation_preset', type_='foreignkey')
        batch.drop_column('cost_cents')
        batch.drop_column('original_image_path')
        batch.drop_column('rexven_url')
        batch.drop_column('occasions_json')
        batch.drop_column('recipients_json')
        batch.drop_column('chain_style')
        batch.drop_column('theme')
        batch.drop_column('is_featured')
        batch.drop_column('holiday_override')
        batch.drop_column('stone_shape')
        batch.drop_column('material_type')
        batch.drop_column('target_keyword')
        batch.drop_column('personalization_template_id')
        batch.drop_column('variation_preset_id')

    op.drop_index('ix_variation_rows_product_id', table_name='variation_rows')
    op.drop_table('variation_rows')
    op.drop_table('shop_sections')
    op.drop_table('personalization_templates')
    op.drop_table('pricing_strategy')
    op.drop_table('variation_presets')
    op.drop_table('default_attributes')
    op.drop_table('description_templates')
    op.drop_table('shop_settings')
