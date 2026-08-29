"""
Tests for the Rexven capture normalizer.

Fixtures are the description blocks and option sets of three real products,
chosen because each breaks a different assumption:

  REX-271  925 silver — five options, multi-value domains, bullet sub-lists.
  REX-922  brass      — NO length dropdown (fixed "16+2 inch" in prose only),
                        a single-value Renk domain, a 'Sipariş yeri' control,
                        and a free note outside the label pattern.
  REX-946  brass      — a count dimension under a product-specific label.
"""
import pytest

from src.db.models import MaterialType
from src.sourcing.rexven_normalizer import (
    build_attributes,
    classify_option,
    normalize_capture,
    parse_color_domain,
    parse_description_block,
    parse_length_domain,
    parse_length_inches,
    parse_material,
    reconcile_preset,
)

# --------------------------------------------------------------------------
# Fixtures — verbatim from the pages
# --------------------------------------------------------------------------

SILVER_DESCRIPTION = """
<h3><strong><u>AÇIKLAMALAR:</u></strong></h3><p><br></p>
<p><strong>Ürün Ölçüleri:</strong><span> En: 9 mm - Boy: 9 mm</span></p><p><br></p>
<p><strong>Malzeme:</strong><span> 925 Ayar (Milyem) Gümüş</span></p><p><br></p>
<p><strong>Renk:</strong><span> Gold, Silver, Rose Gold Olarak Üç Renk Seçeneği Mevcuttur.</span></p>
<ol>
  <li data-list="bullet"><span>Gold ürünler 925 ayar üzerine 14 ayar altın kaplama yapılmaktadır.</span></li>
  <li data-list="bullet"><span>Rose Gold ürünler 925 ayar üzerine 14 ayar altın kaplama yapılmaktadır.</span></li>
</ol>
<p><strong>Ağırlık:</strong><span> Modeldeki değişikliklere göre değişkenlik gösterebilir.</span></p><p><br></p>
<p><strong>Zincir Uzunluğu:</strong><span> 12-14-16-18-20-22-24 inch uzunluklarda üretim yapılabilir.</span></p>
<p><strong>Tarz:</strong><span> Minimalist</span></p><p><br></p>
<p><strong>Geri Dönüşüm Yapılabilir mi?:</strong><span> Evet</span></p><p><br></p>
<p><strong>Numune Üretim Süresi:</strong><span> 7 İş Günü</span></p>
"""

SILVER_OPTIONS = [
    {"name": "Zincir Uzunluğu", "selected": "12 inches", "values": None},
    {"name": "Renk", "selected": "Gold", "values": None},
    {"name": "Zincir Tipi", "selected": "30 Force (cable) Chain", "values": None},
    {"name": "Materyal", "selected": "925 Ayar Gümüş", "values": None},
    {"name": "Pati Sayısı", "selected": "2", "values": None},
]

BRASS_DESCRIPTION = """
<h3><strong><u>AÇIKLAMALAR:</u></strong></h3><h3><br></h3>
<h4><strong>Not</strong>: 5 farklı zincir bulunmaktadır.</h4><h3><br></h3>
<p><strong>Malzeme:</strong><span> Pirinç (Brass)</span></p><p><br></p>
<p><strong>Renk:</strong><span> Gold Renk Seçeneği Mevcuttur..</span></p><p><br></p>
<p><strong>Zincir Uzunluğu:</strong><span> 16+2 inch uzunlukta üretim yapılır.</span></p><p><br></p>
<p><strong>Tarz:</strong><span> Minimalist</span></p><p><br></p>
<p><strong>Geri Dönüşüm Yapılabilir mi?:</strong><span> Evet</span></p>
"""

BRASS_OPTIONS = [
    {"name": "Zincir Tipi", "selected": "Twist", "values": None},
    {"name": "Materyal", "selected": "Pirinç (Brass)", "values": None},
    {"name": "Renk", "selected": "Gold", "values": None},
]


# --------------------------------------------------------------------------
# Value parsers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("925 Ayar Gümüş", MaterialType.SILVER_925.value),
        ("925 Ayar (Milyem) Gümüş", MaterialType.SILVER_925.value),
        ("Pirinç (Brass)", MaterialType.BRASS.value),
        ("Gold Plated", MaterialType.GOLD_PLATED.value),
        ("", None),
        (None, None),
    ],
)
def test_parse_material(raw, expected):
    assert parse_material(raw) == expected


