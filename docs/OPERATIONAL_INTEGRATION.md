# OPERATIONAL INTEGRATION — Shop Settings + Listing Builder
## Etsy Research Extension v2.5 + Backend Patch — Harmonizing SEO Depth with UI Workflow

> **Why this document exists:** Two training bodies inform the system. The SEO-depth training (Title 137-140 chars, 13-tag distribution, originality, alt text, etc.) is already encoded in Phase 1, 3, 6, and 7. The new operational training (Production Partner setup, description scaffolds, variation UI, default attributes, renewal options, return policy, draft templates) covers Etsy form mechanics that no current Phase handles. This document specifies how to fold the operational training into the existing system **without breaking SEO depth** and **without forcing the user to re-enter the same operational details on every product**.
>
> **Design principle:** **One-time configuration > Per-product configuration.** Anything that doesn't change per product — production partner, description scaffold, default attributes, variation skeleton, pricing strategy, return/renewal policy — lives in `ShopSettings` and is merged into every listing automatically. Per-product input is reduced to truly product-specific data (carrier pillar, stone shape, personalization type, override price).
>
> **Compatibility:** All existing Phases stay intact. This module wraps Phase 4 (Manual Input), Phase 6 (Content Pipeline), and Phase 8 (Etsy API). Old `/products/new` route keeps working unchanged; a new `/listings/build` route adds the streamlined flow. Users can pick either.
>
> **Prerequisites:** Phases 0-8 of `AI_Coding_Agent_Prompt.md` implemented. Phase 4 (Sourcing Intelligence) from `PHASE_4_Sourcing_Intelligence.md` either in place or planned (Listing Builder calls it when present, falls back to manual keyword input when absent).

---

## SECTION A: ARCHITECTURAL OVERVIEW

### Current state (recap)

```
Manual Input (Phase 4)
   │   user enters: pillar, material, stone, shape, style,
   │   occasion, recipient, size, cost, price, image
   ▼
"Process Product"
   │
   ├──► AI Image Pipeline (Phase 5)        → 5-6 AI images
   └──► Content Pipeline (Phase 6)         → 3 ListingVariants (title+tags+description each)
                                              ▼
                                       Approval UI (Phase 7)
                                              ▼
                                    Etsy API Upload (Phase 8)
```

**Gap:** Phase 8 has nothing to say about Production Partner ID, variation matrix, renewal options, return policy, featured listing flag, default attribute values, or personalization scaffolds. Today the user fills these manually in Etsy's web form after upload — which defeats the purpose of automation.

### New state (with this module)

```
                  ┌────────────────────────────────┐
                  │   Shop Settings (one-time)     │
                  │   /settings                    │
                  │                                │
                  │   • Production Partner profile │
                  │   • Description Templates      │
                  │     (necklace/bracelet/        │
                  │      earring/ring)             │
                  │   • Default Attributes         │
                  │   • Variation Presets          │
                  │     (Finish × Length matrix)   │
                  │   • Pricing Strategy           │
                  │   • Personalization Library    │
                  │   • Return Policy              │
                  │   • Renewal Options            │
                  │   • Shop Sections              │
                  └────────────┬───────────────────┘
                               │ merges into every listing
                               ▼
       ┌────────────────────────────────────────────┐
       │   Listing Builder (per product)            │
       │   /listings/build  +  Extension "Build" tab│
       │                                            │
       │   1. Reksven URL or SKU input              │
       │   2. Slim form (only product-specific):    │
       │      • Carrier Pillar (auto-suggested)    │
       │      • Personalization Type (preset pick) │
       │      • Stone Shape (Drop/Round/Heart/...)  │
       │      • Override Price (optional)          │
       │   3. Build button                          │
       └────────────┬───────────────────────────────┘
                    │
                    ▼
       ┌─────────────────────────────────────────────┐
       │  Backend orchestration                      │
       │                                             │
       │  a) Reksven scrape (image + title + cost)   │
       │  b) Defaults merge from ShopSettings        │
       │  c) Sourcing Intelligence (Phase 4)         │
       │     → recommended keywords                  │
       │  d) Content Pipeline (Phase 6)              │
       │     → 3 ListingVariants — title prompts now │
       │       include adjective ladder from Section │
       │       F below                               │
       │  e) Description Template Engine             │
       │     → fills "How to Order, Materials,       │
       │       Packaging, Gift Note, Best Gifts For, │
       │       Have a Question" scaffold             │
       │  f) Variation Matrix Builder                │
       │     → Finish × Length permutations           │
       │  g) Pricing Engine                          │
       │     → Rose × 12-inch loss leader            │
       │  h) AI Image Pipeline (Phase 5, expanded)   │
       │     → 3 mannequin + 3 concept + 3 chart     │
       │     → cover photo auto-crop                 │
       └────────────┬────────────────────────────────┘
                    │
                    ▼
            Approval UI (Phase 7, extended)
                    │
                    ▼
            Etsy API Upload (Phase 8, patched)
            full payload pre-filled from Settings
```

### What changes per phase

| Phase | Change | Backward compatible? |
|-------|--------|----------------------|
| Phase 4 (Manual Input) | Old form unchanged; new `/listings/build` added | Yes |
| Phase 5 (Image Pipeline) | New "9-image" mode (3+3+3); cover-photo auto-crop; chart generators | Yes — workflow flag |
| Phase 6 (Content Pipeline) | Title prompts get adjective ladder; description gen now consumes `DescriptionTemplate` scaffold | Yes — when scaffold absent, falls back to original free-form generation |
| Phase 7 (Approval UI) | Adds variation matrix preview, pricing matrix, personalization preview | Yes |
| Phase 8 (Etsy API) | Payload now includes production partner ID, variation inventory, defaults, renewal, return policy, featured flag | Yes — payload builder additive |
| Phase 4 (Sourcing) | Used as the keyword feed for Listing Builder when available | Yes |
| Extension | Two new tabs: **Title Helper**, **Listing Builder** | Yes — existing Phase 1, 2, Sourcing tabs unchanged |

---

## SECTION B: SHOP SETTINGS MODULE

### Step B.1: Domain Models

Add to `src/db/models.py`:

```python
class ShopSettings(Base):
    """Singleton table — exactly one row holds all shop-level configuration."""
    __tablename__ = "shop_settings"
    
    id = Column(Integer, primary_key=True)
    # Only id=1 is ever used; enforced at app layer
    
    shop_name = Column(String(100))
    shop_id = Column(String(20))  # Etsy shop ID after API auth
    
    # ---- Production Partner (one-time Etsy setup) ----
    production_partner_id = Column(String(50))     # Etsy returns this after creation
    production_partner_name = Column(String(100))  # "Rexven"
    production_partner_about = Column(String(255)) # "Cemalri Atelier"
    production_partner_location = Column(String(100))  # "Dallas, Texas"
    # The 3-question form Etsy asks — stored once, used forever
    production_partner_q1 = Column(String(50), default="capacity")
        # = "I do not have the capacity to do this myself"
    production_partner_q2 = Column(String(50), default="design")
        # = "I design everything myself"
    production_partner_q3 = Column(String(50), default="everything")
        # = "They do everything for me — packaging, shipping, etc."
    
    # ---- Operational policies ----
    renewal_option = Column(Enum(RenewalOption), default=RenewalOption.AUTOMATIC)
    return_policy_days = Column(Integer, default=14)  # 0 = no returns
    feature_listing_default = Column(Boolean, default=False)
    
    # ---- Quantity strategy ----
    default_quantity = Column(Integer, default=999)
    
    # ---- 22K disclosure rule (from Master Rehber) ----
    omit_karat_in_title = Column(Boolean, default=True)
    
    # ---- Carrier pillars active for this shop ----
    active_pillars = Column(JSON, default=lambda: [
        "cross", "name", "birthstone", "birth_flower", "pet", "pendant"
    ])
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RenewalOption(str, Enum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"


class DescriptionTemplate(Base):
    """Per category description scaffold. Filled with product-specific blanks at gen time."""
    __tablename__ = "description_templates"
    
    id = Column(Integer, primary_key=True)
    category = Column(Enum(JewelryCategory), nullable=False, unique=True)
    
    # The 6 fixed sections from the new training, each as raw markdown with {placeholders}
    section_intro = Column(Text)             # 1-2 sentence product opener
    section_how_to_order = Column(Text)      # variant selection guidance
    section_materials = Column(Text)         # "{material}, {plating}" pattern
    section_packaging = Column(Text)         # shipping + box note
    section_gift_note = Column(Text)         # gift note availability
    section_best_gifts_for = Column(Text)    # occasion list per pillar
    section_have_a_question = Column(Text)   # CTA closer
    
    # Material-aware override blocks
    brass_overrides = Column(JSON)   # e.g. {"materials": "Premium Brass, 14K Gold Plated"}
    silver_overrides = Column(JSON)  # e.g. {"materials": "925 Sterling Silver"}
    
    # Default chain note (brass-only)
    default_chain_text = Column(Text)  # "Standard 16 inch + 2 inch extender..."
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class JewelryCategory(str, Enum):
    NECKLACE = "necklace"
    BRACELET = "bracelet"
    EARRING = "earring"
    RING = "ring"
    ANKLET = "anklet"


class DefaultAttributes(Base):
    """Default Etsy attribute values applied to every listing unless overridden."""
    __tablename__ = "default_attributes"
    
    id = Column(Integer, primary_key=True)
    category = Column(Enum(JewelryCategory), nullable=False)
    
    # Defaults from the training (Section 15 of the new transcript)
    style = Column(String(50), default="Minimalist")
    theme = Column(String(50), default="Love & Friendship")
    holiday_default = Column(String(50), default="Christmas")
    # Holiday override map — for Islamic products use "Eid", for Halloween-themed use "Halloween"
    
    sustainability = Column(String(50), default="Made with Recycled Metals")
    chain_style = Column(String(50), default="Cable Chain")
    adjustable = Column(Boolean, default=True)
    convertible = Column(Boolean, default=True)
    
    # Occasion default when nothing else applies
    default_occasion = Column(String(50), default="Birthday")
    
    # Recipient defaults (5 from training)
    default_recipients = Column(JSON, default=lambda: [
        "Her", "Mother", "Wife", "Daughter", "Sister"
    ])


class VariationPreset(Base):
    """Variation matrix template. Each row = one default skeleton."""
    __tablename__ = "variation_presets"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    # e.g. "necklace_brass_standard", "necklace_silver_standard", 
    # "necklace_brass_multi_birthstone", "earring_basic"
    
    category = Column(Enum(JewelryCategory), nullable=False)
    material_type = Column(Enum(MaterialType), nullable=False)
    
    # Finish dimension
    finishes = Column(JSON)   # ["Gold", "Silver", "Rose"] for silver; ["Gold", "Silver"] for brass
    
    # Length dimension (empty list = no length variation)
    lengths_inches = Column(JSON)  # [12, 14, 16, 18, 20, 22, 24] for silver; [] for brass
    
    # Multi-item dimension (for multi-birthstone, multi-flower, multi-name)
    multi_count_label = Column(String(50), nullable=True)  # "Birthstone", "Birth Flower", "Name"
    multi_count_range = Column(JSON, nullable=True)        # [1, 2, 3, 4, 5] or null
    
    # Whether this preset uses chain length variation
    has_length_variation = Column(Boolean, default=True)


class MaterialType(str, Enum):
    BRASS = "brass"
    SILVER_925 = "silver_925"
    GOLD_PLATED = "gold_plated"  # synonym for brass-with-plating in this context


class PricingStrategy(Base):
    """How prices are computed across the variation matrix."""
    __tablename__ = "pricing_strategy"
    
    id = Column(Integer, primary_key=True)
    
    # Base retail multiplier on Reksven cost
    base_multiplier = Column(Float, default=4.0)  # cost $7 → retail $28
    
    # Per-finish price offsets (additive %, vs base finish which is Gold)
    finish_offsets_pct = Column(JSON, default=lambda: {
        "Gold": 0.0, "Silver": -3.0, "Rose": -5.0
    })
    
    # Per-length price offsets (% increase per inch over the base 16")
    length_base_inches = Column(Integer, default=16)
    length_price_per_extra_inch_pct = Column(Float, default=2.5)
    # 18 inch = base + 2 × 2.5% = +5%; 22 inch = base + 6 × 2.5% = +15%
    
    # Loss-leader override — the cheapest variation shown on search results
    # is intentionally set to a low margin to attract clicks (training: Rose × 12")
    loss_leader_enabled = Column(Boolean, default=True)
    loss_leader_finish = Column(String(20), default="Rose")
    loss_leader_length = Column(Integer, default=12)
    loss_leader_margin_pct = Column(Float, default=15.0)
    # 15% margin on cost; the cheapest cell shown by Etsy's search card


class PersonalizationTemplate(Base):
    """Library of personalization scaffolds. Picked per product."""
    __tablename__ = "personalization_templates"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    # e.g. "birthstone_initial_single", "multi_birthstone_3", 
    # "name_only", "name_date", "custom_text"
    
    instruction_text = Column(Text)
    # The "Please Provide..." block shown to the buyer.
    # Uses {placeholders} like {n} for count.
    
    example_text = Column(Text)
    # The "For example: ..." sample.
    
    reference_note = Column(Text)
    # "You can see birthstone types in the photo"
    
    max_characters = Column(Integer, default=0)  # 0 = no limit
    is_optional = Column(Boolean, default=False)
    
    # Which categories this applies to
    applicable_categories = Column(JSON, default=lambda: ["necklace", "bracelet"])
    # Which personalization types this represents
    type_signature = Column(JSON)
    # e.g. {"has_initial": true, "has_birthstone": true, "count": 1}
    # Used by Listing Builder to auto-pick


class ShopSection(Base):
    """The 20 shop sections from the new training."""
    __tablename__ = "shop_sections"
    
    id = Column(Integer, primary_key=True)
    etsy_section_id = Column(String(50))  # from Etsy after creation
    name = Column(String(50), nullable=False, unique=True)
    # e.g. "Name Necklace", "Initial Necklace", "Birthstone Necklace",
    # "Birth Flower Necklace", "Pet Necklace", "Christmas Gifts"
    carrier_pillar = Column(String(50))  # mapping to carrier pillar enum
    display_order = Column(Integer, default=0)
```

**Validation:**
- Alembic migration runs cleanly
- Singleton constraint enforced on `ShopSettings` (only id=1)
- All enums round-trip through DB
- Foreign keys cascade where appropriate

---

### Step B.2: Seed Data Loader

**Goal:** Ship sane defaults so a fresh install has every preset already populated from the training.

Create `src/db/seed_shop_defaults.py`:

```python
def seed_description_templates(session):
    """Seed the 4 main category templates from the training scaffold."""
    
    necklace_template = DescriptionTemplate(
        category=JewelryCategory.NECKLACE,
        section_intro=(
            "{product_name} — a dainty piece designed to be worn every day. "
            "Whether you wear it solo or layered, this necklace adds a "
            "personal touch to any look."
        ),
        section_how_to_order=(
            "**How to Order**\n"
            "1. Choose your preferred finish — Gold, Silver, or Rose Gold.\n"
            "2. Select your chain length: {length_options}.\n"
            "{personalization_instructions}"
        ),
        section_materials=(
            "**Materials**\n"
            "{materials_line}\n"
            "{chain_note}"
        ),
        section_packaging=(
            "**Packaging & Shipping**\n"
            "Every order ships in a branded gift box, ready to give. "
            "Standard processing time is 3-5 business days."
        ),
        section_gift_note=(
            "**Gift Note**\n"
            "Want to add a personal message? Include a gift note at checkout "
            "and we'll print it on a small card included with your order — at no extra cost."
        ),
        section_best_gifts_for=(
            "**Best Gifts For**\n"
            "This necklace makes a thoughtful gift for {recipients_list} for "
            "{occasions_list}."
        ),
        section_have_a_question=(
            "**Have a Question?**\n"
            "Message us anytime — we usually reply within a few hours. "
            "We love working with you on a custom piece, too."
        ),
        brass_overrides={
            "materials_line": "Premium Brass with 14K Gold/Silver/Rose Gold Plating"
        },
        silver_overrides={
            "materials_line": "925 Sterling Silver with optional Gold/Rose Gold Plating"
        },
        default_chain_text=(
            "The chain is the standard 16 inch length with a 2 inch extender, "
            "so you can wear it at 16 or 18 inches."
        ),
    )
    session.add(necklace_template)
    
    # Repeat for bracelet, earring, ring with their own scaffolds
    # ...
    session.commit()


def seed_personalization_templates(session):
    """Seed the personalization library."""
    
    templates = [
        PersonalizationTemplate(
            name="birthstone_initial_single",
            instruction_text=(
                "Please Provide:\n"
                "1. Birthstone (e.g. May, October)\n"
                "2. Initial (one letter)"
            ),
            example_text="For example: Birthstone (May), Initial (E)",
            reference_note="You can see birthstone types in the photo.",
            max_characters=0,
            is_optional=False,
            applicable_categories=["necklace", "bracelet"],
            type_signature={"has_initial": True, "has_birthstone": True, "count": 1},
        ),
        PersonalizationTemplate(
            name="multi_birthstone_3",
            instruction_text=(
                "Please Provide:\n"
                "1. Number of Birthstones (1-3)\n"
                "2. Birth Month for each (in order)\n"
                "3. Initial for each (in order)"
            ),
            example_text="For example: 3 birthstones, May/June/August, A/B/C",
            reference_note="You can see birthstone types in the photo.",
            max_characters=0,
            is_optional=False,
            applicable_categories=["necklace"],
            type_signature={"has_initial": True, "has_birthstone": True, "count_max": 3},
        ),
        PersonalizationTemplate(
            name="name_only",
            instruction_text="Please Provide:\nThe name to be engraved.",
            example_text="For example: Sarah",
            reference_note="",
            max_characters=8,
            is_optional=False,
            applicable_categories=["necklace", "bracelet"],
            type_signature={"has_name": True, "count": 1},
        ),
        PersonalizationTemplate(
            name="name_date",
            instruction_text=(
                "Please Provide:\n"
                "1. Name\n"
                "2. Date (MM/DD/YYYY)"
            ),
            example_text="For example: Sarah, 05/12/2024",
            reference_note="",
            max_characters=20,
            is_optional=False,
            applicable_categories=["necklace", "bracelet"],
            type_signature={"has_name": True, "has_date": True},
        ),
        PersonalizationTemplate(
            name="none",
            instruction_text="",
            example_text="",
            reference_note="",
            max_characters=0,
            is_optional=True,
            applicable_categories=["necklace", "bracelet", "earring", "ring"],
            type_signature={"none": True},
        ),
        # ... add multi_birth_flower, custom_text, etc.
    ]
    
    for tpl in templates:
        session.add(tpl)
    session.commit()


def seed_variation_presets(session):
    """Seed the 4 default variation skeletons."""
    presets = [
        VariationPreset(
            name="necklace_brass_standard",
            category=JewelryCategory.NECKLACE,
            material_type=MaterialType.BRASS,
            finishes=["Gold", "Silver"],
            lengths_inches=[],  # brass — no length variation per training
            has_length_variation=False,
        ),
        VariationPreset(
            name="necklace_silver_standard",
            category=JewelryCategory.NECKLACE,
            material_type=MaterialType.SILVER_925,
            finishes=["Gold", "Silver", "Rose"],
            lengths_inches=[12, 14, 16, 18, 20, 22, 24],
            has_length_variation=True,
        ),
        VariationPreset(
            name="necklace_brass_multi_birthstone",
            category=JewelryCategory.NECKLACE,
            material_type=MaterialType.BRASS,
            finishes=["Gold", "Silver"],
            lengths_inches=[],
            multi_count_label="Birthstone",
            multi_count_range=[1, 2, 3],
            has_length_variation=False,
        ),
        VariationPreset(
            name="earring_basic",
            category=JewelryCategory.EARRING,
            material_type=MaterialType.BRASS,
            finishes=["Gold", "Silver"],
            lengths_inches=[],
            has_length_variation=False,
        ),
    ]
    for p in presets:
        session.add(p)
    session.commit()
```

**Validation:**
- Seed runs on empty DB → all tables populated
- Re-run is idempotent (use ON CONFLICT or check existence)
- A fresh user has a working baseline within 30 seconds of install

---

### Step B.3: Settings UI

**Goal:** A single page (`/settings`) where the user reviews/edits all defaults — this is the **only** place where these operational details ever need to be touched.

**Implementation:**
- Route: `GET /settings` — tabbed layout
  - Tab 1: Production Partner (edit + sync to Etsy)
  - Tab 2: Description Templates (per-category editor with markdown preview)
  - Tab 3: Default Attributes (per-category)
  - Tab 4: Variation Presets (matrix editor)
  - Tab 5: Pricing Strategy (multiplier + offsets + loss leader)
  - Tab 6: Personalization Library (preset list, add/edit)
  - Tab 7: Operations (return policy days, renewal option, default quantity)
  - Tab 8: Shop Sections (list editor, syncs with Etsy)
- Route: `POST /settings/{tab}` — save with validation

**Production Partner sync flow:**

```python
@router.post("/settings/production-partner/sync")
async def sync_production_partner(session: Session = Depends(get_session)):
    """Create or update the production partner on Etsy. One-time per shop."""
    settings = session.query(ShopSettings).first()
    
    if settings.production_partner_id:
        # Already created — just verify it still exists
        existing = etsy_client.get_production_partner(settings.production_partner_id)
        if existing:
            return {"status": "exists", "partner_id": settings.production_partner_id}
    
    # Create it
    payload = {
        "partner_name": settings.production_partner_name,
        "about_partner": settings.production_partner_about,
        "location": settings.production_partner_location,
        # The 3-question form mapping (Etsy field names — verify in docs)
        "why_partner": "no_capacity",   # capacity → "I don't have the capacity"
        "your_role": "design_lead",     # design → "I design everything"
        "their_role": "full_service",   # everything → "They do everything"
    }
    
    created = etsy_client.create_production_partner(payload)
    settings.production_partner_id = created["production_partner_id"]
    session.commit()
    return {"status": "created", "partner_id": settings.production_partner_id}
```

