# Business Rules (Section 1 of Full Spec)

These are the hard rules. Every output the system produces MUST comply. Validators throw on violation.

---

# 🚫 SECTION 1: STRICT BUSINESS RULES (NEVER VIOLATE)

These rules come from the Etsy training documents and are **non-negotiable**. Every output the system produces must comply.

## 1.1 Title Rules (HARDCODED VALIDATORS REQUIRED)
- Length: **EXACTLY 137-140 characters**
- First 60 characters: niche product description only (no "Gift for Mom" style big terms)
- **NEVER** use word "Stone" → use "CZ" or "Pave" instead
- **NEVER** use "Pendant" alone → always "Pendant Necklace"
- **NEVER** combine "Solid Gold" and "Gold Plated" in same title
- **NEVER** repeat the same word twice
- Use 2-3 synonyms for the main product
- Only 1-2 big-search terms at the end (e.g. "Gifts for Mom")
- Comma + space separator between phrases (NEVER pipe `|`)
- First letter of each word capitalized
- "Mother's Day Gift" → use "Gifts for Mom" instead
- "Animal" for sea creatures → use "Sea Animal" or "Ocean"
- "Floral" only for visual flowers (not script/letter flowers)
- "Diamond" → don't use for brass/plated products
- "Twisted" means twisted/burgulu (not dönen)
- For real silver products: include "925 Sterling Silver"
- For gold plated (brass-based): do NOT include karat
- 22K products: don't mention karat at all

## 1.2 Tag Rules
- **EXACTLY 13 tags**
- Distribution:
  - 8-9 niche/specific tags (long-tail)
  - 2-3 medium tags (Pendant Necklace, Minimalist Necklace, Everyday Necklace)
  - 1-2 big tags only (e.g. "Gifts for Mom")
- Max 20 characters per tag
- Don't repeat keywords already in title (waste of tag slot)
- Comma + space separator
- First letter of each word capitalized
- **NEVER** "Mother's Day Gift" → use "Gifts for Mom"

## 1.3 Description Rules
- 150-220 words
- **CRITICAL:** Each description must be UNIQUE. AI templated outputs get rejected by Etsy.
- Originality target: 96%+ vs existing descriptions in DB
- Must contain organically (not as a list):
  - Product description (1 sentence)
  - Material/stone details (2 sentences)
  - Gift positioning (1 sentence)
  - Size/weight (1 sentence)
  - Shipping note (1 sentence)
- Include 2-3 store-internal links (to similar products / collections)
- Forbidden cliché phrases:
  - "Discover the beauty of..."
  - "Elevate your style..."
  - "Perfect for any occasion"
  - "Add a touch of elegance"

## 1.4 Images Rules
- Minimum 8 images per listing (test showed 6 caused view drop)
- Image order strategy:
  - Image 1: Main product (mannequin or close-up)
  - Images 2-3: Variations/colors
  - Images 4-5: Trust shots (size chart, material detail)
  - Images 6-7: Lifestyle/gift-focused
  - Image 8: Box
  - Image 9: Variation chart (if applicable)
- Each image has SEO-friendly file name: `gold-plated-cross-necklace-1.jpg` (NOT `IMG_1234.jpg`)
- Each image has alt text:
  - Image 1: Main keyword phrase
  - Images 2-3: Variation + category
  - Images 4-7: Trust + materials
  - Images 5-6-7: Gift-focused
- All images 2000x2000 px minimum

## 1.5 Listing Attributes (NEVER LEAVE EMPTY)
Every Etsy listing must fill:
- Material (Gold Plated / Brass / Sterling Silver)
- Karat (for silver only)
- Has Stone? + details (Baguette Cut Garnet)
- Shape (Letter, Heart, Animal, Flower, Disk)
- Second Color (if applicable)
- Style (Minimalist, Gothic, Art Deco, Boho)
- Occasion (Mother's Day, Christmas, Valentine's, Graduation, 4th of July, Baptism, Confirmation, Easter)
- Recipient (Her, Him, Mom, Wife, Daughter)
- Personalization (Custom / Personalized)

## 1.6 Quantity Strategy
- For confident bestsellers → 999 (signals "I'm a producer")
- For test products → 10 initially, then raise to 300 after 2 sales (Etsy aktivlik sinyali)
- Never let it drop to 0

## 1.7 Section Strategy
- Etsy allows 20 sections per shop → use all 20
- Section names should be specific: "Cross Necklace", "Birthstone Necklace", "Birth Flower Necklace", "Family Necklace", "Pet Necklace", "Mother's Day Gifts", "Christmas Gifts", etc.

## 1.8 Renew Strategy
- 4 renews per day at Turkey time: **17:00, 21:00, 02:00, 05:00**
- Only renew:
  - Top selling products
  - Newly listed products with high confidence
- Never renew underperforming middle products

## 1.9 Carrier Pillars (Mağaza Strategy)
Every store needs 5-6 strong categories. Each product must belong to one:
1. Cross Necklace
2. Name Necklace
3. Birthstone Necklace
4. Birth Flower Necklace
5. Pet Necklace
6. Pendant Necklace (general)

## 1.10 AI-Generated Content Warning ⚠️
- **NEVER** publish raw AI output (especially descriptions)
- Etsy detects template-pattern AI text and rejects it
- Always require human approval gate before Etsy upload
- Originality validator must run before approval is allowed

## 1.11 Image Generation Hybrid Rule
For Etsy AI image policy compliance:
- **At least 3 images per listing** must be real Reksven photos (close-up, size, box)
- 5-6 images can be AI lifestyle (real jewelry + AI scene)
- This balance keeps Etsy compliance + AI scale

## 1.12 Forbidden Keywords (Auto-Reject)
| Forbidden | Use Instead |
|-----------|-------------|
| Stone | CZ or Pave |
| Diamond (in plated) | (don't use) |
| Mother's Day Gift | Gifts for Mom |
| Pendant (alone) | Pendant Necklace |
| Pave (misspelling "Pawe") | Pave (P-A-V-E) |
| Twisted (as "dönen") | Twist Chain |

---