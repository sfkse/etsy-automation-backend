"""Deterministic-output tests for the 9-image chart generators (PR 4)."""
from __future__ import annotations

import hashlib
import io

import pytest

from src.modules.images.chart_generators import (
    CHART_SIZE,
    BirthstoneChartGenerator,
    CareInstructionsChartGenerator,
    SizeChartGenerator,
)


def _png_bytes(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _sha(img) -> str:
    return hashlib.sha256(_png_bytes(img)).hexdigest()


@pytest.mark.parametrize(
    "factory",
    [
        lambda: BirthstoneChartGenerator(),
        lambda: SizeChartGenerator([14, 16, 18, 20, 22, 24]),
        lambda: CareInstructionsChartGenerator(),
    ],
)
def test_chart_output_is_deterministic(factory):
    a = factory().render()
    b = factory().render()
    assert _sha(a) == _sha(b)
    assert a.size == CHART_SIZE


def test_size_chart_input_order_does_not_change_output():
    """Sorting/dedupe inside the generator means callers can pass any order."""
    a = SizeChartGenerator([18, 14, 22, 16, 20, 24]).render()
    b = SizeChartGenerator([14, 16, 18, 20, 22, 24, 24]).render()
    assert _sha(a) == _sha(b)


def test_save_writes_png_and_returns_path(tmp_path):
    path_str = BirthstoneChartGenerator().save(tmp_path)
    assert path_str.endswith("birthstone_chart.png")
    assert (tmp_path / "birthstone_chart.png").exists()
