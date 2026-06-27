"""
Manual Input Module — SKU generation and image storage utilities.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from src.db.models import Product


def generate_sku(session: Session) -> str:
    """Return the next auto-incremented SKU in the format TAKI-NNNN."""
    last = (
        session.query(Product.sku)
        .order_by(Product.id.desc())
        .first()
    )
    if last is None:
        return "TAKI-0001"
    match = re.search(r"(\d+)$", last[0])
    next_n = (int(match.group(1)) + 1) if match else 1
    return f"TAKI-{next_n:04d}"


async def save_product_images(
    sku: str,
    primary_file: UploadFile,
    extra_files: list[UploadFile],
    images_dir: str,
) -> list[dict]:
    """
    Write uploaded images to {images_dir}/{SKU}/originals/.

    Returns a list of dicts with keys: file_path, is_real, rank.
    Primary image gets rank=1 and is_real=True.
    Extra images get rank=2+ and is_real=True.
    """
    dest_dir = Path(images_dir) / sku / "originals"
    dest_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []

    all_files = [(primary_file, 1)] + [
        (f, idx + 2) for idx, f in enumerate(extra_files) if f.filename
    ]

    for upload, rank in all_files:
        if not upload.filename:
            continue
        safe_name = Path(upload.filename).name
        dest_path = dest_dir / safe_name
        # Avoid clobbering by adding rank prefix when names collide
        if dest_path.exists() and rank > 1:
            dest_path = dest_dir / f"{rank}_{safe_name}"
        contents = await upload.read()
        dest_path.write_bytes(contents)
        results.append({
            "file_path": str(dest_path),
            "is_real": True,
            "rank": rank,
        })

    return results
