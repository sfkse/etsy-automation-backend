# Phase 3

From the Full Spec. Implement in order. Each step ends with a validation block.

---

## PHASE 3: RESEARCH MODULE (Competitor Intelligence)

> **Purpose:** Ingest competitor data scraped from Etsy via the companion Chrome extension (Etsy Research Extension v1.1+) and turn it into structured intelligence that feeds the Content Pipeline (Phase 6). This module is what makes the LLM's title/tag/description generation grounded in **real bestseller data** instead of inventing from scratch.
>
> **Input:** CSV file exported from the Chrome extension (manual upload by user).
> **Output:** Populated `CompetitorListing`, `KeywordResearch`, `CompetitorShop` tables; analyzers produce summary objects that get injected into Phase 6 LLM prompts.

### Step 3.1: Research Domain Models
**Goal:** SQLAlchemy models for competitor intelligence.

**Implementation:**

Add to `src/db/models.py`:

```python
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
    image_url = Column(String(1000))  # primary thumbnail from search card
    shop_name = Column(String(100), index=True)
    shop_id = Column(String(20))
    shop_url = Column(String(500))
    shop_age_years = Column(Float)  # extracted from shop tooltip "X years on Etsy"
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
    
    # Page-level: total Etsy search results for the keyword (search volume proxy).
    # Same value for every row of the same keyword. Stored per-row for simplicity.
    keyword_total_results = Column(Integer)
    
    # ---- EHunt-injected enrichment (null if EHunt extension was not installed) ----
    # These come from EHunt's overlay on Etsy search pages. The user pays for EHunt;
    # we just read what EHunt has already placed in the DOM. No EHunt API calls.
    eh_sales_total = Column(Integer)        # e.g. 2700 (lifetime sales estimate)
    eh_sales_recent = Column(Integer)       # e.g. 15 (recent period, likely weekly)
    eh_favorites = Column(Integer)
    eh_shop_weekly_sales = Column(Integer)  # ground truth for "rising shop" detection
    eh_listed_date = Column(Date)           # when the listing was published
    
    # Listing-detail-level fields (Phase 2 of extension)
    views_24h_count = Column(String(20))  # e.g. "20+" or "150"
    cart_count = Column(Integer)
    stock_warning = Column(String(100))
    shop_total_sales = Column(Integer)
    has_sale_countdown = Column(Boolean, default=False)
    personalization_required = Column(Boolean, default=False)
    
    # Enrichment fields for LLM (extension v1.1+ only)
    tags = Column(JSON)  # list of strings — the listing's actual 13 seller tags (via EHunt panel)
    tag_volumes = Column(JSON)  # {tag: search_volume_int} — per-tag search volume from EHunt
    description_text = Column(Text)
    description_length = Column(Integer)
    image_count = Column(Integer)
    
    # ---- EHunt detail panel enrichment (extension v2.4+, listing-detail Phase 2 only) ----
    # When EHunt is installed, the listing detail page contains a #etsy-rank-tool-product-table
    # panel with these fields. They are richer than the Phase 1 EHunt search-card data:
    # the listing's actual 13 seller tags (otherwise hidden from public DOM since 2026),
    # search volumes per tag, release date, EHunt's own sales/reviews/favorites counts,
    # review ratio (good conversion proxy), Etsy category breadcrumb, current stock,
    # and average conversion rate (often "N/A").
    eh_detail_release_date = Column(Date)
    eh_detail_total_sales = Column(Integer)       # EHunt's Phase 2 sales count, may differ from Phase 1
    eh_detail_total_reviews = Column(Integer)
    eh_detail_total_favorites = Column(Integer)
    eh_detail_review_ratio = Column(String(20))   # e.g. "18.44%" — kept as string since EHunt formats it
    eh_detail_category = Column(String(255))      # e.g. "Weddings > Gifts & Mementos > Bridesmaids Gifts > Jewelry"
    eh_detail_stocks = Column(Integer)
    eh_detail_conv_rate = Column(String(20))      # often "N/A"; rarely a percent like "2.5%"
    
    # Computed
    sales_signal_score = Column(Float, index=True)  # see Step 3.7
    
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
    
    # Cached analyzer outputs (JSON blobs)
    title_patterns = Column(JSON)        # see Step 3.5
    top_tags_by_frequency = Column(JSON) # see Step 3.6
    common_cliches = Column(JSON)        # see Step 3.6
    underused_keywords = Column(JSON)    # see Step 3.5 — differentiation opportunity
    # Volume-stratified tag pools (only populated when ≥20% of listings have EHunt tag_volumes).
    # Used by Phase 6.3 to give each variant angle a different volume profile.
    volume_stratified_tags = Column(JSON)    # {"mainstream":[(tag,vol),...], "medium":[...], "niche":[...]}
    avg_volume_by_position = Column(JSON)    # list of 13 ints — typical volume per tag slot in the niche
    
    last_analyzed_at = Column(DateTime)


class CompetitorShop(Base):
    """Aggregated per-shop data for the 3-tier shop tracking strategy."""
    __tablename__ = "competitor_shops"
    
    id = Column(Integer, primary_key=True)
    shop_id = Column(String(20), unique=True, nullable=False)
    shop_name = Column(String(100), index=True)
    shop_url = Column(String(500))
    
    total_sales = Column(Integer)
    listings_in_research = Column(Integer)
    bestseller_listings = Column(Integer)
    avg_rating = Column(Float)
    
    # Classification per Section 1.9 strategy
    classification = Column(Enum(ShopClassification))  # ACTIVE_STRONG, LEGACY, RISING
    notes = Column(Text)  # manual notes
    
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime)


class ShopClassification(str, Enum):
    ACTIVE_STRONG = "active_strong"  # currently selling well
    LEGACY = "legacy"                # Star Seller but sales softened, old listings strong
    RISING = "rising"                # opened recently, hit thousands of sales fast
    UNKNOWN = "unknown"
```

