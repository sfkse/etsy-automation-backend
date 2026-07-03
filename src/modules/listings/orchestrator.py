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
from sqlalchemy.orm import Session

from src.db.models import (
    JewelryCategory,
    MaterialType,
    PersonalizationTemplate,
    Product,
    ProductStatus,
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

    variation_preset_name: Optional[str] = None

    target_keyword: Optional[str] = None


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
        cost_cents = req.cost_cents_override or rexven.get("cost_cents") or 0
        if not cost_cents:
            raise ValueError(
                "cost_cents_override required when Rexven scrape yields no cost"
            )

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
            rexven_url=req.rexven_url,
            original_image_path=req.uploaded_image_path or rexven.get("image_path"),
            cost_cents=cost_cents,
            cost=Decimal(cost_cents) / Decimal(100),
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
    Background task: runs the existing content orchestrator, then wraps
    each variant's description in the operational scaffold.

    Kept as a module-level coroutine so FastAPI's ``BackgroundTasks``
    can enqueue it directly.
    """
    from src.web.routes.content import _build_orchestrator   # local import to avoid cycles

    session = SessionLocal()
    try:
        product = session.query(Product).filter_by(sku=product_sku).first()
        if not product:
            _log.error("listing_pipeline_product_missing", sku=product_sku)
            return

        orchestrator = _build_orchestrator(session)

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
        product.status = ProductStatus.AWAITING_APPROVAL.value
        session.commit()
        _log.info(
            "listing_pipeline_complete",
            sku=product_sku,
            variants=len(bundle.variants),
        )
    finally:
        session.close()


def _category_from_preset(preset: Optional[VariationPreset]) -> str:
    if preset is None:
        return JewelryCategory.NECKLACE.value
    return preset.category
