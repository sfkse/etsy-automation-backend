from datetime import datetime, date
from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from src.db.session import Base
from src.domain.carrier_pillar import CarrierPillar  # noqa: F401 — re-used in column


# ---------------------------------------------------------------------------
# Phase 4: Sourcing Intelligence — Enums
# ---------------------------------------------------------------------------


class SourcingStatus(str, Enum):
    PENDING = "pending"
    LAYER_A_RUNNING = "layer_a_running"
    LAYER_B_RUNNING = "layer_b_running"
    LAYER_C_RUNNING = "layer_c_running"
    COMPLETED = "completed"
    FAILED = "failed"


class KeywordTier(str, Enum):
    NICHE = "niche"
    MEDIUM = "medium"
    BROAD = "broad"


class ProductStatus(str, Enum):
    MANUAL_INPUT = "manual_input"
    IMAGE_PROCESSING = "image_processing"
    CONTENT_GENERATING = "content_generating"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    PUBLISHED = "published"
    FAILED = "failed"


class TagCategory(str, Enum):
    NICHE = "niche"
    MEDIUM = "medium"
    BIG = "big"


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    sku = Column(String(20), unique=True, nullable=False)
    carrier_pillar = Column(String(20), nullable=False)

    # Manual input fields
    user_provided_title = Column(String(255))
    material = Column(String(100))
    color = Column(String(50))
    has_stone = Column(Boolean, default=False)
    stone_type = Column(String(100))
    shape = Column(String(50))
    style = Column(String(50))
    occasion = Column(String(100))
    recipient = Column(String(50))
    size_info = Column(Text)
    cost = Column(Numeric(10, 2))
    selling_price = Column(Numeric(10, 2))

    # Generated content (3 variants)
    generated_variants = Column(JSONB)

    # Final selections (after human approval).
    # Kept as a compatibility mirror of the FIRST published variant — read by the
    # description-originality corpus, Sheets sync, the Etsy publisher, the internal
    # linker, and the dashboard. See publish_variants() in modules/approval/service.py.
    final_title = Column(String(140))
    final_tags = Column(JSONB)
    final_description = Column(Text)
    selected_variant_id = Column(String(10))

    # Multi-listing publish (Christmas-2 strategy): each chosen variant becomes its
    # own Etsy listing. published_variant_ids holds the variant ids the user elected
    # to publish, e.g. ["A", "B", "C"] or ["B"] or ["A", "HYBRID"].
    published_variant_ids = Column(
        JSONB, default=list, nullable=False, server_default="[]"
    )
    # Per-variant Etsy listing URLs pasted back after manual publishing:
    # {"A": "https://etsy.com/...", "B": "..."}.
    etsy_urls = Column(JSONB, default=dict, nullable=False, server_default="{}")

    # Etsy
    etsy_listing_id = Column(String(50))
    etsy_section_id = Column(String(50))

    # Status
    status = Column(String(30), default=ProductStatus.MANUAL_INPUT.value)
    image_workflow_used = Column(String(20))

    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime)
    published_at = Column(DateTime)

    # Operational Integration (v2.5) — Listing Builder additive columns
    variation_preset_id = Column(
        Integer, ForeignKey("variation_presets.id"), nullable=True
    )
    personalization_template_id = Column(
        Integer, ForeignKey("personalization_templates.id"), nullable=True
    )
    target_keyword = Column(String(100), nullable=True)
    material_type = Column(String(30), nullable=True)  # MaterialType enum value
    stone_shape = Column(String(50), nullable=True)
    holiday_override = Column(String(50), nullable=True)
    is_featured = Column(Boolean, default=False)
    theme = Column(String(100), nullable=True)
    chain_style = Column(String(50), nullable=True)
    recipients_json = Column(JSONB, nullable=True)
    occasions_json = Column(JSONB, nullable=True)
    rexven_url = Column(String(500), nullable=True)
    rexven_sku = Column(
        String(50), nullable=True, index=True
    )  # Supplier-side SKU (e.g. "REX-1664")
    original_image_path = Column(String(500), nullable=True)
    cost_cents = Column(
        Integer, nullable=True
    )  # Landed cost (product + shipping) when use_landed_cost was true
    supplier_product_cents = Column(
        Integer, nullable=True
    )  # Rexven Premium "Product Price" in cents
    supplier_shipping_cents = Column(
        Integer, nullable=True
    )  # Rexven Premium "Shipping Price" in cents
    supplier_total_cents = Column(
        Integer, nullable=True
    )  # Rexven Premium "Total Price" in cents
    selected_keyword_score_id = Column(
        Integer, nullable=True
    )  # Phase 4 sourcing: KeywordScore chosen to ground content generation

    images = relationship("ProductImage", back_populates="product")
    stats = relationship("ProductStats", back_populates="product")
    approval_overrides = relationship("ApprovalOverride", back_populates="product")
    renew_logs = relationship("RenewLog", back_populates="product")
    variation_rows = relationship(
        "VariationRow", back_populates="product", cascade="all, delete-orphan"
    )

    @property
    def is_multi_published(self) -> bool:
        """True when the product was published as more than one separate listing."""
        return len(self.published_variant_ids or []) > 1


