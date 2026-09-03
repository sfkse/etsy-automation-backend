"""
Background removal preprocessing (Step 5.2).
Uses rembg (local, no API cost) to strip backgrounds from jewelry photos.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from PIL import Image

_MODEL_NAME = "u2net"

# rembg runs u2net through an ONNX InferenceSession, and building one loads the
# ~176MB model into memory. Calling ``remove()`` without a ``session=`` argument
# builds a throwaway session per call, so a 9-image build paid that cost nine
# times over. Cached here for the life of the process and passed explicitly.
# The lock guards the build: run_image_pipeline calls this via asyncio.to_thread,
# so two concurrent builds could otherwise race and load the model twice.
_SESSION: Any = None
_SESSION_LOCK = threading.Lock()


def get_rembg_session() -> Any:
    """Return the process-wide rembg session, building it on first use."""
    global _SESSION
    if _SESSION is None:
        with _SESSION_LOCK:
            if _SESSION is None:
                try:
                    from rembg import new_session  # type: ignore[import]
                except ImportError as exc:
                    raise ImportError(
                        "rembg is required for background removal. "
                        "Install it with: pip install rembg"
                    ) from exc
                _SESSION = new_session(_MODEL_NAME)
    return _SESSION


def warm_up() -> None:
    """Preload the u2net model.

    Called from the app lifespan so the download + ONNX init happens at boot
    rather than inside the first listing build. Blocking — run it in a thread.
    """
    get_rembg_session()


def remove_background(image_path: str | Path) -> Image.Image:
    """
    Remove background from a jewelry photo using rembg.

    Returns a PIL Image with transparent background (RGBA).

    Blocking CPU work — never call this directly from a coroutine.
    """
    try:
        from rembg import remove  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "rembg is required for background removal. "
            "Install it with: pip install rembg"
        ) from exc

    source = Image.open(image_path).convert("RGBA")
    result: Image.Image = remove(source, session=get_rembg_session())
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
