"""
Operational Integration v2.5 — seed loader.

Idempotently populates ShopSettings, PricingStrategy, DescriptionTemplate,
DefaultAttributes, VariationPreset, and PersonalizationTemplate rows so a
fresh install boots with a working baseline that matches the training
defaults.

Safe to call repeatedly: each seed_* helper checks for existing rows via
its unique key and only inserts what is missing. Never overwrites user
edits.
"""
from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from src.db.models import (
    DefaultAttributes,
    DescriptionTemplate,
    JewelryCategory,
    MaterialType,
    PersonalizationTemplate,
    PricingStrategy,
    RenewalOption,
    ShopSettings,
    VariationPreset,
)

_log = structlog.get_logger(__name__)


# ── ShopSettings & PricingStrategy singletons ─────────────────────────────────


def seed_shop_settings(session: Session) -> None:
    if session.query(ShopSettings).filter_by(id=1).first():
        return
    session.add(ShopSettings(
        id=1,
        renewal_option=RenewalOption.AUTOMATIC.value,
        return_policy_days=14,
        feature_listing_default=False,
        default_quantity=999,
        omit_karat_in_title=True,
        image_workflow_mode="jewelry_9",
    ))
    session.commit()


def seed_pricing_strategy(session: Session) -> None:
    if session.query(PricingStrategy).filter_by(id=1).first():
        return
    session.add(PricingStrategy(
        id=1,
        base_multiplier=4.0,
        finish_offsets_pct={"Gold": 0.0, "Silver": -3.0, "Rose": -5.0},
        length_base_inches=16,
        length_price_per_extra_inch_pct=2.5,
        loss_leader_enabled=True,
        loss_leader_finish="Rose",
        loss_leader_length=12,
        loss_leader_margin_pct=15.0,
        multi_count_extra_pct=12.0,
    ))
    session.commit()


# ── DescriptionTemplate — one row per JewelryCategory ─────────────────────────


_NECKLACE_TEMPLATE = {
    "section_intro": (
        "{product_name} — a dainty piece designed to be worn every day. "
        "Whether you wear it solo or layered, this necklace adds a "
        "personal touch to any look."
    ),
    "section_how_to_order": (
        "**How to Order**\n"
        "1. Choose your preferred finish — Gold, Silver, or Rose Gold.\n"
        "2. Select your chain length: {length_options}.\n"
        "{personalization_instructions}"
    ),
    "section_materials": (
        "**Materials**\n"
        "{materials_line}\n"
        "{chain_note}"
    ),
    "section_packaging": (
        "**Packaging & Shipping**\n"
        "Every order ships in a branded gift box, ready to give. "
        "Standard processing time is 3-5 business days."
    ),
    "section_gift_note": (
        "**Gift Note**\n"
        "Want to add a personal message? Include a gift note at checkout "
        "and we'll print it on a small card included with your order — at no extra cost."
    ),
    "section_best_gifts_for": (
        "**Best Gifts For**\n"
        "This necklace makes a thoughtful gift for {recipients_list} for "
        "{occasions_list}."
    ),
    "section_have_a_question": (
        "**Have a Question?**\n"
        "Message us anytime — we usually reply within a few hours. "
        "We love working with you on a custom piece, too."
    ),
    "brass_overrides": {"materials_line": "Premium Brass with 14K Gold/Silver/Rose Gold Plating"},
    "silver_overrides": {"materials_line": "925 Sterling Silver with optional Gold/Rose Gold Plating"},
    "default_chain_text": (
        "The chain is the standard 16 inch length with a 2 inch extender, "
        "so you can wear it at 16 or 18 inches."
    ),
}


def _tpl(category: JewelryCategory, product_word: str, **overrides) -> dict:
    """Build a template dict per category, defaulting to the necklace scaffold."""
    tpl = dict(_NECKLACE_TEMPLATE)
    tpl["section_intro"] = tpl["section_intro"].replace("necklace", product_word)
    tpl["section_best_gifts_for"] = tpl["section_best_gifts_for"].replace("necklace", product_word)
    tpl.update(overrides)
    tpl["category"] = category.value
    return tpl


def seed_description_templates(session: Session) -> None:
    seed_specs = [
        _tpl(JewelryCategory.NECKLACE, "necklace"),
        _tpl(JewelryCategory.BRACELET, "bracelet",
             default_chain_text="The bracelet is 7 inch with a 1 inch extender."),
        _tpl(JewelryCategory.EARRING, "pair of earrings",
             section_how_to_order=(
                "**How to Order**\n"
                "1. Choose your preferred finish — Gold or Silver.\n"
                "{personalization_instructions}"
             ),
             default_chain_text=""),
        _tpl(JewelryCategory.RING, "ring",
             section_how_to_order=(
                "**How to Order**\n"
                "1. Choose your preferred finish — Gold, Silver, or Rose Gold.\n"
                "2. Select your ring size.\n"
                "{personalization_instructions}"
             ),
             default_chain_text=""),
    ]

    for spec in seed_specs:
        if session.query(DescriptionTemplate).filter_by(category=spec["category"]).first():
            continue
        session.add(DescriptionTemplate(**spec))
    session.commit()


# ── DefaultAttributes — one per category ──────────────────────────────────────


