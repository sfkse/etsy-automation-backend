# Phase 11

From the Full Spec. Implement in order. Each step ends with a validation block.

---

## PHASE 11: TESTING & FINAL VALIDATION

### Step 11.1: Business Rule Tests
**Goal:** Comprehensive test of all validators.

**Implementation:**
- For each rule in Section 1, write at least 2 tests (passing + failing)
- Use pytest
- Include in CI workflow (if added later)

**Validation:**
- All tests pass
- Coverage of business rules > 90%

---

### Step 11.2: Integration Test (Full Pipeline)
**Goal:** End-to-end test with sample product.

**Implementation:**
- Test scenario:
  1. Create product manually
  2. Run image generation (use mock or test API)
  3. Run content generation
  4. Approve via UI
  5. Upload to Etsy test mode
  6. Verify Etsy listing exists with correct data

**Validation:**
- Full pipeline completes
- Final Etsy listing matches expectations
- All business rules respected throughout

---