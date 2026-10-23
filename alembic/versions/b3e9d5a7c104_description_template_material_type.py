"""description_templates: one template per (category, material)

Brass and silver necklaces need different description text (material line,
fixed 16"+2" chain vs 12-24" lengths), so a template is now keyed by
(category, material_type) instead of category alone. ``material_type`` is a
MaterialType value or ``"any"`` for a template shared by every material.

Data: the existing ``necklace`` row becomes ``brass`` and is copied as
``silver_925`` so any user edits carry over to both. Other rows stay ``any``.

Revision ID: b3e9d5a7c104
Revises: a7d2f6c31b95
Create Date: 2026-10-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3e9d5a7c104"
down_revision: Union[str, None] = "a7d2f6c31b95"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# postgres' default name for the original `UniqueConstraint('category')`.
_OLD_UNIQUE = "description_templates_category_key"
_NEW_UNIQUE = "uq_description_templates_category_material"

_COPY_COLUMNS = (
    "category, section_intro, section_how_to_order, section_materials, "
    "section_finish, section_packaging, section_gift_note, "
    "section_best_gifts_for, section_have_a_question, brass_overrides, "
    "silver_overrides, default_chain_text, updated_at"
)


def upgrade() -> None:
    op.add_column(
        "description_templates",
        sa.Column(
            "material_type", sa.String(length=20), nullable=False, server_default="any"
        ),
    )
    op.drop_constraint(_OLD_UNIQUE, "description_templates", type_="unique")
    op.create_unique_constraint(
        _NEW_UNIQUE, "description_templates", ["category", "material_type"]
    )
    op.execute(
        "UPDATE description_templates SET material_type = 'brass' "
        "WHERE category = 'necklace'"
    )
    op.execute(
        f"INSERT INTO description_templates ({_COPY_COLUMNS}, material_type) "
        f"SELECT {_COPY_COLUMNS}, 'silver_925' FROM description_templates "
        "WHERE category = 'necklace' AND material_type = 'brass'"
    )


def downgrade() -> None:
    # Keep one row per category (brass/any) so UNIQUE(category) can come back.
    op.execute(
        "DELETE FROM description_templates WHERE material_type NOT IN ('brass', 'any')"
    )
    op.drop_constraint(_NEW_UNIQUE, "description_templates", type_="unique")
    op.create_unique_constraint(_OLD_UNIQUE, "description_templates", ["category"])
    op.drop_column("description_templates", "material_type")
