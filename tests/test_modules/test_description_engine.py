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


def _material_session(rows: dict) -> MagicMock:
    """Session whose filter_by(...) resolves by (category, material_type) kwargs.

    ``rows`` maps (category, material_type) → template; a filter without
    material_type returns the first row for the category.
    """
    session = MagicMock()

    def filter_by(**kwargs):
        result = MagicMock()
        category = kwargs.get("category")
        if "material_type" in kwargs:
            result.first.return_value = rows.get((category, kwargs["material_type"]))
        else:
            result.first.return_value = next(
                (t for (c, _), t in rows.items() if c == category), None
            )
        return result

    session.query.return_value.filter_by.side_effect = filter_by
    return session


def _named_template(materials: str) -> DescriptionTemplate:
    tpl = _template()
    tpl.section_materials = materials
    return tpl


def test_picks_material_specific_template():
    rows = {
        ("necklace", "brass"): _named_template("Material: Brass row"),
        ("necklace", "silver_925"): _named_template("Material: Silver row"),
    }
    engine = DescriptionEngine(_material_session(rows))
    kwargs = dict(product=_product(), llm_intro="Intro.", personalization=None,
                  category="necklace")

    brass = engine.fill(preset=_brass_preset(), **kwargs)
    silver = engine.fill(preset=_silver_preset(), **kwargs)

    assert "Brass row" in brass and "Silver row" not in brass
    assert "Silver row" in silver and "Brass row" not in silver


def test_falls_back_to_shared_any_template():
    rows = {("necklace", "any"): _named_template("Material: Shared row")}
    engine = DescriptionEngine(_material_session(rows))
    body = engine.fill(product=_product(), llm_intro="Intro.",
                       preset=_silver_preset(), personalization=None,
                       category="necklace")
    assert "Shared row" in body


def test_brass_fixed_chain_has_no_other_lengths_note():
    tpl = _template()
    tpl.section_finish = "Chain:\n{length_bullets}"
    tpl.default_chain_text = "16 inches with a 2 inch extender"
    engine = DescriptionEngine(_session(tpl))
    kwargs = dict(product=_product(), llm_intro="Intro.", personalization=None,
                  category="necklace")

    brass = engine.fill(preset=_brass_preset(), **kwargs)
    silver = engine.fill(preset=_silver_preset(), **kwargs)

    assert "• 16 inches with a 2 inch extender" in brass
    assert "other lengths" not in brass
    assert "• 18 inches" in silver and "other lengths" in silver


def test_string_override_does_not_crash():
    tpl = _template()
    tpl.brass_overrides = "{'materials_line': 'saved from a textarea'}"
    engine = DescriptionEngine(_session(tpl))
    body = engine.fill(product=_product(), llm_intro="Intro.",
                       preset=_brass_preset(), personalization=None,
                       category="necklace")
    assert "Materials: —" in body


def test_title_line_uses_variant_title_not_truncated_intro():
    tpl = _template()
    tpl.section_intro = "{product_name}"
    engine = DescriptionEngine(_session(tpl))
    intro = (
        "This sterling silver spiritual ankh cross necklace features an Egyptian "
        "cross pendant with your choice of birthstone for personalized meaning."
    )
    body = engine.fill(
        product=_product(),  # no final_title yet — as during generation
        llm_intro=intro,
        preset=_silver_preset(),
        personalization=None,
        category="necklace",
        title="Sterling Silver Ankh Necklace with Birthstone, Egyptian Cross, Gift for Her",
    )
    first_line, second = body.split("\n\n")[:2]
    assert first_line == "Sterling Silver Ankh Necklace with Birthstone"
    assert second == intro


def test_title_line_never_derived_from_intro():
    tpl = _template()
    tpl.section_intro = "{product_name}"
    engine = DescriptionEngine(_session(tpl))
    body = engine.fill(product=_product(), llm_intro="A long intro sentence here.",
                       preset=_silver_preset(), personalization=None,
                       category="necklace")
    assert body.split("\n\n")[0] == "Handmade Necklace"
