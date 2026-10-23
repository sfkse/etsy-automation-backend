"""
Background removal preprocessing (Step 5.2).
Uses rembg (local, no API cost) to strip backgrounds from jewelry photos.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

# Max per-pixel distance (in 0-255 RGB space) from the sampled backdrop color
# for a pixel to be treated as background and forced transparent in
# ``_clear_enclosed_background``. Tuned empirically: 18 clears the flat white
# backdrop and any enclosed backdrop-colored holes while leaving painted
# enamel/gemstone colors (which differ from a flat studio white/cream by more
# than this) untouched.
_BACKDROP_COLOR_TOLERANCE = 18

_MODEL_NAME = "isnet-general-use"

# rembg runs this model through an ONNX InferenceSession, and building one loads
# the model into memory. Calling ``remove()`` without a ``session=`` argument
# builds a throwaway session per call, so a 9-image build paid that cost nine
# times over. Cached here for the life of the process and passed explicitly.
# The lock guards the build: run_image_pipeline calls this via asyncio.to_thread,
# so two concurrent builds could otherwise race and load the model twice.
#
# Was "u2net" — it reliably erased thin, low-contrast foreground detail (a
# second small charm, fine chain links) on multi-charm jewelry photos, e.g.
# TAKI-0012's letter "H" charm vanished during background removal and the AI
# generator, only ever seeing the mangled reference, reproduced just the
# remaining evil-eye charm. isnet-general-use segments fine edges/thin
# structures far more reliably.
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
    """Preload the background-removal model.

    Called from the app lifespan so the download + ONNX init happens at boot
    rather than inside the first listing build. Blocking — run it in a thread.
    """
    get_rembg_session()


def _clear_enclosed_background(source: Image.Image, result: Image.Image) -> Image.Image:
    """Force fully-transparent any pixel matching the photo's backdrop color.

    rembg's segmentation mask is built from the object's silhouette, so an
    open/pierced pendant (a cutout letter, a geometric openwork design) gets
    its interior "holes" kept opaque — the mask sees them as enclosed by the
    foreground and never marks them background, even though the backdrop is
    still visible through them in the original photo. That leaves a
    solid-white (or cream) fill behind the piercing that reads as an
    unintended white-enamel infill once an AI generator uses the reference.

    Fixes it by sampling the backdrop color from the photo's four corners
    (these shots are always on a seamless studio backdrop) and zeroing alpha
    on every pixel within ``_BACKDROP_COLOR_TOLERANCE`` of that color,
    regardless of whether it's enclosed by the silhouette or touches the
    image border. Painted enamel/gemstone colors sit far enough from a flat
    studio white/cream to survive this untouched.
    """
    src_arr = np.asarray(source.convert("RGBA")).astype(np.int16)
    out_arr = np.array(result.convert("RGBA"))

    h, w = src_arr.shape[:2]
    edge = max(1, min(20, h // 10, w // 10))
    corners = np.concatenate(
        [
            src_arr[0:edge, 0:edge, :3].reshape(-1, 3),
            src_arr[0:edge, w - edge : w, :3].reshape(-1, 3),
            src_arr[h - edge : h, 0:edge, :3].reshape(-1, 3),
            src_arr[h - edge : h, w - edge : w, :3].reshape(-1, 3),
        ]
    )
    backdrop_color = corners.mean(axis=0)

    distance = np.sqrt(((src_arr[:, :, :3] - backdrop_color) ** 2).sum(axis=2))
    backdrop_like = distance < _BACKDROP_COLOR_TOLERANCE

    fixed = out_arr.copy()
    fixed[backdrop_like, 3] = 0
    return Image.fromarray(fixed, "RGBA")


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
    return _clear_enclosed_background(source, result)


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
