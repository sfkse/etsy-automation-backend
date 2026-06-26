# Phase 8

From the Full Spec. Implement in order. Each step ends with a validation block.

---

## PHASE 8: ETSY API INTEGRATION

### Step 8.1: OAuth 2.0 Setup
**Goal:** Get Etsy API access token for user's shop.

**Implementation:**
- Route: `GET /admin/etsy/connect` — initiates OAuth flow
- Use PKCE flow
- Save token in encrypted local file `./data/etsy_token.json`
- Auto-refresh when expired

**Validation:**
- User clicks Connect → redirected to Etsy → grants permission → returns
- Token saved successfully
- Refresh works after expiry

---

### Step 8.2: Rate-Limited Etsy Client
**Goal:** Etsy API client with built-in rate limiting (10/sec, 10k/day).

**Implementation:**
```python
class EtsyClient:
    BASE_URL = "https://openapi.etsy.com/v3"
    
    def __init__(self, token_manager, shop_id):
        self.token_manager = token_manager
        self.shop_id = shop_id
        self.rate_limiter = TokenBucket(capacity=10, refill_rate=10)
    
    async def request(self, method, endpoint, **kwargs):
        await self.rate_limiter.acquire()
        
        token = await self.token_manager.get_valid_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "x-api-key": settings.ETSY_API_KEY
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method, f"{self.BASE_URL}{endpoint}",
                headers=headers, **kwargs
            )
            
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                logger.warning(f"Rate limited, waiting {retry_after}s")
                await asyncio.sleep(retry_after)
                return await self.request(method, endpoint, **kwargs)
            
            response.raise_for_status()
            return response.json()
```

**Validation:**
- 10 rapid requests succeed within rate limit
- 11th request waits, not fails
- 429 triggers backoff

---

### Step 8.3: Listing Creation
**Goal:** Create listing on Etsy.

**Implementation:**
```python
async def create_listing(self, product: Product) -> str:
    """Returns Etsy listing_id"""
    
    payload = {
        "quantity": product.quantity or 999,  # Section 1.6
        "title": product.final_title,
        "description": product.final_description,
        "price": float(product.selling_price),
        "who_made": "i_did",
        "when_made": "made_to_order",
        "taxonomy_id": JEWELRY_NECKLACE_TAXONOMY_ID,
        "shipping_profile_id": settings.SHIPPING_PROFILE_ID,
        "return_policy_id": settings.RETURN_POLICY_ID,
        "tags": product.final_tags,
        "is_personalizable": product.is_personalized,
        "personalization_is_required": False,
        "state": "draft",  # don't go live until images uploaded
    }
    
    response = await self.request(
        "POST",
        f"/application/shops/{self.shop_id}/listings",
        json=payload
    )
    
    return response['listing_id']
```

**Validation:**
- Create test listing in draft mode
- All fields populated correctly
- Returns listing_id

---

### Step 8.4: Image Upload
**Goal:** Upload all 8-9 images to listing.

**Implementation:**
```python
async def upload_images(self, listing_id: str, images: list[ProductImage]):
    for image in sorted(images, key=lambda x: x.rank):
        with open(image.file_path, 'rb') as f:
            files = {'image': f}
            data = {
                'rank': image.rank,
                'alt_text': image.alt_text
            }
            
            await self.request(
                "POST",
                f"/application/shops/{self.shop_id}/listings/{listing_id}/images",
                files=files, data=data
            )
        
        # Human-like pacing (Section: avoid spam detection)
        await asyncio.sleep(random.uniform(1, 3))
```

**Validation:**
- All images uploaded in correct order
- Alt text set
- No rate limit hit

---

### Step 8.5: Attributes & Inventory
**Goal:** Set all attributes from Section 1.5.

**Implementation:**
- Fetch taxonomy attributes for jewelry necklace
- Map product fields to Etsy attribute IDs
- Set via API
- Set inventory (quantity, price) per variation if applicable

**Validation:**
- All 9 attribute categories filled (Section 1.5)
- Inventory shows correct quantity

---

### Step 8.6: Section Assignment
**Goal:** Assign listing to correct shop section.

**Implementation:**
- Map carrier_pillar → section_id
- API call to set section

**Validation:**
- Listing appears in correct section in Etsy shop view

---

### Step 8.7: Publish (Activate Listing)
**Goal:** Move from draft to active.

**Implementation:**
- After all images + attributes set, PATCH listing state to "active"
- Update product status to PUBLISHED in DB
- Save etsy_listing_id

**Validation:**
- Listing becomes live on Etsy
- All fields visible publicly

---

### Step 8.8: Bulk Upload with Pacing
**Goal:** Upload multiple approved products with human-like timing.

**Implementation:**
```python
async def bulk_publish(approved_skus: list[str]):
    is_new_shop = check_if_new_shop()  # < 6 months old
    max_per_day = 15 if is_new_shop else 50  # Spam prevention
    
    today_count = await get_today_publish_count()
    remaining_today = max_per_day - today_count
    
    to_publish = approved_skus[:remaining_today]
    
    for i, sku in enumerate(to_publish):
        product = await get_product(sku)
        listing_id = await create_listing(product)
        await upload_images(listing_id, product.images)
        await set_attributes(listing_id, product)
        await assign_section(listing_id, product)
        await activate_listing(listing_id)
        
        await update_status(sku, ProductStatus.PUBLISHED)
        
        # Human-like wait between products
        wait_time = random.uniform(30, 90)
        logger.info(f"Published {sku} ({i+1}/{len(to_publish)}). Waiting {wait_time:.0f}s")
        await asyncio.sleep(wait_time)
```

**Validation:**
- New shop limited to 15/day
- Old shop allowed 50/day
- 30-90 sec between listings
- Stops when daily limit reached

---