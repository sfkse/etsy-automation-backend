# Phase 10

From the Full Spec. Implement in order. Each step ends with a validation block.

---

## PHASE 10: GOOGLE SHEETS SYNC (Optional, Later)

### Step 10.1: Sheets Integration
**Goal:** Mirror PostgreSQL DB to Google Sheets for visibility.

**Implementation:**
- Use google-api-python-client
- On product status change → upsert row in Sheets
- Sheet columns match DB columns
- Conflict resolution: DB is source of truth

**Validation:**
- New product → row added to Sheets
- Update status → Sheets row updated
- Manual edit in Sheets → reflected in DB on next sync

---