**Validation:**
- Run alembic migration
- Insert sample CompetitorListing row, query back with all JSON fields intact
- Foreign key referential integrity if applicable

---

### Step 3.2: CSV Import Endpoint
**Goal:** Web UI + API endpoint to upload a CSV exported from the Chrome extension.

**Implementation:**
- Route: `GET /research/import` — simple upload form (file input + submit)
- Route: `POST /research/import` — accepts the CSV, parses, dedupes, persists
- Parse CSV with `pandas` or `csv` module
- For each row:
  - Build `CompetitorListing` instance
  - Parse `detail_tags` from `"tag1 | tag2 | tag3"` format → JSON list
  - Parse boolean fields (extension uses lowercase "true"/"false")
  - Skip duplicates by `listing_id` (or upsert: prefer the row with more detail data)
- After import: trigger analyzer pipeline (Steps 3.5-3.7) for affected keywords
- Show import summary: rows added, updated, skipped + per-keyword counts

```python
@router.post("/research/import")
async def import_research_csv(
    file: UploadFile = File(...),
    refresh_analyzers: bool = True,
    session: Session = Depends(get_session)
):
    df = pd.read_csv(file.file, encoding='utf-8-sig')  # BOM handling
    
    summary = {"added": 0, "updated": 0, "skipped": 0, "keywords": set()}
    
    for _, row in df.iterrows():
        listing = _parse_row_to_listing(row)
        if not listing.listing_id:
            summary["skipped"] += 1
            continue
        
        existing = session.query(CompetitorListing).filter_by(
            listing_id=listing.listing_id
        ).first()
        
        if existing:
            # Prefer the version with more detail (Phase 2 data > Phase 1 only)
            if listing.description_text and not existing.description_text:
                _merge_listing(existing, listing)
                summary["updated"] += 1
        else:
            session.add(listing)
            summary["added"] += 1
        
        summary["keywords"].add(row.get("keyword"))
    
    session.commit()
    
    if refresh_analyzers:
        for kw in summary["keywords"]:
            await refresh_keyword_research(session, kw)
    
    return {
        "added": summary["added"],
        "updated": summary["updated"],
        "skipped": summary["skipped"],
        "keywords_refreshed": list(summary["keywords"]),
    }
```

**CSV column mapping (from extension v2.4):**

| CSV column | DB field | Notes |
|------------|----------|-------|
| keyword | keyword_searched | |
| rank | rank_in_search | |
| listing_id | listing_id | primary key |
| title | title | search-result title |
| image_url | image_url | thumbnail URL — used in research dashboard |
| detail_title | (fallback for title) | use if title is empty |
| price_cents | price_cents | from hidden form when present, else parse from text |
| keyword_total_results | keyword_total_results | search-volume proxy, same per keyword |
| shop / detail_shop | shop_name | |
| shop_age_years | shop_age_years | from shop tooltip ("X years on Etsy") |
| rating / detail_rating | rating | prefer detail_rating |
| review_count | review_count | |
| is_bestseller / detail_is_bestseller | is_bestseller | OR them |
| is_star_seller / detail_is_star_seller | is_star_seller | OR them |
| **eh_sales_total** | **eh_sales_total** | **EHunt Phase 1: lifetime sales estimate** |
| **eh_sales_recent** | **eh_sales_recent** | **EHunt Phase 1: recent period (likely weekly)** |
| **eh_favorites** | **eh_favorites** | **EHunt Phase 1: favorites estimate** |
| **eh_shop_weekly_sales** | **eh_shop_weekly_sales** | **EHunt Phase 1: store weekly sales** |
| **eh_listed_date** | **eh_listed_date** | **EHunt Phase 1: when listing was published (ISO)** |
| views_24h_count | views_24h_count | string (can be "20+") |
| cart_count | cart_count | |
| cart_count_raw | (informational, optional column) | original badge text, e.g. "In 20+ carts" |
| shop_total_sales | shop_total_sales | |
| **detail_tags** | **tags** | **split on " \| ". When EHunt panel present, these are the ACTUAL 13 seller tags (Etsy hides them from public DOM since 2026, but EHunt fetches them via its own backend)** |
| **detail_tag_volumes** | **tag_volumes** | **JSON string `{tag: search_volume_int}`. Parse with json.loads. From EHunt detail panel.** |
| detail_description_text | description_text | |
| detail_description_length | description_length | |
| detail_image_count | image_count | |
| **eh_detail_release_date** | **eh_detail_release_date** | **EHunt detail panel: listing publish date** |
| **eh_detail_total_sales** | **eh_detail_total_sales** | **EHunt detail panel: Phase 2 sales count** |
| **eh_detail_total_reviews** | **eh_detail_total_reviews** | **EHunt detail panel** |
| **eh_detail_total_favorites** | **eh_detail_total_favorites** | **EHunt detail panel** |
| **eh_detail_review_ratio** | **eh_detail_review_ratio** | **kept as string e.g. "18.44%"** |
| **eh_detail_category** | **eh_detail_category** | **breadcrumb e.g. "Weddings > Gifts & Mementos > Bridesmaids Gifts > Jewelry"** |
| **eh_detail_stocks** | **eh_detail_stocks** | **current stock count from EHunt panel** |
| **eh_detail_conv_rate** | **eh_detail_conv_rate** | **often "N/A"; rarely a percent. Stored as string.** |