**Validation:**
- Settings page loads in < 500ms
- Each tab edits in isolation (saving one doesn't reload others)
- Production partner sync creates exactly one partner on Etsy, idempotent
- Pricing strategy preview shows a computed matrix in real time when offsets change

---

## SECTION C: VARIATION MATRIX BUILDER

This is the bridge between `VariationPreset` and Etsy's inventory schema.

### Step C.1: Builder Logic

Create `src/listings/variation_builder.py`:

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class VariationCell:
    """One cell in the Finish × Length × MultiCount matrix."""
    finish: str
    length: Optional[int]      # None if preset has no length variation
    multi_count: Optional[int]  # None if preset has no multi-count variation
    price_cents: int
    sku_suffix: str             # appended to product SKU
    is_loss_leader: bool = False


class VariationMatrixBuilder:
    def __init__(self, settings: ShopSettings, session: Session):
        self.settings = settings
        self.session = session
    
    def build(
        self,
        preset_name: str,
        rexven_cost_cents: int,
        override_base_price_cents: Optional[int] = None,
    ) -> list[VariationCell]:
        preset = self.session.query(VariationPreset).filter_by(name=preset_name).first()
        pricing = self.session.query(PricingStrategy).first()
        
        # Compute base price (Gold × 16 inch baseline)
        base_price_cents = (
            override_base_price_cents
            or int(rexven_cost_cents * pricing.base_multiplier)
        )
        
        cells = []
        for finish in preset.finishes:
            length_dim = preset.lengths_inches or [None]
            multi_dim = preset.multi_count_range or [None]
            
            for length in length_dim:
                for multi_count in multi_dim:
                    price = self._compute_price(
                        base_price_cents, finish, length, multi_count, pricing
                    )
                    
                    is_loss_leader = (
                        pricing.loss_leader_enabled
                        and finish == pricing.loss_leader_finish
                        and length == pricing.loss_leader_length
                    )
                    
                    if is_loss_leader:
                        # Override with loss-leader price
                        margin = pricing.loss_leader_margin_pct / 100.0
                        price = int(rexven_cost_cents * (1.0 + margin))
                    
                    cell = VariationCell(
                        finish=finish,
                        length=length,
                        multi_count=multi_count,
                        price_cents=price,
                        sku_suffix=self._build_sku_suffix(finish, length, multi_count),
                        is_loss_leader=is_loss_leader,
                    )
                    cells.append(cell)
        
        return cells
    
    def _compute_price(
        self, base_cents, finish, length, multi_count, pricing
    ) -> int:
        price = base_cents
        
        # Finish offset
        finish_off = pricing.finish_offsets_pct.get(finish, 0.0) / 100.0
        price = int(price * (1.0 + finish_off))
        
        # Length offset
        if length is not None:
            extra_inches = length - pricing.length_base_inches
            length_off = extra_inches * pricing.length_price_per_extra_inch_pct / 100.0
            price = int(price * (1.0 + length_off))
        
        # Multi-count offset — extra stones add fixed surcharge per stone
        if multi_count is not None and multi_count > 1:
            per_extra_pct = 12.0  # heuristic; tunable
            offset = (multi_count - 1) * per_extra_pct / 100.0
            price = int(price * (1.0 + offset))
        
        return price
    
    def _build_sku_suffix(self, finish, length, multi_count) -> str:
        parts = [finish[:2].upper()]  # GO, SI, RO
        if length is not None:
            parts.append(f"L{length}")
        if multi_count is not None:
            parts.append(f"N{multi_count}")
        return "-".join(parts)
```

**Variation label that Etsy will display:**

```python
def variation_display_label(cell: VariationCell, preset: VariationPreset) -> str:
    """
    Build the label shown to buyers, per the training:
    - Single finish + length: "Gold / 16 inch"
    - Multi-count: "Gold - 2 Birthstone"
    - Multi-count + length: "Gold - 2 Birthstone / 16 inch" 
    """
    parts = [cell.finish]
    if cell.multi_count is not None:
        parts.append(f"- {cell.multi_count} {preset.multi_count_label}")
    label_left = " ".join(parts)
    
    if cell.length is not None:
        return f"{label_left} / {cell.length} inch"
    return label_left
```

**Validation:**
- Necklace silver standard with $7.50 cost → produces 3 × 7 = 21 cells
- Loss leader cell (Rose × 12") shows up flagged and priced ~15% margin above cost
- All non-loss-leader cells have positive margin (sanity check)
- Brass preset with no length variation → produces 2 cells (Gold, Silver)
- Multi-birthstone preset → produces finishes × multi_count cells (no length)

---

## SECTION D: DESCRIPTION TEMPLATE ENGINE

### Step D.1: Filler

Goal: Take a `DescriptionTemplate` row + product context and produce a finished description that satisfies all SEO rules **and** matches the operational scaffold.

```python
class DescriptionEngine:
    def __init__(self, session: Session):
        self.session = session
    
    def fill(
        self,
        product: Product,
        variant: ListingVariant,
        preset: VariationPreset,
        personalization: Optional[PersonalizationTemplate],
        internal_links: list[InternalLink],
    ) -> str:
        template = self.session.query(DescriptionTemplate).filter_by(
            category=product.category
        ).first()
        
        # Decide material vocabulary
        if preset.material_type == MaterialType.BRASS:
            material_overrides = template.brass_overrides or {}
            chain_note = template.default_chain_text  # brass uses fixed chain note
        else:
            material_overrides = template.silver_overrides or {}
            chain_note = ""  # silver gets length variation, no fixed note needed
        
        # Build personalization block
        if personalization and not personalization.type_signature.get("none"):
            pers_block = (
                f"\n3. {personalization.instruction_text}\n"
                f"   {personalization.example_text}\n"
                f"   {personalization.reference_note}"
            )
        else:
            pers_block = ""
        
        # Build length options string for "How to Order"
        if preset.has_length_variation:
            lengths_str = ", ".join(f"{l} inch" for l in preset.lengths_inches)
        else:
            lengths_str = "Standard 16 inch with 2 inch extender"
        
        # Build recipients + occasions strings from product attributes
        recipients_str = self._format_list(product.recipients or [])
        occasions_str = self._format_list(product.occasions or [])
        
        # Fill placeholders
        context = {
            "product_name": variant.title.split(",")[0],  # use the niche descriptor
            "length_options": lengths_str,
            "personalization_instructions": pers_block,
            "materials_line": material_overrides.get("materials_line", "—"),
            "chain_note": chain_note,
            "recipients_list": recipients_str,
            "occasions_list": occasions_str,
        }
        
        # Assemble sections
        sections = [
            template.section_intro,
            template.section_how_to_order,
            template.section_materials,
            template.section_packaging,
            template.section_gift_note,
            template.section_best_gifts_for,
            template.section_have_a_question,
        ]
        
        body = "\n\n".join(s.format(**context) for s in sections if s)
        
        # Append internal links (Phase 6.5 logic, preserved)
        if internal_links:
            link_block = self._format_links(internal_links)
            body = body + "\n\n" + link_block
        
        return body
    
    @staticmethod
    def _format_list(items: list[str]) -> str:
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return f"{items[0]} and {items[1]}"
        return ", ".join(items[:-1]) + f", and {items[-1]}"
    
    def _format_links(self, links: list[InternalLink]) -> str:
        lines = ["**Looking for similar pieces?**"]
        for link in links:
            lines.append(f"View our {link.label}: {link.url}")
        return "\n".join(lines)
```

**Note on coexistence with Phase 6:** Phase 6's `DescriptionGenerator` still runs first — it produces the "voice" and personality content. The engine then **wraps** that into the scaffold via the `{product_name}` and other placeholders. This preserves originality (every product gets unique LLM-written body) while ensuring the scaffold structure is consistent.

**Validation:**
- Brass necklace + multi-birthstone preset + birthstone_initial template → produces description containing chain note, materials line, and personalization block
- Silver necklace → no fixed chain note, full length options listed
- Originality check still passes (the LLM portion remains unique)
- Length is 200-350 words (scaffold + intro from LLM)

---

## SECTION E: PERSONALIZATION AUTO-PICKER

### Step E.1: Type detection

When the user picks "Single Birthstone + Initial" in the Listing Builder form, we need to map that to a `PersonalizationTemplate`. The mapping uses the `type_signature` JSON field.

```python
class PersonalizationPicker:
    """Maps a user-facing personalization type to a PersonalizationTemplate row."""
    
    USER_FACING_OPTIONS = [
        # (display_label, type_signature)
        ("None",                          {"none": True}),
        ("Single Birthstone + Initial",   {"has_initial": True, "has_birthstone": True, "count": 1}),
        ("Multi (2-3) Birthstones",       {"has_initial": True, "has_birthstone": True, "count_max": 3}),
        ("Multi (4-5) Birthstones",       {"has_initial": True, "has_birthstone": True, "count_max": 5}),
        ("Single Birth Flower + Initial", {"has_initial": True, "has_flower": True, "count": 1}),
        ("Multi (2-3) Birth Flowers",     {"has_initial": True, "has_flower": True, "count_max": 3}),
        ("Name Only",                     {"has_name": True, "count": 1}),
        ("Name + Date",                   {"has_name": True, "has_date": True}),
        ("Custom Text",                   {"has_custom_text": True}),
    ]
    
    def __init__(self, session: Session):
        self.session = session
    
    def pick(self, user_choice_label: str, category: JewelryCategory) -> Optional[PersonalizationTemplate]:
        signature = dict(self.USER_FACING_OPTIONS).get(user_choice_label)
        if not signature or signature.get("none"):
            return None
        
        # Find first template with matching type_signature applicable to this category
        candidates = self.session.query(PersonalizationTemplate).filter(
            PersonalizationTemplate.applicable_categories.contains([category.value])
        ).all()
        
        for c in candidates:
            if self._signature_matches(c.type_signature, signature):
                return c
        return None
    
    @staticmethod
    def _signature_matches(template_sig: dict, target_sig: dict) -> bool:
        for k, v in target_sig.items():
            if template_sig.get(k) != v:
                return False
        return True
```

**Validation:**
- Each user-facing option maps to exactly one template
- Unknown options return None gracefully
- Category mismatch (e.g. earring + name+date) returns None

---

## SECTION F: TITLE PROMPT — ADJECTIVE LADDER

### Step F.1: Patch to Phase 6 title generator

The new training crystallizes the most-effective adjective vocabulary for jewelry titles. Add this to the title generator's prompt so the LLM uses these consistently.

Update the title generation prompt in `src/content/title_generator.py`:

```python
JEWELRY_ADJECTIVE_LADDER = """
APPROVED ADJECTIVE VOCABULARY (use these to vary titles within the 137-140 char limit):

Personalization-type adjectives (pick 1-2 per title):
- Custom
- Personalized  
- Customized

Aesthetic adjectives (pick 1-2 per title):
- Dainty
- Minimalist

Material adjectives (pick 1, must match the actual material):
- Gold
- 14K Gold       (only if actually 14K solid or 14K plated)
- Silver
- Sterling Silver  (only if 925 sterling — never for brass)

Forbidden combinations:
- "Solid Gold" + "Gold Plated" — never both
- "Sterling Silver" + brass material — never together
- "Stone" — never; use "CZ" or "Pave" instead
- "Pendant" alone — always "Pendant Necklace"

Shape descriptors (use only if the visible product has the shape):
- Drop / Water Drop  (for teardrop-shaped stones)
- Heart
- Round
- Pear
- Marquise
- Pave
- Baguette
"""


def build_title_prompt(product, variant, research, settings):
    return f"""You are an Etsy SEO specialist for handmade jewelry.

{JEWELRY_ADJECTIVE_LADDER}

PRODUCT CONTEXT
- Carrier pillar: {product.carrier_pillar}
- Material: {product.material}
- Stone/shape: {product.stone_shape or "none"}
- Personalization: {product.personalization_type or "none"}
- Recipients: {product.recipients}
- Occasions: {product.occasions}

VARIANT STRATEGY
{variant.strategy_label}: {variant.strategy_rationale}

RESEARCH CONTEXT (top patterns from bestselling competitors)
{research.top_title_ngrams if research else "Cold start — no research available"}

RULES
- Output 5 candidate titles, one per line
- Each title MUST be 137-140 characters
- First 60 characters must paint the product (niche description, not gift framing)
- Comma + space between phrases
- Capitalize first letter of each word
- Use 2-3 synonyms for the main product type
- Only 1-2 broad gift terms at the end (e.g. "Gifts for Mom")

OUTPUT FORMAT: 5 titles, one per line, no numbering, no preamble.
"""
```

**Validation:**
- Generated titles use approved adjectives at higher rate than baseline (measure: `adjective_overlap` metric)
- No forbidden combinations appear
- Existing title validator (Phase 2) still catches violations as backup

---

## SECTION G: AI IMAGE PIPELINE — 9-IMAGE MODE

The new training specifies **3 mannequin + 3 concept + 3 chart = 9 images** per listing as the production standard. Existing Phase 5 supports configurable image counts; add an explicit 9-image preset.

### Step G.1: Image set spec

```python
@dataclass
class JewelryImageSet:
    """The 9-image production standard."""
    # 3 mannequin shots — product worn on a person
    mannequin_shots: list[GeneratedImage]   # 3 different angles/poses/skin tones
    
    # 3 concept shots — product in lifestyle/flat-lay/styled environment
    concept_shots: list[GeneratedImage]     # 3 different scenes
    
    # 3 charts — informational graphics
    birthstone_chart: GeneratedImage        # color chart of birthstones if applicable
    size_chart: GeneratedImage              # length/chain size reference
    care_instructions_chart: GeneratedImage # care + cleaning guidance
    
    # Optional 10th: branded gift box shot
    gift_box_shot: Optional[GeneratedImage] = None
```

### Step G.2: Chart generators

Charts are not AI-generated — they are programmatically composed from templates so they look identical across products. Create `src/images/chart_generators.py`:

```python
from PIL import Image, ImageDraw, ImageFont

class BirthstoneChartGenerator:
    """Generates a static birthstone reference chart, fixed across listings."""
    TEMPLATE_PATH = "assets/charts/birthstone_chart_template.png"
    
    def generate(self, output_path: str) -> str:
        # The chart is the same image every time (12 birthstones, color swatches)
        # Just copy the template — no per-listing customization
        import shutil
        shutil.copy(self.TEMPLATE_PATH, output_path)
        return output_path


class SizeChartGenerator:
    """Generates a size chart with the variation lengths overlaid."""
    BASE_TEMPLATE = "assets/charts/size_chart_template.png"
    
    def generate(self, output_path: str, lengths_inches: list[int]) -> str:
        img = Image.open(self.BASE_TEMPLATE).convert("RGB")
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype("assets/fonts/Inter-Medium.ttf", 32)
        
        # Render the specific lengths this product supports
        if lengths_inches:
            text = " · ".join(f'{l}"' for l in lengths_inches)
        else:
            text = '16" with 2" extender'
        
        draw.text((400, 1700), text, fill="#222", font=font)
        img.save(output_path, quality=92)
        return output_path


class CareInstructionsChartGenerator:
    """Single fixed image — same on every listing."""
    TEMPLATE_PATH = "assets/charts/care_instructions.png"
    
    def generate(self, output_path: str) -> str:
        import shutil
        shutil.copy(self.TEMPLATE_PATH, output_path)
        return output_path
```

**Why this approach (not LLM/diffusion-generated charts):**
- Charts must be pixel-perfect for buyer trust (jewelry sizing is not subjective)
- Repeating chart imagery actually helps brand consistency
- Cost = $0 per generation
- The training implies charts should be uniform across listings

### Step G.3: Cover photo auto-crop ("encadrement")

The training emphasizes zooming the cover photo so the product reads clearly on mobile thumbnails. Add a post-processing step:

```python
def auto_crop_cover_photo(
    image_path: str,
    output_path: str,
    target_aspect: tuple[int, int] = (1, 1),
    product_bbox: Optional[tuple] = None,
) -> str:
    """
    Crop the cover photo so the product fills ~70% of the frame.
    
    If `product_bbox` (x1,y1,x2,y2) is provided, crop around it.
    Otherwise use saliency detection (cheap heuristic: center of mass of non-background pixels).
    """
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    
    if product_bbox:
        cx = (product_bbox[0] + product_bbox[2]) // 2
        cy = (product_bbox[1] + product_bbox[3]) // 2
        bw = product_bbox[2] - product_bbox[0]
        bh = product_bbox[3] - product_bbox[1]
    else:
        # Fallback: assume product is centered
        cx, cy = w // 2, h // 2
        bw, bh = w // 2, h // 2
    
    # Target crop size = max(bw, bh) × 1.43 (so product fills 70%)
    target_side = int(max(bw, bh) * 1.43)
    target_side = min(target_side, min(w, h))  # don't go off image
    
    half = target_side // 2
    left = max(0, cx - half)
    top = max(0, cy - half)
    right = min(w, left + target_side)
    bottom = min(h, top + target_side)
    
    cropped = img.crop((left, top, right, bottom))
    # Re-size to a standard 2000×2000
    cropped = cropped.resize((2000, 2000), Image.LANCZOS)
    cropped.save(output_path, quality=92)
    return output_path
```

**Validation:**
- 9-image set generates in < 90 seconds
- Charts are pixel-identical across runs
- Cover photo crop visibly improves thumbnail readability on a phone

---

## SECTION H: LISTING BUILDER ORCHESTRATOR

This is the core new flow — what runs when the user clicks "Build" in the extension or on `/listings/build`.

### Step H.1: Slim input model

```python
class ListingBuildRequest(BaseModel):
    """Per-product input — only what cannot be inferred from settings."""
    
    rexven_url: Optional[str] = None
    rexven_sku: Optional[str] = None
    uploaded_image_path: Optional[str] = None
    
    # Product-specific
    carrier_pillar: str                  # e.g. "birthstone"
    category: JewelryCategory = JewelryCategory.NECKLACE
    material_type: MaterialType          # BRASS or SILVER_925
    
    # Personalization (mapped to template via PersonalizationPicker)
    personalization_choice: str          # e.g. "Single Birthstone + Initial"
    
    # Shape (drives title adjectives)
    stone_shape: Optional[str] = None    # "Drop", "Heart", "Round", etc.
    
    # Override price (if blank, computed from PricingStrategy)
    override_base_price_cents: Optional[int] = None
    
    # Variation preset choice (auto-suggested but overridable)
    variation_preset_name: Optional[str] = None
    
    # Optional: a candidate keyword (from Title Helper or Sourcing Phase 4)
    target_keyword: Optional[str] = None
```

### Step H.2: Orchestrator

```python
class ListingBuilder:
    def __init__(self, deps: BuilderDeps):
        self.deps = deps  # holds all dependencies (scraper, sourcing, content, etc.)
    
    async def build(self, req: ListingBuildRequest) -> Product:
        # 1. Load settings (cached singleton)
        settings = self.deps.settings_cache.get()
        
        # 2. Resolve Rexven product (scrape or pull from DB)
        rexven = await self._resolve_rexven_product(req)
        
        # 3. Suggest variation preset if not provided
        preset_name = req.variation_preset_name or self._auto_preset(
            req.category, req.material_type, req.personalization_choice
        )
        preset = self.deps.session.query(VariationPreset).filter_by(name=preset_name).first()
        
        # 4. Build variation matrix + pricing
        matrix = self.deps.variation_builder.build(
            preset_name=preset_name,
            rexven_cost_cents=rexven.cost_cents,
            override_base_price_cents=req.override_base_price_cents,
        )
        
        # 5. Resolve personalization template
        personalization = self.deps.personalization_picker.pick(
            req.personalization_choice, req.category
        )
        
        # 6. Run Sourcing (Phase 4) if target_keyword not provided
        sourcing_result = None
        if not req.target_keyword:
            sourcing_result = await self.deps.sourcing.analyze(
                image_path=rexven.image_path,
                category=req.category,
            )
            target_keyword = sourcing_result.top_keyword
        else:
            target_keyword = req.target_keyword
        
        # 7. Create Product row (status = BUILDING)
        product = Product(
            sku=self._next_sku(),
            carrier_pillar=req.carrier_pillar,
            category=req.category,
            material_type=req.material_type,
            stone_shape=req.stone_shape,
            personalization_template_id=personalization.id if personalization else None,
            variation_preset_id=preset.id,
            target_keyword=target_keyword,
            rexven_url=req.rexven_url,
            original_image_path=rexven.image_path,
            cost_cents=rexven.cost_cents,
            status=ProductStatus.BUILDING,
        )
        self.deps.session.add(product)
        self.deps.session.commit()
        
        # 8. Persist variation matrix
        for cell in matrix:
            self.deps.session.add(VariationRow(
                product_id=product.id,
                finish=cell.finish,
                length_inches=cell.length,
                multi_count=cell.multi_count,
                price_cents=cell.price_cents,
                sku_suffix=cell.sku_suffix,
                is_loss_leader=cell.is_loss_leader,
            ))
        self.deps.session.commit()
        
        # 9. Kick off background pipeline — image gen + content gen run in parallel
        background_tasks.add_task(self._run_async_pipeline, product.id)
        
        return product
    
    async def _run_async_pipeline(self, product_id: int):
        product = self.deps.session.query(Product).get(product_id)
        
        # Stage A: Image set (9-image mode)
        product.status = ProductStatus.IMAGE_PROCESSING
        self.deps.session.commit()
        image_set = await self.deps.image_pipeline.generate_jewelry_set(product)
        
        # Stage B: Content variants (existing Phase 6, with adjective ladder patch)
        product.status = ProductStatus.CONTENT_GENERATING
        self.deps.session.commit()
        variants = await self.deps.content_pipeline.generate_bundle(product)
        
        # Stage C: Apply description scaffold to each variant
        preset = self.deps.session.query(VariationPreset).get(product.variation_preset_id)
        personalization = (
            self.deps.session.query(PersonalizationTemplate)
            .get(product.personalization_template_id)
            if product.personalization_template_id else None
        )
        internal_links = self.deps.linker.find_links(product)
        
        for variant in variants:
            scaffolded = self.deps.description_engine.fill(
                product=product,
                variant=variant,
                preset=preset,
                personalization=personalization,
                internal_links=internal_links,
            )
            variant.description = scaffolded
        
        # Stage D: Validation (existing Phase 2 + originality)
        product.status = ProductStatus.AWAITING_APPROVAL
        self.deps.session.commit()
    
    def _auto_preset(
        self, category: JewelryCategory, material: MaterialType, pers_choice: str
    ) -> str:
        """Heuristic: pick a sensible variation preset."""
        if category == JewelryCategory.NECKLACE:
            if material == MaterialType.SILVER_925:
                return "necklace_silver_standard"
            elif "Multi" in pers_choice:
                return "necklace_brass_multi_birthstone"
            else:
                return "necklace_brass_standard"
        if category == JewelryCategory.EARRING:
            return "earring_basic"
        # ... etc.
        return "necklace_brass_standard"  # safe default
```

**Validation:**
- End-to-end run on a fresh Rexven URL completes in ~90 seconds (scrape + sourcing + content + images)
- Status transitions are correctly emitted (frontend polls and updates)
- Re-running with same URL on a product already in DB is idempotent (no duplicate Products created)
- All 3 variants share the same description scaffold but have unique intros

---

## SECTION I: CHROME EXTENSION — TWO NEW TABS

### Step I.1: "Listing Builder" Tab

The third tab (alongside Phase 1, Phase 2, Sourcing). Triggered from a Rexven product page; collects the slim input and POSTs to `/listings/build`.

```
┌─────────────────────────────────────────────┐
│   Etsy Research Extension v2.5              │
│   ┌────────────────────────────────────┐    │
│   │ Phase 1 │ Phase 2 │ Sourcing │ ▶BUILD│  │
│   └────────────────────────────────────┘    │
│                                              │
│   [Listing Builder]                          │
│                                              │
│   📦 Product detected:                       │
│      Multicolor CZ Station Chain Necklace    │
│      Cost: $7.38 (premium $6.60)             │
│      Category: Kolye → Necklace             │
│                                              │
│   Carrier Pillar    [Birthstone        ▼]    │
│   Material          [Brass             ▼]    │
│   Personalization   [Single Bstone+Init ▼]   │
│   Stone Shape       [Drop              ▼]    │
│                                              │
│   Target keyword (optional):                 │
│   [_____________________________]            │
│   ↳ leave empty to use Sourcing recommendation│
│                                              │
│   Override base price (optional, $):         │
│   [_______]                                  │
│                                              │
│       ┌──────────────────────────┐           │
│       │   ▶  BUILD LISTING       │           │
│       └──────────────────────────┘           │
│                                              │
│   Status: ready                              │
└─────────────────────────────────────────────┘
```

JS code (`popup/listing_builder.js`):

```javascript
document.getElementById('build-btn').addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  
  if (!tab.url.includes('rexven.com')) {
    alert('Open a Rexven product page first');
    return;
  }
  
  const payload = {
    rexven_url: tab.url,
    carrier_pillar: document.getElementById('pillar').value,
    category: 'necklace',  // derived from Rexven category
    material_type: document.getElementById('material').value,
    personalization_choice: document.getElementById('personalization').value,
    stone_shape: document.getElementById('shape').value,
    target_keyword: document.getElementById('target-keyword').value || null,
    override_base_price_cents: parsePrice(document.getElementById('price').value),
  };
  
  setStatus('Building listing — scraping Rexven...');
  
  const resp = await fetch(`${BACKEND_URL}/listings/build`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  
  const { product_sku, poll_url } = await resp.json();
  
  // Poll until status = AWAITING_APPROVAL or FAILED
  while (true) {
    await new Promise(r => setTimeout(r, 3000));
    const poll = await fetch(`${BACKEND_URL}${poll_url}`);
    const data = await poll.json();
    
    setStatus(`Building... [${data.status}]`);
    
    if (data.status === 'AWAITING_APPROVAL') {
      window.open(`${BACKEND_URL}/products/${product_sku}/approve`, '_blank');
      break;
    }
    if (data.status === 'FAILED') {
      setStatus(`Failed: ${data.error}`);
      break;
    }
  }
});

