"""
Phase 11.2 — Full pipeline integration test.

Exercises all five stages of the product pipeline using mocks for every
external dependency (DB, image generator, LLM, Etsy API, Sheets sync).

No real database is used (SQLite is incompatible with the JSONB columns in the
schema). All session interactions are handled by MagicMock.

Stages tested:
  1. Product creation        → status MANUAL_INPUT
  2. Image pipeline          → status AWAITING_APPROVAL (mocked generator)
  3. Content generation      → VariantBundle with 3 validated variants
  4. Human approval          → status APPROVED, final fields populated
  5. Etsy publish            → status PUBLISHED, etsy_listing_id set
"""
from __future__ import annotations

import asyncio
import io
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from src.config.settings import Settings
from src.db.models import Product, ProductImage, ProductStatus
from src.domain.validators import validate_description, validate_tags, validate_title
from src.modules.llm.variants import ListingVariant, VariantBundle


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_valid_title() -> str:
    """
    Build a 140-char title that passes ALL Section 1.1 validators:
    - Length 137-140
    - No forbidden keywords (Stone, Mother's Day Gift, Diamond, Floral)
    - No bare "Pendant" (only "Pendant Necklace")
    - No Solid Gold + Gold Plated conflict
    - No repeated non-stop words
    """
    # Exactly 140 chars; every significant word is unique
    title = "925 Sterling Silver Cross Jewelry, Minimalist Layering Chain, Dainty Religious Symbol, Handcrafted Blessing Baptism Elegant Confirmation Her"
    assert len(title) == 140, f"Test title length is {len(title)}, expected 140"
    return title


def _make_valid_tags() -> list[str]:
    """Return exactly 13 unique tags each ≤ 20 chars."""
    return [
        "Cross Necklace",
        "Silver Necklace",
        "Minimalist Chain",
        "Layering Necklace",
        "Dainty Cross",
        "Religious Gift",
        "Gifts for Mom",
        "Sterling Silver",
        "Cross Jewelry",
        "Pendant Necklace",
        "Baptism Gift",
        "Confirmation Gift",
        "Everyday Necklace",
    ]


def _make_valid_description() -> str:
    """Return a 160-word description with no cliché phrases."""
    # 12 words per sentence × 15 repetitions = 180; slice to exactly 160
    sentence = "A handcrafted cross necklace in 925 sterling silver designed for everyday wear."
    words = sentence.split()
    extended = words * 15
    return " ".join(extended[:160])


def _make_dummy_pil_image() -> Image.Image:
    """Return a tiny white 10×10 RGBA PIL image."""
    return Image.new("RGBA", (10, 10), (255, 255, 255, 255))


def _make_variant_bundle(product: Product) -> VariantBundle:
    """Build a VariantBundle with 3 valid variants."""
    title = _make_valid_title()
    tags = _make_valid_tags()
    description = _make_valid_description()

    variants = [
        ListingVariant(
            variant_id=vid,
            strategy_label=f"Strategy {vid}",
            strategy_rationale=f"Rationale for {vid}",
            title=title,
            tags=tags,
            description=description,
            estimated_ctr_signal="medium",
        )
        for vid in ("A", "B", "C")
    ]
    return VariantBundle(
        product_sku=product.sku,
        variants=variants,
        research_snapshot_id="test-snapshot",
        generated_at=datetime.utcnow(),
    )


def _make_product() -> Product:
    """Return a minimal unsaved Product in MANUAL_INPUT state."""
    return Product(
        id=1,
        sku="TAKI-0001",
        carrier_pillar="cross",
        material="925 Sterling Silver",
        color="Silver",
        has_stone=False,
        selling_price=29.99,
        status=ProductStatus.MANUAL_INPUT.value,
    )


def _make_mock_session(product: Product) -> MagicMock:
    """Return a MagicMock session pre-wired for the image pipeline queries."""
    real_img = MagicMock(spec=ProductImage)
    real_img.id = 1
    real_img.product_id = product.id
    real_img.file_path = "/tmp/taki-0001-primary.jpg"
    real_img.rank = 1
    real_img.is_real = True
    real_img.alt_text = None

    session = MagicMock()
    # image pipeline: query(ProductImage).filter_by(is_real=True).order_by().all()
    session.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [real_img]
    # publish: query(ProductImage).filter_by(is_selected=True).order_by().all()
    selected_img = MagicMock(spec=ProductImage)
    selected_img.id = 2
    selected_img.product_id = product.id
    selected_img.file_path = "/tmp/taki-0001-selected.jpg"
    selected_img.rank = 1
    selected_img.alt_text = "Cross necklace"
    session.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [selected_img]
    return session