class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"))

    file_path = Column(String(500))
    rank = Column(Integer)
    is_real = Column(Boolean, default=False)
    workflow_source = Column(String(20))
    alt_text = Column(String(250))
    is_selected = Column(Boolean, default=False)

    # User-supplied art direction appended to the slot's built-in prompt on the
    # last regenerate — persisted so the images page can pre-fill it for iteration.
    regen_instructions = Column(Text, nullable=True)

    # Colour palette used on the last (re)generation of this slot — persisted so
    # the images page can pre-fill the per-image palette override.
    palette_used = Column(String(40), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="images")


class ApprovalOverride(Base):
    """Audit log of human overrides to validator violations during approval."""

    __tablename__ = "approval_overrides"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    field_name = Column(String(50), nullable=False)  # "title" | "tags" | "description"
    violation = Column(Text, nullable=False)  # the rule that was violated
    overridden_value = Column(Text)  # the value user forced through
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="approval_overrides")


class CopyPasteProgress(Base):
    """Per-variant checklist state for the copy-paste helper.

    One row per (product, variant, field) the user has ticked off while manually
    pasting a published variant into Etsy. Field is one of:
    title | tags | description | photos | variations | attributes.
    """

    __tablename__ = "copy_paste_progress"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "variant_id", "field", name="uq_copy_progress_field"
        ),
    )

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    variant_id = Column(String(10), nullable=False)  # "A" | "B" | "C" | "HYBRID"
    field = Column(String(20), nullable=False)
    checked_at = Column(DateTime, default=datetime.utcnow)


class KeywordPool(Base):
    __tablename__ = "keyword_pool"

    id = Column(Integer, primary_key=True)
    keyword = Column(String(50), unique=True, nullable=False)
    category = Column(String(10))
    carrier_pillar = Column(String(20))
    # Universal SEO staples (Christmas 2 training) apply across all pillars;
    # these rows carry carrier_pillar=None and are offered to every listing.
    is_universal = Column(
        Boolean, default=False, nullable=False, server_default="false", index=True
    )


class ProductStats(Base):
    __tablename__ = "product_stats"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"))

    date = Column(Date)
    views = Column(Integer, default=0)
    favorites = Column(Integer, default=0)
    cart_adds = Column(Integer, default=0)
    sales = Column(Integer, default=0)

    product = relationship("Product", back_populates="stats")


class RenewLog(Base):
    """Audit log of every listing renewal attempt."""

    __tablename__ = "renew_log"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    listing_id = Column(String(50), nullable=False)
    renewed_at = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean, default=True)
    error_message = Column(Text)

    product = relationship("Product", back_populates="renew_logs")


# ---------------------------------------------------------------------------
# Phase 3: Research / Competitor Intelligence
# ---------------------------------------------------------------------------


class ShopClassification(str, Enum):
    ACTIVE_STRONG = "active_strong"
    LEGACY = "legacy"
    RISING = "rising"
    UNKNOWN = "unknown"


