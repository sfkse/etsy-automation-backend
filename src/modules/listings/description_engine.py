"""
Description Template Engine (Section D of OPERATIONAL_INTEGRATION.md).

Wraps the LLM-generated intro/personality content inside a fixed 7-section
scaffold: intro, How to Order, Materials, Packaging, Gift Note, Best Gifts
For, Have a Question. This preserves originality (LLM writes the unique
intro) while giving every listing the same operational skeleton.

Coexistence: Phase 6's DescriptionGenerator still runs first — its output
becomes the {product_name}/intro slot. The engine merely wraps it.
"""
from __future__ import annotations

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
    ) -> str:
        """
        Assemble the 7 sections into a full description body.

        Args:
            product:         The Product being built.
            llm_intro:       The LLM-generated intro paragraph (unique per variant).
            preset:          Chosen VariationPreset (drives brass/silver material line).
            personalization: Chosen PersonalizationTemplate, or None.
            category:        JewelryCategory value ("necklace" | "bracelet" | ...).

        Returns the assembled description text (without internal links —
        callers should append those separately via InternalLinker).
        """
        template = (
            self.session.query(DescriptionTemplate)
            .filter_by(category=category)
            .first()
        )
        if template is None:
            _log.warning("description_engine_no_template", category=category)
            return llm_intro

        # Material vocabulary
        if preset.material_type == MaterialType.BRASS.value:
            material_overrides = template.brass_overrides or {}
            chain_note = template.default_chain_text or ""
        else:
            material_overrides = template.silver_overrides or {}
            chain_note = ""  # silver gets length variation, no fixed chain note

        # Personalization block
        if personalization and not (personalization.type_signature or {}).get("none"):
            pers_lines = ["", personalization.instruction_text or ""]
            if personalization.example_text:
                pers_lines.append(personalization.example_text)
            if personalization.reference_note:
                pers_lines.append(personalization.reference_note)
            pers_block = "\n".join(l for l in pers_lines if l is not None)
        else:
            pers_block = ""

        # Length options
        if preset.has_length_variation and preset.lengths_inches:
            lengths_str = ", ".join(f"{l} inch" for l in preset.lengths_inches)
        else:
            lengths_str = "Standard 16 inch with 2 inch extender"

        # Recipients / occasions — prefer JSON list on Product, fall back to singular
        recipients = product.recipients_json or (
            [product.recipient] if product.recipient else []
        )
        occasions = product.occasions_json or (
            [product.occasion] if product.occasion else []
        )

        product_name = self._product_name(product, llm_intro)

        context = {
            "product_name": product_name,
            "length_options": lengths_str,
            "personalization_instructions": pers_block,
            "materials_line": material_overrides.get("materials_line", "—"),
            "chain_note": chain_note,
            "recipients_list": self._format_list(recipients),
            "occasions_list": self._format_list(occasions) or "special occasions",
        }

        sections = [
            template.section_intro,
            template.section_how_to_order,
            template.section_materials,
            template.section_packaging,
            template.section_gift_note,
            template.section_best_gifts_for,
            template.section_have_a_question,
        ]

        rendered: list[str] = []
        for section in sections:
            if not section:
                continue
            try:
                rendered.append(section.format(**context))
            except KeyError as exc:
                _log.warning(
                    "description_engine_missing_placeholder",
                    placeholder=str(exc),
                    category=category,
                )
                rendered.append(section)

        # Prepend the LLM's unique intro when the scaffold intro doesn't already
        # embed it via {product_name}. We always include llm_intro at the top so
        # each variant reads uniquely.
        body_parts: list[str] = []
        if llm_intro and llm_intro.strip() and llm_intro not in rendered[0]:
            body_parts.append(llm_intro.strip())
        body_parts.extend(rendered)

        return "\n\n".join(part for part in body_parts if part.strip())

    @staticmethod
    def _product_name(product: Product, llm_intro: str) -> str:
        """Best-effort product name for the {product_name} slot."""
        if product.final_title:
            return product.final_title.split(",")[0].strip()
        if product.user_provided_title:
            return product.user_provided_title.split(",")[0].strip()
        # Fallback: first sentence of the LLM intro, truncated.
        first = llm_intro.split(".")[0].strip() if llm_intro else ""
        return first[:80] or "This piece"

    @staticmethod
    def _format_list(items: list[str]) -> str:
        cleaned = [i for i in items if i]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        if len(cleaned) == 2:
            return f"{cleaned[0]} and {cleaned[1]}"
        return ", ".join(cleaned[:-1]) + f", and {cleaned[-1]}"
