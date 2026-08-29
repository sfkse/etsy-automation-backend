"""Tests for POST /approval/{sku}/variant/{vid}/regenerate.

Same harness as test_approval.py: a minimal app mounting only the approval
router, with a MagicMock session returning one hand-built Product. The
orchestrator builder is patched out so no LLM client is constructed.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.db.dependencies import get_session
from src.db.models import Product, ProductStatus
from src.modules.llm.angles import ANGLE_CONSERVATIVE
from src.web.routes import approval as approval_routes

TITLE = (
    "Dainty Cross Necklace for Women, Minimalist Gold Pendant Necklace, "
    "Layering Chain Jewelry, Religious Faith Charm Accessory"
)
TAGS = [
    "Cross Pendant", "Faith Jewelry", "Dainty Necklace", "Religious Gift",
    "Christian Charm", "Gold Necklace", "Layered Chain", "Minimalist Gift",
    "Gifts for Mom", "Baptism Gift", "Confirmation Gift", "Tiny Cross",
    "Everyday Jewelry",
]


def _product() -> Product:
    return Product(
        id=1,
        sku="TAKI-0042",
        carrier_pillar="cross",
        status=ProductStatus.AWAITING_APPROVAL.value,
        published_variant_ids=[],
        etsy_urls={},
        generated_variants=[
            {
                "id": "A",
                "strategy_label": ANGLE_CONSERVATIVE.label,
                "title": TITLE,
                "tags": list(TAGS),
                "description": "Existing description.",
                "estimated_ctr_signal": "medium",
            },
            {
                "id": "HYBRID",
                "strategy_label": "Hybrid (user composed)",
                "title": TITLE,
                "tags": list(TAGS),
                "description": "User composed.",
            },
        ],
    )


def _make_session(product: Product | None) -> MagicMock:
    session = MagicMock()

    def query_side(model):
        q = MagicMock()
        if model is Product:
            q.filter_by.return_value.first.return_value = product
        else:
            q.filter_by.return_value.first.return_value = None
        return q

    session.query.side_effect = query_side
    return session


def _client(product: Product | None):
    app = FastAPI()
    app.include_router(approval_routes.router)
    session = _make_session(product)
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app), session


def _orchestrator(new_tags: list[str] | None = None) -> MagicMock:
    orch = MagicMock()
    orch.title.generate_for_angle = AsyncMock(return_value="A regenerated title.")
    orch.tag.generate_for_angle = AsyncMock(return_value=new_tags or list(TAGS))
    orch.tag.pool.get_candidates.return_value = ["Spiritual Charm"]
    orch.desc.generate_for_angle = AsyncMock(return_value="A regenerated description.")
    orch.linker.insert_links = AsyncMock(side_effect=lambda d, p: d)
    orch._estimate_ctr_signal.return_value = "high"
    return orch


def _post(client, sku="TAKI-0042", vid="A", field="tags"):
    return client.post(
        f"/approval/{sku}/variant/{vid}/regenerate", json={"field": field}
    )


def test_regenerates_tags_and_persists_them():
    product = _product()
    client, _ = _client(product)
    new_tags = [f"Fresh Tag {i:02d}" for i in range(13)]

    with patch(
        "src.web.routes.content._build_orchestrator",
        return_value=_orchestrator(new_tags=new_tags),
    ):
        resp = _post(client, field="tags")

    assert resp.status_code == 200
    body = resp.json()
    assert body["regenerated"] is True
    assert body["updates"]["tags"] == new_tags
    # Written back into the stored variant, not just returned.
    assert product.generated_variants[0]["tags"] == new_tags


def test_other_variants_are_untouched():
    product = _product()
    client, _ = _client(product)
    before = dict(product.generated_variants[1])

    with patch(
        "src.web.routes.content._build_orchestrator", return_value=_orchestrator()
    ):
        _post(client, field="tags")

    assert product.generated_variants[1] == before


def test_ctr_signal_is_refreshed_alongside_tags():
    product = _product()
    client, _ = _client(product)

    with patch(
        "src.web.routes.content._build_orchestrator", return_value=_orchestrator()
    ):
        _post(client, field="tags")

    assert product.generated_variants[0]["estimated_ctr_signal"] == "high"


def test_response_carries_validation_of_the_new_value():
    product = _product()
    client, _ = _client(product)

    with patch(
        "src.web.routes.content._build_orchestrator", return_value=_orchestrator()
    ):
        body = _post(client, field="tags").json()

    assert "valid" in body and "violations" in body


def test_hybrid_variant_is_rejected():
    product = _product()
    client, _ = _client(product)

    with patch(
        "src.web.routes.content._build_orchestrator", return_value=_orchestrator()
    ):
        resp = _post(client, vid="HYBRID", field="title")

    assert resp.status_code == 409
    assert "angle" in resp.json()["error"]


def test_unknown_field_is_rejected_before_any_llm_call():
    product = _product()
    client, _ = _client(product)
    orch = _orchestrator()

    with patch("src.web.routes.content._build_orchestrator", return_value=orch):
        resp = _post(client, field="price")

    assert resp.status_code == 422
    assert orch.title.generate_for_angle.await_count == 0


def test_unknown_variant_returns_404():
    client, _ = _client(_product())

    with patch(
        "src.web.routes.content._build_orchestrator", return_value=_orchestrator()
    ):
        resp = _post(client, vid="Z", field="tags")

    assert resp.status_code == 404


def test_missing_product_returns_404():
    client, _ = _client(None)
    resp = _post(client, field="tags")
    assert resp.status_code == 404


def test_generator_failure_surfaces_as_500_with_reason():
    product = _product()
    client, _ = _client(product)
    orch = _orchestrator()
    orch.tag.generate_for_angle = AsyncMock(side_effect=RuntimeError("LLM exploded"))

    with patch("src.web.routes.content._build_orchestrator", return_value=orch):
        resp = _post(client, field="tags")

    assert resp.status_code == 500
    assert "LLM exploded" in resp.json()["error"]
    # The stored variant is left as it was.
    assert product.generated_variants[0]["tags"] == TAGS