function parsePrice(input) {
  if (!input) return null;
  return Math.round(parseFloat(input) * 100);
}

function setStatus(msg) {
  document.getElementById('build-status').textContent = msg;
}
```

### Step I.2: "Title Helper" Tab

Alongside Phase 1 / Sourcing. Used when the user wants to **manually research a title** for a specific product (the training's "search the product on Etsy, copy a bestseller title, micro-edit" workflow).

The training emphasizes:
- Avoid clicking "Ad by" listings (don't burn competitor ad budget)
- Pick from Star Sellers / high-review shops
- Don't insist on identical product — close-enough match is fine
- Copy the title, then micro-edit by swapping/adding adjectives from the ladder

```
┌─────────────────────────────────────────────┐
│   [Title Helper]                            │
│                                              │
│   Search query:                              │
│   [Sideways Initial Necklace Birthstone___]  │
│       ┌──────────────────┐                   │
│       │   ▶  SEARCH       │                  │
│       └──────────────────┘                   │
│                                              │
│   Filter:                                    │
│   [✓] Hide "Ad by" listings                  │
│   [✓] Star Sellers only                      │
│   [ ] Bestsellers only                       │
│                                              │
│   Results (12 organic, 5 ads filtered out):  │
│                                              │
│   ⭐ Sideways Initial Birthstone Necklace,    │
│   Personalized Letter Necklace, Gemstone     │
│   Letter Necklace, Personalized Birthday...  │
│   [SilverPark] · 3,521 reviews · $24.50      │
│   [Copy Title] [Use for Build]               │
│                                              │
│   ⭐ Custom Sideways Initial Necklace with    │
│   Birthstone, Dainty Letter Pendant...       │
│   [DainTyShop] · 1,891 reviews · $26.00      │
│   [Copy Title] [Use for Build]               │
│                                              │
│   ...                                        │
└─────────────────────────────────────────────┘
```

The Title Helper is a UI on top of the existing Phase 1 scraper — it just runs a small-depth scrape (top 20, no EHunt detail) and filters out ads client-side using the Phase 1 enrichment data already present (`is_ad`).

```javascript
async function runTitleHelper(query) {
  const resp = await fetch(`${BACKEND_URL}/research/quick-scrape`, {
    method: 'POST',
    body: JSON.stringify({ keyword: query, depth: 20, include_details: false }),
  });
  const { listings } = await resp.json();
  
  const filterAds = document.getElementById('hide-ads').checked;
  const filterStarSeller = document.getElementById('star-seller').checked;
  
  let filtered = listings;
  if (filterAds) filtered = filtered.filter(l => !l.is_ad);
  if (filterStarSeller) filtered = filtered.filter(l => l.is_star_seller);
  
  renderResults(filtered);
}