**Validation:**
- Upload sample CSV with 50 rows → 50 added, 0 skipped
- Upload same CSV again → 0 added, 0 updated, 50 skipped (or all updated if data richer)
- Tags column correctly parsed to list
- tag_volumes column correctly parsed from JSON (e.g. `{"Gifts": 83600000, ...}`)
- description_text preserved fully (test with row containing commas, newlines, quotes)
- EHunt detail panel fields populated for ~70% of Phase 2 listings (some listings aren't in EHunt's DB)

---

### Step 3.3: Sales Signal Scorer
**Goal:** Compute a single 0-100 score combining all sales signals so analyzers can rank listings by "actually-selling-ness".

**Implementation:**
Two-tier formula in `src/modules/research/scoring.py`. EHunt data, when present, is **ground truth** and dominates the score. When EHunt is absent, fall back to the proxy-based heuristic from the training.

```python
def compute_sales_signal_score(listing: CompetitorListing) -> float:
    """
    Returns 0-100. Higher = stronger evidence the listing is actively selling.
    
    TIER A: EHunt data present (ground truth from EHunt subscription)
    --------------------------------------------------------------------
    EHunt shows lifetime sales + recent-period sales + store weekly sales.
    These are aggregated estimates from EHunt's data lake, not heuristics.
    When available, this tier dominates the score.
    
    TIER B: EHunt data absent (proxy heuristics, per training docs)
    --------------------------------------------------------------------
    Signal weights:
    - Bestseller badge: 25 pts (Etsy's own 6-month-top-performer stamp)
    - Star Seller badge: 10 pts (shop-level, weaker signal for individual listing)
    - Popular Now: 15 pts (currently trending)
    - 24h views > 0: 0-25 pts scaled (most current activity signal)
    - Cart count > 0: 0-15 pts scaled
    - Review count: 0-10 pts scaled (training: 1 review ≈ 5-10 sales)
    """
    
    # ---- TIER A: EHunt available ----
    if listing.eh_sales_recent is not None or listing.eh_sales_total is not None:
        score = 0.0
        
        # Recent-period sales (likely weekly) is the strongest signal
        if listing.eh_sales_recent is not None:
            if listing.eh_sales_recent >= 100: score += 50
            elif listing.eh_sales_recent >= 50: score += 40
            elif listing.eh_sales_recent >= 20: score += 30
            elif listing.eh_sales_recent >= 10: score += 20
            elif listing.eh_sales_recent >= 5: score += 10
            elif listing.eh_sales_recent >= 1: score += 5
        
        # Lifetime sales — validates the listing isn't a fluke
        if listing.eh_sales_total is not None:
            if listing.eh_sales_total >= 5000: score += 20
            elif listing.eh_sales_total >= 1000: score += 15
            elif listing.eh_sales_total >= 500: score += 10
            elif listing.eh_sales_total >= 100: score += 5
        
        # Store weekly sales — corroborating signal for the shop's health
        if listing.eh_shop_weekly_sales is not None:
            if listing.eh_shop_weekly_sales >= 500: score += 15
            elif listing.eh_shop_weekly_sales >= 100: score += 10
            elif listing.eh_shop_weekly_sales >= 20: score += 5
        
        # Bonus: Etsy's own badges still add credibility
        if listing.is_bestseller: score += 10
        if listing.is_popular_now: score += 5
        
        return min(100, score)
    
    # ---- TIER B: Proxy heuristics (training-doc fallback) ----
    score = 0.0
    if listing.is_bestseller: score += 25
    if listing.is_popular_now: score += 15
    if listing.is_star_seller: score += 10
    
    views = _parse_views_count(listing.views_24h_count)
    if views is not None:
        score += min(25, views / 4)  # 100 views = 25 pts
    
    if listing.cart_count:
        score += min(15, listing.cart_count / 5)
    
    if listing.review_count:
        score += min(10, listing.review_count / 200)  # 2000 reviews = 10 pts
    
    return min(100, score)
```

