# Phase 9

From the Full Spec. Implement in order. Each step ends with a validation block.

---

## PHASE 9: TRACKING & SCHEDULING (Initial)

### Step 9.1: Stats Sync Job
**Goal:** Daily fetch of listing stats from Etsy.

**Implementation:**
- APScheduler job runs daily at 6:00 AM TR time
- For each published product: fetch stats from Etsy
- Insert into `product_stats` table

**Validation:**
- Stats fetched for all live products
- Stored with date

---

### Step 9.2: Renew Scheduler
**Goal:** Auto-renew top performers at Section 1.8 hours.

**Implementation:**
- APScheduler jobs at TR 17:00, 21:00, 02:00, 05:00
- Query top-performing products (recent sales, high views)
- For each (configurable limit): call Etsy renew API
- Log each renew

**Validation:**
- Jobs fire at correct times
- Only top performers renewed
- Renew API call succeeds

---

### Step 9.3: Performance Dashboard
**Goal:** Local web view of all products and metrics.

**Implementation:**
- Route: `GET /dashboard`
- Show:
  - Total products by status
  - Today's views/sales
  - Top performers (last 7 days)
  - Underperformers (0 views in 7 days) — candidate for tag update
  - Renew schedule status

**Validation:**
- Dashboard loads with all key metrics
- Updates in real-time (poll or websocket optional)

---