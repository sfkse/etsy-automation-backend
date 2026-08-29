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
    KeywordScore,
    MaterialType,
    PersonalizationTemplate,
    Product,
    ProductStatus,
    ShopSection,
    ShopSettings,
    SourcingAnalysis,
    VariationPreset,
    VariationRow,
)
from src.db.session import SessionLocal
from src.modules.input import generate_sku
from src.modules.listings.description_engine import DescriptionEngine
from src.modules.listings.personalization_picker import PersonalizationPicker
from src.modules.listings.variation_builder import VariationMatrixBuilder
from src.sourcing.rexven_normalizer import reconcile_preset
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


# Stone vocabulary → the value stored in ``Product.stone_type``. Ordered
# specific → generic, first match wins, so "birthstone accent ... gemstone
# center" resolves to Birthstone rather than the generic Gemstone. Same
# discipline as the extension's PILLAR_HINTS.
_STONE_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("Birthstone", ("birthstone", "birth stone")),
    ("Cubic Zirconia", ("cubic zirconia", "cz ", " cz", "zirconia")),
    ("Pearl", ("pearl",)),
    ("Opal", ("opal",)),
    ("Crystal", ("crystal",)),
    ("Gemstone", ("gemstone", "gem stone", "stone", "diamond")),
]

# Vision fields worth scanning. `theme` and `material` carry the stone on real
# captures ("Christian cross with birthstone accent" / "Gold-plated brass with
# blue gemstone center"); `form` occasionally does. `style`, `occasion` and
# `recipient` are excluded — "birthstone jewelry lover" under recipient would
# fire on a piece that merely targets that buyer.
_STONE_FIELDS = ("theme", "material", "form")


def _detected_attributes(analysis: "SourcingAnalysis | None") -> Optional[dict]:
    """Layer A's vision read of the product, off whichever candidate carries it.

    Every candidate of an analysis shares the same blob; the first non-empty one
    is the whole picture. Mirrors the lookup in ``sourcing._run_layer_c``.
    """
    if analysis is None:
        return None
    return next(
        (c.detected_attributes for c in analysis.candidates if c.detected_attributes),
        None,
    )


def infer_stone(
    detected: Optional[dict], stone_shape: Optional[str] = None
) -> tuple[bool, Optional[str]]:
    """Return ``(has_stone, stone_type)`` for a product.

    Reads Layer A's detected attributes, because the supplier's own spec block
    does not state the stone. ``stone_shape`` (from the popup) independently
    proves there is one even when the vision text says nothing nameable, so it
    can set ``has_stone`` without naming a type.
    """
    blob = ""
    if detected:
        blob = " ".join(str(detected.get(f, "")) for f in _STONE_FIELDS).lower()

    stone_type: Optional[str] = None
    if blob:
        for label, hints in _STONE_HINTS:
            if any(h in blob for h in hints):
                stone_type = label
                break

    return bool(stone_type) or bool(stone_shape), stone_type