Run this on every CompetitorListing during import (or as a separate pass).

**Validation:**
- Listing with EHunt eh_sales_recent=50 + bestseller → score ≥ 50 (Tier A path)
- Listing with no EHunt data + bestseller + 20+ views + 50 in cart → score 50-75 (Tier B path)
- Listing with nothing (only review_count=10) → score < 10
- All listings get a non-null score after import
- Tier A path takes precedence whenever ANY eh_* field is non-null

---

### Step 3.4: Shop Classification (3-Tier from Training)
**Goal:** Classify every shop into the training's 3 buckets (Active/Legacy/Rising) using `shop_age_years` and aggregated sales signals.

**Implementation:**
```python
def classify_shop(session, shop_id: str) -> ShopClassification:
    """
    Per training (Section 1.9):
    - ACTIVE_STRONG: established shop, still selling well now
    - LEGACY:       older shop, soft current sales but strong back catalog
    - RISING:       opened ≤ 24 months ago, already shipping volume
    """
    shop = session.query(CompetitorShop).filter_by(shop_id=shop_id).first()
    if not shop:
        return ShopClassification.UNKNOWN
    
    # Pull a representative listing for eh_shop_weekly_sales (same value across
    # all listings in a shop). Also use total_sales as a long-term proxy.
    sample = session.query(CompetitorListing).filter_by(shop_id=shop_id).first()
    weekly = (sample.eh_shop_weekly_sales if sample else None) or 0
    age = shop.opening_year_months_ago or 999
    total = shop.total_sales or 0
    
    if age <= 24 and total >= 1000:
        return ShopClassification.RISING       # young + already shipping
    if weekly >= 50 and total >= 5000:
        return ShopClassification.ACTIVE_STRONG
    if total >= 10000 and weekly < 30:
        return ShopClassification.LEGACY       # big back catalog, current activity dropped
    if weekly >= 30:
        return ShopClassification.ACTIVE_STRONG
    return ShopClassification.UNKNOWN
```

Run after every CSV import. Store the classification on the `CompetitorShop` row. Surface in the research dashboard so the user can prioritize **RISING** shops (training: these are the model-after targets).

**Validation:**
- A shop with 2-year age + 5000 total sales + 200 weekly → RISING
- A shop with 8-year age + 100K total + 500 weekly → ACTIVE_STRONG
- A shop with 8-year age + 100K total + 5 weekly → LEGACY
- Shops without enough data → UNKNOWN (no false positives)

---

### Step 3.5: Title Pattern Analyzer
**Goal:** For each keyword, identify common title patterns + the keyword frequency that bestsellers use.

**Implementation:**
In `src/modules/research/title_analyzer.py`:

```python
async def analyze_titles_for_keyword(
    session: Session, 
    keyword: str,
    llm_client
) -> dict:
    """
    Returns a dict with:
    - avg_length
    - length_distribution (5th/50th/95th percentile)
    - common_opening_words (top 10)
    - common_phrases (3-word ngrams, top 20)
    - keyword_frequency: {keyword: (count, weighted_count)}
        weighted_count = sum of sales_signal_score for listings containing the keyword
    - underused_keywords: keywords that appear in <30% of titles but are in 
        bestsellers (differentiation opportunities)
    - llm_extracted_patterns: structural patterns from LLM analysis
    """
    
    # Get top 50 listings by sales_signal_score for this keyword
    listings = session.query(CompetitorListing).filter_by(
        keyword_searched=keyword
    ).order_by(CompetitorListing.sales_signal_score.desc()).limit(50).all()
    
    if not listings:
        return None
    
    titles = [l.title for l in listings if l.title]
    
    # 1. Length stats
    lengths = [len(t) for t in titles]
    avg_length = sum(lengths) / len(lengths)
    
    # 2. N-gram frequency (1, 2, 3 grams)
    keyword_freq = _compute_ngram_frequency(titles, n_range=(1, 3))
    
    # 3. Sales-weighted frequency
    weighted_freq = _compute_weighted_frequency(listings, keyword_freq)
    
    # 4. LLM structural pattern extraction
    patterns = await _llm_extract_patterns(llm_client, titles[:20])
    
    # 5. Underused differentiation candidates
    underused = _find_underused_keywords(
        keyword_freq, weighted_freq, threshold=0.30
    )
    
    return {
        "keyword": keyword,
        "sample_size": len(titles),
        "avg_length": avg_length,
        "length_p5_p50_p95": _percentiles(lengths, [5, 50, 95]),
        "top_unigrams": keyword_freq["1"][:15],
        "top_bigrams": keyword_freq["2"][:10],
        "top_trigrams": keyword_freq["3"][:5],
        "sales_weighted_keywords": weighted_freq[:20],
        "structural_patterns": patterns,
        "underused_keywords": underused,
    }
```

