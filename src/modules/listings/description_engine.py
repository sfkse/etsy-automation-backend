"""
Description Template Engine (Section D of OPERATIONAL_INTEGRATION.md).

Wraps the LLM-generated intro inside a fixed section scaffold, rendered in the
shop's Etsy style — a title line, one short intro paragraph, then
"★★ H O W - T O - O R D E R ★★"-style headers with • bullet lists: How to
Order, Material, Finish (+ Chain Length), Package, Gift Note, Best Gift, Have a
Question. The LLM writes only the unique intro; every listing shares the same
operational skeleton.

Coexistence: Phase 6's DescriptionGenerator still runs first — its output
becomes the intro slot. The engine merely wraps it.
"""
from __future__ import annotations

import re
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from src.db.models import (
    DescriptionTemplate,
    MaterialType,
    PersonalizationTemplate,
    Product,
    VariationPreset,
)

_log = structlog.get_logger(__name__)

# Recipients / occasions every listing mentions, after the product's own ones.
_DEFAULT_GIFT_RECIPIENTS = [
    "mother", "wife", "girlfriend", "daughter", "sister", "grandma", "best friend",
]
_DEFAULT_GIFT_OCCASIONS = [
    "Birthday", "Graduation", "Anniversary", "Christmas", "Mother's Day",
    "Valentine's Day",
]
# Recipient tags that don't read after "a special gift for your ...".
_NON_NOUN_RECIPIENTS = {"her", "him", "them", "anyone", "everyone", "unisex", "women", "men"}

# InternalLinker appends lines in this shape; they belong at the very end.
_LINK_LINE = re.compile(r"^View our \[.+\]\(https?://\S+\)$")
_LINKS_LEAD_IN = "For more of our collection, you can visit the links below:"


def spaced_header(label: str) -> str:
    """'How to Order' -> '★★ H O W - T O - O R D E R ★★'."""
    words = [" ".join(word.upper()) for word in label.split()]
    return f"★★ {' - '.join(words)} ★★"


