"""
Per-field, per-variant content regeneration.

The approval screen needs to redo ONE field of ONE variant — variant B's tags,
variant C's description — without re-running the whole 3-variant pipeline and
without touching the scrape. The generators are already per-angle, so this
module is the wiring: recover the variant's angle, call the one generator, keep
the variant internally coherent, and write back the single field.

Coherence: the generation pipeline is serialized (title → tags → description)
because each step pairs with the previous one's output. Regenerating tags or a
description alone is clean — both pair against the variant's *current* stored
title. Regenerating a title alone is not: the existing tags were written to
complement the old one. Rather than cascade into extra LLM calls, a title regen
re-runs ``normalize_tags`` against the new title, which drops tags the new title
has made redundant and backfills from the keyword pool for free. The description
is left alone and reported as stale — rewriting it costs a real call the caller
may not want.
"""
from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from src.db.models import PersonalizationTemplate, Product, VariationPreset
from src.domain.validators import normalize_tags
from src.modules.content.orchestrator import VariantBundleOrchestrator
from src.modules.llm.angles import angle_for_label

_log = structlog.get_logger(__name__)

REGENERABLE_FIELDS: frozenset[str] = frozenset({"title", "tags", "description"})


class RegenerationError(Exception):
    """Raised when a field cannot be regenerated (unknown variant, no angle …)."""


async def regenerate_variant_field(
    product: Product,
    variant: dict,
    field: str,
    orchestrator: VariantBundleOrchestrator,
    session: Session | None = None,
) -> dict:
    """Regenerate ``field`` for one variant. Exactly one LLM call.

    ``variant`` is the stored variant dict from ``product.generated_variants``.
    Returns ``{"updates": {...}, "notes": [...]}`` — the fields to persist and
    any human-readable notes about knock-on effects. Does not touch the DB; the
    caller persists via ``update_variant_field`` so the write stays a
    read-modify-write of individual fields.
    """
    if field not in REGENERABLE_FIELDS:
        raise RegenerationError(f"Field {field!r} cannot be regenerated")

    variant_id = variant.get("id", "")
    label = variant.get("strategy_label", "")
    angle = angle_for_label(label, variant_letter=variant_id)
    if angle is None:
        # HYBRID is user-composed — there is no angle to generate against.
        raise RegenerationError(
            f"Variant {variant_id} ({label or 'no strategy'}) has no strategic "
            "angle to regenerate from"
        )

    title = variant.get("title", "")
    tags = list(variant.get("tags") or [])

    updates: dict = {}
    notes: list[str] = []

    if field == "title":
        new_title = await orchestrator.title.generate_for_angle(product, angle)
        updates["title"] = new_title

        # The stored tags were written against the OLD title. Drop the ones the
        # new title has made redundant and backfill — no extra LLM call.
        cleaned, tag_notes = normalize_tags(tags, new_title)
        dropped = len(tags) - len(cleaned)
        if dropped:
            updates["tags"] = _backfill_tags(
                cleaned, tags, product, new_title, orchestrator, want=len(tags)
            )
            replaced = sum(
                1 for t in updates["tags"] if t.lower() not in {o.lower() for o in tags}
            )
            if replaced:
                notes.append(
                    f"{dropped} tag(s) duplicated the new title; {replaced} replaced "
                    "from the keyword pool"
                )
            else:
                notes.append(
                    f"{dropped} tag(s) now duplicate the new title, but the keyword "
                    "pool had no replacements — they were kept so all "
                    f"{len(tags)} slots stay filled. Worth editing by hand."
                )
            notes.extend(tag_notes)
        if variant.get("description"):
            notes.append(
                "Description still echoes the previous title — regenerate it too "
                "if you want them aligned"
            )

    elif field == "tags":
        updates["tags"] = await orchestrator.tag.generate_for_angle(
            product, angle, paired_title=title
        )

    else:  # description
        description = await orchestrator.desc.generate_for_angle(
            product, angle, paired_title=title, paired_tags=tags
        )
        # Store links live in the description; without this the regenerated copy
        # silently loses them (guide §4 — in-shop links raise session time).
        description = await orchestrator.linker.insert_links(description, product)

        # The LLM only writes the unique intro. Everything else the buyer reads —
        # How to Order, Materials, Finish, Packaging, Gift Note, Best Gifts For,
        # Have a Question — comes from the DescriptionEngine scaffold, applied by
        # the listings pipeline after generation. Skipping it here replaced a
        # fully-formed description with a bare intro paragraph.
        description, scaffolded = _apply_scaffold(product, description, session)
        if not scaffolded and _looks_scaffolded(variant.get("description", "")):
            notes.append(
                "The previous description had operational sections (How to Order, "
                "Materials …) that could not be rebuilt — this product has no "
                "variation preset. Regenerated intro only; re-check before publishing."
            )
        updates["description"] = description

    # The CTR badge is derived from title + tags, so it goes stale whenever
    # either changes.
    if "title" in updates or "tags" in updates:
        updates["estimated_ctr_signal"] = orchestrator._estimate_ctr_signal(
            updates.get("title", title),
            updates.get("tags", tags),
            angle,
            product,
        )

    _log.info(
        "variant_field_regenerated",
        sku=product.sku,
        variant=variant_id,
        field=field,
        angle=angle.label,
        also_updated=sorted(set(updates) - {field}),
    )
    return {"updates": updates, "notes": notes}