function renderResults(listings) {
  const container = document.getElementById('title-results');
  container.innerHTML = listings.map(l => `
    <div class="result-card">
      ${l.is_star_seller ? '⭐ ' : ''}
      <div class="title">${escapeHtml(l.title)}</div>
      <div class="meta">${l.shop_name} · ${l.review_count} reviews · $${(l.price_cents/100).toFixed(2)}</div>
      <button onclick="copyTitle('${l.listing_id}')">Copy Title</button>
      <button onclick="useForBuild('${l.listing_id}')">Use for Build</button>
    </div>
  `).join('');
}

function copyTitle(listingId) {
  const title = lookupTitle(listingId);
  navigator.clipboard.writeText(title);
}

function useForBuild(listingId) {
  const title = lookupTitle(listingId);
  // Store in extension storage; Listing Builder tab picks it up
  chrome.storage.local.set({ candidate_title: title });
  // Switch to Listing Builder tab
  switchTab('listing_builder');
}
```

**Important:** "Use for Build" doesn't replace the variant generator — it passes the candidate title to the content pipeline as **one of three reference titles** the LLM should consider when producing variants. The 3-variant output still wins on diversity.

**Validation:**
- Title Helper search returns results in <8s
- Ad-filter correctly hides `is_ad=true` listings
- "Copy Title" copies to clipboard
- "Use for Build" persists candidate title across tab switch and Build endpoint receives it

---

## SECTION J: APPROVAL UI EXTENSIONS

The existing approval UI shows 3 variants side by side. Add three new panels.

### Panel 1: Variation Matrix Preview

Below each variant card, show the variation matrix the listing will publish with:

```
Variation Matrix (necklace_silver_standard preset)

         12"       14"       16"       18"       20"       22"       24"
