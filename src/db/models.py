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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from src.db.session import Base
from src.domain.carrier_pillar import CarrierPillar  # noqa: F401 — re-used in column


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

    # Final selections (after human approval)
    final_title = Column(String(140))
    final_tags = Column(JSONB)
    final_description = Column(Text)
    selected_variant_id = Column(String(10))

    # Etsy
    etsy_listing_id = Column(String(50))
    etsy_section_id = Column(String(50))

    # Status
    status = Column(String(30), default=ProductStatus.MANUAL_INPUT.value)
    image_workflow_used = Column(String(20))

    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime)
    published_at = Column(DateTime)

    images = relationship("ProductImage", back_populates="product")
    stats = relationship("ProductStats", back_populates="product")
    approval_overrides = relationship("ApprovalOverride", back_populates="product")


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

    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="images")


class ApprovalOverride(Base):
    """Audit log of human overrides to validator violations during approval."""

    __tablename__ = "approval_overrides"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    field_name = Column(String(50), nullable=False)   # "title" | "tags" | "description"
    violation = Column(Text, nullable=False)          # the rule that was violated
    overridden_value = Column(Text)                   # the value user forced through
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="approval_overrides")


class KeywordPool(Base):
    __tablename__ = "keyword_pool"

    id = Column(Integer, primary_key=True)
    keyword = Column(String(50), unique=True, nullable=False)
    category = Column(String(10))
    carrier_pillar = Column(String(20))


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
    tags = Column(JSONB)         # list of strings — actual 13 seller tags via EHunt panel
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
    volume_stratified_tags = Column(JSONB)   # {"mainstream":[...], "medium":[...], "niche":[...]}
    avg_volume_by_position = Column(JSONB)   # list of 13 ints

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
