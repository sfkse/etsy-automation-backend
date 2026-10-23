"""Route tests for the common-images gallery endpoints on the images page.

Mounts only the products (input) router; the static_assets helpers are patched
on the route module so no files or DB rows are touched.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.dependencies import get_session
from src.db.models import Product, ProductImage
from src.web.routes import input as input_routes

SKU = "TAKI-ASSET-TEST"
LIBRARY = [{"name": "chain_chart.png", "label": "Chain Chart", "url": "/assets/chain_chart.png"}]


def _client(product: Product | None = None):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = (
        product if product is not None else Product(id=1, sku=SKU, carrier_pillar="cross")
    )
    app = FastAPI()
    app.include_router(input_routes.router)
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app), session


def _row() -> ProductImage:
    return ProductImage(id=11, product_id=1, rank=8, file_path="/x/data/images/TAKI/a.jpg",
                        workflow_source="asset:chain_chart")


def test_list_returns_library_and_attached():
    client, _ = _client()
    with patch.object(input_routes, "list_assets", return_value=LIBRARY), \
         patch.object(input_routes, "attached_assets", return_value=[_row()]):
        body = client.get(f"/products/{SKU}/assets").json()
    assert body["library"] == LIBRARY
    assert body["attached"][0]["image_id"] == 11
    assert body["attached"][0]["stem"] == "chain_chart"
    assert body["attached"][0]["label"] == "Chain Chart"


def test_attach_commits_and_returns_attached():
    client, session = _client()
    with patch.object(input_routes, "attach_asset", return_value=_row()) as attach, \
         patch.object(input_routes, "attached_assets", return_value=[_row()]):
        resp = client.post(f"/products/{SKU}/assets", data={"name": "chain_chart.png"})
    assert resp.status_code == 200
    assert attach.call_args.args[3] == "chain_chart.png"
    assert session.commit.called
    assert resp.json()["attached"][0]["image_id"] == 11


def test_attach_unknown_name_is_404():
    client, session = _client()
    with patch.object(input_routes, "attach_asset", return_value=None):
        resp = client.post(f"/products/{SKU}/assets", data={"name": "../secret.png"})
    assert resp.status_code == 404
    assert not session.commit.called


def test_detach_non_asset_is_404():
    client, _ = _client()
    with patch.object(input_routes, "detach_asset", return_value=False):
        resp = client.delete(f"/products/{SKU}/assets/3")
    assert resp.status_code == 404


def test_detach_returns_remaining():
    client, session = _client()
    with patch.object(input_routes, "detach_asset", return_value=True), \
         patch.object(input_routes, "attached_assets", return_value=[]):
        resp = client.delete(f"/products/{SKU}/assets/11")
    assert resp.status_code == 200
    assert resp.json() == {"attached": []}
    assert session.commit.called


# ── Upload / remove from the shared library ─────────────────────────────────────

def test_upload_adds_to_library_and_returns_updated_lists():
    client, _ = _client()
    new_library = LIBRARY + [{"name": "new.png", "label": "New", "url": "/assets/new.png"}]
    with patch.object(input_routes, "save_uploaded_asset") as save, \
         patch.object(input_routes, "list_assets", return_value=new_library), \
         patch.object(input_routes, "attached_assets", return_value=[]):
        resp = client.post(
            f"/products/{SKU}/assets/library",
            files={"file": ("new.png", b"fake-bytes", "image/png")},
        )
    assert resp.status_code == 200
    assert save.call_args.args[1] == "new.png"
    assert save.call_args.args[2] == b"fake-bytes"
    assert resp.json()["library"] == new_library


def test_upload_rejects_non_image_with_400():
    client, _ = _client()
    with patch.object(input_routes, "save_uploaded_asset", side_effect=ValueError("not a valid image")):
        resp = client.post(
            f"/products/{SKU}/assets/library",
            files={"file": ("bad.png", b"not an image", "image/png")},
        )
    assert resp.status_code == 400
    assert "not a valid image" in resp.json()["error"]


def test_upload_missing_product_is_404():
    # _client()'s product param can't express "no product" (its None default
    # already means "use a real product"), so build the missing-product
    # session directly instead.
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    app = FastAPI()
    app.include_router(input_routes.router)
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)

    with patch.object(input_routes, "save_uploaded_asset") as save:
        resp = client.post(
            f"/products/{SKU}/assets/library",
            files={"file": ("new.png", b"x", "image/png")},
        )
    assert resp.status_code == 404
    save.assert_not_called()


def test_remove_from_library_returns_updated_lists():
    client, _ = _client()
    with patch.object(input_routes, "remove_from_library", return_value=True) as remove, \
         patch.object(input_routes, "list_assets", return_value=[]), \
         patch.object(input_routes, "attached_assets", return_value=[]):
        resp = client.delete(f"/products/{SKU}/assets/library/chain_chart.png")
    assert resp.status_code == 200
    assert remove.call_args.args[1] == "chain_chart.png"
    assert resp.json()["library"] == []


def test_remove_from_library_unknown_name_is_404():
    client, _ = _client()
    with patch.object(input_routes, "remove_from_library", return_value=False):
        resp = client.delete(f"/products/{SKU}/assets/library/nope.png")
    assert resp.status_code == 404
