"""Tests for the common-images asset library (static_assets)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image

from src.db.models import (
    PersonalizationTemplate,
    Product,
    ProductImage,
    VariationPreset,
)
from src.modules.images import static_assets
from src.modules.images.alt_text import generate_alt_text


@pytest.fixture()
def settings(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    Image.new("RGB", (2500, 2000), (240, 240, 240)).save(assets / "birthstone_chart.png")
    Image.new("RGBA", (2025, 2025), (0, 0, 0, 0)).save(assets / "chain_chart.png")
    Image.new("RGB", (800, 800), (255, 255, 255)).save(assets / "care_instructions.png")
    (assets / "notes.txt").write_text("not an image")
    return SimpleNamespace(ASSETS_DIR=str(assets), IMAGES_DIR=str(tmp_path / "images"))


def _session(preset=None, personalization=None, existing=None, ranks=()):
    session = MagicMock()

    def get(model, _id):
        if model is VariationPreset:
            return preset
        if model is PersonalizationTemplate:
            return personalization
        if model is ProductImage:
            return existing
        return None

    session.get.side_effect = get
    q = session.query.return_value
    q.filter_by.return_value.filter.return_value.first.return_value = existing
    q.filter_by.return_value.all.return_value = [(r,) for r in ranks]
    return session


def _product(**kw) -> Product:
    base = dict(id=7, sku="TAKI-0007", carrier_pillar="cross", material="Brass",
                material_type="brass", variation_preset_id=1)
    base.update(kw)
    return Product(**base)


NECKLACE = VariationPreset(id=1, category="necklace")


# ── Library ───────────────────────────────────────────────────────────────────

def test_list_assets_ignores_non_images(settings):
    names = [a["name"] for a in static_assets.list_assets(settings)]
    assert names == ["birthstone_chart.png", "care_instructions.png", "chain_chart.png"]
    chain = next(a for a in static_assets.list_assets(settings) if a["name"] == "chain_chart.png")
    assert chain == {"name": "chain_chart.png", "label": "Chain Chart", "url": "/assets/chain_chart.png"}


def test_asset_path_rejects_traversal_and_unknown(settings):
    assert static_assets.asset_path(settings, "../secret.png") is None
    assert static_assets.asset_path(settings, "nope.png") is None
    assert static_assets.asset_path(settings, "chain_chart.png") is not None


# ── Rules ─────────────────────────────────────────────────────────────────────

def test_silver_necklace_gets_chain_and_care():
    product = _product(material_type="silver_925")
    assert static_assets.default_assets_for(product, _session(preset=NECKLACE)) == [
        "chain_chart.png", "care_instructions.png",
    ]


def test_brass_birthstone_gets_birthstone_and_care():
    product = _product(stone_type="Birthstone")
    assert static_assets.default_assets_for(product, _session(preset=NECKLACE)) == [
        "birthstone_chart.png", "care_instructions.png",
    ]


def test_silver_birthstone_necklace_gets_all_three_in_order():
    product = _product(material_type="silver_925", carrier_pillar="birthstone")
    assert static_assets.default_assets_for(product, _session(preset=NECKLACE)) == [
        "chain_chart.png", "birthstone_chart.png", "care_instructions.png",
    ]


def test_birthstone_personalization_counts():
    pers = PersonalizationTemplate(type_signature={"has_birthstone": True})
    product = _product(personalization_template_id=3)
    assert "birthstone_chart.png" in static_assets.default_assets_for(
        product, _session(preset=NECKLACE, personalization=pers)
    )


def test_cz_stone_shape_alone_is_not_a_birthstone():
    product = _product(stone_shape="round", stone_type="Cubic Zirconia")
    assert static_assets.default_assets_for(product, _session(preset=NECKLACE)) == [
        "care_instructions.png",
    ]


def test_silver_ring_gets_no_chain_chart():
    product = _product(material_type="silver_925")
    ring = VariationPreset(id=1, category="ring")
    assert "chain_chart.png" not in static_assets.default_assets_for(
        product, _session(preset=ring)
    )


# ── Attach / detach ───────────────────────────────────────────────────────────

def test_attach_writes_uncropped_jpeg_and_row(settings):
    product = _product()
    session = _session(ranks=[1, 7])

    row = static_assets.attach_asset(product, session, settings, "birthstone_chart.png")

    assert row.workflow_source == "asset:birthstone_chart"
    assert row.rank == 8
    assert row.is_real is False and row.is_selected is False
    assert row.file_path.endswith("TAKI-0007/assets/taki-0007-asset-birthstone_chart.jpg")
    with Image.open(row.file_path) as img:
        assert img.format == "JPEG"
        assert img.size == (2000, 1600)  # fit, not cropped
    session.add.assert_called_once_with(row)


def test_attach_transparent_png_flattens_to_rgb(settings):
    row = static_assets.attach_asset(_product(), _session(), settings, "chain_chart.png")
    with Image.open(row.file_path) as img:
        assert img.mode == "RGB"


def test_attach_is_idempotent_and_keeps_rank(settings):
    existing = ProductImage(id=5, product_id=7, rank=9, is_real=False,
                            file_path="old", workflow_source="asset:care_instructions")
    session = _session(existing=existing)

    row = static_assets.attach_asset(_product(), session, settings, "care_instructions.png")

    assert row is existing and row.rank == 9
    session.add.assert_not_called()


def test_attach_unknown_name_returns_none(settings):
    assert static_assets.attach_asset(_product(), _session(), settings, "../x.png") is None


def test_detach_refuses_ai_photos(tmp_path):
    ai = ProductImage(id=3, product_id=7, workflow_source="gemini", file_path=str(tmp_path / "a.jpg"))
    session = _session(existing=ai)
    assert static_assets.detach_asset(_product(), session, 3) is False
    session.delete.assert_not_called()


def test_detach_removes_row_and_file(tmp_path):
    f = tmp_path / "x.jpg"
    f.write_bytes(b"x")
    row = ProductImage(id=4, product_id=7, workflow_source="asset:chain_chart", file_path=str(f))
    session = _session(existing=row)
    assert static_assets.detach_asset(_product(), session, 4) is True
    session.delete.assert_called_once_with(row)
    assert not f.exists()


# ── Alt text ──────────────────────────────────────────────────────────────────

def test_alt_text_names_the_asset():
    product = _product(color="Gold", material="925 Sterling Silver")
    row = ProductImage(rank=8, workflow_source="asset:chain_chart")
    assert generate_alt_text(product, row).endswith(" - chain chart")


def test_workflow_source_tag_fits_the_column_for_every_library_asset(settings):
    """Regression: product_images.workflow_source is a fixed-length VARCHAR.

    The mocked-session tests above don't enforce column length, so a tag built
    from a long asset filename (e.g. "asset:birthstone_chart", "asset:care_
    instructions") could pass every unit test and still fail against real
    Postgres with StringDataRightTruncation. Assert directly against the
    column's length instead of relying on a real DB in CI.
    """
    from src.db.models import ProductImage

    max_len = ProductImage.__table__.c.workflow_source.type.length
    for asset in static_assets.list_assets(settings):
        tag = f"{static_assets.ASSET_SOURCE_PREFIX}{__import__('pathlib').Path(asset['name']).stem}"
        assert len(tag) <= max_len, f"{tag!r} ({len(tag)} chars) exceeds workflow_source({max_len})"


# ── Upload / remove from library ───────────────────────────────────────────────

def _png_bytes(size=(600, 400), mode="RGB", color=(10, 20, 30)) -> bytes:
    import io
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format="PNG")
    return buf.getvalue()


def test_save_uploaded_asset_adds_png_to_library(settings):
    item = static_assets.save_uploaded_asset(settings, "New Size Guide.png", _png_bytes())

    assert item["name"] == "New-Size-Guide.png"
    assert item["label"] == "New Size Guide"
    assert item["url"] == "/assets/New-Size-Guide.png"
    names = [a["name"] for a in static_assets.list_assets(settings)]
    assert "New-Size-Guide.png" in names


def test_save_uploaded_asset_converts_jpeg_source_to_png(settings):
    import io
    buf = io.BytesIO()
    Image.new("RGB", (400, 400), (5, 5, 5)).save(buf, format="JPEG")

    item = static_assets.save_uploaded_asset(settings, "photo.jpg", buf.getvalue())

    assert item["name"] == "photo.png"
    with Image.open(Path(settings.ASSETS_DIR) / item["name"]) as img:
        assert img.format == "PNG"


def test_save_uploaded_asset_sanitizes_weird_filenames(settings):
    item = static_assets.save_uploaded_asset(settings, "../../etc/weird name!!.png", _png_bytes())
    assert "/" not in item["name"] and ".." not in item["name"]
    assert item["name"] == "weird-name.png"


def test_save_uploaded_asset_dedupes_name_collisions(settings):
    first = static_assets.save_uploaded_asset(settings, "care_instructions.png", _png_bytes())
    # "care_instructions.png" already exists in the fixture library.
    assert first["name"] == "care_instructions-2.png"


def test_save_uploaded_asset_rejects_non_image_data(settings):
    with pytest.raises(ValueError):
        static_assets.save_uploaded_asset(settings, "fake.png", b"not an image at all")


def test_remove_from_library_deletes_file(settings):
    path = Path(settings.ASSETS_DIR) / "chain_chart.png"
    assert path.exists()

    assert static_assets.remove_from_library(settings, "chain_chart.png") is True

    assert not path.exists()
    assert "chain_chart.png" not in [a["name"] for a in static_assets.list_assets(settings)]


def test_remove_from_library_unknown_name_returns_false(settings):
    assert static_assets.remove_from_library(settings, "../secret.png") is False
    assert static_assets.remove_from_library(settings, "nope.png") is False


def test_remove_from_library_does_not_touch_attached_product_copy(settings):
    """A product's own copy lives under IMAGES_DIR, not ASSETS_DIR — removing
    the library master must not affect listings that already used it."""
    product = _product()
    row = static_assets.attach_asset(product, _session(ranks=[1]), settings, "chain_chart.png")
    assert Path(row.file_path).exists()

    static_assets.remove_from_library(settings, "chain_chart.png")

    assert Path(row.file_path).exists()