def _fit(value: Optional[str], limit: int) -> Optional[str]:
    """Trim a supplier-supplied string to its column width.

    Supplier prose is free-form ("30 Force (cable) Chain"), so a value that fits
    today may not tomorrow. Truncating beats a 500 at build time for a field that
    is descriptive rather than load-bearing.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


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

    # True when the extension kicked off a Phase-2 competitor deep-dive for the
    # selected keyword right before this build. The content pipeline then waits
    # (bounded) for the deep-dive ingest to refresh KeywordResearch, so the
    # generated content is grounded in the enriched data without a blocking
    # user checkpoint.
    deepdive_pending: bool = False

    # How long this build may wait for its deep-dive, in seconds. Deep-dives run
    # serially in the extension (one scrape window), so in a multi-keyword batch
    # the Nth keyword's dive only starts once N-1 have finished. The extension
    # sizes this by queue position; without it every build past the first would
    # exhaust the default budget waiting for a dive that had not begun. Clamped
    # server-side by _DEEPDIVE_WAIT_CAP_S.
    deepdive_wait_s: Optional[int] = None


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

        # Supplier attributes captured during sourcing (options, spec block).
        # Looked up rather than re-sent: the analysis behind the chosen keyword
        # already holds them.
        supplier = self._load_supplier_capture(req)
        attributes = (supplier.rexven_attributes if supplier else None) or {}
        supplier_options = (supplier.rexven_options if supplier else None) or []

        # The supplier states its material outright ("925 Ayar Gümüş" /
        # "Pirinç (Brass)"), and that choice drives the preset, the Etsy
        # materials field and the brass/silver description overrides. Prefer it
        # over the popup dropdown, which is hand-picked and silently wrong on a
        # mis-click.
        material_type = attributes.get("material_type") or req.material_type

        # What kind of stone the piece carries, read off Layer A's vision pass.
        # The supplier's spec block does not state it — REX-936's `rexven_attributes`
        # holds only care/color/style/packaging/size_info/chain_style — but the
        # vision model sees it plainly ("Christian cross with birthstone accent").
        #
        # Without this, `has_stone`/`stone_type` were never set by this flow, so
        # `_extract_features` (title) and `_product_summary` (description) both
        # skipped their stone branch and the word "birthstone" reached the LLM only
        # when the target keyword happened to contain it. On a listing targeting
        # "baptism gift cross necklace" that meant the product's differentiating
        # feature was absent from generation entirely.
        has_stone, stone_type = infer_stone(
            _detected_attributes(supplier), req.stone_shape
        )

        preset_name = req.variation_preset_name or self._auto_preset(
            req.category, material_type, req.personalization_choice
        )
        preset = (
            self.session.query(VariationPreset)
            .filter_by(name=preset_name)
            .first()
        )
        if preset is None:
            raise ValueError(f"Variation preset not found: {preset_name!r}")

        self._log_preset_mismatch(preset, supplier_options, req.rexven_sku)

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
            material_type=material_type,
            material=self._material_display(material_type),
            stone_shape=req.stone_shape,
            has_stone=has_stone,
            stone_type=stone_type,
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
            supplier_options=supplier_options or None,
            # Descriptive columns that already have readers but have always been
            # NULL: description_generator._product_summary builds "Color:",
            # "Style:" and "Size/Length:" lines from these, and
            # payload_builder._build_attributes sends chain_style to Etsy as a
            # filterable attribute (defaulting every listing to "Cable Chain").
            # Without them the description LLM knows only pillar, material and a
            # price, so any dimension it states is invented.
            color=_fit(attributes.get("color"), 50),
            style=_fit(attributes.get("style"), 50),
            size_info=attributes.get("size_info"),  # Text column, no cap needed
            chain_style=_fit(attributes.get("chain_style"), 50),
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

    def _load_supplier_capture(
        self, req: ListingBuildRequest
    ) -> Optional[SourcingAnalysis]:
        """Find the SourcingAnalysis this build came from, if any.

        Preferred route is the KeywordScore the user picked in the Sourcing tab,
        which points straight at its analysis. Falls back to the most recent
        analysis for the same supplier SKU, which covers a build started from the
        Build tab without going through sourcing first.
        """
        if req.selected_keyword_score_id:
            score = (
                self.session.query(KeywordScore)
                .filter_by(id=req.selected_keyword_score_id)
                .first()
            )
            if score is not None:
                analysis = (
                    self.session.query(SourcingAnalysis)
                    .filter_by(id=score.analysis_id)
                    .first()
                )
                if analysis is not None:
                    return analysis

        if req.rexven_sku:
            return (
                self.session.query(SourcingAnalysis)
                .filter_by(rexven_sku=req.rexven_sku)
                .order_by(SourcingAnalysis.id.desc())
                .first()
            )
        return None

    def _log_preset_mismatch(
        self,
        preset: VariationPreset,
        supplier_options: list,
        sku: Optional[str],
    ) -> None:
        """Record variations the preset offers that the supplier doesn't stock.

        Deliberately does not block or alter the matrix — the matrix is still
        preset-driven. This accumulates the evidence needed to decide whether to
        derive it from the supplier instead. Known live case: REX-922's preset
        offers a Silver finish while the supplier lists Gold only, so that
        listing carries a variation nobody can fulfil.
        """
        if not supplier_options:
            return
        problems = reconcile_preset(
            supplier_options,
            preset.finishes or [],
            preset.lengths_inches or [],
        )
        for problem in problems:
            _log.warning(
                "supplier_preset_mismatch",
                rexven_sku=sku,
                preset=preset.name,
                detail=problem,
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


# Ceiling on a client-supplied deep-dive wait. A batch of 6 keywords at roughly
# 8 minutes a dive is about 48 minutes; past an hour the run has gone wrong and
# building on existing grounding beats waiting longer.
_DEEPDIVE_WAIT_CAP_S = 3600
_DEEPDIVE_WAIT_DEFAULT_S = 600


async def run_listing_content_pipeline(
    product_sku: str,
    wait_for_deepdive: bool = False,
    deepdive_wait_s: Optional[int] = None,
) -> None:
    """
    Background task: runs the existing content orchestrator, wraps each
    variant's description in the operational scaffold, then kicks off the
    image pipeline so approval-page reviewers see both text and images.

    When ``wait_for_deepdive`` is true (extension auto-started a Phase-2
    competitor deep-dive just before the build), content generation first
    waits — bounded — for the deep-dive ingest to refresh KeywordResearch,
    then proceeds with whatever grounding is available.

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

        if wait_for_deepdive and product.selected_keyword_score_id:
            await _await_deepdive_grounding(
                session,
                product.selected_keyword_score_id,
                timeout_s=min(
                    deepdive_wait_s or _DEEPDIVE_WAIT_DEFAULT_S,
                    _DEEPDIVE_WAIT_CAP_S,
                ),
            )

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


