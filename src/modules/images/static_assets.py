"""
Common listing images — charts and cards shared by every product.

The asset library is a folder of finished images (``settings.ASSETS_DIR``,
default ``data/assets``): birthstone chart, chain-length chart, care
instructions … Any image dropped there shows up in the images-page gallery.

Attaching an asset copies it into the product's image folder as a JPEG and adds
a ``ProductImage`` row (``workflow_source="asset:<stem>"``), so the approval
page, the images ZIP and publishing all pick it up like any other photo.

The jewelry-9 pipeline auto-attaches ``default_assets_for(product)``; the user
can add or remove any library image by hand from the images page.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from src.config.settings import Settings
from src.db.models import (
    JewelryCategory,
    MaterialType,
    PersonalizationTemplate,
    Product,
    ProductImage,
    VariationPreset,
)
from src.modules.images.alt_text import generate_alt_text
from src.utils.logger import get_logger

logger = get_logger(__name__)

ASSET_SOURCE_PREFIX = "asset:"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_SIDE = 2000

CHAIN_CHART = "chain_chart.png"
BIRTHSTONE_CHART = "birthstone_chart.png"
CARE_INSTRUCTIONS = "care_instructions.png"


# ── Library ─────────────────────────────────────────────────────────────────


def _label(stem: str) -> str:
    return stem.replace("_", " ").replace("-", " ").title()


def list_assets(settings: Settings) -> list[dict]:
    """Image files in the asset library, sorted by name."""
    root = Path(settings.ASSETS_DIR)
    if not root.is_dir():
        return []
    return [
        {"name": p.name, "label": _label(p.stem), "url": f"/assets/{p.name}"}
        for p in sorted(root.iterdir())
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ]


def asset_path(settings: Settings, name: str) -> Optional[Path]:
    """Library path for ``name``, or None if it isn't a library image.

    Only names that ``list_assets`` returns are accepted, so a request can't
    reach outside the library (``../`` etc.).
    """
    if name not in {a["name"] for a in list_assets(settings)}:
        return None
    return Path(settings.ASSETS_DIR) / name


def _sanitize_stem(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-_")
    return stem[:60] or "asset"


def _unique_library_path(root: Path, stem: str, ext: str) -> Path:
    """``stem.ext``, or ``stem-2.ext``, ``stem-3.ext`` … so an upload never
    silently overwrites an existing library image."""
    candidate = root / f"{stem}{ext}"
    n = 1
    while candidate.exists():
        n += 1
        candidate = root / f"{stem}-{n}{ext}"
    return candidate


def save_uploaded_asset(settings: Settings, filename: str, data: bytes) -> dict:
    """Add a new image to the library from raw uploaded bytes.

    Always re-saved as PNG, regardless of the source format: keeps
    transparency, avoids re-compressing an already-lossy JPEG a second time,
    and gives every library file a predictable extension. Returns the same
    shape as a ``list_assets`` row. Raises ``ValueError`` if ``data`` isn't a
    readable image — the gallery can then show that reason instead of adding
    a broken thumbnail.
    """
    try:
        img = Image.open(io.BytesIO(data))
        img.load()  # decode now so a truncated upload fails here, not on first render
    except Exception as exc:
        raise ValueError(f"not a valid image: {exc}") from exc

    root = Path(settings.ASSETS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    stem = _sanitize_stem(Path(filename or "asset").stem)
    dest = _unique_library_path(root, stem, ".png")
    img.save(dest, format="PNG")

    return {"name": dest.name, "label": _label(dest.stem), "url": f"/assets/{dest.name}"}


def remove_from_library(settings: Settings, name: str) -> bool:
    """Delete a library image. Returns False if ``name`` isn't in the library.

    Leaves any product's already-attached copy alone — ``attach_asset`` copies
    the file into that product's own folder, so removing the library master
    doesn't touch listings that already used it.
    """
    path = asset_path(settings, name)
    if path is None:
        return False
    path.unlink(missing_ok=True)
    return True


# ── Auto-attach rules ───────────────────────────────────────────────────────


def _has_birthstone(product: Product, session: Session) -> bool:
    if (product.stone_type or "").lower() == "birthstone":
        return True
    if (product.carrier_pillar or "").lower() == "birthstone":
        return True
    if product.personalization_template_id:
        pers = session.get(PersonalizationTemplate, product.personalization_template_id)
        if pers and isinstance(pers.type_signature, dict):
            return bool(pers.type_signature.get("has_birthstone"))
    return False


def _is_silver_necklace(product: Product, session: Session) -> bool:
    if product.material_type != MaterialType.SILVER_925.value:
        return False
    preset = (
        session.get(VariationPreset, product.variation_preset_id)
        if product.variation_preset_id
        else None
    )
    category = preset.category if preset else JewelryCategory.NECKLACE.value
    return category == JewelryCategory.NECKLACE.value


def default_assets_for(product: Product, session: Session) -> list[str]:
    """Library images to attach automatically, in listing order.

    - chain chart: silver necklaces (brass has one fixed chain)
    - birthstone chart: products with a birthstone — not any stone, so a CZ
      ``stone_shape`` alone doesn't qualify
    - care instructions: every product
    """
    names: list[str] = []
    if _is_silver_necklace(product, session):
        names.append(CHAIN_CHART)
    if _has_birthstone(product, session):
        names.append(BIRTHSTONE_CHART)
    names.append(CARE_INSTRUCTIONS)
    return names


# ── Attach / detach ─────────────────────────────────────────────────────────


def _output_path(product: Product, settings: Settings, name: str) -> Path:
    stem = Path(name).stem
    return (
        Path(settings.IMAGES_DIR)
        / product.sku
        / "assets"
        / f"{product.sku.lower()}-asset-{stem}.jpg"
    )


def _write_jpeg(src: Path, dest: Path) -> None:
    """Flatten to RGB and fit within MAX_SIDE — never cropped, so a non-square
    chart keeps all of its content."""
    with Image.open(src) as img:
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            canvas = Image.new("RGBA", img.size, (255, 255, 255, 255))
            canvas.paste(img, (0, 0), img)
            img = canvas
        img = img.convert("RGB")
        if max(img.size) > MAX_SIDE:
            img = ImageOps.contain(img, (MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, format="JPEG", quality=92)


def attach_asset(
    product: Product,
    session: Session,
    settings: Settings,
    name: str,
    rank: Optional[int] = None,
) -> Optional[ProductImage]:
    """Copy library image ``name`` into the product and upsert its row.

    Idempotent: re-attaching refreshes the file and keeps the existing row (and
    its rank, unless ``rank`` is given). Returns None if ``name`` isn't in the
    library.
    """
    src = asset_path(settings, name)
    if src is None:
        logger.warning("static_asset_missing", sku=product.sku, asset=name)
        return None

    dest = _output_path(product, settings, name)
    _write_jpeg(src, dest)

    row = (
        session.query(ProductImage)
        .filter_by(product_id=product.id, is_real=False)
        .filter(ProductImage.file_path.like(f"%{dest.name}"))
        .first()
    )
    if row is None:
        if rank is None:
            ranks = [
                r for (r,) in session.query(ProductImage.rank)
                .filter_by(product_id=product.id, is_real=False)
                .all()
                if r is not None
            ]
            rank = max(ranks, default=0) + 1
        row = ProductImage(product_id=product.id, file_path=str(dest), is_real=False)
        session.add(row)
    if rank is not None:
        row.rank = rank
    row.file_path = str(dest)
    row.workflow_source = f"{ASSET_SOURCE_PREFIX}{Path(name).stem}"
    row.is_selected = False
    session.flush()
    row.alt_text = generate_alt_text(product, row)
    return row


def is_asset_row(image: ProductImage) -> bool:
    return (image.workflow_source or "").startswith(ASSET_SOURCE_PREFIX)


def detach_asset(product: Product, session: Session, image_id: int) -> bool:
    """Remove an attached asset (row + file). Refuses non-asset images."""
    row = session.get(ProductImage, image_id)
    if row is None or row.product_id != product.id or not is_asset_row(row):
        return False
    if row.file_path:
        Path(row.file_path).unlink(missing_ok=True)
    session.delete(row)
    session.flush()
    return True


def attached_assets(product: Product, session: Session) -> list[ProductImage]:
    """The product's attached asset rows, in rank order."""
    rows = (
        session.query(ProductImage)
        .filter_by(product_id=product.id, is_real=False)
        .order_by(ProductImage.rank)
        .all()
    )
    return [r for r in rows if is_asset_row(r)]


def asset_stem(image: ProductImage) -> str:
    return (image.workflow_source or "")[len(ASSET_SOURCE_PREFIX):]


__all__ = [
    "ASSET_SOURCE_PREFIX",
    "BIRTHSTONE_CHART",
    "CARE_INSTRUCTIONS",
    "CHAIN_CHART",
    "asset_path",
    "asset_stem",
    "attach_asset",
    "attached_assets",
    "default_assets_for",
    "detach_asset",
    "is_asset_row",
    "list_assets",
    "remove_from_library",
    "save_uploaded_asset",
]
