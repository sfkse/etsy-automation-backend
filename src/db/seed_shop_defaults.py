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
from src.modules.listings.description_engine import spaced_header

_log = structlog.get_logger(__name__)


# ── ShopSettings & PricingStrategy singletons ─────────────────────────────────


def seed_shop_settings(session: Session) -> None:
    if session.query(ShopSettings).filter_by(id=1).first():
        return
    session.add(
        ShopSettings(
            id=1,
            renewal_option=RenewalOption.AUTOMATIC.value,
            return_policy_days=14,
            feature_listing_default=False,
            default_quantity=999,
            omit_karat_in_title=True,
            image_workflow_mode="jewelry_9",
            image_palette="soft_blush_neutral",
            auto_create_sections=True,
        )
    )
    session.commit()


def seed_pricing_strategy(session: Session) -> None:
    if session.query(PricingStrategy).filter_by(id=1).first():
        return
    session.add(
        PricingStrategy(
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
        )
    )
    session.commit()


# ── DescriptionTemplate — one row per (category, material) ────────────────────
#
# Shop house style: title line, one short LLM intro paragraph, then
# "★★ S P A C E D ★★" headers with • bullets. Placeholders are filled by
# DescriptionEngine.fill (see its context dict for the full list). Necklaces get
# a brass and a silver_925 template; DescriptionEngine picks by the preset's
# material_type and falls back to the category's "any" row.

_H = spaced_header

_ANY = "any"

_NECKLACE_TEMPLATE = {
    "section_intro": "{product_name}",
    "section_how_to_order": (
        f"{_H('How to Order')}\n\n"
        "• Choose the color: {finish_options}\n"
        "• Choose necklace length: {length_summary}\n"
        "{personalization_instructions}\n\n"
        "• Please let us know if you need help with your order."
    ),
    "section_materials": f"{_H('Material')}\n\n" "• {materials_line}",
    "section_finish": (
        f"{_H('Finish')}\n\n"
        "{finish_bullets}\n\n"
        f"{_H('Chain Length')}\n\n"
        "{length_bullets}\n\n"
        "This necklace beautifully catches the light and leaves a gleaming "
        "impression! Energetic, unique, and wonderfully dynamic — like you, it "
        "is full of personality. It makes a glorious gift or a personal treat "
        "for yourself. :)"
    ),
    "section_packaging": (
        f"{_H('Package')}\n\n"
        "• Comes with a stylish gift box\n"
        "• Ready to ship in 3-5 business days"
    ),
    "section_gift_note": (
        f"{_H('Gift Note')}\n\n"
        "• If you want to include a short gift note, we will be happy to add a "
        "handwritten note to your order. Please let us know your message at "
        "checkout."
    ),
    "section_best_gifts_for": (
        f"{_H('Best Gift')}\n\n"
        "• This necklace can be a special gift for your {gift_recipients}. "
        "Each piece is packaged in a beautiful gift box, suitable for "
        "{gift_occasions}."
    ),
    "section_have_a_question": (
        f"{_H('Have a Question?')}\n\n"
        "• Feel free to message us with any question you may have, or any "
        "problem you may face during or after your order.\n\n"
        "• Each order is made to your specifications, so please make sure to "
        "select the right options before checkout, as we do not offer a free "
        "replacement.\n\n"
        "Thank you for choosing our {product_name}! We are confident you will "
        "love the style, comfort, and quality of our handmade jewelry."
    ),
    "brass_overrides": {
        "materials_line": "Premium Brass with 14K Gold/Silver/Rose Gold Plating"
    },
    "silver_overrides": {
        "materials_line": "925 Sterling Silver with optional Gold/Rose Gold Plating"
    },
    "default_chain_text": "16 inches with a 2 inch extender",
}

# Brass necklaces: one fixed chain, no length choice.
_NECKLACE_BRASS = {
    "section_how_to_order": (
        f"{_H('How to Order')}\n\n"
        "• Choose the color: {finish_options}\n"
        "• Chain length: {length_summary}\n"
        "{personalization_instructions}\n\n"
        "• Please let us know if you need help with your order."
    ),
    "section_materials": (
        f"{_H('Material')}\n\n" "• Premium Brass with 14K Gold / Silver Plating"
    ),
    "default_chain_text": "16 inches with a 2 inch extender",
}

# Silver necklaces: lengths come from the preset ({length_summary}/{length_bullets}).
_NECKLACE_SILVER = {
    "section_materials": f"{_H('Material')}\n\n" "• 925 Sterling Silver",
    "default_chain_text": "",
}


def _tpl(
    category: JewelryCategory, product_word: str, material: str = _ANY, **overrides
) -> dict:
    """Build a template dict per category, defaulting to the necklace scaffold."""
    tpl = dict(_NECKLACE_TEMPLATE)
    for key in ("section_how_to_order", "section_finish", "section_best_gifts_for"):
        tpl[key] = tpl[key].replace("necklace", product_word)
    tpl.update(overrides)
    tpl["category"] = category.value
    tpl["material_type"] = material
    return tpl


