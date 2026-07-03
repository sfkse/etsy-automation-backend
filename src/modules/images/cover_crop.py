"""
Cover-photo auto-crop for the 9-image jewelry pipeline (PR 4).

Given a mannequin/product image, produce a square cover crop centred on
the subject. Subject detection uses a lightweight non-white centre-of-mass
heuristic (no external saliency model) — sufficient for pre-preprocessed
imagery where the background has already been removed / replaced with
white by ``preprocessing.preprocess_and_save``.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

_WHITE_THRESHOLD = 240  # any channel < this => pixel counts as subject


def _subject_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Return (x0, y0, x1, y1) bounding box of non-white pixels, or None."""
    gray = img.convert("L")
    # Any pixel darker than threshold is "subject". point() returns 0/255 mask.
    mask = gray.point(lambda p: 255 if p < _WHITE_THRESHOLD else 0, mode="L")
    return mask.getbbox()


def auto_crop_cover_photo(
    image_path: str | Path,
    output_path: str | Path,
    target_size: tuple[int, int] = (2000, 2000),
    product_bbox: tuple[int, int, int, int] | None = None,
) -> str:
    """
    Centre-crop an image on the detected (or supplied) subject and resize
    to ``target_size``. The output is always square when ``target_size`` is
    square.

    Args:
        image_path: Input image path.
        output_path: Destination path (JPEG or PNG inferred from suffix).
        target_size: Output (width, height). Defaults to 2000x2000.
        product_bbox: Optional pre-computed (x0, y0, x1, y1) subject bbox
            in input-image coordinates. If ``None``, uses non-white
            centre-of-mass as a saliency fallback.

    Returns:
        The output path as a string.
    """
    img = Image.open(image_path).convert("RGB")
    w, h = img.size

    bbox = product_bbox or _subject_bbox(img)
    if bbox is None:
        # Fully-white image — degenerate case. Just center-crop the input.
        bbox = (w // 4, h // 4, 3 * w // 4, 3 * h // 4)

    cx = (bbox[0] + bbox[2]) // 2
    cy = (bbox[1] + bbox[3]) // 2

    # Largest centred square crop that keeps the subject centre at the
    # output centre without falling off the input edges.
    half = min(cx, w - cx, cy, h - cy)
    if half <= 0:
        # Subject touches an edge — fall back to a smaller centred crop.
        half = min(w, h) // 4

    crop_box = (cx - half, cy - half, cx + half, cy + half)
    cropped = img.crop(crop_box)
    resized = cropped.resize(target_size, Image.LANCZOS)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = "JPEG" if output_path.suffix.lower() in {".jpg", ".jpeg"} else "PNG"
    save_kwargs = {"quality": 92} if fmt == "JPEG" else {}
    resized.save(output_path, format=fmt, **save_kwargs)

    return str(output_path)


__all__ = ["auto_crop_cover_photo"]
