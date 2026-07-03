"""
Deterministic chart generators for the 9-image jewelry pipeline (PR 4).

Each generator produces a 2000x2000 PNG using pure Pillow drawing (no LLM,
no external template) so the output is byte-stable across runs — a
prerequisite for the SHA-256 snapshot tests in
``test_modules/test_chart_generators.py``.

Determinism notes:
- Uses ``ImageFont.load_default()`` (bundled bitmap font) to avoid shipping
  a variable font file.
- All draw calls use fixed integer coordinates.
- PNG save uses default Pillow options; ``optimize=False`` is the default
  and PNG chunks contain no timestamps unless explicitly requested.

Visual polish (brand palette, real templates) is a follow-up per the doc's
"Open decisions" section.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CHART_SIZE = (2000, 2000)
_BG = (255, 255, 255)
_FG = (30, 30, 30)
_ACCENT = (170, 130, 60)  # muted gold
_MUTED = (120, 120, 120)


def _font(size: int) -> ImageFont.ImageFont:
    """Return a deterministic font. Uses the bundled bitmap font so no
    external .ttf is required and output bytes are stable."""
    return ImageFont.load_default()


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", CHART_SIZE, _BG)
    draw = ImageDraw.Draw(img)
    return img, draw


def _header(draw: ImageDraw.ImageDraw, text: str) -> None:
    draw.rectangle([(0, 0), (CHART_SIZE[0], 200)], fill=_ACCENT)
    draw.text((80, 80), text, fill=_BG, font=_font(72))


class _AbstractChart(ABC):
    filename: str = "chart.png"

    @abstractmethod
    def render(self) -> Image.Image:
        raise NotImplementedError

    def save(self, output_dir: Path | str) -> str:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / self.filename
        img = self.render()
        img.save(path, format="PNG")
        return str(path)


class BirthstoneChartGenerator(_AbstractChart):
    """Grid of 12 birthstone swatches (one per month)."""

    filename = "birthstone_chart.png"

    _MONTHS = [
        ("January", "Garnet", (150, 30, 60)),
        ("February", "Amethyst", (110, 60, 160)),
        ("March", "Aquamarine", (90, 180, 200)),
        ("April", "Diamond", (220, 220, 230)),
        ("May", "Emerald", (30, 140, 90)),
        ("June", "Pearl", (240, 230, 220)),
        ("July", "Ruby", (200, 30, 60)),
        ("August", "Peridot", (170, 200, 60)),
        ("September", "Sapphire", (30, 70, 170)),
        ("October", "Opal", (230, 190, 200)),
        ("November", "Topaz", (230, 170, 60)),
        ("December", "Turquoise", (60, 180, 200)),
    ]

    def render(self) -> Image.Image:
        img, draw = _canvas()
        _header(draw, "Birthstone Guide")

        cols, rows = 3, 4
        pad_x, pad_y = 120, 260
        cell_w = (CHART_SIZE[0] - 2 * pad_x) // cols
        cell_h = (CHART_SIZE[1] - pad_y - 120) // rows

        for idx, (month, name, color) in enumerate(self._MONTHS):
            r, c = divmod(idx, cols)
            x0 = pad_x + c * cell_w + 20
            y0 = pad_y + r * cell_h + 20
            x1 = x0 + cell_w - 40
            y1 = y0 + cell_h - 40

            swatch_h = int((y1 - y0) * 0.55)
            draw.rectangle([(x0, y0), (x1, y0 + swatch_h)], fill=color)
            draw.rectangle([(x0, y0), (x1, y1)], outline=_FG, width=3)
            draw.text((x0 + 20, y0 + swatch_h + 20), month, fill=_FG, font=_font(28))
            draw.text((x0 + 20, y0 + swatch_h + 60), name, fill=_MUTED, font=_font(24))

        return img


class SizeChartGenerator(_AbstractChart):
    """Necklace length reference chart."""

    filename = "size_chart.png"

    def __init__(self, lengths_inches: list[int] | None = None) -> None:
        # Sort + dedupe for determinism regardless of caller input order.
        raw = lengths_inches or [14, 16, 18, 20, 22, 24]
        self.lengths = sorted({int(x) for x in raw})

    def render(self) -> Image.Image:
        img, draw = _canvas()
        _header(draw, "Necklace Size Guide")

        x_axis = 240
        y_top = 340
        row_height = 140

        draw.text((x_axis, y_top - 60), "Length", fill=_FG, font=_font(36))
        draw.text((x_axis + 900, y_top - 60), "Sits At", fill=_FG, font=_font(36))

        sit_at = {
            12: "Collar",
            14: "Choker",
            16: "Base of Neck",
            18: "Just Below Collarbone",
            20: "Above Bust",
            22: "At Bust",
            24: "Below Bust",
            26: "Sternum",
            28: "Mid-Chest",
        }

        for i, length in enumerate(self.lengths):
            y = y_top + i * row_height
            bar_w = 20 + length * 40
            draw.rectangle([(x_axis, y), (x_axis + bar_w, y + 60)], fill=_ACCENT)
            draw.text((x_axis + bar_w + 20, y + 10), f'{length}"', fill=_FG, font=_font(36))
            draw.text(
                (x_axis + 900, y + 10),
                sit_at.get(length, "Custom"),
                fill=_MUTED,
                font=_font(30),
            )

        return img


class CareInstructionsChartGenerator(_AbstractChart):
    """Four numbered care rules."""

    filename = "care_instructions.png"

    _RULES = [
        ("1", "Avoid Water", "Remove before showering, swimming, or washing hands."),
        ("2", "Skip the Chemicals", "Keep away from perfume, lotion, and hairspray."),
        ("3", "Store Dry", "Store in the pouch provided; keep away from humidity."),
        ("4", "Clean Gently", "Wipe with a soft, dry cloth after each wear."),
    ]

    def render(self) -> Image.Image:
        img, draw = _canvas()
        _header(draw, "Care Instructions")

        y = 340
        for badge, title, body in self._RULES:
            draw.ellipse([(140, y), (280, y + 140)], fill=_ACCENT)
            draw.text((190, y + 45), badge, fill=_BG, font=_font(56))
            draw.text((340, y + 20), title, fill=_FG, font=_font(44))
            draw.text((340, y + 80), body, fill=_MUTED, font=_font(30))
            y += 380

        return img


__all__ = [
    "BirthstoneChartGenerator",
    "SizeChartGenerator",
    "CareInstructionsChartGenerator",
    "CHART_SIZE",
]