# Signatures of earlier defaults ("**How to Order**" markdown headers, the
# "dainty piece" intro, sentence-form chain text, and the material-agnostic
# house-style sections that predate the brass/silver split). Rows still holding
# these are upgraded in place; anything else is a user edit and kept.
_LEGACY_MARKERS = (
    "**",
    "a dainty piece designed to be worn every day",
    "The chain is the standard 16 inch",
    "The bracelet is 7 inch with",
)
_LEGACY_EXACT = {
    _NECKLACE_TEMPLATE["section_how_to_order"],
    _NECKLACE_TEMPLATE["section_materials"],
}
_UPGRADABLE_FIELDS = (
    "section_intro",
    "section_how_to_order",
    "section_materials",
    "section_finish",
    "section_packaging",
    "section_gift_note",
    "section_best_gifts_for",
    "section_have_a_question",
    "default_chain_text",
)


def _is_legacy(value: str | None) -> bool:
    return (
        not value
        or value in _LEGACY_EXACT
        or any(marker in value for marker in _LEGACY_MARKERS)
    )


def seed_description_templates(session: Session) -> None:
    seed_specs = [
        _tpl(
            JewelryCategory.NECKLACE, "necklace", MaterialType.BRASS.value,
            **_NECKLACE_BRASS,
        ),
        _tpl(
            JewelryCategory.NECKLACE, "necklace", MaterialType.SILVER_925.value,
            **_NECKLACE_SILVER,
        ),
        _tpl(
            JewelryCategory.RING,
            "ring",
            section_how_to_order=(
                f"{_H('How to Order')}\n\n"
                "• Choose the color: {finish_options}\n"
                "• Choose your ring size\n"
                "{personalization_instructions}\n\n"
                "• Please let us know if you need help with your order."
            ),
            section_finish=(
                f"{_H('Finish')}\n\n"
                "{finish_bullets}\n\n"
                "This ring beautifully catches the light and leaves a gleaming "
                "impression! Energetic, unique, and wonderfully dynamic — like "
                "you, it is full of personality. It makes a glorious gift or a "
                "personal treat for yourself. :)"
            ),
            default_chain_text="",
        ),
    ]

    for spec in seed_specs:
        existing = (
            session.query(DescriptionTemplate)
            .filter_by(category=spec["category"], material_type=spec["material_type"])
            .first()
        )
        if existing:
            # Upgrade sections still on an old default to the current text;
            # sections the user rewrote in Settings are left untouched.
            for field in _UPGRADABLE_FIELDS:
                current = getattr(existing, field)
                if field == "default_chain_text" and not current and not spec[field]:
                    continue
                if _is_legacy(current):
                    setattr(existing, field, spec[field])
            continue
        session.add(DescriptionTemplate(**spec))
    session.commit()


# ── DefaultAttributes — one per category ──────────────────────────────────────


def seed_default_attributes(session: Session) -> None:
    for category in JewelryCategory:
        if session.query(DefaultAttributes).filter_by(category=category.value).first():
            continue
        session.add(
            DefaultAttributes(
                category=category.value,
                style="Minimalist",
                theme="Love & Friendship",
                holiday_default="Christmas",
                sustainability="Made with Recycled Metals",
                chain_style=(
                    "Cable Chain" if category == JewelryCategory.NECKLACE else ""
                ),
                adjustable=True,
                convertible=True,
                default_occasion="Birthday",
            )
        )
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
            type_signature={
                "has_initial": True,
                "has_birthstone": True,
                "count_max": 3,
            },
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
            instruction_text=("Please Provide:\n" "1. Name\n" "2. Date (MM/DD/YYYY)"),
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


# ── Universal keyword staples (Christmas 2 SEO/tag training) ──────────────────


def seed_universal_keywords(session: Session) -> None:
    """Seed the 9 universal jewelry SEO keywords the tag training says belong in
    every title/tag pass. They carry carrier_pillar=None and is_universal=True so
    the tag generator offers them across all pillars. Idempotent."""
    from src.db.models import KeywordPool

    universals = [
        ("Custom", "big"),
        ("Personalized", "big"),
        ("Gold", "big"),
        ("14K Gold", "medium"),
        ("14K Gold Plated", "niche"),
        ("925 Silver", "medium"),
        ("Sterling Silver", "big"),
        ("Dainty", "big"),
        ("Minimalist", "big"),
    ]

    inserted = 0
    for kw, cat in universals:
        if session.query(KeywordPool).filter_by(keyword=kw).first():
            continue
        session.add(
            KeywordPool(
                keyword=kw,
                category=cat,
                carrier_pillar=None,
                is_universal=True,
            )
        )
        inserted += 1
    session.commit()

    if inserted:
        _log.info("universal_keywords_seeded", count=inserted)


# ── Top-level entry ───────────────────────────────────────────────────────────


def seed_all(session: Session) -> None:
    """Run every seeder. Idempotent — safe on repeated calls."""
    seed_shop_settings(session)
    seed_pricing_strategy(session)
    seed_description_templates(session)
    seed_default_attributes(session)
    seed_variation_presets(session)
    seed_personalization_templates(session)
    seed_universal_keywords(session)
    _log.info("operational_integration_seed_complete")


if __name__ == "__main__":
    from src.db.session import SessionLocal

    with SessionLocal() as s:
        seed_all(s)
        print("Seed complete.")