def test_silver_wins_over_its_own_gold_plating():
    """'925 üzerine 14 ayar altın kaplama' is plating ON silver — still silver.

    If the gold-plated pattern were checked first, every gold-finish silver item
    would be classified brass-adjacent and routed to the wrong preset.
    """
    assert (
        parse_material("925 ayar üzerine 14 ayar altın kaplama")
        == MaterialType.SILVER_925.value
    )


def test_parse_color_domain_keeps_standalone_gold_alongside_rose_gold():
    """The substring trap: 'rose gold' contains 'gold'."""
    assert parse_color_domain(
        "Gold, Silver, Rose Gold Olarak Üç Renk Seçeneği Mevcuttur."
    ) == ["Gold", "Silver", "Rose Gold"]


def test_parse_color_domain_single_value():
    """REX-922 offers exactly one colour — not 'unknown', and not [Gold, Silver]."""
    assert parse_color_domain("Gold Renk Seçeneği Mevcuttur..") == ["Gold"]


def test_parse_length_domain_enumerated():
    assert parse_length_domain(
        "12-14-16-18-20-22-24 inch uzunluklarda üretim yapılabilir."
    ) == [12, 14, 16, 18, 20, 22, 24]


def test_parse_length_domain_extender_is_not_a_second_length():
    """'16+2 inch' is a 16" chain with a 2" extender, not lengths 16 and 2."""
    assert parse_length_domain("16+2 inch uzunlukta üretim yapılır.") == [16]


def test_parse_length_inches_from_dropdown():
    assert parse_length_inches("12 inches") == 12
    assert parse_length_inches("16+2 inch") == 16
    assert parse_length_inches(None) is None


# --------------------------------------------------------------------------
# Option classification
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Renk", "finish"),
        ("Zincir Uzunluğu", "length"),
        ("Zincir Tipi", "chain_type"),
        ("Materyal", "material"),
        # Count labels are product-specific, so they match by suffix.
        ("Pati Sayısı", "count"),
        ("Taş Sayısı", "count"),
        ("Doğum Taşı Sayısı", "count"),
        # Not a product attribute — must NOT become a variation dimension.
        ("Sipariş yeri", None),
    ],
)
def test_classify_option(name, expected):
    assert classify_option(name) == expected


def test_classification_survives_turkish_casing():
    """'İ'.lower() is not 'i' in Python — the normalizer folds it explicitly."""
    assert classify_option("ZİNCİR UZUNLUĞU") == "length"


# --------------------------------------------------------------------------
# Description block
# --------------------------------------------------------------------------


def test_description_block_maps_known_labels():
    parsed = parse_description_block(SILVER_DESCRIPTION)
    assert parsed["material"] == "925 Ayar (Milyem) Gümüş"
    assert parsed["style"] == "Minimalist"
    assert parsed["dimensions"] == "En: 9 mm - Boy: 9 mm"
    assert parsed["recyclable"] == "Evet"


def test_description_block_absorbs_bullet_sublists():
    """The plating notes belong to the 'Renk' label above them."""
    parsed = parse_description_block(SILVER_DESCRIPTION)
    assert "14 ayar altın kaplama" in parsed["colors"]


def test_description_block_collects_free_notes():
    """REX-922's '<h4><strong>Not</strong>: 5 farklı zincir...' has no field."""
    parsed = parse_description_block(BRASS_DESCRIPTION)
    assert any("5 farklı zincir" in n for n in parsed["notes"])


def test_description_heading_is_not_a_field():
    parsed = parse_description_block(SILVER_DESCRIPTION)
    assert not any(k.lower().startswith("açıklamalar") for k in parsed["extra"])


def test_unknown_labels_are_kept_not_dropped():
    """Different product families expose different fields; none may be lost."""
    parsed = parse_description_block(
        "<p><strong>Kolye Ucu Boyutu:</strong><span> 12 mm</span></p>"
    )
    assert parsed["extra"]["Kolye Ucu Boyutu"] == "12 mm"


def test_empty_description_is_safe():
    parsed = parse_description_block(None)
    assert parsed == {"extra": {}, "notes": []}


