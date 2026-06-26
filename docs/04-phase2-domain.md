# Phase 2

From the Full Spec. Implement in order. Each step ends with a validation block.

---

## PHASE 2: DOMAIN MODELS & VALIDATORS

### Step 2.1: Carrier Pillar Domain
**Goal:** Strict enum + helper functions.

**Implementation:**
- `CarrierPillar` enum with 6 values
- Function `get_section_name(pillar) -> str` returns Etsy section name
- Function `get_default_attributes(pillar) -> dict` returns common attrs

**Validation:**
- Each pillar maps to a section name
- Unit test covers all 6 pillars

---

### Step 2.2: Title Validator
**Goal:** Hardcoded function that validates a title against ALL Section 1.1 rules.

**Implementation:**
```python
def validate_title(title: str) -> tuple[bool, list[str]]:
    """
    Returns (is_valid, list_of_violations).
    Violations are human-readable error messages.
    """
    violations = []
    
    # 1. Length
    if not (137 <= len(title) <= 140):
        violations.append(f"Length {len(title)} not in [137, 140]")
    
    # 2. Stone keyword
    if "stone" in title.lower():
        violations.append("'Stone' keyword forbidden, use 'CZ' or 'Pave'")
    
    # 3. Pendant alone
    if re.search(r"\bPendant\b(?!\s+Necklace)", title):
        violations.append("'Pendant' alone not allowed, use 'Pendant Necklace'")
    
    # 4. Solid Gold + Gold Plated
    if "solid gold" in title.lower() and "gold plated" in title.lower():
        violations.append("'Solid Gold' and 'Gold Plated' cannot coexist")
    
    # 5. Repeated words (excluding common words)
    common = {"and", "for", "the", "with", "a", "an", "of", "in", "to"}
    words = [w.lower() for w in title.split() if w.lower() not in common]
    if len(words) != len(set(words)):
        duplicates = [w for w in words if words.count(w) > 1]
        violations.append(f"Repeated words: {set(duplicates)}")
    
    # 6. Mother's Day Gift
    if "mother's day gift" in title.lower():
        violations.append("Use 'Gifts for Mom' instead of 'Mother's Day Gift'")
    
    # 7. Capitalize first letter check (informational warning)
    # ... more rules as needed
    
    return (len(violations) == 0, violations)
```

**Validation:**
- Unit tests for each rule (both passing and failing cases)
- All 7 rules tested
- Edge cases: exact 137, exact 140, exact 136 (fail), exact 141 (fail)

---

### Step 2.3: Tag Validator
**Goal:** Validate 13-tag list against Section 1.2.

**Implementation:**
```python
def validate_tags(tags: list[str], title: str = "") -> tuple[bool, list[str]]:
    violations = []
    
    # Count
    if len(tags) != 13:
        violations.append(f"Tag count {len(tags)} != 13")
    
    # Length
    for tag in tags:
        if len(tag) > 20:
            violations.append(f"Tag '{tag}' exceeds 20 chars")
    
    # Forbidden phrases
    for tag in tags:
        if "mother's day gift" in tag.lower():
            violations.append(f"Tag '{tag}': use 'Gifts for Mom'")
    
    # Repeated tags
    if len(tags) != len(set(t.lower() for t in tags)):
        violations.append("Duplicate tags detected")
    
    # Duplicate with title (warning, not error)
    if title:
        title_words = set(title.lower().split())
        for tag in tags:
            if tag.lower() in title_words:
                violations.append(f"Tag '{tag}' already in title (wasted slot)")
    
    return (len(violations) == 0, violations)
```

**Validation:**
- Tests for count, length, forbidden phrases, duplicates

---

### Step 2.4: Description Originality Checker
**Goal:** Check new description doesn't match existing ones.

**Implementation:**
- Use `sentence-transformers` (model: `all-MiniLM-L6-v2`)
- Compute embedding of new description
- Compare against all existing descriptions in DB
- Return max similarity score
- Threshold: 0.85 means too similar → reject

```python
class OriginalityChecker:
    def __init__(self, session):
        self.session = session
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
    
    def check(self, new_description: str, threshold: float = 0.85) -> tuple[bool, float]:
        new_emb = self.model.encode(new_description)
        
        existing = self.session.query(Product.final_description).filter(
            Product.final_description.isnot(None)
        ).all()
        
        if not existing:
            return (True, 0.0)
        
        existing_embs = self.model.encode([d[0] for d in existing])
        similarities = cosine_similarity([new_emb], existing_embs)[0]
        
        max_sim = float(similarities.max())
        is_original = max_sim < threshold
        
        return (is_original, max_sim)
    
    def check_cliches(self, description: str) -> list[str]:
        """Check for forbidden cliché phrases."""
        found = []
        for cliche in CLICHE_DESCRIPTION_PHRASES:
            if cliche.lower() in description.lower():
                found.append(cliche)
        return found
```

**Validation:**
- Insert 3 sample descriptions, check 4th against them
- Test cliché detection

---