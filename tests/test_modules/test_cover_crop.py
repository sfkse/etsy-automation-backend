"""Cover-photo auto-crop tests (PR 4)."""
from __future__ import annotations

from PIL import Image

from src.modules.images.cover_crop import auto_crop_cover_photo


def _make_synthetic(path, subject_box: tuple[int, int, int, int]) -> None:
    """2000x2000 white canvas with a black square at ``subject_box``."""
    img = Image.new("RGB", (2000, 2000), (255, 255, 255))
    for y in range(subject_box[1], subject_box[3]):
        for x in range(subject_box[0], subject_box[2]):
            img.putpixel((x, y), (0, 0, 0))
    img.save(path, format="PNG")


def test_auto_crop_centres_on_offcenter_subject(tmp_path):
    src = tmp_path / "in.png"
    out = tmp_path / "out.jpg"
    _make_synthetic(src, (500, 500, 900, 900))

    result_path = auto_crop_cover_photo(src, out, target_size=(2000, 2000))
    assert result_path == str(out)

    result = Image.open(out).convert("L")
    assert result.size == (2000, 2000)

    mask = result.point(lambda p: 255 if p < 120 else 0, mode="L")
    bbox = mask.getbbox()
    assert bbox is not None, "subject not found in output"

    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    assert abs(cx - 1000) <= 5, f"subject cx={cx} not centred"
    assert abs(cy - 1000) <= 5, f"subject cy={cy} not centred"


def test_auto_crop_handles_all_white_input(tmp_path):
    """Degenerate saliency fallback: no non-white pixels → still returns a
    valid output of target_size without raising."""
    src = tmp_path / "white.png"
    out = tmp_path / "out.png"
    Image.new("RGB", (2000, 2000), (255, 255, 255)).save(src)

    auto_crop_cover_photo(src, out, target_size=(2000, 2000))
    assert Image.open(out).size == (2000, 2000)
