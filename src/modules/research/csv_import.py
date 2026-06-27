"""
CSV Import helpers (Step 3.2)

Parses rows from a Chrome extension v2.4 CSV export into CompetitorListing
instances. All parsing logic lives here so the route stays thin.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

import pandas as pd

from src.db.models import CompetitorListing


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def parse_csv_to_listings(df: pd.DataFrame) -> list[CompetitorListing]:
    """Parse every row in the DataFrame into CompetitorListing objects."""
    listings = []
    for _, row in df.iterrows():
        listing = _parse_row_to_listing(row)
        if listing is not None:
            listings.append(listing)
    return listings


def merge_listing(existing: CompetitorListing, incoming: CompetitorListing) -> None:
    """
    Prefer the incoming row when it carries richer Phase 2 data.
    Fields that are already set on `existing` are NOT overwritten unless the
    incoming value is non-null and the existing value is null/falsy.
    """
    detail_fields = [
        "description_text", "description_length", "image_count",
        "views_24h_count", "cart_count", "stock_warning",
        "shop_total_sales", "has_sale_countdown", "personalization_required",
        "tags", "tag_volumes", "image_url",
        "eh_detail_release_date", "eh_detail_total_sales",
        "eh_detail_total_reviews", "eh_detail_total_favorites",
        "eh_detail_review_ratio", "eh_detail_category",
        "eh_detail_stocks", "eh_detail_conv_rate",
        "eh_sales_total", "eh_sales_recent", "eh_favorites",
        "eh_shop_weekly_sales", "eh_listed_date",
        "rating", "review_count", "is_bestseller", "is_star_seller",
        "is_popular_now",
    ]
    for field in detail_fields:
        incoming_val = getattr(incoming, field, None)
        if incoming_val is not None and not getattr(existing, field, None):
            setattr(existing, field, incoming_val)


# ---------------------------------------------------------------------------
# Row parser
# ---------------------------------------------------------------------------

def _parse_row_to_listing(row: pd.Series) -> CompetitorListing | None:
    listing_id = _str(row, "listing_id")
    if not listing_id:
        return None

    # Title: prefer detail_title if base title is empty
    title = _str(row, "title") or _str(row, "detail_title")

    # Shop name: prefer detail_shop
    shop_name = _str(row, "detail_shop") or _str(row, "shop")

    # Rating: prefer detail_rating
    rating = _float(row, "detail_rating") or _float(row, "rating")

    # Bestseller / star seller: OR search + detail flags
    is_bestseller = _bool(row, "is_bestseller") or _bool(row, "detail_is_bestseller")
    is_star_seller = _bool(row, "is_star_seller") or _bool(row, "detail_is_star_seller")

    # Tags: split "tag1 | tag2 | tag3" → list
    tags = _parse_pipe_tags(_str(row, "detail_tags"))

    # Tag volumes: JSON string → dict
    tag_volumes = _parse_json_field(row, "detail_tag_volumes")

    # EHunt detail-panel fields
    eh_detail_release_date = _date(row, "eh_detail_release_date")
    eh_detail_total_sales = _int(row, "eh_detail_total_sales")
    eh_detail_total_reviews = _int(row, "eh_detail_total_reviews")
    eh_detail_total_favorites = _int(row, "eh_detail_total_favorites")
    eh_detail_review_ratio = _str(row, "eh_detail_review_ratio")
    eh_detail_category = _str(row, "eh_detail_category")
    eh_detail_stocks = _int(row, "eh_detail_stocks")
    eh_detail_conv_rate = _str(row, "eh_detail_conv_rate")

    return CompetitorListing(
        listing_id=listing_id,
        url=_str(row, "url"),
        keyword_searched=_str(row, "keyword"),
        rank_in_search=_int(row, "rank"),
        title=title,
        image_url=_str(row, "image_url"),
        shop_name=shop_name,
        shop_id=_str(row, "shop_id"),
        shop_url=_str(row, "shop_url"),
        shop_age_years=_float(row, "shop_age_years"),
        price_cents=_int(row, "price_cents"),
        currency=_str(row, "currency"),
        original_price_cents=_int(row, "original_price_cents"),
        discount_pct=_int(row, "discount_pct"),
        rating=rating,
        review_count=_int(row, "review_count"),
        is_bestseller=is_bestseller,
        is_star_seller=is_star_seller,
        is_popular_now=_bool(row, "is_popular_now"),
        is_etsys_pick=_bool(row, "is_etsys_pick"),
        is_ad=_bool(row, "is_ad"),
        has_video=_bool(row, "has_video"),
        keyword_total_results=_int(row, "keyword_total_results"),
        # EHunt Phase 1
        eh_sales_total=_int(row, "eh_sales_total"),
        eh_sales_recent=_int(row, "eh_sales_recent"),
        eh_favorites=_int(row, "eh_favorites"),
        eh_shop_weekly_sales=_int(row, "eh_shop_weekly_sales"),
        eh_listed_date=_date(row, "eh_listed_date"),
        # Listing detail
        views_24h_count=_str(row, "views_24h_count"),
        cart_count=_int(row, "cart_count"),
        stock_warning=_str(row, "stock_warning"),
        shop_total_sales=_int(row, "shop_total_sales"),
        has_sale_countdown=_bool(row, "has_sale_countdown"),
        personalization_required=_bool(row, "personalization_required"),
        # LLM enrichment
        tags=tags,
        tag_volumes=tag_volumes,
        description_text=_str(row, "detail_description_text"),
        description_length=_int(row, "detail_description_length"),
        image_count=_int(row, "detail_image_count"),
        # EHunt detail panel
        eh_detail_release_date=eh_detail_release_date,
        eh_detail_total_sales=eh_detail_total_sales,
        eh_detail_total_reviews=eh_detail_total_reviews,
        eh_detail_total_favorites=eh_detail_total_favorites,
        eh_detail_review_ratio=eh_detail_review_ratio,
        eh_detail_category=eh_detail_category,
        eh_detail_stocks=eh_detail_stocks,
        eh_detail_conv_rate=eh_detail_conv_rate,
        scraped_at=_datetime(row, "scraped_at"),
        imported_at=datetime.utcnow(),
    )


# ---------------------------------------------------------------------------
# Type coercion helpers
# ---------------------------------------------------------------------------

def _val(row: pd.Series, key: str) -> Any:
    """Return raw cell or None if missing / NaN."""
    v = row.get(key)
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    return v


def _str(row: pd.Series, key: str) -> str | None:
    v = _val(row, key)
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _int(row: pd.Series, key: str) -> int | None:
    v = _val(row, key)
    if v is None:
        return None
    try:
        cleaned = re.sub(r"[^\d]", "", str(v))
        return int(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


def _float(row: pd.Series, key: str) -> float | None:
    v = _val(row, key)
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _bool(row: pd.Series, key: str) -> bool:
    v = _val(row, key)
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes")


def _date(row: pd.Series, key: str) -> date | None:
    v = _val(row, key)
    if v is None:
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _datetime(row: pd.Series, key: str) -> datetime | None:
    v = _val(row, key)
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _parse_pipe_tags(value: str | None) -> list[str] | None:
    if not value:
        return None
    tags = [t.strip() for t in value.split("|") if t.strip()]
    return tags if tags else None


def _parse_json_field(row: pd.Series, key: str) -> dict | None:
    v = _val(row, key)
    if v is None:
        return None
    if isinstance(v, dict):
        return v
    s = str(v).strip()
    if not s or s in ("nan", "None", "null"):
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None
