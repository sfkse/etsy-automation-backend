"""
Tests for the DescriptionEngine scaffold (Section D).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from src.db.models import (
    DescriptionTemplate,
    MaterialType,
    PersonalizationTemplate,
    Product,
    VariationPreset,
)
from src.modules.listings.description_engine import DescriptionEngine


def _template() -> DescriptionTemplate:
    return DescriptionTemplate(
        category="necklace",
        section_intro="{product_name} — dainty necklace.",
        section_how_to_order=(
            "How to Order:\n"
            "Choose finish. Lengths: {length_options}.\n"
            "{personalization_instructions}"
        ),
        section_materials="Materials: {materials_line}\n{chain_note}",
        section_finish="**Finish** Gold / Silver / Rose Gold.",
        section_packaging="Packaging block.",
        section_gift_note="Gift note block.",
        section_best_gifts_for="Gifts for {recipients_list} for {occasions_list}.",
        section_have_a_question="Question CTA.",
        brass_overrides={"materials_line": "Premium Brass with plating"},
        silver_overrides={"materials_line": "925 Sterling Silver"},
        default_chain_text="Standard 16 inch + 2 inch extender.",
    )


def _session(template: DescriptionTemplate) -> MagicMock:
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = template
    return session


def _brass_preset() -> VariationPreset:
    return VariationPreset(
        id=1,
        category="necklace",
        material_type=MaterialType.BRASS.value,
        finishes=["Gold", "Silver"],
        lengths_inches=[],
        has_length_variation=False,
    )


def _silver_preset() -> VariationPreset:
    return VariationPreset(
        id=2,
        category="necklace",
        material_type=MaterialType.SILVER_925.value,
        finishes=["Gold", "Silver", "Rose"],
        lengths_inches=[16, 18, 20],
        has_length_variation=True,
    )


def _product() -> Product:
    return Product(
        id=1,
        sku="TAKI-9999",
        carrier_pillar="birthstone",
        recipients_json=["Her", "Mother"],
        occasions_json=["Birthday", "Christmas"],
    )


def test_brass_uses_chain_note_and_brass_materials_line():
    engine = DescriptionEngine(_session(_template()))
    body = engine.fill(
        product=_product(),
        llm_intro="Bright unique intro paragraph.",
        preset=_brass_preset(),
        personalization=None,
        category="necklace",
    )
    assert "Premium Brass with plating" in body
    assert "Standard 16 inch + 2 inch extender." in body


def test_silver_omits_default_chain_note():
    engine = DescriptionEngine(_session(_template()))
    body = engine.fill(
        product=_product(),
        llm_intro="Bright unique intro paragraph.",
        preset=_silver_preset(),
        personalization=None,
        category="necklace",
    )
    assert "925 Sterling Silver" in body
    assert "Standard 16 inch + 2 inch extender." not in body
    # Silver preset lists actual length options
    assert "16 inch" in body


def test_personalization_block_injected():
    pers = PersonalizationTemplate(
        instruction_text="Please Provide: name",
        example_text="For example: Sarah",
        reference_note="Reference note.",
        max_characters=8,
        is_optional=False,
        type_signature={"has_name": True},
    )
    engine = DescriptionEngine(_session(_template()))
    body = engine.fill(
        product=_product(),
        llm_intro="Intro.",
        preset=_brass_preset(),
        personalization=pers,
        category="necklace",
    )
    assert "Please Provide: name" in body
    assert "For example: Sarah" in body
    assert "Reference note." in body


def test_recipients_and_occasions_formatting():
    engine = DescriptionEngine(_session(_template()))
    body = engine.fill(
        product=_product(),
        llm_intro="Intro.",
        preset=_brass_preset(),
        personalization=None,
        category="necklace",
    )
    assert "Her and Mother" in body
    assert "Birthday and Christmas" in body


def test_llm_intro_appears_in_body():
    engine = DescriptionEngine(_session(_template()))
    body = engine.fill(
        product=_product(),
        llm_intro="Bright unique intro paragraph.",
        preset=_brass_preset(),
        personalization=None,
        category="necklace",
    )
    assert "Bright unique intro paragraph." in body


def test_finish_section_renders_between_materials_and_packaging():
    engine = DescriptionEngine(_session(_template()))
    body = engine.fill(
        product=_product(),
        llm_intro="Bright unique intro paragraph.",
        preset=_brass_preset(),
        personalization=None,
        category="necklace",
    )
    assert "**Finish** Gold / Silver / Rose Gold." in body
    # Finish is its own section, sitting between Materials and Packaging.
    assert body.index("Materials:") < body.index("**Finish**") < body.index("Packaging block.")
