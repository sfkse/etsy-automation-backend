"""
Research Refresh Pipeline (Step 3.7)

refresh_keyword_research(): re-runs all analyzers for one keyword, persists
  results to KeywordResearch. Called after each CSV import and from dashboard.

refresh_all_keywords_job(): the weekly APScheduler job (wired in Phase 9).
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from src.db.models import CompetitorListing, KeywordResearch
from src.modules.research.scoring import compute_sales_signal_score
from src.modules.research.title_analyzer import analyze_titles_for_keyword
from src.modules.research.tag_analyzer import analyze_tags_for_keyword, extract_cliches

logger = logging.getLogger(__name__)


async def refresh_keyword_research(
    session: Session,
    keyword: str,
    llm_client,
) -> KeywordResearch | None:
    """
    Re-compute sales signal scores + all analyzers for `keyword`.
    Upserts the KeywordResearch row.
    Returns the updated KeywordResearch or None if no listings found.
    """
    # Score any listings that haven't been scored yet
    unscored = (
        session.query(CompetitorListing)
        .filter_by(keyword_searched=keyword)
        .filter(CompetitorListing.sales_signal_score.is_(None))
        .all()
    )
    for listing in unscored:
        listing.sales_signal_score = compute_sales_signal_score(listing)
    if unscored:
        session.flush()

    # Run analyzers
    title_analysis = await analyze_titles_for_keyword(session, keyword, llm_client)
    if not title_analysis:
        logger.warning("No listings found for keyword %r — skipping refresh", keyword)
        return None

    tag_analysis = analyze_tags_for_keyword(session, keyword)
    cliches = await extract_cliches(session, keyword, llm_client)

    # Upsert KeywordResearch row
    research = session.query(KeywordResearch).filter_by(keyword=keyword).first()
    if not research:
        research = KeywordResearch(keyword=keyword)
        session.add(research)

    all_listings = (
        session.query(CompetitorListing).filter_by(keyword_searched=keyword).all()
    )

    research.total_listings_scraped = title_analysis["sample_size"]
    research.avg_title_length = title_analysis["avg_length"]
    research.title_patterns = title_analysis
    research.underused_keywords = title_analysis["underused_keywords"]
    research.top_tags_by_frequency = tag_analysis
    research.common_cliches = cliches
    research.last_analyzed_at = datetime.utcnow()

    research.bestseller_count = sum(1 for l in all_listings if l.is_bestseller)
    research.star_seller_count = sum(1 for l in all_listings if l.is_star_seller)

    prices = [l.price_cents for l in all_listings if l.price_cents is not None]
    research.avg_price_cents = sum(prices) / len(prices) if prices else None

    reviews = [l.review_count for l in all_listings if l.review_count is not None]
    research.avg_review_count = sum(reviews) / len(reviews) if reviews else None

    images = [l.image_count for l in all_listings if l.image_count is not None]
    research.avg_image_count = sum(images) / len(images) if images else None

    # Persist volume-stratified data from tag analysis if available
    if tag_analysis:
        research.volume_stratified_tags = tag_analysis.get("volume_stratified_tags")
        research.avg_volume_by_position = tag_analysis.get("avg_volume_by_position")

    session.commit()
    logger.info("Refreshed keyword research for %r (%d listings)", keyword, len(all_listings))
    return research


async def refresh_all_keywords_job(session: Session, llm_client) -> None:
    """
    Weekly job — scheduled via APScheduler in Phase 9.
    Re-analyzes all keywords that have at least one listing.
    """
    keywords = [r.keyword for r in session.query(KeywordResearch).all()]

    # Also pick up keywords with listings but no KeywordResearch row yet
    from sqlalchemy import distinct
    scraped_keywords = [
        row[0]
        for row in session.query(distinct(CompetitorListing.keyword_searched)).all()
        if row[0]
    ]
    all_keywords = list({*keywords, *scraped_keywords})

    logger.info("Weekly research refresh: %d keywords", len(all_keywords))
    for kw in all_keywords:
        try:
            await refresh_keyword_research(session, kw, llm_client)
        except Exception as exc:
            logger.error("Refresh failed for %r: %s", kw, exc)

    logger.info("Weekly refresh complete: %d keywords processed", len(all_keywords))
