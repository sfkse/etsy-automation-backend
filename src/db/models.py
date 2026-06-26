from datetime import datetime, date
from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
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