class DescriptionEngine:
    """Fill a category DescriptionTemplate with product-specific context."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def fill(
        self,
        product: Product,
        llm_intro: str,
        preset: VariationPreset,
        personalization: Optional[PersonalizationTemplate],
        category: str,
        title: str = "",
    ) -> str:
        """
        Assemble the title line, LLM intro and scaffold sections into a full
        description body.

        Args:
            product:         The Product being built.
            llm_intro:       The LLM-generated intro paragraph (unique per variant).
                             Any trailing InternalLinker lines are moved to the end.
            preset:          Chosen VariationPreset (drives material/finish/length lines).
            personalization: Chosen PersonalizationTemplate, or None.
            category:        JewelryCategory value ("necklace" | "bracelet" | ...).
            title:           The variant's own title — its first comma segment
                             becomes the title line / {product_name}.

        Returns the assembled description text.
        """
        template = self._find_template(category, preset.material_type)
        if template is None:
            _log.warning("description_engine_no_template", category=category)
            return llm_intro

        intro, links = self._split_links(llm_intro or "")

        # Material vocabulary
        # Legacy material vocabulary — per-material templates write their
        # material text directly, but older rows still use {materials_line}.
        if preset.material_type == MaterialType.BRASS.value:
            material_overrides = template.brass_overrides
            chain_note = template.default_chain_text or ""
        else:
            material_overrides = template.silver_overrides
            chain_note = ""  # silver gets length variation, no fixed chain note
        if not isinstance(material_overrides, dict):
            material_overrides = {}  # e.g. saved as a plain string from Settings

        # Personalization block
        if personalization and not (personalization.type_signature or {}).get("none"):
            pers_lines = ["", "• Add your personalization:"]
            for text in (
                personalization.instruction_text,
                personalization.example_text,
                personalization.reference_note,
            ):
                if text:
                    pers_lines.append(text)
            pers_block = "\n".join(pers_lines)
        else:
            pers_block = ""

        # Length options
        if preset.has_length_variation and preset.lengths_inches:
            lengths = list(preset.lengths_inches)
            lengths_str = ", ".join(f"{l} inch" for l in lengths)
            length_summary = (
                f"{min(lengths)}” to {max(lengths)}” available"
                if len(lengths) > 1
                else f"{lengths[0]}”"
            )
            length_bullets = (
                "\n".join(f"• {l} inches" for l in lengths)
                + "\n\n(Please leave a message for any other lengths upon request.)"
            )
        else:
            fixed = template.default_chain_text or "16 inches with a 2 inch extender"
            lengths_str = length_summary = fixed
            length_bullets = f"• {fixed}"

        finishes = list(preset.finishes or [])

        # Recipients / occasions — prefer JSON list on Product, fall back to singular
        recipients = product.recipients_json or (
            [product.recipient] if product.recipient else []
        )
        occasions = product.occasions_json or (
            [product.occasion] if product.occasion else []
        )

        product_name = self._product_name(product, title, category)

        context = {
            "product_name": product_name,
            "length_options": lengths_str,
            "length_summary": length_summary,
            "length_bullets": length_bullets,
            "finish_options": ", ".join(finishes) or "Gold, Silver",
            "finish_bullets": "\n".join(f"• {f}" for f in finishes) or "• Gold\n• Silver",
            "personalization_instructions": pers_block,
            "materials_line": material_overrides.get("materials_line", "—"),
            "chain_note": chain_note,
            "recipients_list": self._format_list(recipients),
            "occasions_list": self._format_list(occasions) or "special occasions",
            "gift_recipients": self._format_list(
                self._merge(
                    [r for r in recipients if r and r.lower() not in _NON_NOUN_RECIPIENTS],
                    _DEFAULT_GIFT_RECIPIENTS,
                ),
                conj="or",
            ),
            "gift_occasions": self._format_list(
                self._merge(occasions, _DEFAULT_GIFT_OCCASIONS)
            ),
        }

        def render(section: Optional[str]) -> str:
            if not section:
                return ""
            try:
                return section.format(**context)
            except KeyError as exc:
                _log.warning(
                    "description_engine_missing_placeholder",
                    placeholder=str(exc),
                    category=category,
                )
                return section

        # Title line first, then the LLM's unique intro, then the scaffold.
        body_parts = [render(template.section_intro), intro]
        body_parts.extend(
            render(section)
            for section in (
                template.section_how_to_order,
                template.section_materials,
                template.section_finish,
                template.section_packaging,
                template.section_gift_note,
                template.section_best_gifts_for,
                template.section_have_a_question,
            )
        )
        if links:
            body_parts.append(_LINKS_LEAD_IN + "\n" + "\n".join(links))

        body = "\n\n".join(part.strip() for part in body_parts if part.strip())
        # Empty placeholders (no personalization, no chain note) leave blank runs.
        body = re.sub(r"[ \t]+\n", "\n", body)
        return re.sub(r"\n{3,}", "\n\n", body)

    def _find_template(
        self, category: str, material_type: Optional[str]
    ) -> Optional[DescriptionTemplate]:
        """Material-specific template, else the category's shared ("any") one,
        else any row for the category (gold_plated presets, pre-split DBs)."""
        query = self.session.query(DescriptionTemplate)
        for criteria in (
            {"category": category, "material_type": material_type},
            {"category": category, "material_type": "any"},
            {"category": category},
        ):
            if criteria.get("material_type", "") is None:
                continue
            template = query.filter_by(**criteria).first()
            if template is not None:
                return template
        return None

    @staticmethod
    def _split_links(text: str) -> tuple[str, list[str]]:
        """Separate trailing InternalLinker lines from the intro text."""
        lines = text.rstrip().split("\n")
        links: list[str] = []
        while lines and _LINK_LINE.match(lines[-1].strip()):
            links.insert(0, lines.pop().strip())
        return "\n".join(lines).strip(), links

    @staticmethod
    def _product_name(product: Product, title: str, category: str) -> str:
        """Product name for the {product_name} slot: the first comma segment of
        the variant title, else the approved / user-provided title.

        Never derived from the intro — final_title is unset until approval, and
        a truncated intro sentence made the title line read as cut-off text.
        """
        for candidate in (title, product.final_title, product.user_provided_title):
            if candidate and candidate.split(",")[0].strip():
                return candidate.split(",")[0].strip()
        return f"Handmade {category.replace('_', ' ').title()}"

    @staticmethod
    def _merge(own: list[str], defaults: list[str]) -> list[str]:
        """Product values first, then defaults, deduplicated case-insensitively."""
        seen: set[str] = set()
        merged: list[str] = []
        for item in [*own, *defaults]:
            if item and item.lower() not in seen:
                seen.add(item.lower())
                merged.append(item)
        return merged

    @staticmethod
    def _format_list(items: list[str], conj: str = "and") -> str:
        cleaned = [i for i in items if i]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        if len(cleaned) == 2:
            return f"{cleaned[0]} {conj} {cleaned[1]}"
        return ", ".join(cleaned[:-1]) + f", {conj} {cleaned[-1]}"
