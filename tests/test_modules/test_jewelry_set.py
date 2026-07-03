"""Tests for jewelry_set.generate_jewelry_set (PR 4).

Uses MagicMock/AsyncMock to stub every AbstractImageGenerator call so the
suite runs offline. Verifies the 3+3+3 shape, chart selection heuristic,
and that all 6 AI calls dispatch concurrently via asyncio.gather.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from src.db.models import PersonalizationTemplate, Product, VariationPreset
from src.modules.images.base import ImageGenerationResult
from src.modules.images.jewelry_set import generate_jewelry_set


def _fake_ai_result() -> ImageGenerationResult:
    return ImageGenerationResult(
        image=Image.new("RGB", (512, 512), (200, 180, 160)),
        model_name="mock",
        cost_estimate=0.0,
    )


def _mock_generator(concurrency_probe: list[int]) -> MagicMock:
    """Return a generator whose .generate coroutine records concurrency."""
    active = {"n": 0, "max": 0}

    async def fake_generate(_request):
        active["n"] += 1
        active["max"] = max(active["max"], active["n"])
        await asyncio.sleep(0)  # let other tasks start
        active["n"] -= 1
        concurrency_probe.append(active["max"])
        return [_fake_ai_result()]

    gen = MagicMock()
    gen.generate = AsyncMock(side_effect=fake_generate)
    return gen


def _make_product(stone_shape=None, personalization=None, preset=None) -> Product:
    p = Product(
        id=1,
        sku="TAKI-9001",
        carrier_pillar="cross",
        stone_shape=stone_shape,
        variation_preset_id=(preset.id if preset else None),
        personalization_template_id=(personalization.id if personalization else None),
    )
    return p


def _session_returning(preset=None, personalization=None) -> MagicMock:
    session = MagicMock()

    def query_side(model):
        q = MagicMock()
        if model is VariationPreset:
            q.filter_by.return_value.first.return_value = preset
        elif model is PersonalizationTemplate:
            q.filter_by.return_value.first.return_value = personalization
        else:
            q.filter_by.return_value.first.return_value = None
        return q

    session.query.side_effect = query_side
    return session


@pytest.mark.asyncio
async def test_generates_3_mannequin_3_concept_and_3_charts_when_birthstone(tmp_path):
    preset = VariationPreset(id=1, name="p", lengths_inches=[16, 18, 20])
    personalization = PersonalizationTemplate(
        id=1,
        name="birthstone_single",
        type_signature={"has_birthstone": True},
    )
    product = _make_product(stone_shape="round", personalization=personalization, preset=preset)
    session = _session_returning(preset=preset, personalization=personalization)

    probe: list[int] = []
    with patch(
        "src.modules.images.jewelry_set.ImageWorkflowFactory.get",
        return_value=_mock_generator(probe),
    ):
        result = await generate_jewelry_set(
            product=product,
            workflow="flux",
            session=session,
            settings=MagicMock(),
            reference_image=Image.new("RGBA", (256, 256), (255, 255, 255, 255)),
            output_dir=tmp_path,
        )

    assert len(result.mannequin_shots) == 3
    assert len(result.concept_shots) == 3
    assert result.size_chart is not None
    assert result.birthstone_chart is not None
    assert result.care_instructions_chart is not None

    assert max(probe) >= 2, "AI generator calls did not run concurrently"

    charts_dir = tmp_path / "charts"
    assert (charts_dir / "size_chart.png").exists()
    assert (charts_dir / "birthstone_chart.png").exists()
    assert (charts_dir / "care_instructions.png").exists()


@pytest.mark.asyncio
async def test_skips_birthstone_chart_when_not_warranted(tmp_path):
    product = _make_product(stone_shape=None, personalization=None, preset=None)
    session = _session_returning()

    with patch(
        "src.modules.images.jewelry_set.ImageWorkflowFactory.get",
        return_value=_mock_generator([]),
    ):
        result = await generate_jewelry_set(
            product=product,
            workflow="flux",
            session=session,
            settings=MagicMock(),
            reference_image=Image.new("RGBA", (256, 256), (255, 255, 255, 255)),
            output_dir=tmp_path,
        )

    assert result.birthstone_chart is None
    assert result.size_chart is not None
    assert result.care_instructions_chart is not None
