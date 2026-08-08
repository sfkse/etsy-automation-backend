"""Tests for the Phase 4 sourcing-grounding bridge.

``patch_research_builder_for_sourcing`` is the shared helper both content
pipelines rely on — the classic ``/products/{sku}/generate-content`` route and
the extension's ``/listings/build`` background task — to inject a chosen
keyword's market brief into every LLM call. These tests assert the addendum
reaches the orchestrator's research builder (and all three generators) without
needing a DB or LLM.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from src.db.models import Product
from src.modules.research.context_builder import (
    ResearchContext,
    ResearchContextBuilder,
    patch_research_builder_for_sourcing,
)


def _make_orchestrator() -> SimpleNamespace:
    """Mimic VariantBundleOrchestrator's wiring: research builder + three
    generators that each hold their own reference to it."""
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    builder = ResearchContextBuilder(session)
    return SimpleNamespace(
        research=builder,
        title=SimpleNamespace(research=builder),
        tag=SimpleNamespace(research=builder),
        desc=SimpleNamespace(research=builder),
    )


def test_patch_injects_addendum_into_build_for_product():
    orch = _make_orchestrator()
    product = Product(sku="TAKI-1", carrier_pillar="cross")

    patch_research_builder_for_sourcing(orch, "SOURCING BRIEF")

    ctx = orch.research.build_for_product(product)
    assert ctx.sourcing_addendum == "SOURCING BRIEF"


def test_patch_injects_addendum_into_build_for_keywords():
    orch = _make_orchestrator()

    patch_research_builder_for_sourcing(orch, "KW BRIEF")

    ctx = orch.research.build_for_keywords(["cross necklace"])
    assert ctx.sourcing_addendum == "KW BRIEF"


def test_patch_rebinds_all_generators_to_the_patched_builder():
    orch = _make_orchestrator()

    patch_research_builder_for_sourcing(orch, "X")

    assert orch.title.research is orch.research
    assert orch.tag.research is orch.research
    assert orch.desc.research is orch.research


def test_format_for_prompt_surfaces_addendum_when_research_data_present():
    """When the product has competitor data, the sourcing brief must appear in
    the prompt the LLM sees."""
    ctx = ResearchContext(
        sample_size=10,
        avg_title_length=120.0,
        top_keywords_sales_weighted=[],
        underused_keywords=[],
        structural_patterns=[],
        top_tags=[],
        cliches_to_avoid=[],
        sourcing_addendum="PRIMARY TARGET KEYWORD: 'cross necklace'",
    )

    out = ctx.format_for_prompt()

    assert "PRIMARY TARGET KEYWORD" in out