def _make_mock_settings() -> Settings:
    """Return a Settings object safe for testing (no real API calls)."""
    settings = MagicMock(spec=Settings)
    settings.IMAGES_DIR = "/tmp/etsy_test_images"
    settings.DEFAULT_IMAGE_WORKFLOW = "gemini"
    settings.GOOGLE_SHEETS_ENABLED = False
    return settings


# ── Test class ────────────────────────────────────────────────────────────────


class TestFullPipelineIntegration:
    """
    Five-stage pipeline integration test.

    Each stage asserts product state AND validates business rules.
    """

    # ── Stage 1: Product creation ─────────────────────────────────────────────

    def test_stage1_product_starts_at_manual_input(self) -> None:
        product = _make_product()
        assert product.status == ProductStatus.MANUAL_INPUT.value
        assert product.sku == "TAKI-0001"
        assert product.carrier_pillar == "cross"

    # ── Stage 2: Image pipeline ───────────────────────────────────────────────

    @pytest.mark.asyncio
    @patch("src.modules.images.pipeline.upsert_product_row")
    @patch("src.modules.images.pipeline.generate_alt_text", return_value="cross necklace lifestyle")
    @patch("src.modules.images.pipeline.ImageWorkflowFactory")
    @patch("src.modules.images.pipeline.preprocess_and_save")
    @patch("src.modules.images.pipeline.Image")
    async def test_stage2_image_pipeline_advances_status(
        self,
        mock_pil,
        mock_preprocess,
        mock_factory,
        mock_alt_text,
        mock_upsert,
    ) -> None:
        product = _make_product()
        session = _make_mock_session(product)
        settings = _make_mock_settings()

        # preprocess_and_save returns a dummy path
        mock_preprocess.return_value = "/tmp/taki-0001-bg-removed.png"

        # PIL Image.open returns a dummy image
        dummy_img = _make_dummy_pil_image()
        mock_pil.open.return_value.__enter__ = MagicMock(return_value=dummy_img)
        mock_pil.open.return_value = dummy_img
        mock_pil.new.return_value = dummy_img

        # Image generator returns one result per prompt
        fake_result = MagicMock()
        fake_result.image = dummy_img
        fake_result.cost_estimate = 0.01

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(return_value=[fake_result])
        mock_factory.get.return_value = mock_generator

        from src.modules.images.pipeline import run_image_pipeline
        await run_image_pipeline(product, session, settings)

        assert product.status == ProductStatus.AWAITING_APPROVAL.value

    # ── Stage 3: Content generation ───────────────────────────────────────────

    def test_stage3_variant_bundle_has_three_valid_variants(self) -> None:
        product = _make_product()
        bundle = _make_variant_bundle(product)

        assert len(bundle.variants) == 3
        assert bundle.product_sku == "TAKI-0001"

        for variant in bundle.variants:
            title_ok, title_violations = validate_title(variant.title)
            assert title_ok, f"Title invalid for variant {variant.variant_id}: {title_violations}"

            tags_ok, tags_violations = validate_tags(variant.tags, title=variant.title)
            assert tags_ok, f"Tags invalid for variant {variant.variant_id}: {tags_violations}"

            desc_ok, desc_violations = validate_description(variant.description)
            assert desc_ok, f"Description invalid for variant {variant.variant_id}: {desc_violations}"

    def test_stage3_variant_ids_are_a_b_c(self) -> None:
        product = _make_product()
        bundle = _make_variant_bundle(product)
        ids = [v.variant_id for v in bundle.variants]
        assert ids == ["A", "B", "C"]

    # ── Stage 4: Approval ─────────────────────────────────────────────────────

    @patch("src.modules.approval.service.upsert_product_row")
    def test_stage4_approve_variant_advances_to_approved(self, _mock_upsert) -> None:
        from src.modules.approval.service import approve_variant

        product = _make_product()
        bundle = _make_variant_bundle(product)
        product.generated_variants = [v.to_dict() for v in bundle.variants]

        session = MagicMock()
        result = approve_variant(session, product, "A")

        assert result is True
        assert product.status == ProductStatus.APPROVED.value
        assert product.selected_variant_id == "A"

    @patch("src.modules.approval.service.upsert_product_row")
    def test_stage4_final_fields_pass_business_rules(self, _mock_upsert) -> None:
        from src.modules.approval.service import approve_variant

        product = _make_product()
        bundle = _make_variant_bundle(product)
        product.generated_variants = [v.to_dict() for v in bundle.variants]

        session = MagicMock()
        approve_variant(session, product, "B")

        title_ok, title_v = validate_title(product.final_title)
        assert title_ok, f"Final title failed rules: {title_v}"

        tags_ok, tags_v = validate_tags(product.final_tags, title=product.final_title)
        assert tags_ok, f"Final tags failed rules: {tags_v}"

        desc_ok, desc_v = validate_description(product.final_description)
        assert desc_ok, f"Final description failed rules: {desc_v}"

    @patch("src.modules.approval.service.upsert_product_row")
    def test_stage4_approved_at_is_set(self, _mock_upsert) -> None:
        from src.modules.approval.service import approve_variant

        product = _make_product()
        bundle = _make_variant_bundle(product)
        product.generated_variants = [v.to_dict() for v in bundle.variants]

        session = MagicMock()
        approve_variant(session, product, "C")

        assert product.approved_at is not None

    # ── Stage 5: Etsy publish ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    @patch("src.modules.etsy.publisher.upsert_product_row")
    async def test_stage5_publish_sets_listing_id_and_status(self, _mock_upsert) -> None:
        from src.modules.etsy.publisher import publish_product

        product = _make_product()
        bundle = _make_variant_bundle(product)
        product.generated_variants = [v.to_dict() for v in bundle.variants]
        product.final_title = bundle.variants[0].title
        product.final_tags = bundle.variants[0].tags
        product.final_description = bundle.variants[0].description
        product.selected_variant_id = "A"
        product.status = ProductStatus.APPROVED.value

        # Mock the Etsy client
        mock_client = MagicMock()
        mock_client.shop_id = "TEST_SHOP"
        mock_client.post = AsyncMock(return_value={"listing_id": "TEST-123"})
        mock_client.patch = AsyncMock(return_value={})
        mock_client.request = AsyncMock(return_value={})
        mock_client.get_shop_sections = AsyncMock(return_value=[])

        # Mock session: query(ProductImage).filter_by(is_selected=True).order_by().all()
        selected_img = MagicMock(spec=ProductImage)
        selected_img.id = 2
        selected_img.product_id = product.id
        selected_img.file_path = "/tmp/taki-0001.jpg"
        selected_img.rank = 1
        selected_img.alt_text = "cross necklace"
        session = MagicMock()
        session.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [
            selected_img
        ]

        # Patch open() since we don't have a real image file
        with patch("builtins.open", MagicMock()):
            await publish_product(
                client=mock_client,
                product=product,
                session=session,
                shipping_profile_id=12345,
                return_policy_id=67890,
            )

        assert product.etsy_listing_id == "TEST-123"
        assert product.status == ProductStatus.PUBLISHED.value
        assert product.published_at is not None

    @pytest.mark.asyncio
    @patch("src.modules.etsy.publisher.upsert_product_row")
    async def test_stage5_published_title_still_passes_rules(self, _mock_upsert) -> None:
        """Business rules must hold on the published data."""
        from src.modules.etsy.publisher import publish_product

        product = _make_product()
        bundle = _make_variant_bundle(product)
        product.generated_variants = [v.to_dict() for v in bundle.variants]
        product.final_title = bundle.variants[0].title
        product.final_tags = bundle.variants[0].tags
        product.final_description = bundle.variants[0].description
        product.selected_variant_id = "A"
        product.status = ProductStatus.APPROVED.value

        mock_client = MagicMock()
        mock_client.shop_id = "TEST_SHOP"
        mock_client.post = AsyncMock(return_value={"listing_id": "TEST-456"})
        mock_client.patch = AsyncMock(return_value={})
        mock_client.request = AsyncMock(return_value={})
        mock_client.get_shop_sections = AsyncMock(return_value=[])

        selected_img = MagicMock(spec=ProductImage)
        selected_img.file_path = "/tmp/taki-0001.jpg"
        selected_img.rank = 1
        selected_img.alt_text = "cross necklace"
        session = MagicMock()
        session.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [
            selected_img
        ]

        with patch("builtins.open", MagicMock()):
            await publish_product(
                client=mock_client,
                product=product,
                session=session,
                shipping_profile_id=12345,
                return_policy_id=67890,
            )

        # Post-publish: business rules are still respected
        title_ok, title_v = validate_title(product.final_title)
        assert title_ok, f"Published title violated rules: {title_v}"

        tags_ok, tags_v = validate_tags(product.final_tags)
        assert tags_ok, f"Published tags violated rules: {tags_v}"
