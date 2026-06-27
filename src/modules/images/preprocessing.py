"""
Background removal preprocessing (Step 5.2).
Uses rembg (local, no API cost) to strip backgrounds from jewelry photos.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image


def remove_background(image_path: str | Path) -> Image.Image:
    """
    Remove background from a jewelry photo using rembg.

    Returns a PIL Image with transparent background (RGBA).
    """
    try:
        from rembg import remove  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "rembg is required for background removal. "
            "Install it with: pip install rembg"
        ) from exc

    source = Image.open(image_path).convert("RGBA")
    result: Image.Image = remove(source)
    return result


def preprocess_and_save(
    image_path: str | Path,
    sku: str,
    images_dir: str | Path,
) -> Path:
    """
    Remove background and persist to {images_dir}/{sku}/preprocessed/bg_removed.png.

    Returns the path of the saved file.
    """
    output_dir = Path(images_dir) / sku / "preprocessed"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "bg_removed.png"

    result = remove_background(image_path)
    result.save(output_path, format="PNG")
    return output_path