# --------------------------------------------------------------------------
# End-to-end normalization
# --------------------------------------------------------------------------


def test_silver_capture():
    options, attrs = normalize_capture(SILVER_OPTIONS, SILVER_DESCRIPTION)

    by_key = {o["key"]: o for o in options}
    assert by_key["finish"]["values"] == ["Gold", "Silver", "Rose Gold"]
    assert by_key["length"]["values"] == ['12"', '14"', '16"', '18"', '20"', '22"', '24"']
    assert by_key["count"]["selected"] == "2"

    assert attrs["material_type"] == MaterialType.SILVER_925.value
    assert attrs["color"] == "Gold"
    assert attrs["chain_style"] == "30 Force (cable) Chain"
    assert attrs["style"] == "Minimalist"
    assert "9 mm" in attrs["size_info"]
    assert attrs["count_selected"] == 2
    assert attrs["recyclable"] is True


def test_brass_capture_has_no_length_option_but_still_has_a_size():
    """The size exists only in prose — the page has no length dropdown at all."""
    options, attrs = normalize_capture(BRASS_OPTIONS, BRASS_DESCRIPTION)

    assert all(o["key"] != "length" for o in options)
    assert "16+2 inch" in attrs["size_info"]
    assert attrs["material_type"] == MaterialType.BRASS.value
    assert attrs["chain_style"] == "Twist"


def test_brass_finish_domain_is_single_valued():
    options, _ = normalize_capture(BRASS_OPTIONS, BRASS_DESCRIPTION)
    finish = next(o for o in options if o["key"] == "finish")
    assert finish["values"] == ["Gold"]
    assert finish["values_source"] == "description"


def test_unknown_option_is_retained_with_no_key():
    """'Sipariş yeri' must survive the round-trip without becoming a dimension."""
    options, _ = normalize_capture(
        [{"name": "Sipariş yeri", "selected": "Yurt Dışı", "values": None}], None
    )
    assert options[0]["name"] == "Sipariş yeri"
    assert options[0]["key"] is None
    assert options[0]["selected"] == "Yurt Dışı"


def test_api_domain_beats_description():
    """When the tap captured real domains, prose parsing must not override them."""
    options, _ = normalize_capture(
        [{"name": "Renk", "selected": "Gold", "values": ["Gold", "Silver"]}],
        SILVER_DESCRIPTION,
    )
    assert options[0]["values"] == ["Gold", "Silver"]
    assert options[0]["values_source"] == "api"


def test_capture_with_nothing_is_safe():
    options, attrs = normalize_capture(None, None)
    assert options == []
    assert attrs["material_type"] is None


def test_build_attributes_prefers_dropdown_over_prose():
    """The selected value is what was priced; prose describes the range."""
    attrs = build_attributes(
        [{"name": "Materyal", "key": "material", "selected": "Pirinç (Brass)", "values": None}],
        {"material": "925 Ayar Gümüş"},
    )
    assert attrs["material_type"] == MaterialType.BRASS.value


# --------------------------------------------------------------------------
# Preset reconciliation
# --------------------------------------------------------------------------


def test_reconcile_flags_finish_the_supplier_does_not_stock():
    """The live REX-922 case: preset offers Silver, supplier lists Gold only."""
    options, _ = normalize_capture(BRASS_OPTIONS, BRASS_DESCRIPTION)
    problems = reconcile_preset(options, ["Gold", "Silver"], [])
    assert len(problems) == 1
    assert "Silver" in problems[0]


def test_reconcile_flags_lengths_when_supplier_has_no_length_option():
    options, _ = normalize_capture(BRASS_OPTIONS, BRASS_DESCRIPTION)
    problems = reconcile_preset(options, ["Gold"], [12, 16, 18])
    assert any("no length option" in p for p in problems)


def test_reconcile_is_silent_when_domains_agree():
    options, _ = normalize_capture(SILVER_OPTIONS, SILVER_DESCRIPTION)
    assert reconcile_preset(options, ["Gold", "Silver", "Rose"], [12, 16, 24]) == []


def test_reconcile_does_not_report_unknown_domains():
    """Absence of evidence is not a mismatch — never guess against the preset."""
    options = [{"name": "Renk", "key": "finish", "selected": "Gold", "values": None}]
    assert reconcile_preset(options, ["Gold", "Silver"], []) == []
