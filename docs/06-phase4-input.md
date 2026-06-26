# Phase 4

From the Full Spec. Implement in order. Each step ends with a validation block.

---

## PHASE 4: MANUAL INPUT MODULE

### Step 4.1: Manual Input Form (Web UI)
**Goal:** Web form for entering product manually.

**Implementation:**
- Route: `GET /products/new` and `POST /products/new`
- Form fields:
  - Carrier Pillar (dropdown: 6 pillars)
  - Material (Gold Plated / Brass / 925 Sterling Silver)
  - Color
  - Has stone? + stone type (CZ Baguette etc.)
  - Shape (dropdown)
  - Style (dropdown)
  - Occasion (multi-select)
  - Recipient (dropdown)
  - Size info (text)
  - Cost (decimal)
  - Selling price (decimal)
  - **Image upload:** at least 1 real product image (from Reksven)
  - Optional: additional reference images
- Submit → creates Product with status MANUAL_INPUT
- Auto-generates SKU: `TAKI-{next_number:04d}`

**Validation:**
- Form renders correctly
- File upload saves to `./data/images/{SKU}/originals/`
- Product is created in DB with all fields
- SKU auto-increments

---

### Step 4.2: Product List & Detail Views
**Goal:** See all products, click into one.

**Implementation:**
- Route: `GET /products` — list all products with status badges
- Route: `GET /products/{sku}` — detail view
  - Show: all fields, all images, status, generated content (if any)
  - Action buttons (status-dependent):
    - **"Process Product"** (if MANUAL_INPUT) — triggers the full async pipeline (Stage 1→2→3 from Section 2)
    - **"View Progress"** (if IMAGE_PROCESSING or CONTENT_GENERATING) — polls status endpoint, shows progress
    - **"Review & Approve"** (if AWAITING_APPROVAL) — opens approval interface
    - **"View Live Listing"** (if PUBLISHED) — opens Etsy listing in new tab
    - **"Retry"** (if FAILED) — re-runs pipeline from last successful stage
  - Workflow selector dropdown next to "Process Product" (default: from settings)

**Validation:**
- List shows all products, sortable
- Detail page shows everything correctly
- "Process Product" button triggers pipeline + redirects to progress view
- Progress view auto-refreshes via polling, then redirects to approval when ready

---