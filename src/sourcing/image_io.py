"""
Image I/O helpers for the Sourcing module.

Handles saving uploaded FastAPI files and downloading remote images to the
local data/images/sourcing/ directory.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import structlog

_log = structlog.get_logger(__name__)

_SOURCING_DIR = Path("./data/images/sourcing")
_DOWNLOAD_TIMEOUT = 30

_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def _ensure_dir() -> Path:
    _SOURCING_DIR.mkdir(parents=True, exist_ok=True)
    return _SOURCING_DIR


async def save_uploaded_image(upload_file) -> str:
    """
    Save a FastAPI UploadFile to disk and return the local path string.
    Accepts jpg, jpeg, png, webp, gif.
    """
    target_dir = _ensure_dir()

    # Determine extension from filename or content type
    filename = upload_file.filename or ""
    suffix = Path(filename).suffix.lower() if filename else ".jpg"
    if suffix not in _ALLOWED_EXTENSIONS:
        suffix = ".jpg"

    dest_name = f"{uuid.uuid4().hex}{suffix}"
    dest_path = target_dir / dest_name

    content = await upload_file.read()
    dest_path.write_bytes(content)

    _log.info("sourcing_image_saved", path=str(dest_path), size=len(content))
    return str(dest_path)


def download_remote_image(url: str) -> str:
    """
    Download an image from a URL to disk and return the local path string.
    Raises httpx.HTTPError on failure.
    """
    target_dir = _ensure_dir()

    # Guess extension from URL
    url_path = url.split("?")[0]
    suffix = Path(url_path).suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        suffix = ".jpg"

    dest_name = f"{uuid.uuid4().hex}{suffix}"
    dest_path = target_dir / dest_name

    with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=_DOWNLOAD_TIMEOUT) as client:
        resp = client.get(url)
        resp.raise_for_status()
        dest_path.write_bytes(resp.content)

    _log.info("sourcing_image_downloaded", url=url, path=str(dest_path), size=len(resp.content))
    return str(dest_path)