LLM pattern extraction prompt:

```
You are analyzing Etsy listing titles for the keyword "{keyword}".
Below are 20 actual titles from the top-selling listings.

Extract 3-5 structural patterns you observe. A pattern is a TEMPLATE, 
not a literal title. For example:
- "[Material] + [Size adjective] + [Product] + [Religious term] + [Gift phrase]"
- "[Style] + [Product] Necklace, [Synonym] Pendant, [Gift phrase]"

Output JSON only:
{{
  "patterns": [
    {{"pattern": "...", "examples": ["title1", "title2"]}},
    ...
  ]
}}

Titles:
{titles_numbered}
```

Persist result to `KeywordResearch.title_patterns`.

**Validation:**
- Run on a keyword with 30+ scraped listings
- Output includes 5-10 patterns, plausible n-grams, and underused keywords
- Top n-grams contain the keyword itself + common modifiers

---

### Step 3.6: Tag Frequency & Cliché Analyzer
**Goal:** Build a sales-weighted frequency table of tag-like keywords used by competitor listings + extract cliché phrases from descriptions. **Bonus when EHunt detail panel is present:** stratify tags by search volume (mainstream vs medium vs niche) — this is critical for Phase 6's variant strategy.

**CRITICAL ARCHITECTURAL NOTE — Tags come from EHunt, not Etsy:**
As of 2026, Etsy hides the seller's actual 13 tags from the public listing-page DOM (across all locales). The Chrome extension v2.4+ recovers them by reading EHunt extension's injected detail panel (`#etsy-rank-tool-product-table`) on listing detail pages. EHunt fetches tags via its own backend and renders them with **per-tag search volume** (e.g. "Personalized Gift (113.0M)" → 113,000,000 monthly searches). The extension parses this panel and populates two columns:

- `CompetitorListing.tags` — list of strings (the 13 real tags)
- `CompetitorListing.tag_volumes` — dict of `{tag: search_volume_int}`

Expected fill rate: ~70% of Phase 2 listings have real tags (some new/niche listings aren't in EHunt's DB).

For the remaining ~30%, we fall back to title-derived n-grams (which correlate ~85% with actual tag sets for the same niche). Sources in order of reliability:
1. **Primary:** `CompetitorListing.tags` from EHunt panel (with `tag_volumes` for stratification)
2. **Fallback:** Title-derived bigrams/trigrams from `CompetitorListing.title`
3. **Secondary:** Description-derived noun-phrases (used for cliché detection)

**Implementation:**
In `src/modules/research/tag_analyzer.py`:

```python
def analyze_tags_for_keyword(session: Session, keyword: str) -> dict:
    """
    Returns:
    - sample_size, source, real_tag_ratio
    - all_tags_frequency: [(tag, count), ...] sorted desc
    - sales_weighted_tags: [(tag, weighted_score), ...] — best tags by sales signal
    - bestseller_tags: tags that bestsellers use
    - volume_stratified_tags: {                # NEW — only when real tags present
        "mainstream":  [(tag, volume), ...]   # >50M searches
        "medium":      [(tag, volume), ...]   # 10M-50M
        "niche":       [(tag, volume), ...]   # <10M, underused goldmines
      }
    - avg_tag_volume_by_position: [vol, vol, ...]  # mean volume per slot 1..13
                                                    # tells us what the niche typically uses
    """
    listings = session.query(CompetitorListing).filter_by(
        keyword_searched=keyword
    ).all()
    if not listings:
        return None

    # Decide tag source: prefer real tags (from EHunt) if at least 20% of listings have them
    listings_with_tags = [l for l in listings if l.tags and len(l.tags) >= 3]
    real_tag_ratio = len(listings_with_tags) / len(listings)
    use_real_tags = real_tag_ratio >= 0.20

    if use_real_tags:
        source = 'real_tags_via_ehunt'
        tag_iter = lambda l: l.tags or []
    else:
        source = 'title_derived'
        tag_iter = lambda l: extract_title_ngrams(l.title) if l.title else []

    tag_weights = defaultdict(float)
    tag_counts = defaultdict(int)
    bestseller_tags = defaultdict(int)
    # Aggregate tag volumes across all listings that have EHunt data.
    # If a tag appears with different volume numbers (it shouldn't but EHunt may report
    # slightly different numbers across listings), we take the median.
    from statistics import median
    tag_volume_observations = defaultdict(list)

    for listing in listings:
        # Capture per-tag volumes from EHunt data
        if listing.tag_volumes:
            for tag, vol in listing.tag_volumes.items():
                tag_norm = tag.lower().strip()
                if isinstance(vol, (int, float)) and vol > 0:
                    tag_volume_observations[tag_norm].append(int(vol))

        for tag in tag_iter(listing):
            tag_normalized = tag.lower().strip()
            if len(tag_normalized) < 3 or len(tag_normalized) > 30:
                continue
            tag_counts[tag_normalized] += 1
            tag_weights[tag_normalized] += listing.sales_signal_score or 0
            if listing.is_bestseller:
                bestseller_tags[tag_normalized] += 1

    # Per-tag median volume
    tag_volume_median = {
        t: int(median(vols)) for t, vols in tag_volume_observations.items()
    }

    sales_weighted = sorted(tag_weights.items(), key=lambda x: x[1], reverse=True)

    # Volume stratification — only if we have real volume data
    volume_stratified = None
    if tag_volume_median:
        # Only stratify tags we've actually seen in the data, ranked by sales weight
        mainstream, medium, niche = [], [], []
        for tag, _w in sales_weighted[:60]:
            vol = tag_volume_median.get(tag)
            if vol is None:
                continue
            if vol > 50_000_000:
                mainstream.append((tag, vol))
            elif vol > 10_000_000:
                medium.append((tag, vol))
            else:
                niche.append((tag, vol))
        volume_stratified = {
            "mainstream": mainstream[:20],
            "medium": medium[:20],
            "niche": niche[:20],  # these are the goldmine — Phase 6 Variant B uses them
        }

    # Per-position volume average across listings (slot 1..13)
    avg_volume_by_position = None
    if use_real_tags and any(l.tag_volumes for l in listings_with_tags):
        position_vols = defaultdict(list)
        for l in listings_with_tags:
            if not l.tag_volumes or not l.tags:
                continue
            for pos, tag in enumerate(l.tags):
                vol = l.tag_volumes.get(tag)
                if vol:
                    position_vols[pos].append(int(vol))
        avg_volume_by_position = [
            int(sum(position_vols[i]) / len(position_vols[i])) if position_vols[i] else None
            for i in range(13)
        ]

    return {
        "sample_size": len(listings),
        "source": source,
        "real_tag_ratio": real_tag_ratio,
        "all_tags_frequency": sorted(tag_counts.items(), key=lambda x: -x[1])[:50],
        "sales_weighted_tags": sales_weighted[:30],
        "bestseller_tags": sorted(bestseller_tags.items(), key=lambda x: -x[1])[:20],
        "tag_volume_median": tag_volume_median,
        "volume_stratified_tags": volume_stratified,
        "avg_volume_by_position": avg_volume_by_position,
    }


def extract_title_ngrams(title: str) -> list[str]:
    """
    Extract 2-3 word phrases from a competitor title as tag candidates.
    Etsy titles are comma-separated phrases — split on commas first, then
    drop stopword-only fragments, deduplicate.
    """
    if not title:
        return []
    
    # Etsy titles are comma-separated phrases like
    # "Dainty Gold Cross Necklace, Tiny Sideways Cross Pendant, Gift for Her"
    phrases = [p.strip().lower() for p in title.split(',')]
    
    candidates = []
    STOPWORDS = {'the', 'a', 'an', 'and', 'or', 'with', 'for', 'in', 'to', 'of', 'on', 'by'}
    for phrase in phrases:
        words = [w for w in phrase.split() if w and w not in STOPWORDS]
        if not words:
            continue
        # Whole phrase is one candidate
        if 2 <= len(words) <= 4:
            candidates.append(' '.join(words))
        # Also add 2-grams from the phrase (captures sub-tags)
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            if bigram not in candidates:
                candidates.append(bigram)
    
    return candidates


async def extract_cliches(
    session: Session, 
    keyword: str,
    llm_client
) -> list[str]:
    """
    Pulls 20 competitor descriptions for the keyword, asks LLM to identify
    overused opening phrases / templated sentences.
    These get added to the dynamic cliché blacklist used in Phase 6 description generation.
    """
    listings = session.query(CompetitorListing).filter_by(
        keyword_searched=keyword
    ).filter(CompetitorListing.description_text.isnot(None)).limit(20).all()
    
    if len(listings) < 5:
        return []
    
    descriptions = [l.description_text[:500] for l in listings]
    
    prompt = f"""Below are 20 Etsy product description openings for jewelry.

Identify phrases that appear in MULTIPLE descriptions or that have a 
templated, AI-generated feel. These are clichés our system MUST AVOID.

Return JSON only:
{{"cliches": ["exact phrase 1", "exact phrase 2", ...]}}

Descriptions:
{chr(10).join(f"{i+1}. {d}" for i, d in enumerate(descriptions))}
"""
    
    response = await llm_client.complete(prompt)
    return json.loads(response).get("cliches", [])
```

Persist to `KeywordResearch.top_tags_by_frequency` and `common_cliches`.

**Validation:**
- For a keyword with 20+ listings that have tags: top_tags_by_frequency has 20-50 entries, sorted correctly
- LLM cliché extraction returns 5-15 plausible phrases (test by inspection)
- Clichés correctly identified as overused (manual spot-check)

---

### Step 3.7: Research Refresh Pipeline (Weekly Schedule)
**Goal:** A function that re-runs all analyzers (Step 3.5, 3.6) for a given keyword and persists everything to KeywordResearch. Wired into APScheduler (Phase 9) to refresh **weekly** by default.