def _apply_scaffold(
    product: Product, llm_intro: str, session: Session | None
) -> tuple[str, bool]:
    """Wrap ``llm_intro`` in the operational 8-section scaffold.

    Mirrors what ``run_listing_content_pipeline`` does after generation: the
    scaffold only applies when the product has a variation preset (the source of
    the material/length vocabulary), so products built through the classic
    generate-content route are returned unchanged — exactly as they were built.

    Returns ``(description, was_scaffolded)``.
    """
    if session is None or not product.variation_preset_id:
        return llm_intro, False

    # Local imports: the listings package imports from content, so module-level
    # imports here would close a cycle.
    from src.modules.listings.description_engine import DescriptionEngine
    from src.modules.listings.orchestrator import _category_from_preset

    preset = session.get(VariationPreset, product.variation_preset_id)
    if preset is None:
        return llm_intro, False

    personalization = (
        session.get(PersonalizationTemplate, product.personalization_template_id)
        if product.personalization_template_id
        else None
    )

    filled = DescriptionEngine(session).fill(
        product=product,
        llm_intro=llm_intro,
        preset=preset,
        personalization=personalization,
        category=_category_from_preset(preset),
    )
    return filled, filled != llm_intro


# Headings the DescriptionEngine scaffold emits. Used only to warn when a
# previously-scaffolded description cannot be rebuilt.
_SCAFFOLD_MARKERS = (
    "How to Order",
    "Best Gifts For",
    "Have a Question",
    "Packaging",
)


def _looks_scaffolded(description: str) -> bool:
    return sum(m in description for m in _SCAFFOLD_MARKERS) >= 2


def _backfill_tags(
    cleaned: list[str],
    original: list[str],
    product: Product,
    title: str,
    orchestrator: VariantBundleOrchestrator,
    want: int,
) -> list[str]:
    """Top ``cleaned`` back up to ``want`` tags, never returning fewer.

    Sources are tried in order — pillar pool, then universal staples — and if
    both are exhausted the dropped tags go back in. The keyword pool is often
    empty for a given carrier_pillar, and an unfilled tag slot is worse than a
    redundant one; ``validate_tags`` still surfaces the wasted slot for review.
    """
    if len(cleaned) >= want:
        return cleaned[:want]

    taken = {t.lower() for t in cleaned}

    def _take_from(source: list[str], allow_title_dupes: bool = False) -> None:
        for candidate in source:
            if len(cleaned) >= want:
                break
            normalized, _ = normalize_tags(
                [candidate], "" if allow_title_dupes else title
            )
            if not normalized or normalized[0].lower() in taken:
                continue
            cleaned.append(normalized[0])
            taken.add(normalized[0].lower())

    _take_from(orchestrator.tag.pool.get_candidates(
        pillar=product.carrier_pillar,
        features=product.shape,
        exclude_in_title=title,
    ))
    _take_from(orchestrator.tag.pool.get_universal_keywords())
    _take_from(original, allow_title_dupes=True)

    return cleaned[:want]