async def _await_deepdive_grounding(
    session: Session,
    keyword_score_id: int,
    timeout_s: int = _DEEPDIVE_WAIT_DEFAULT_S,
    poll_interval_s: int = 15,
) -> None:
    """Wait (bounded) for the extension's Phase-2 deep-dive to refresh
    KeywordResearch for the chosen keyword, then return.

    The deep-dive scrapes ~10 competitor listings (~5-8 min) and its ingest
    endpoint refreshes ``KeywordResearch.last_analyzed_at``. We poll for a
    refresh that happened after this wait started; on timeout we proceed with
    whatever grounding already exists — never blocks the build indefinitely.

    ``timeout_s`` is sized by the caller from the build's position in the
    extension's serial deep-dive queue, since a later keyword's dive has not
    started yet when its build begins waiting.
    """
    import asyncio
    from datetime import datetime, timedelta

    from src.db.models import KeywordResearch, KeywordScore

    score = session.query(KeywordScore).filter_by(id=keyword_score_id).first()
    if score is None:
        return
    keyword = score.keyword

    # Small margin: the deep-dive may have finished moments before the build.
    started = datetime.utcnow() - timedelta(minutes=2)
    deadline = datetime.utcnow() + timedelta(seconds=timeout_s)

    while datetime.utcnow() < deadline:
        # Reset the transaction snapshot so we see commits made by the
        # deep-dive ingest request in its own session.
        session.rollback()
        research = (
            session.query(KeywordResearch).filter_by(keyword=keyword).first()
        )
        if research and research.last_analyzed_at and research.last_analyzed_at >= started:
            _log.info(
                "listing_pipeline_deepdive_ready",
                keyword=keyword,
                analyzed_at=str(research.last_analyzed_at),
            )
            return
        await asyncio.sleep(poll_interval_s)

    _log.warning(
        "listing_pipeline_deepdive_timeout",
        keyword=keyword,
        waited_s=timeout_s,
        hint="proceeding with existing grounding",
    )


def _category_from_preset(preset: Optional[VariationPreset]) -> str:
    if preset is None:
        return JewelryCategory.NECKLACE.value
    return preset.category
