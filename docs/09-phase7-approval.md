# Phase 7

From the Full Spec. Implement in order. Each step ends with a validation block.

---

## PHASE 7: HUMAN APPROVAL UI

### Step 7.1: Approval Queue View
**Goal:** Show all products awaiting approval.

**Implementation:**
- Route: `GET /approval`
- Lists products with status `AWAITING_APPROVAL`
- Shows: SKU, carrier pillar, image count, generated time

**Validation:**
- All AWAITING_APPROVAL products listed
- Sortable by creation time

---

### Step 7.2: Variant Comparison & Approval View
**Goal:** Show all 3 generated variants side-by-side for visual comparison, let user pick one (or hybrid-edit), then approve.

**Implementation:**
- Route: `GET /approval/{sku}`
- 3-column responsive grid (collapses to vertical on narrow screens). Each column shows one variant:

```
┌─────────────────────┬─────────────────────┬─────────────────────┐
│ VARIANT A           │ VARIANT B           │ VARIANT C           │
│ Conservative niche  │ Differentiated      │ Gift-focused        │
│ ⊙ Pick this         │ ⊙ Pick this         │ ⊙ Pick this         │
│ CTR signal: HIGH    │ CTR signal: MEDIUM  │ CTR signal: HIGH    │
│                     │                     │                     │
│ TITLE (138 chars):  │ TITLE (139 chars):  │ TITLE (137 chars):  │
│ "Dainty Gold        │ "Confirmation       │ "Cross Necklace     │
│  Cross Necklace,    │  Cross Necklace,    │  Gift for Daughter, │
│  Tiny Sideways..."  │  Everyday..."        │  Faith Necklace..." │
│                     │                     │                     │
│ TAGS (13):          │ TAGS (13):          │ TAGS (13):          │
│ • cross necklace    │ • cross necklace    │ • cross necklace    │
│ • dainty necklace   │ • confirmation gift │ • gift for daughter │
│ • gift for her      │ • everyday wear     │ • mothers day gift  │
│ ...                 │ ...                 │ ...                 │
│                     │                     │                     │
│ DESCRIPTION         │ DESCRIPTION         │ DESCRIPTION         │
│ (187 words)         │ (203 words)         │ (195 words)         │
│ "Discover the       │ "Quiet faith every  │ "She'll smile from  │
│  timeless beauty    │  morning. This..."  │  the moment she..." │
│  of..."             │                     │                     │
│ [Edit inline]       │ [Edit inline]       │ [Edit inline]       │
│                     │                     │                     │
│ STRATEGY RATIONALE: │ STRATEGY RATIONALE: │ STRATEGY RATIONALE: │
│ Closest to bestsel- │ Uses 3 underused    │ Leads with gift     │
│ ler patterns. Safe  │ keywords. Stands    │ moment for daughter │
│ SEO bet.            │ out from competitors│ recipient.          │
└─────────────────────┴─────────────────────┴─────────────────────┘

[Below all 3 columns:]
SHARED FIELDS (apply to whichever variant you pick):
- 9 product images (one set, used across all variants)
- Section assignment: [Cross Necklaces ▼]
- Price: $32.99
- Quantity: 999

[Actions]
- "Approve selected variant" — uses the picked variant
- "Save as draft" — keep all 3 for later
- "Reject all & regenerate" — sends back to Step 6.7
- "Hybrid edit" — opens an editor pre-filled with picked variant, user can swap in
                 fields from other variants (e.g. "take title from A, description from B")
```

**Hybrid edit flow:**
- User clicks "Hybrid edit" → opens single-column editor
- Pre-filled with whichever variant was selected
- Sidebar shows the other 2 variants' fields with "← Use this" buttons
- Click "← Use this" next to Variant B's description → replaces description in current editor
- All edits go through validators in real-time
- Save → creates a `ListingVariant` with `variant_id="HYBRID"`, source angles logged

**Database flow:**
- All 3 variants saved to DB on generation (`listing_variants` table, FK to product)
- Selected variant marked `is_selected=True`
- Other 2 remain available for analytics: "user picks Conservative 60% of the time, Differentiated 30%, Gift 10%"

**Validation:**
- All 3 variants render with distinct titles/tags/descriptions
- Radio button selection updates which variant gets the "selected" highlight
- Inline edits update DB on blur (auto-save)
- Hybrid edit successfully composes mixed-field variant
- After approval, only the selected variant proceeds to Phase 8 (Etsy upload)

---

### Step 7.3: Edit/Override Capability
**Goal:** Let user override any AI-generated field.

**Implementation:**
- All form fields editable
- On save: re-run validators
- Display violations inline before final approve
- User can override violations with explicit confirmation (last resort)

**Validation:**
- User can type custom title → validator runs → shows errors if any
- User can override validator with checkbox: "I know this breaks rules, proceed anyway"
- Override logged in audit table

---