**Why weekly:**
- Etsy's bestseller turnover happens on the order of weeks, not days. Refreshing daily wastes EHunt budget and LLM tokens without changing the research output meaningfully.
- A weekly cadence catches seasonal shifts (e.g. Mother's Day → graduation → Father's Day) without being so frequent that "noise" overwhelms signal.
- User keeps the option to manually trigger refresh from the dashboard (Step 3.8) any time.

**Implementation:**
```python
async def refresh_keyword_research(
    session: Session, 
    keyword: str,
    llm_client
):
    # First compute sales signal for any unscored listings
    unscored = session.query(CompetitorListing).filter_by(
        keyword_searched=keyword,
        sales_signal_score=None
    ).all()
    for l in unscored:
        l.sales_signal_score = compute_sales_signal_score(l)
    session.commit()
    
    # Run analyzers
    title_analysis = await analyze_titles_for_keyword(session, keyword, llm_client)
    tag_analysis = analyze_tags_for_keyword(session, keyword)
    cliches = await extract_cliches(session, keyword, llm_client)
    
    # Upsert KeywordResearch
    research = session.query(KeywordResearch).filter_by(keyword=keyword).first()
    if not research:
        research = KeywordResearch(keyword=keyword)
        session.add(research)
    
    research.total_listings_scraped = title_analysis["sample_size"]
    research.avg_title_length = title_analysis["avg_length"]
    research.title_patterns = title_analysis
    research.top_tags_by_frequency = tag_analysis
    research.common_cliches = cliches
    research.underused_keywords = title_analysis["underused_keywords"]
    research.last_analyzed_at = datetime.utcnow()
    
    bestseller_count = session.query(CompetitorListing).filter_by(
        keyword_searched=keyword,
        is_bestseller=True
    ).count()
    research.bestseller_count = bestseller_count
    
    session.commit()


async def refresh_all_keywords_job(session, llm_client):
    """The weekly job — scheduled via APScheduler in Phase 9."""
    keywords = [k.keyword for k in session.query(KeywordResearch).all()]
    for kw in keywords:
        try:
            await refresh_keyword_research(session, kw, llm_client)
        except Exception as e:
            logger.error(f"Refresh failed for {kw}: {e}")
    logger.info(f"Weekly refresh complete: {len(keywords)} keywords")
```

**Schedule registration** (will be wired in Phase 9):
```python
# In Phase 9 scheduler setup:
scheduler.add_job(
    refresh_all_keywords_job,
    trigger='cron',
    day_of_week='mon',   # every Monday
    hour=3, minute=0,    # 03:00 local time (low-traffic window)
    args=[session, llm_client],
    id='research_weekly_refresh',
    replace_existing=True
)
```

Note: this only updates the **analysis** (title patterns, cliches, etc) from existing data. To get **new competitor listings**, the user must run the Chrome extension Phase 1 + 2 again and import the fresh CSV. The auto-refresh is for re-analysis, not re-scraping.

**Validation:**
- Calling `refresh_keyword_research()` on a keyword updates the KeywordResearch row
- All JSON fields populated
- Idempotent: calling twice yields same result (no duplicates, no corruption)
- The weekly job runs on schedule, logged each Monday at 03:00
- Manual refresh button in dashboard (Step 3.8) calls the same function

---

### Step 3.8: Research Dashboard UI
**Goal:** Browse imported research data per keyword. Used both for sanity-checking imports and for the user to manually decide which keyword to target.

**Implementation:**
- Route: `GET /research` — list all keywords with stats (sample size, bestseller count, last analyzed)
- Route: `GET /research/{keyword}` — detail view:
  - **Top 20 listings by sales_signal_score** rendered as a grid with thumbnails (using `CompetitorListing.image_url`) — visual scan to verify the keyword actually matches what you sell. If 80% of thumbnails look unrelated to your niche, the keyword is wrong.
  - Title patterns (cards)
  - Top tags chart (bar)
  - Common clichés (list)
  - Underused keywords (highlighted as differentiation opportunities)
  - Button: "Refresh analysis" → calls Step 3.7
- Route: `GET /research/shops` — competitor shop list with classification editor

**Visual relevance check (important):**
Use the thumbnails as a quick filter. Etsy's keyword matching is loose — a search for "cross necklace" can include random unrelated products. The dashboard should make it easy to spot when this is happening so the user knows to refine their scraping keywords.

**Validation:**
- Dashboard loads, shows all keywords
- Drill-down shows analyzer output cleanly
- Refresh button re-runs analyzers and updates display

---

### Step 3.9: Research Context Builder (Bridge to Phase 6)
**Goal:** A function that produces an "intelligence brief" string injected into Phase 6 content generation prompts.