Gold    $29.40   $30.15   $30.90   $31.65   $32.40   $33.15   $33.90
Silver  $28.52   $29.25   $29.97   $30.70   $31.43   $32.15   $32.88
Rose   ◉$8.63   $27.92   $28.61   $29.30   $29.99   $30.68   $31.37

◉ = loss leader (cheapest shown by Etsy in search cards)
```

### Panel 2: Description Preview

Render the scaffolded description with the LLM-generated intro slot filled. User can edit inline; edits go back to `variant.description`.

### Panel 3: Etsy Payload Preview

A collapsible section showing the exact JSON that will be sent to Etsy API on approval:

```json
{
  "title": "...",
  "tags": [...],
  "description": "...",
  "production_partner_ids": ["12345"],
  "renewal_option": "automatic",
  "should_auto_renew": true,
  "is_personalizable": true,
  "personalization_instructions": "Please Provide...",
  "is_personalization_optional": false,
  "shipping_profile_id": "...",
  "shop_section_id": "...",
  "attributes": {
    "style": "Minimalist",
    "occasion": "Birthday",
    ...
  },
  "inventory": {
    "products": [
      { "sku": "TAKI-0142-GO-L12", "offerings": [{ "price": 29.40, "quantity": 999 }], "property_values": [...] },
      ...
    ]
  }
}
```

This panel gives the user transparency before the final Approve click — exactly what hits Etsy. No surprises.

**Validation:**
- Matrix renders accurately matching backend state
- Inline description edit persists
- Payload preview matches the actual outgoing request body byte-for-byte

---

## SECTION K: ETSY API MODULE PATCH

Phase 8's payload builder gets extended.

### Step K.1: Payload assembler

```python
class EtsyListingPayloadBuilder:
    def __init__(self, settings: ShopSettings, session: Session):
        self.settings = settings
        self.session = session
    
    def build(self, product: Product, chosen_variant: ListingVariant) -> dict:
        preset = self.session.query(VariationPreset).get(product.variation_preset_id)
        defaults = self.session.query(DefaultAttributes).filter_by(
            category=product.category
        ).first()
        personalization = (
            self.session.query(PersonalizationTemplate)
            .get(product.personalization_template_id)
            if product.personalization_template_id else None
        )
        section = self.session.query(ShopSection).filter_by(
            carrier_pillar=product.carrier_pillar
        ).first()
        
        payload = {
            # Phase 6 content
            "title": chosen_variant.title,
            "tags": chosen_variant.tags,
            "description": chosen_variant.description,
            "materials": self._materials_list(preset.material_type),
            
            # Production partner (one-time setting reused)
            "production_partner_ids": [self.settings.production_partner_id],
            
            # Operational defaults
            "should_auto_renew": (self.settings.renewal_option == RenewalOption.AUTOMATIC),
            "is_personalizable": personalization is not None,
            "personalization_is_required": (
                personalization is not None and not personalization.is_optional
            ),
            "personalization_char_count_max": personalization.max_characters if personalization else 0,
            "personalization_instructions": (
                self._build_personalization_block(personalization) if personalization else ""
            ),
            
            "shop_section_id": section.etsy_section_id if section else None,
            "is_featured": product.is_featured or self.settings.feature_listing_default,
            
            # Default attributes (already in Etsy attribute schema)
            "attributes": self._build_attributes(product, defaults),
            
            # Inventory (variation matrix)
            "inventory": self._build_inventory(product, preset),
            
            # Static-ish
            "who_made": "someone_else",
            "when_made": "made_to_order",
            "is_supply": False,
            
            # Return policy
            "return_policy_id": self._get_or_create_return_policy(),
            
            # Shipping
            "shipping_profile_id": self.settings.default_shipping_profile_id,
        }
        
        return payload
    
    def _build_attributes(self, product: Product, defaults: DefaultAttributes) -> dict:
        # Holiday override logic from training
        holiday = self._pick_holiday(product)
        
        return {
            "style": defaults.style,
            "theme": product.theme or defaults.theme,
            "holiday": holiday,
            "sustainability": defaults.sustainability,
            "chain_style": product.chain_style or defaults.chain_style,
            "is_adjustable": defaults.adjustable,
            "is_convertible": defaults.convertible,
            "occasions": product.occasions or [defaults.default_occasion],
            "recipients": product.recipients or defaults.default_recipients,
            "shape": product.stone_shape,
            "has_stone": bool(product.stone_shape),
            # ... map all remaining Etsy attribute fields
        }
    
    def _pick_holiday(self, product: Product) -> str:
        """Holiday selection per training Section 15."""
        # Explicit override on product
        if product.holiday_override:
            return product.holiday_override
        
        # Theme-based mapping
        theme = (product.theme or "").lower()
        if "islamic" in theme or "ramadan" in theme:
            return "Eid"
        if "halloween" in theme or "spooky" in theme:
            return "Halloween"
        if "valentine" in theme or "love" in theme:
            return "Valentine's Day"
        
        # Date-aware default — if December, use Christmas; April, Easter; etc.
        # Skipped for simplicity here; implement if desired.
        
        return "Christmas"  # training-recommended default
    
    def _build_inventory(self, product: Product, preset: VariationPreset) -> dict:
        rows = (
            self.session.query(VariationRow)
            .filter_by(product_id=product.id)
            .order_by(VariationRow.finish, VariationRow.length_inches)
            .all()
        )
        
        property_set = self._collect_property_set(preset)
        
        products = []
        for row in rows:
            property_values = []
            
            # Map row attributes to Etsy property_values format
            if "Finish" in property_set:
                property_values.append({
                    "property_id": property_set["Finish"]["id"],
                    "value_ids": [self._finish_value_id(row.finish)],
                    "values": [row.finish],
                })
            if "Length" in property_set and row.length_inches:
                property_values.append({
                    "property_id": property_set["Length"]["id"],
                    "value_ids": [self._length_value_id(row.length_inches)],
                    "values": [f'{row.length_inches}"'],
                })
            if "Multi" in property_set and row.multi_count:
                property_values.append({
                    "property_id": property_set["Multi"]["id"],
                    "value_ids": [self._multi_value_id(row.multi_count)],
                    "values": [f"{row.multi_count} {preset.multi_count_label}"],
                })
            
            products.append({
                "sku": f"{product.sku}-{row.sku_suffix}",
                "property_values": property_values,
                "offerings": [{
                    "price": row.price_cents / 100.0,
                    "quantity": self.settings.default_quantity,
                    "is_enabled": True,
                }],
            })
        
        return {"products": products}
    
    def _build_personalization_block(self, pers: PersonalizationTemplate) -> str:
        parts = [pers.instruction_text]
        if pers.example_text:
            parts.append(f"\n{pers.example_text}")
        if pers.reference_note:
            parts.append(f"\n{pers.reference_note}")
        return "\n".join(parts)