class CompetitorListing(Base):
    """One row per Etsy listing scraped via the Chrome extension."""

    __tablename__ = "competitor_listings"

    id = Column(Integer, primary_key=True)
    listing_id = Column(String(20), unique=True, nullable=False, index=True)
    url = Column(String(500))
    keyword_searched = Column(String(100), index=True)
    rank_in_search = Column(Integer)

    # Search-result-level fields (Phase 1 of extension)
    title = Column(String(255))
    image_url = Column(String(1000))
    shop_name = Column(String(100), index=True)
    shop_id = Column(String(20))
    shop_url = Column(String(500))
    shop_age_years = Column(Float)
    price_cents = Column(Integer)
    currency = Column(String(10))
    original_price_cents = Column(Integer)
    discount_pct = Column(Integer)
    rating = Column(Float)
    review_count = Column(Integer)
    is_bestseller = Column(Boolean, default=False)
    is_star_seller = Column(Boolean, default=False)
    is_popular_now = Column(Boolean, default=False)
    is_etsys_pick = Column(Boolean, default=False)
    is_ad = Column(Boolean, default=False)
    has_video = Column(Boolean, default=False)

    # Total Etsy results for the keyword (same value per keyword row — search volume proxy)
    keyword_total_results = Column(Integer)

    # EHunt Phase 1 enrichment (null when EHunt extension not installed)
    eh_sales_total = Column(Integer)
    eh_sales_recent = Column(Integer)
    eh_favorites = Column(Integer)
    eh_shop_weekly_sales = Column(Integer)
    eh_listed_date = Column(Date)

    # Listing-detail-level fields (Phase 2 of extension)
    views_24h_count = Column(String(20))
    cart_count = Column(Integer)
    stock_warning = Column(String(100))
    shop_total_sales = Column(Integer)
    has_sale_countdown = Column(Boolean, default=False)
    personalization_required = Column(Boolean, default=False)

    # Enrichment fields for LLM (extension v1.1+)
    tags = Column(JSONB)  # list of strings — actual 13 seller tags via EHunt panel
    tag_volumes = Column(JSONB)  # {tag: search_volume_int} from EHunt
    description_text = Column(Text)
    description_length = Column(Integer)
    image_count = Column(Integer)

    # EHunt detail panel enrichment (extension v2.4+, listing-detail Phase 2 only)
    eh_detail_release_date = Column(Date)
    eh_detail_total_sales = Column(Integer)
    eh_detail_total_reviews = Column(Integer)
    eh_detail_total_favorites = Column(Integer)
    eh_detail_review_ratio = Column(String(20))
    eh_detail_category = Column(String(255))
    eh_detail_stocks = Column(Integer)
    eh_detail_conv_rate = Column(String(20))

    # Computed
    sales_signal_score = Column(Float, index=True)

    scraped_at = Column(DateTime)
    imported_at = Column(DateTime, default=datetime.utcnow)

    # Phase 4: Sourcing Intelligence — mini-Phase-1 scrape tagging
    scraped_for_sourcing = Column(Boolean, default=False, index=True)
    sourcing_analysis_id = Column(
        Integer, ForeignKey("sourcing_analyses.id"), nullable=True
    )

    # Phase 4: CLIP embedding (stored as JSON float list; migrate to pgvector later)
    image_embedding = Column(JSONB, nullable=True)
    image_embedding_model = Column(String(50), nullable=True)
    image_embedding_computed_at = Column(DateTime, nullable=True)


class KeywordResearch(Base):
    """Aggregated stats per keyword. Refreshed after each CSV import."""

    __tablename__ = "keyword_research"

    id = Column(Integer, primary_key=True)
    keyword = Column(String(100), unique=True, nullable=False, index=True)

    total_listings_scraped = Column(Integer)
    bestseller_count = Column(Integer)
    star_seller_count = Column(Integer)
    avg_title_length = Column(Float)
    avg_review_count = Column(Float)
    avg_price_cents = Column(Float)
    avg_image_count = Column(Float)

    # Cached analyzer outputs
    title_patterns = Column(JSONB)
    top_tags_by_frequency = Column(JSONB)
    common_cliches = Column(JSONB)
    underused_keywords = Column(JSONB)
    volume_stratified_tags = Column(
        JSONB
    )  # {"mainstream":[...], "medium":[...], "niche":[...]}
    avg_volume_by_position = Column(JSONB)  # list of 13 ints

    last_analyzed_at = Column(DateTime)