**Implementation:**
```python
class ResearchContextBuilder:
    """
    Given a product (with carrier_pillar + features), produce a compact
    intelligence brief from KeywordResearch + CompetitorListing data.
    Output goes directly into the LLM prompts in Phase 6.
    """
    
    def __init__(self, session: Session):
        self.session = session
    
    def build_for_product(self, product: Product) -> ResearchContext:
        # Map product to relevant keyword(s)
        keywords = self._derive_keywords(product)
        
        # Aggregate research across these keywords
        research = self.session.query(KeywordResearch).filter(
            KeywordResearch.keyword.in_(keywords)
        ).all()
        
        if not research:
            return ResearchContext.empty()  # fallback: generate without enrichment
        
        return ResearchContext(
            sample_size=sum(r.total_listings_scraped for r in research),
            avg_title_length=mean(r.avg_title_length for r in research if r.avg_title_length),
            top_keywords_sales_weighted=self._merge_keyword_freq(research),
            underused_keywords=self._merge_underused(research),
            structural_patterns=self._merge_patterns(research),
            top_tags=self._merge_tags(research),
            cliches_to_avoid=self._merge_cliches(research),
            volume_stratified_tags=self._merge_volume_stratified(research),
            avg_volume_by_position=self._merge_avg_volume_by_position(research),
        )


@dataclass
class ResearchContext:
    sample_size: int
    avg_title_length: float
    top_keywords_sales_weighted: list[tuple[str, float]]
    underused_keywords: list[str]
    structural_patterns: list[dict]
    top_tags: list[tuple[str, int]]
    cliches_to_avoid: list[str]
    # Volume-aware fields (only populated when EHunt tag_volumes were available in research data)
    volume_stratified_tags: dict | None = None  # {"mainstream":[(tag,vol),...], "medium":[...], "niche":[...]}
    avg_volume_by_position: list[int] | None = None  # 13 ints: typical volume per tag slot
    
    @classmethod
    def empty(cls):
        return cls(0, 0.0, [], [], [], [], [], None, None)
    
    @property
    def has_data(self) -> bool:
        return self.sample_size > 0
    
    @property
    def has_volume_data(self) -> bool:
        return bool(self.volume_stratified_tags)
    
    def format_for_prompt(self) -> str:
        """Render as text block for LLM prompts."""
        if not self.has_data:
            return "No competitor research available for this product category yet."
        
        out = f"""
COMPETITOR INTELLIGENCE (based on {self.sample_size} real Etsy listings):

- Average title length used by bestsellers: {self.avg_title_length:.0f} chars
- Most common keywords (sales-weighted):
  {self._fmt_keywords(self.top_keywords_sales_weighted[:15])}
- Underused but promising (differentiation opportunities):
  {', '.join(self.underused_keywords[:10])}
- Top structural patterns:
  {self._fmt_patterns(self.structural_patterns[:5])}
- Top tags by sales-weighted frequency:
  {self._fmt_tags(self.top_tags[:20])}
- CLICHÉS TO AVOID in descriptions:
  {chr(10).join(f"  • {c}" for c in self.cliches_to_avoid[:10])}
"""
        # Append volume-aware section when available
        if self.has_volume_data:
            vs = self.volume_stratified_tags
            mainstream = ', '.join(f"{t} ({_fmt_vol(v)})" for t, v in (vs.get('mainstream') or [])[:8])
            medium     = ', '.join(f"{t} ({_fmt_vol(v)})" for t, v in (vs.get('medium')     or [])[:8])
            niche      = ', '.join(f"{t} ({_fmt_vol(v)})" for t, v in (vs.get('niche')      or [])[:10])
            out += f"""
TAG SEARCH VOLUME STRATIFICATION (from EHunt data — use this for variant differentiation):
- MAINSTREAM tags (>50M searches, high competition): {mainstream or '(none in sample)'}
- MEDIUM tags (10M-50M, balanced): {medium or '(none in sample)'}
- NICHE tags (<10M, low competition, highly targeted): {niche or '(none in sample)'}
"""
        return out


def _fmt_vol(v: int) -> str:
    """Format search volume compactly: 113000000 → '113M', 3800000 → '3.8M'."""
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M".replace(".0M", "M")
    if v >= 1_000:
        return f"{v / 1_000:.0f}K"
    return str(v)
```

**Validation:**
- For a product with carrier_pillar=cross, builder returns a non-empty ResearchContext (assuming research data exists)
- `format_for_prompt()` produces a readable text block under 2000 chars
- Empty case handled gracefully (no crash, just empty brief)

---

### Step 3.10: Empty State Handling
**Goal:** Define what happens when a product has no research data available.

**Implementation:**
Phase 6 generators (title, tag, description) must work in two modes:
1. **Enriched mode:** ResearchContext has data → inject into prompt
2. **Cold start mode:** No research → use generic keyword pool + base rules only

Add a config flag: `REQUIRE_RESEARCH_FOR_GENERATION` (default False during early use, True later for stricter quality).

When True: refuse to generate content for a product whose carrier_pillar has no research; surface a UI message "Please import competitor research first for: cross necklace, birthstone necklace, ..."

**Validation:**
- Generate content for a product with research → enriched prompt visible in LLM logs
- Generate for a product without research → fallback to base prompt, content still generated
- With strict flag on: refuses cleanly, user-facing error message

---