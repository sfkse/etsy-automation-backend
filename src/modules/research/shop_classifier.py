"""
Shop Classifier (Step 3.4)

Classifies each CompetitorShop into ACTIVE_STRONG / LEGACY / RISING / UNKNOWN
based on age, total sales, and EHunt weekly-sales data (per training Section 1.9).
Also provides upsert_competitor_shop() used by the CSV import pipeline.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from src.db.models import CompetitorListing, CompetitorShop, ShopClassification


def classify_shop(session: Session, shop_id: str) -> ShopClassification:
    """
    Rules (Section 1.9):
    - RISING:        opened ≤ 24 months ago AND already ≥ 1000 total sales
    - ACTIVE_STRONG: ≥ 5000 total sales AND weekly sales ≥ 50
                     OR weekly sales ≥ 30 (no total threshold)
    - LEGACY:        ≥ 10000 total sales AND weekly sales < 30
    - UNKNOWN:       insufficient data
    """
    shop = session.query(CompetitorShop).filter_by(shop_id=shop_id).first()
    if not shop:
        return ShopClassification.UNKNOWN

    # Derive age in months from the most recent listing's shop_age_years
    sample = (
        session.query(CompetitorListing)
        .filter_by(shop_id=shop_id)
        .filter(CompetitorListing.shop_age_years.isnot(None))
        .first()
    )
    age_months = int(sample.shop_age_years * 12) if sample and sample.shop_age_years is not None else 9999

    # EHunt weekly sales — same value across all listings from this shop
    weekly_sample = (
        session.query(CompetitorListing)
        .filter_by(shop_id=shop_id)
        .filter(CompetitorListing.eh_shop_weekly_sales.isnot(None))
        .first()
    )
    weekly = weekly_sample.eh_shop_weekly_sales if weekly_sample else 0
    total = shop.total_sales or 0

    if age_months <= 24 and total >= 1000:
        return ShopClassification.RISING
    if weekly >= 50 and total >= 5000:
        return ShopClassification.ACTIVE_STRONG
    if total >= 10000 and weekly < 30:
        return ShopClassification.LEGACY
    if weekly >= 30:
        return ShopClassification.ACTIVE_STRONG
    return ShopClassification.UNKNOWN


def upsert_competitor_shop(session: Session, shop_id: str) -> CompetitorShop:
    """
    Build (or refresh) a CompetitorShop row from aggregated CompetitorListing data,
    then run classification. Called after each CSV import.
    """
    listings = session.query(CompetitorListing).filter_by(shop_id=shop_id).all()
    if not listings:
        return None

    sample = listings[0]
    shop = session.query(CompetitorShop).filter_by(shop_id=shop_id).first()
    if not shop:
        shop = CompetitorShop(shop_id=shop_id, first_seen_at=datetime.utcnow())
        session.add(shop)

    shop.shop_name = sample.shop_name
    shop.shop_url = sample.shop_url
    shop.last_seen_at = datetime.utcnow()
    shop.listings_in_research = len(listings)
    shop.bestseller_listings = sum(1 for l in listings if l.is_bestseller)

    # Use the max shop_total_sales seen across listings (all rows report the same shop stat)
    sales_values = [l.shop_total_sales for l in listings if l.shop_total_sales is not None]
    shop.total_sales = max(sales_values) if sales_values else None

    ratings = [l.rating for l in listings if l.rating is not None]
    shop.avg_rating = sum(ratings) / len(ratings) if ratings else None

    session.flush()

    classification = classify_shop(session, shop_id)
    shop.classification = classification.value

    return shop