def seed_default_attributes(session: Session) -> None:
    for category in JewelryCategory:
        if session.query(DefaultAttributes).filter_by(category=category.value).first():
            continue
        session.add(DefaultAttributes(
            category=category.value,
            style="Minimalist",
            theme="Love & Friendship",
            holiday_default="Christmas",
            sustainability="Made with Recycled Metals",
            chain_style="Cable Chain" if category == JewelryCategory.NECKLACE else "",
            adjustable=True,
            convertible=True,
            default_occasion="Birthday",
        ))
    session.commit()


# ── VariationPreset — the 4 default skeletons ─────────────────────────────────


def seed_variation_presets(session: Session) -> None:
    presets = [
        dict(
            name="necklace_brass_standard",
            category=JewelryCategory.NECKLACE.value,
            material_type=MaterialType.BRASS.value,
            finishes=["Gold", "Silver"],
            lengths_inches=[],
            has_length_variation=False,
        ),
        dict(
            name="necklace_silver_standard",
            category=JewelryCategory.NECKLACE.value,
            material_type=MaterialType.SILVER_925.value,
            finishes=["Gold", "Silver", "Rose"],
            lengths_inches=[12, 14, 16, 18, 20, 22, 24],
            has_length_variation=True,
        ),
        dict(
            name="necklace_brass_multi_birthstone",
            category=JewelryCategory.NECKLACE.value,
            material_type=MaterialType.BRASS.value,
            finishes=["Gold", "Silver"],
            lengths_inches=[],
            multi_count_label="Birthstone",
            multi_count_range=[1, 2, 3],
            has_length_variation=False,
        ),
        dict(
            name="earring_basic",
            category=JewelryCategory.EARRING.value,
            material_type=MaterialType.BRASS.value,
            finishes=["Gold", "Silver"],
            lengths_inches=[],
            has_length_variation=False,
        ),
    ]

    for spec in presets:
        if session.query(VariationPreset).filter_by(name=spec["name"]).first():
            continue
        session.add(VariationPreset(**spec))
    session.commit()


# ── PersonalizationTemplate — library ─────────────────────────────────────────


def seed_personalization_templates(session: Session) -> None:
    templates = [
        dict(
            name="none",
            instruction_text="",
            example_text="",
            reference_note="",
            max_characters=0,
            is_optional=True,
            applicable_categories=["necklace", "bracelet", "earring", "ring"],
            type_signature={"none": True},
        ),
        dict(
            name="birthstone_initial_single",
            instruction_text=(
                "Please Provide:\n"
                "1. Birthstone (e.g. May, October)\n"
                "2. Initial (one letter)"
            ),
            example_text="For example: Birthstone (May), Initial (E)",
            reference_note="You can see birthstone types in the photo.",
            max_characters=0,
            is_optional=False,
            applicable_categories=["necklace", "bracelet"],
            type_signature={"has_initial": True, "has_birthstone": True, "count": 1},
        ),
        dict(
            name="multi_birthstone_3",
            instruction_text=(
                "Please Provide:\n"
                "1. Number of Birthstones (1-3)\n"
                "2. Birth Month for each (in order)\n"
                "3. Initial for each (in order)"
            ),
            example_text="For example: 3 birthstones, May/June/August, A/B/C",
            reference_note="You can see birthstone types in the photo.",
            max_characters=0,
            is_optional=False,
            applicable_categories=["necklace"],
            type_signature={"has_initial": True, "has_birthstone": True, "count_max": 3},
        ),
        dict(
            name="name_only",
            instruction_text="Please Provide:\nThe name to be engraved.",
            example_text="For example: Sarah",
            reference_note="",
            max_characters=8,
            is_optional=False,
            applicable_categories=["necklace", "bracelet"],
            type_signature={"has_name": True, "count": 1},
        ),
        dict(
            name="name_date",
            instruction_text=(
                "Please Provide:\n"
                "1. Name\n"
                "2. Date (MM/DD/YYYY)"
            ),
            example_text="For example: Sarah, 05/12/2024",
            reference_note="",
            max_characters=20,
            is_optional=False,
            applicable_categories=["necklace", "bracelet"],
            type_signature={"has_name": True, "has_date": True},
        ),
        dict(
            name="custom_text",
            instruction_text="Please Provide:\nThe custom text to be engraved.",
            example_text="For example: 'Forever & Always'",
            reference_note="",
            max_characters=25,
            is_optional=False,
            applicable_categories=["necklace", "bracelet", "ring"],
            type_signature={"has_custom_text": True},
        ),
    ]

    for spec in templates:
        if session.query(PersonalizationTemplate).filter_by(name=spec["name"]).first():
            continue
        session.add(PersonalizationTemplate(**spec))
    session.commit()


# ── Top-level entry ───────────────────────────────────────────────────────────


def seed_all(session: Session) -> None:
    """Run every seeder. Idempotent — safe on repeated calls."""
    seed_shop_settings(session)
    seed_pricing_strategy(session)
    seed_description_templates(session)
    seed_default_attributes(session)
    seed_variation_presets(session)
    seed_personalization_templates(session)
    _log.info("operational_integration_seed_complete")


if __name__ == "__main__":
    from src.db.session import SessionLocal

    with SessionLocal() as s:
        seed_all(s)
        print("Seed complete.")