class CompetitorShop(Base):
    """Aggregated per-shop data for the 3-tier shop tracking strategy."""

    __tablename__ = "competitor_shops"

    id = Column(Integer, primary_key=True)
    shop_id = Column(String(20), unique=True, nullable=False, index=True)
    shop_name = Column(String(100), index=True)
    shop_url = Column(String(500))

    total_sales = Column(Integer)
    listings_in_research = Column(Integer)
    bestseller_listings = Column(Integer)
    avg_rating = Column(Float)

    classification = Column(String(20), default=ShopClassification.UNKNOWN.value)
    notes = Column(Text)

    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime)


# ---------------------------------------------------------------------------
# Phase 4: Sourcing Intelligence
# ---------------------------------------------------------------------------


class SourcingAnalysis(Base):
    """One row per 'analyze this Rexven product' invocation."""

    __tablename__ = "sourcing_analyses"

    id = Column(Integer, primary_key=True)

    # Source identification — accept any of three inputs
    rexven_url = Column(String(500), nullable=True, index=True)
    rexven_sku = Column(String(50), nullable=True, index=True)
    image_path = Column(String(500), nullable=True)
    image_url = Column(String(500), nullable=True)

    # Rexven product metadata
    rexven_title_tr = Column(String(255), nullable=True)
    rexven_title_en = Column(String(255), nullable=True)
    rexven_cost_usd_cents = Column(Integer, nullable=True)
    rexven_premium_cost_usd_cents = Column(Integer, nullable=True)
    rexven_category = Column(String(50), nullable=True)
    rexven_has_satisa_uygun_badge = Column(Boolean, default=False)
    rexven_has_yeni_badge = Column(Boolean, default=False)

    # Analysis state
    status = Column(String(30), default=SourcingStatus.PENDING.value)
    layer_a_completed = Column(Boolean, default=False)
    layer_b_completed = Column(Boolean, default=False)
    layer_c_completed = Column(Boolean, default=False)
    error_message = Column(Text, nullable=True)

    # Cost tracking
    vision_tokens_used = Column(Integer, default=0)
    vision_cost_usd_cents = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    candidates = relationship(
        "KeywordCandidate", back_populates="analysis", cascade="all, delete-orphan"
    )
    scores = relationship(
        "KeywordScore", back_populates="analysis", cascade="all, delete-orphan"
    )


class KeywordCandidate(Base):
    """Raw output from Layer A — keyword candidate before scoring."""

    __tablename__ = "keyword_candidates"

    id = Column(Integer, primary_key=True)
    analysis_id = Column(Integer, ForeignKey("sourcing_analyses.id"), nullable=False)

    keyword = Column(String(100), nullable=False, index=True)
    tier = Column(String(10), nullable=False)  # "niche" / "medium" / "broad"

    rationale = Column(Text, nullable=True)
    detected_attributes = Column(JSONB, nullable=True)

    # Which layer proposed this candidate: "A" (vision LLM) or "C" (CLIP similarity)
    source_layer = Column(String(10), default="A")

    analysis = relationship("SourcingAnalysis", back_populates="candidates")


class KeywordScore(Base):
    """Post-Layer-B opportunity-scored keyword. One per candidate that passed scoring."""

    __tablename__ = "keyword_scores"

    id = Column(Integer, primary_key=True)
    analysis_id = Column(Integer, ForeignKey("sourcing_analyses.id"), nullable=False)
    candidate_id = Column(Integer, ForeignKey("keyword_candidates.id"), nullable=False)

    keyword = Column(String(100), nullable=False)

    # Sub-scores (0.0–1.0)
    score_new_shop_share = Column(Float, nullable=True)
    score_price_alignment = Column(Float, nullable=True)
    score_activity = Column(Float, nullable=True)
    score_competition = Column(Float, nullable=True)
    score_diversity = Column(Float, nullable=True)

    opportunity_score = Column(Float, index=True, nullable=True)

    # Empirical market data captured at scoring time
    top20_avg_price_cents = Column(Integer, nullable=True)
    top20_avg_shop_age = Column(Float, nullable=True)
    top20_keyword_total_results = Column(Integer, nullable=True)
    top20_unique_shops = Column(Integer, nullable=True)
    top20_with_recent_sales = Column(Integer, nullable=True)

    # Layer C enrichment (populated when CLIP analysis runs)
    estimated_rank = Column(Integer, nullable=True)
    estimated_page = Column(Integer, nullable=True)
    visual_similarity_support = Column(Integer, nullable=True)

    rank_in_recommendation = Column(Integer, nullable=True)

    analysis = relationship("SourcingAnalysis", back_populates="scores")