```

**Validation:**
- Payload for brass necklace + multi-birthstone produces 6 inventory products (2 finishes × 3 counts)
- Payload for silver necklace produces 21 inventory products (3 × 7 lengths)
- `is_personalizable` matches selected template
- `production_partner_ids` always populated (since it's a one-time setting)
- Holiday correctly switches to "Eid" when theme is Islamic
- `is_featured` defaults to false but honors product override
- Dry-run mode: build payload without sending → log full JSON for inspection

---

## SECTION L: END-TO-END USER FLOW

Here's what the user actually does, start to finish, in the new flow:

### One-time setup (15 minutes, done once)

1. Open backend → `/settings`
2. Tab "Production Partner" → fill (Rexven / Cemalri Atelier / Dallas Texas) → "Sync to Etsy" → partner created
3. Tab "Description Templates" → review necklace/bracelet/earring/ring scaffolds → light edits if desired
4. Tab "Default Attributes" → confirm Style=Minimalist, Theme=Friendship, Holiday=Christmas etc.
5. Tab "Variation Presets" → confirm the 4 seeded presets
6. Tab "Pricing Strategy" → set base multiplier (4×), confirm loss leader (Rose × 12")
7. Tab "Personalization Library" → review presets, add custom if needed
8. Tab "Operations" → return policy = 14 days, renewal = automatic, default quantity = 999
9. Tab "Shop Sections" → create 6-8 sections matching active carrier pillars

### Per product (3-5 minutes)

1. Open Rexven, browse to a product
2. Click extension → Listing Builder tab
3. Fill the 4-question slim form:
   - Carrier Pillar (auto-suggested from Rexven category)
   - Material (Brass / Silver 925)
   - Personalization (dropdown)
   - Stone Shape (only if applicable)
4. Optionally: paste a target keyword from Title Helper, or override price
5. Click "Build Listing"
6. ~90 seconds: scrape + sourcing + 3 variants + 9 images + scaffolded description
7. Approval page opens automatically — review 3 variants, matrix, payload preview
8. Pick the variant you like (or hybrid-edit)
9. Click "Approve & Upload"
10. Listing goes live on Etsy with all defaults applied

**Target: 10-15 listings per day** per the new training's stated goal. At 4 minutes per product (excluding parallel pipeline time) this is achievable in 60 minutes of active user time.

### Compared to old flow

| Step | Old flow | New flow |
|------|----------|----------|
| Manual input form | 12+ fields | 4 fields |
| Description scaffold | Free-form LLM | Scaffolded + LLM intro |
| Variation matrix | Built post-upload in Etsy UI | Built automatically |
| Pricing per variation | Manual one-by-one | Auto with loss leader |
| Production partner | Set manually per listing | One-time, auto-applied |
| Default attributes | Set per-listing | One-time defaults applied |
| Time per product | 8-12 minutes | 3-5 minutes |

---

## SECTION M: MIGRATION & BACKWARD COMPATIBILITY

### What stays

- `/products/new` (old manual input form) continues to work
- Phase 1 / Phase 2 / Sourcing extension tabs unchanged
- Existing products in DB unaffected
- Old approval UI still functions for products created via old form

### What's new (additive only)

- `/settings` route (new)
- `/listings/build` route (new)
- Extension Listing Builder + Title Helper tabs (new)
- New tables in DB (additive; no schema changes to existing tables except optional FK columns on Product)
- New optional columns on `Product`: `variation_preset_id`, `personalization_template_id`, `target_keyword`, `material_type`, `stone_shape`

### Migration plan

1. Run Alembic migration adding new tables + nullable columns
2. Run `seed_shop_defaults.py` once on existing install
3. Open `/settings`, fill Production Partner section, sync to Etsy
4. **Use the new flow for next listing** — old listings keep working as-is
5. Over time, all new products use the Listing Builder; old `/products/new` becomes a fallback

---

## SECTION N: TESTING CHECKLIST

Before considering this module complete:

**Settings**
- [ ] Fresh install: all defaults seeded
- [ ] `/settings` loads and saves correctly on all 8 tabs
- [ ] Production Partner sync creates exactly one Etsy partner, idempotent on re-sync
- [ ] Pricing matrix preview updates live when offsets change

**Variation builder**
- [ ] Silver necklace standard preset → 21 cells (3 finish × 7 lengths)
- [ ] Brass necklace standard preset → 2 cells
- [ ] Multi-birthstone preset → finishes × count cells
- [ ] Loss leader cell always cheapest

**Description engine**
- [ ] Brass listing → uses "Premium Brass" line, includes default chain note
- [ ] Silver listing → uses "925 Sterling Silver" line, no fixed chain note (length is varied)
- [ ] Personalization block injected when applicable
- [ ] Originality check passes for 10 distinct products in same niche

**Listing Builder**
- [ ] Build endpoint with Rexven URL completes in <120 seconds
- [ ] Build endpoint with image upload also works
- [ ] Build endpoint with target_keyword skips Sourcing
- [ ] Status polling reflects each stage transition

**Extension**
- [ ] Listing Builder tab detects Rexven page correctly
- [ ] Title Helper search returns within 10s, ad filter works
- [ ] "Use for Build" carries title across tab switch

**Etsy API**
- [ ] Payload includes production_partner_ids
- [ ] Inventory matches DB variation matrix exactly
- [ ] Personalization block correctly formatted
- [ ] Holiday attribute correctly mapped (test with Islamic/Halloween/default themes)
- [ ] Dry-run mode logs payload without uploading

**End-to-end**
- [ ] One full product cycle: Rexven → Build → Approve → Etsy live listing
- [ ] Variation matrix on Etsy matches DB
- [ ] Cover photo on Etsy is auto-cropped
- [ ] 9 images uploaded in correct order
- [ ] Listing appears in correct Shop Section

---

## SECTION O: OPEN DESIGN QUESTIONS

These deserve a decision before implementation; defaults below in **bold**.

1. **Shop sections — auto-create on first Build?** When user builds a Birthstone listing and no "Birthstone Necklace" section exists, do we auto-create it? **Yes — create on first use to remove friction. Add a Settings toggle to disable.**

2. **Title Helper — call existing Phase 1 scraper or new lightweight scraper?** Phase 1 is heavyweight (writes to DB, runs analyzers). **New lightweight `/research/quick-scrape` endpoint — top-20, no persistence, no analyzers. Stays out of the main research dataset.**

3. **Loss leader — fixed margin or revenue-share calculation?** Current spec: fixed 15% margin on cost. Alternative: compute to undercut the cheapest organic top-10 listing. **Fixed margin for v1; revisit once we have post-launch ranking data.**

4. **Description scaffold — store as template strings or compile to a tree?** Template strings are simpler, but limited. **Strings for v1; tree-based DSL only if we need rich conditional logic later.**

5. **9-image mode — make it the only mode, or keep workflow choice?** Existing Phase 5 supports multiple workflows. **Make 9-image the new default; keep old workflows behind a "Legacy Mode" toggle for now.**

6. **Settings UI — single-page form or wizard?** Single-page is denser but overwhelming for first-time setup. **Wizard for first-time setup (8 steps), single-page tabbed editor afterwards.**

Each of these can flip without affecting the rest of the spec.

---

## SECTION P: WHAT THIS DOES NOT TRY TO DO

Just to be explicit about boundaries:

- **Does not change SEO rules.** All Section 1 hard rules from `AI_Coding_Agent_Prompt.md` (137-140 title, 13 tags, originality, etc.) remain in force. This module sits *underneath* those rules and provides better defaults.
- **Does not change Phase 1/Phase 2 of the extension.** Research scraping is unchanged.
- **Does not change variant generation strategy.** Still 3 variants per product (Conservative / Differentiated / Gift-focused), still A/B/C structure.
- **Does not auto-publish.** Human approval gate remains hard requirement.
- **Does not handle Etsy ad campaigns.** Out of scope; the training's ad strategy is a separate concern.
- **Does not handle bulk publishing.** One product at a time through the gate. Batch mode is a v2 feature.

---

## APPENDIX: TRAINING SOURCES MAPPED TO SECTIONS

For traceability — every operational detail in this spec ties back to one of the two trainings:

| Section | SEO Training | Operational Training (new) |
|---------|--------------|----------------------------|
| Title adjective ladder (F) | Title length, forbidden words | Approved adjective list |
| Variation matrix (C) | — | Finish × Length workflow, multi-count rows |
| Pricing strategy (B) | "En ucuz fiyat ilk gözükür" | Rose × 12 inch loss leader |
| Description scaffold (D) | Originality, mağaza-içi link | How to Order / Materials / Packaging / Gift Note / Best Gifts For / Have a Question |
| Personalization library (E) | "Personalization açık olmalı" | "Please Provide" + example + reference |
| Default attributes (B.1) | Attribute list | Specific defaults (Minimalist, Friendship, Christmas, Cable Chain, Eid override) |
| 9-image mode (G) | 8-9 minimum, alt text | 3 mannequin + 3 concept + 3 chart split |
| Cover crop (G.3) | — | "Encadrement" zoom |
| Renewal options (B + K) | Renew time strategy | Auto vs Manual listing-level |
| Return policy (B + K) | — | 7/14 days vs none tradeoff |
| Featured listing (K) | — | Top-of-shop feature flag |
| Production partner (B.1 + K) | — | Rexven / Cemalri Atelier / Dallas Texas one-time setup |
| Shop sections (B.1) | 20 section optimization | Per-pillar mapping |
| Quantity 999 (B.1) | 999 = "I'm a producer" signal | (same) |

Every operational training point either becomes a Setting (one-time) or a per-product input that the Builder pipes through the existing automation.
