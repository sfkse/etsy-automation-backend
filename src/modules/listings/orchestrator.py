"""
Listing Builder Orchestrator (Section H of OPERATIONAL_INTEGRATION.md).

Coordinates the streamlined per-product flow:

1. Resolve Rexven product (scrape or reuse image path).
2. Merge ShopSettings defaults.
3. Pick a variation preset (auto-heuristic if not supplied).
4. Build the variation matrix + persist VariationRow rows.
5. Resolve the PersonalizationTemplate from the user's choice label.
6. Create the Product row (status = CONTENT_GENERATING) and kick off the
   background content pipeline.
7. Background: run the existing VariantBundleOrchestrator, then wrap each
   variant.description in the DescriptionEngine scaffold.

Design principle: reuses the existing content orchestrator wholesale so the
SEO depth of Phase 6 remains intact.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.models import (
    JewelryCategory,
    MaterialType,
    PersonalizationTemplate,
    Product,
    ProductStatus,
    ShopSection,
    ShopSettings,
    VariationPreset,
    VariationRow,
)
from src.db.session import SessionLocal
from src.modules.input import generate_sku
from src.modules.listings.description_engine import DescriptionEngine
from src.modules.listings.personalization_picker import PersonalizationPicker
from src.modules.listings.variation_builder import VariationMatrixBuilder
from src.sourcing.rexven_scraper import scrape_rexven_product

_log = structlog.get_logger(__name__)


# Carrier-pillar → default section name (PR 6). Values that fall through
# use ``pillar.title()`` — see ``ListingBuilder._ensure_shop_section``.
_PILLAR_TO_SECTION_NAME: dict[str, str] = {
    "cross": "Cross Necklace",
    "name": "Name Necklace",
    "birthstone": "Birthstone Necklace",
    "birth_flower": "Birth Flower Necklace",
    "pet": "Pet Memorial Jewelry",
    "pendant": "Pendant Necklace",
}


class ListingBuildRequest(BaseModel):
    """Per-product input — only what cannot be inferred from settings."""

    rexven_url: Optional[str] = None
    rexven_sku: Optional[str] = None
    uploaded_image_path: Optional[str] = None

    carrier_pillar: str
    category: str = Field(default=JewelryCategory.NECKLACE.value)
    material_type: str = Field(default=MaterialType.BRASS.value)

    personalization_choice: str = "None"

    stone_shape: Optional[str] = None

    override_base_price_cents: Optional[int] = None
    cost_cents_override: Optional[int] = None
    # Rexven price breakdown (Premium tier) captured by the Chrome extension
    # from the authenticated DOM. When ``use_landed_cost`` is true, shipping is
    # folded into the effective cost basis for pricing; either way, all three
    # values are persisted on Product for downstream margin analytics.
    supplier_product_cents: Optional[int] = None
    supplier_shipping_cents: Optional[int] = None
    supplier_total_cents: Optional[int] = None
    use_landed_cost: bool = True

    variation_preset_name: Optional[str] = None

    target_keyword: Optional[str] = None

    # Phase 4 sourcing bridge — the KeywordScore the user picked in the
    # extension's Sourcing tab. Persisted on Product and used to ground content
    # generation in that keyword's empirical top-20 market data.
    selected_keyword_score_id: Optional[int] = None


class ListingBuilder:
    """Assemble a listing from a slim per-product request."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.variation_builder = VariationMatrixBuilder(session)
        self.personalization_picker = PersonalizationPicker(session)
        self.description_engine = DescriptionEngine(session)

    def build(self, req: ListingBuildRequest) -> Product:
        settings = self._load_settings()

        rexven = self._resolve_rexven(req)
        # Base cost precedence: explicit override → Rexven scrape → product-only from extension.
        base_cost_cents = (
            req.cost_cents_override
            or rexven.get("cost_cents")
            or req.supplier_product_cents
            or 0
        )
        if not base_cost_cents:
            raise ValueError(
                "cost_cents_override required when Rexven scrape yields no cost"
            )
        # Landed cost = product + shipping. When the extension supplies shipping
        # and use_landed_cost is on (default), pricing formulas see the fully
        # landed number so margins reflect reality.
        cost_cents = base_cost_cents
        if req.use_landed_cost and req.supplier_shipping_cents:
            # Only fold in shipping if cost_cents_override wasn't already a landed value.
            # Extension sends cost_cents_override = product-only, then relies on
            # this branch to add shipping — keeps the semantics on one side.
            if req.cost_cents_override is None or req.supplier_product_cents == req.cost_cents_override:
                cost_cents = base_cost_cents + req.supplier_shipping_cents

        preset_name = req.variation_preset_name or self._auto_preset(
            req.category, req.material_type, req.personalization_choice
        )
        preset = (
            self.session.query(VariationPreset)
            .filter_by(name=preset_name)
            .first()
        )
        if preset is None:
            raise ValueError(f"Variation preset not found: {preset_name!r}")

        matrix = self.variation_builder.build(
            preset_name=preset_name,
            rexven_cost_cents=cost_cents,
            override_base_price_cents=req.override_base_price_cents,
        )

        personalization = self.personalization_picker.pick(
            req.personalization_choice, req.category
        )

        product = Product(
            sku=generate_sku(self.session),
            carrier_pillar=req.carrier_pillar,
            status=ProductStatus.CONTENT_GENERATING.value,
            material_type=req.material_type,
            material=self._material_display(req.material_type),
            stone_shape=req.stone_shape,
            variation_preset_id=preset.id,
            personalization_template_id=personalization.id if personalization else None,
            target_keyword=req.target_keyword,
            selected_keyword_score_id=req.selected_keyword_score_id,
            rexven_url=req.rexven_url,
            rexven_sku=req.rexven_sku,
            original_image_path=req.uploaded_image_path or rexven.get("image_path"),
            cost_cents=cost_cents,
            cost=Decimal(cost_cents) / Decimal(100),
            supplier_product_cents=req.supplier_product_cents,
            supplier_shipping_cents=req.supplier_shipping_cents,
            supplier_total_cents=req.supplier_total_cents,
            is_featured=settings.feature_listing_default if settings else False,
        )
        self.session.add(product)
        self.session.flush()   # populate product.id for FK on VariationRow

        for cell in matrix:
            self.session.add(VariationRow(
                product_id=product.id,
                finish=cell.finish,
                length_inches=cell.length,
                multi_count=cell.multi_count,
                price_cents=cell.price_cents,
                sku_suffix=cell.sku_suffix,
                is_loss_leader=cell.is_loss_leader,
            ))

        # Persist a base selling price for legacy fields (min-cell price)
        if matrix:
            min_price = min(c.price_cents for c in matrix)
            product.selling_price = Decimal(min_price) / Decimal(100)

        self.session.commit()

        self._ensure_shop_section(product, settings)

        _log.info(
            "listing_builder_created",
            sku=product.sku,
            preset=preset_name,
            variation_cells=len(matrix),
            personalization=personalization.name if personalization else None,
        )
        return product

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load_settings(self) -> Optional[ShopSettings]:
        return self.session.query(ShopSettings).filter_by(id=1).first()

    def _ensure_shop_section(
        self,
        product: Product,
        settings: Optional[ShopSettings],
    ) -> None:
        """Idempotently create a ShopSection for the product's carrier pillar.

        Guarded by ``ShopSettings.auto_create_sections`` (PR 6). Leaves
        ``etsy_section_id`` NULL; the Etsy-side sync ships in PR 7.
        """
        if settings is None or not getattr(settings, "auto_create_sections", True):
            return
        pillar = product.carrier_pillar
        if not pillar:
            return

        existing = (
            self.session.query(ShopSection)
            .filter_by(carrier_pillar=pillar)
            .first()
        )
        if existing is not None:
            return

        name = _PILLAR_TO_SECTION_NAME.get(pillar) or pillar.replace("_", " ").title()
        max_order = (
            self.session.query(func.max(ShopSection.display_order)).scalar() or 0
        )
        section = ShopSection(
            name=name,
            carrier_pillar=pillar,
            display_order=(max_order or 0) + 1,
        )
        self.session.add(section)
        self.session.commit()
        _log.info(
            "shop_section_auto_created",
            name=name,
            carrier_pillar=pillar,
            display_order=section.display_order,
        )

    def _resolve_rexven(self, req: ListingBuildRequest) -> dict:
        """Return dict with keys: image_path, image_url, cost_cents, title_tr."""
        if not req.rexven_url:
            return {
                "image_path": req.uploaded_image_path,
                "cost_cents": req.cost_cents_override or 0,
            }
        try:
            scraped = scrape_rexven_product(req.rexven_url)
        except Exception as exc:  # pragma: no cover — network path
            _log.warning("rexven_scrape_failed", url=req.rexven_url, error=str(exc))
            return {"image_path": None, "cost_cents": req.cost_cents_override or 0}

        return {
            "image_path": None,
            "image_url": scraped.get("image_url"),
            "cost_cents": scraped.get("cost_cents") or 0,
            "title_tr": scraped.get("title_tr"),
        }

    @staticmethod
    def _material_display(material_type: str) -> str:
        return {
            MaterialType.BRASS.value: "Brass",
            MaterialType.SILVER_925.value: "925 Sterling Silver",
            MaterialType.GOLD_PLATED.value: "Gold Plated",
        }.get(material_type, "Brass")

    @staticmethod
    def _auto_preset(category: str, material: str, pers_choice: str) -> str:
        """Heuristic — pick a sensible default variation preset."""
        if category == JewelryCategory.NECKLACE.value:
            if material == MaterialType.SILVER_925.value:
                return "necklace_silver_standard"
            if "Multi" in (pers_choice or ""):
                return "necklace_brass_multi_birthstone"
            return "necklace_brass_standard"
        if category == JewelryCategory.EARRING.value:
            return "earring_basic"
        return "necklace_brass_standard"