class RexvenProductEmbedding(Base):
    """Cached CLIP embedding for a Rexven product image — avoids recomputing."""

    __tablename__ = "rexven_product_embeddings"

    id = Column(Integer, primary_key=True)
    image_hash = Column(String(64), unique=True, nullable=False, index=True)
    image_path = Column(String(500), nullable=True)
    embedding = Column(JSONB, nullable=False)
    model_name = Column(String(50), nullable=True)
    computed_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Operational Integration v2.5 — Shop Settings, Templates, Variations, Pricing
# ---------------------------------------------------------------------------


class RenewalOption(str, Enum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"


class JewelryCategory(str, Enum):
    NECKLACE = "necklace"
    BRACELET = "bracelet"
    EARRING = "earring"
    RING = "ring"
    ANKLET = "anklet"


class MaterialType(str, Enum):
    BRASS = "brass"
    SILVER_925 = "silver_925"
    GOLD_PLATED = "gold_plated"


class ShopSettings(Base):
    """Singleton table — exactly one row (id=1) holds shop-level configuration."""

    __tablename__ = "shop_settings"

    id = Column(Integer, primary_key=True)

    shop_name = Column(String(100), nullable=True)
    shop_id = Column(String(20), nullable=True)

    # Production Partner (one-time Etsy setup)
    production_partner_id = Column(String(50), nullable=True)
    production_partner_name = Column(String(100), nullable=True)
    production_partner_about = Column(String(255), nullable=True)
    production_partner_location = Column(String(100), nullable=True)
    production_partner_q1 = Column(String(50), default="capacity")
    production_partner_q2 = Column(String(50), default="design")
    production_partner_q3 = Column(String(50), default="everything")

    # Operational policies
    renewal_option = Column(String(20), default=RenewalOption.AUTOMATIC.value)
    return_policy_days = Column(Integer, default=14)
    feature_listing_default = Column(Boolean, default=False)

    # Quantity strategy
    default_quantity = Column(Integer, default=999)

    # 22K disclosure rule (from Master Rehber)
    omit_karat_in_title = Column(Boolean, default=True)

    # Carrier pillars active for this shop
    active_pillars = Column(
        JSONB,
        default=lambda: [
            "cross",
            "name",
            "birthstone",
            "birth_flower",
            "pet",
            "pendant",
        ],
    )

    # Default shipping profile (referenced by Etsy payload builder)
    default_shipping_profile_id = Column(String(50), nullable=True)

    # Image workflow mode: "jewelry_9" (3 mannequin + 3 concept + 3 chart) or "legacy" (5 lifestyle)
    image_workflow_mode = Column(String(20), default="jewelry_9")

    # Default colour palette applied to generated photos (see jewelry_set.PALETTES).
    # Per-image regeneration can override this; unknown values fall back to DEFAULT_PALETTE.
    image_palette = Column(String(40), default="soft_blush_neutral")

    # Auto-create a ShopSection the first time a listing is built for a new pillar (PR 6)
    auto_create_sections = Column(Boolean, default=True)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DescriptionTemplate(Base):
    """Per-category description scaffold. Filled with product-specific blanks at gen time."""

    __tablename__ = "description_templates"

    id = Column(Integer, primary_key=True)
    category = Column(String(20), nullable=False, unique=True)  # JewelryCategory value

    section_intro = Column(Text, nullable=True)
    section_how_to_order = Column(Text, nullable=True)
    section_materials = Column(Text, nullable=True)
    section_finish = Column(Text, nullable=True)
    section_packaging = Column(Text, nullable=True)
    section_gift_note = Column(Text, nullable=True)
    section_best_gifts_for = Column(Text, nullable=True)
    section_have_a_question = Column(Text, nullable=True)

    brass_overrides = Column(JSONB, nullable=True)
    silver_overrides = Column(JSONB, nullable=True)

    default_chain_text = Column(Text, nullable=True)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DefaultAttributes(Base):
    """Default Etsy attribute values applied to every listing unless overridden."""

    __tablename__ = "default_attributes"

    id = Column(Integer, primary_key=True)
    category = Column(String(20), nullable=False, unique=True)  # JewelryCategory value

    style = Column(String(50), default="Minimalist")
    theme = Column(String(50), default="Love & Friendship")
    holiday_default = Column(String(50), default="Christmas")

    sustainability = Column(String(50), default="Made with Recycled Metals")
    chain_style = Column(String(50), default="Cable Chain")
    adjustable = Column(Boolean, default=True)
    convertible = Column(Boolean, default=True)

    default_occasion = Column(String(50), default="Birthday")

    default_recipients = Column(
        JSONB, default=lambda: ["Her", "Mother", "Wife", "Daughter", "Sister"]
    )


class VariationPreset(Base):
    """Variation matrix template. One row = one default skeleton."""

    __tablename__ = "variation_presets"

    id = Column(Integer, primary_key=True)
    name = Column(String(60), nullable=False, unique=True)

    category = Column(String(20), nullable=False)  # JewelryCategory
    material_type = Column(String(30), nullable=False)  # MaterialType

    finishes = Column(JSONB, nullable=False)
    lengths_inches = Column(JSONB, nullable=True)

    multi_count_label = Column(String(50), nullable=True)
    multi_count_range = Column(JSONB, nullable=True)

    has_length_variation = Column(Boolean, default=True)


class PricingStrategy(Base):
    """Singleton — how prices are computed across the variation matrix."""

    __tablename__ = "pricing_strategy"

    id = Column(Integer, primary_key=True)

    base_multiplier = Column(Float, default=4.0)

    finish_offsets_pct = Column(
        JSONB, default=lambda: {"Gold": 0.0, "Silver": -3.0, "Rose": -5.0}
    )

    length_base_inches = Column(Integer, default=16)
    length_price_per_extra_inch_pct = Column(Float, default=2.5)

    loss_leader_enabled = Column(Boolean, default=True)
    loss_leader_finish = Column(String(20), default="Rose")
    loss_leader_length = Column(Integer, default=12)
    loss_leader_margin_pct = Column(Float, default=15.0)

    # Multi-count surcharge (percent per extra unit)
    multi_count_extra_pct = Column(Float, default=12.0)


class PersonalizationTemplate(Base):
    """Library of personalization scaffolds. Picked per product."""

    __tablename__ = "personalization_templates"

    id = Column(Integer, primary_key=True)
    name = Column(String(60), nullable=False, unique=True)

    instruction_text = Column(Text, nullable=True)
    example_text = Column(Text, nullable=True)
    reference_note = Column(Text, nullable=True)

    max_characters = Column(Integer, default=0)
    is_optional = Column(Boolean, default=False)

    applicable_categories = Column(JSONB, default=lambda: ["necklace", "bracelet"])
    type_signature = Column(JSONB, nullable=True)


class ShopSection(Base):
    """The shop sections from the operational training."""

    __tablename__ = "shop_sections"

    id = Column(Integer, primary_key=True)
    etsy_section_id = Column(String(50), nullable=True)
    name = Column(String(60), nullable=False, unique=True)
    carrier_pillar = Column(String(50), nullable=True)
    display_order = Column(Integer, default=0)


class VariationRow(Base):
    """One row per cell in a product's Finish x Length x MultiCount matrix."""

    __tablename__ = "variation_rows"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)

    finish = Column(String(20), nullable=False)
    length_inches = Column(Integer, nullable=True)
    multi_count = Column(Integer, nullable=True)

    price_cents = Column(Integer, nullable=False)
    sku_suffix = Column(String(40), nullable=False)
    is_loss_leader = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="variation_rows")