# ── Background content pipeline ───────────────────────────────────────────────


async def run_listing_content_pipeline(product_sku: str) -> None:
    """
    Background task: runs the existing content orchestrator, wraps each
    variant's description in the operational scaffold, then kicks off the
    image pipeline so approval-page reviewers see both text and images.

    Image generation is skipped (with a warning) when no ``is_real=True``
    ``ProductImage`` rows exist — this keeps the JSON-only ``POST /listings/build``
    endpoint usable for scripting/testing without breaking Etsy publish, which
    still requires at least one image and will surface the gap explicitly.

    Kept as a module-level coroutine so FastAPI's ``BackgroundTasks``
    can enqueue it directly.
    """
    from src.config.settings import Settings   # local import to avoid cycles
    from src.db.models import ProductImage
    from src.modules.images.pipeline import run_image_pipeline
    from src.modules.research.context_builder import (
        build_sourcing_addendum,
        patch_research_builder_for_sourcing,
    )
    from src.web.routes.content import _build_orchestrator

    settings = Settings()
    session = SessionLocal()
    try:
        product = session.query(Product).filter_by(sku=product_sku).first()
        if not product:
            _log.error("listing_pipeline_product_missing", sku=product_sku)
            return

        orchestrator = _build_orchestrator(session)

        # Phase 4 bridge: ground every LLM call in the sourcing keyword the user
        # picked in the extension, mirroring the classic generate-content route.
        if product.selected_keyword_score_id:
            addendum = build_sourcing_addendum(session, product.selected_keyword_score_id)
            if addendum:
                patch_research_builder_for_sourcing(orchestrator, addendum)

        try:
            bundle = await orchestrator.generate_bundle(product)
        except Exception as exc:
            _log.exception("listing_pipeline_content_failed", sku=product_sku, error=str(exc))
            product.status = ProductStatus.FAILED.value
            session.commit()
            return

        # Wrap each variant.description with the operational scaffold
        preset = (
            session.query(VariationPreset).get(product.variation_preset_id)
            if product.variation_preset_id
            else None
        )
        personalization: Optional[PersonalizationTemplate] = (
            session.query(PersonalizationTemplate).get(product.personalization_template_id)
            if product.personalization_template_id
            else None
        )

        engine = DescriptionEngine(session)
        category = _category_from_preset(preset)

        for variant in bundle.variants:
            if preset is not None:
                variant.description = engine.fill(
                    product=product,
                    llm_intro=variant.description,
                    preset=preset,
                    personalization=personalization,
                    category=category,
                )

        product.generated_variants = [v.to_dict() for v in bundle.variants]
        session.commit()
        _log.info(
            "listing_pipeline_content_complete",
            sku=product_sku,
            variants=len(bundle.variants),
        )

        # ── Image pipeline stage ─────────────────────────────────────────────
        has_real_image = (
            session.query(ProductImage)
            .filter_by(product_id=product.id, is_real=True)
            .first()
            is not None
        )
        if not has_real_image:
            _log.warning(
                "listing_pipeline_images_skipped_no_real_image",
                sku=product_sku,
                hint="Use POST /listings/build-with-image or attach a ProductImage row.",
            )
            product.status = ProductStatus.AWAITING_APPROVAL.value
            session.commit()
            return

        try:
            await run_image_pipeline(product, session, settings)
        except Exception as exc:
            _log.exception("listing_pipeline_images_failed", sku=product_sku, error=str(exc))
            product.status = ProductStatus.FAILED.value
            session.commit()
            return

        # run_image_pipeline sets AWAITING_APPROVAL itself; re-assert defensively.
        product.status = ProductStatus.AWAITING_APPROVAL.value
        session.commit()
        _log.info("listing_pipeline_complete", sku=product_sku)
    finally:
        session.close()


def _category_from_preset(preset: Optional[VariationPreset]) -> str:
    if preset is None:
        return JewelryCategory.NECKLACE.value
    return preset.category
