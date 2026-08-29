"""
Normalize what the Chrome extension lifted off a Rexven product page into
stable, English-keyed structures.

Three things arrive from the extension, in decreasing order of fidelity:

  1. ``raw_payload`` — the product JSON the SPA fetched for itself, captured by
     the MAIN-world API tap. Carries full option domains when present.
  2. ``options``     — label/selected pairs read off the closed DOM. Radix
     renders a select's options into a portal only while it is open, so this
     path can report *which* dimensions exist and what is currently chosen, but
     never the full domain (``values`` is None).
  3. ``description_html`` — the Quill spec block. Prose, but it is the only
     source for facts that have no dropdown at all.

Design rules, each forced by a real product:

* **Never drop an unmapped label.** REX-271 (silver) exposes five dimensions,
  REX-922 (brass) exposes four *different* ones including ``Sipariş yeri``.
  There is no fixed schema; unknown labels land in ``extra``.
* **Prose beats absence.** REX-922 has no length dropdown, but its description
  says "16+2 inch uzunlukta üretim yapılır" — that is the real size and only the
  prose has it.
* **``values=None`` means "unknown", not "one value".** REX-922's Renk offers
  Gold only, while the ``necklace_brass_standard`` preset seeds
  ``[Gold, Silver]``. Conflating the two is exactly what makes the builder emit a
  Silver variation the supplier cannot make.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from bs4 import BeautifulSoup

from src.db.models import MaterialType

# ---------------------------------------------------------------------------
# Turkish text handling
# ---------------------------------------------------------------------------

_TR_ASCII = str.maketrans(
    {
        "ç": "c", "Ç": "c",
        "ğ": "g", "Ğ": "g",
        "ı": "i", "I": "i", "İ": "i", "i": "i",
        "ö": "o", "Ö": "o",
        "ş": "s", "Ş": "s",
        "ü": "u", "Ü": "u",
    }
)


def _norm(text: str) -> str:
    """Fold a Turkish label to a comparable ASCII key.

    ``str.lower()`` alone is unsafe here: Turkish 'İ' lowercases to 'i' plus a
    combining dot, so 'İş' and 'iş' would not compare equal. Translating the
    Turkish-specific characters first keeps the mapping tables plain ASCII.
    """
    return re.sub(r"\s+", " ", (text or "").translate(_TR_ASCII).lower()).strip()


# ---------------------------------------------------------------------------
# Option-name classification
# ---------------------------------------------------------------------------

# Supplier dropdown label -> the dimension it corresponds to on our side.
# "finish" / "length" / "count" line up with VariationRow's columns; "material"
# and "chain_type" are product attributes rather than variation axes.
_OPTION_KEYS: dict[str, str] = {
    "renk": "finish",
    "zincir uzunlugu": "length",
    "uzunluk": "length",
    "zincir tipi": "chain_type",
    "materyal": "material",
    "malzeme": "material",
}

# Count dimensions are product-specific ("Pati Sayısı", "Taş Sayısı",
# "Doğum Taşı Sayısı"), so they are matched by suffix rather than enumerated.
_COUNT_SUFFIX = "sayisi"


def classify_option(name: str) -> Optional[str]:
    """Map a supplier option label to a known dimension key, or None."""
    key = _norm(name)
    if key in _OPTION_KEYS:
        return _OPTION_KEYS[key]
    if key.endswith(_COUNT_SUFFIX):
        return "count"
    return None


# ---------------------------------------------------------------------------
# Value parsers
# ---------------------------------------------------------------------------

_MATERIAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"925|sterling|gumus"), MaterialType.SILVER_925.value),
    (re.compile(r"pirinc|brass"), MaterialType.BRASS.value),
    (re.compile(r"gold\s*plated|altin\s*kaplama"), MaterialType.GOLD_PLATED.value),
]


def parse_material(value: Optional[str]) -> Optional[str]:
    """'925 Ayar Gümüş' -> 'silver_925'; 'Pirinç (Brass)' -> 'brass'.

    Order matters: a silver item is commonly described as "925 üzerine 14 ayar
    altın kaplama" (plating *over* silver), and its material is still silver.
    """
    if not value:
        return None
    key = _norm(value)
    for pattern, material in _MATERIAL_PATTERNS:
        if pattern.search(key):
            return material
    return None


def parse_length_inches(value: Optional[str]) -> Optional[int]:
    """'12 inches' -> 12; '16+2 inch' -> 16 (the extender is not the length)."""
    if not value:
        return None
    m = re.search(r"(\d{1,2})", value)
    return int(m.group(1)) if m else None


def parse_length_domain(text: Optional[str]) -> list[int]:
    """Pull every chain length out of a prose sentence.

    '12-14-16-18-20-22-24 inch uzunluklarda üretim yapılabilir' -> [12..24]
    '16+2 inch uzunlukta üretim yapılır'                        -> [16]
    """
    if not text:
        return []
    # Stop at the '+' extender form so '16+2' doesn't yield [16, 2].
    head = text.split("+")[0]
    values = [int(n) for n in re.findall(r"\b(\d{1,2})\b", head)]
    return [v for v in values if 6 <= v <= 40]


_COLOR_WORDS = ("gold", "silver", "rose gold", "rose", "black", "white")


def parse_color_domain(text: Optional[str]) -> list[str]:
    """'Gold, Silver, Rose Gold Olarak Üç Renk Seçeneği Mevcuttur.' -> 3 colors.

    'Gold Renk Seçeneği Mevcuttur..' -> ['Gold'] — a genuinely single-value
    domain, which is the case the variation preset gets wrong.

    Matching is by span, not by substring: 'rose gold' contains 'gold', so a
    substring check would drop the standalone 'Gold' from the list above. Each
    position in the text is claimed once, longest colour name first, and the
    result keeps the order the page states.
    """
    if not text:
        return []
    key = _norm(text)

    spans: list[tuple[int, int, str]] = []
    for word in _COLOR_WORDS:
        for m in re.finditer(rf"\b{re.escape(word)}\b", key):
            spans.append((m.start(), m.end(), word))

    # Earliest first; at equal starts prefer the longer name so 'rose gold'
    # claims the span before a bare 'rose' can.
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))

    found: list[str] = []
    claimed_until = -1
    for start, end, word in spans:
        if start < claimed_until:
            continue  # already part of a longer colour name
        claimed_until = end
        title = word.title()
        if title not in found:
            found.append(title)
    return found


def canon_finish(value: Optional[str]) -> str:
    """Fold a finish name to a comparable token.

    Our VariationPresets use short names ('Rose'), Rexven states full ones
    ('Rose Gold'). Comparing them raw reports a mismatch on every silver product,
    which would bury the mismatches that are real. Order matters: 'rose gold'
    contains 'gold', so rose is tested first.
    """
    key = _norm(value or "")
    if "rose" in key:
        return "rose"
    if "silver" in key or "gumus" in key:
        return "silver"
    if "gold" in key or "altin" in key:
        return "gold"
    return key


def parse_bool_tr(value: Optional[str]) -> Optional[bool]:
    """'Evet' -> True, 'Hayır' -> False."""
    if not value:
        return None
    key = _norm(value)
    if key.startswith("evet"):
        return True
    if key.startswith("hayir"):
        return False
    return None


# ---------------------------------------------------------------------------
# Description block
# ---------------------------------------------------------------------------

# Spec-block label -> English key. Anything not here is preserved under "extra".
_SPEC_KEYS: dict[str, str] = {
    "malzeme": "material",
    "renk": "colors",
    "urun olculeri": "dimensions",
    "agirlik": "weight",
    "zincir uzunlugu": "chain_lengths",
    "zincir tipi": "chain_type",
    "uyarilar": "care",
    "tarz": "style",
    "geri donusum yapilabilir mi?": "recyclable",
    "numune uretim boyutu": "sample_size",
    "numune uretim suresi": "sample_lead_time",
    "paketleme": "packaging",
}

# Labels that introduce a free-form remark rather than a field. Without this
# they'd land in `extra` under a key ("Not") whose meaning differs per product —
# REX-922's is "5 farklı zincir bulunmaktadır", which is a note, not a spec.
_NOTE_LABELS = {"not", "notlar", "note", "dikkat"}


def parse_description_block(html: Optional[str]) -> dict[str, Any]:
    """
    Parse the Quill spec block into English keys.

    The markup comes in three shapes across sampled products, all handled here:

      1. ``<strong>Label:</strong><span>value</span>``  — the common case.
      2. ``<ol><li data-list="bullet">``                — sub-points under a
         label (REX-271's plating notes), appended to that label's value.
      3. Free text with no label — ``<h4><strong>Not</strong>: 5 farklı zincir
         bulunmaktadır.</h4>`` (REX-922). Collected into ``notes``.

    Returns ``{<english key>: str, "extra": {<raw label>: str}, "notes": [str]}``.
    """
    result: dict[str, Any] = {"extra": {}, "notes": []}
    if not html:
        return result

    soup = BeautifulSoup(html, "html.parser")
    current_key: Optional[str] = None

    for block in soup.find_all(["p", "h1", "h2", "h3", "h4", "li"]):
        label_el = block.find("strong")
        text = block.get_text(" ", strip=True)
        if not text:
            continue

        if label_el is not None:
            label_raw = label_el.get_text(" ", strip=True).rstrip(":").strip()
            label = _norm(label_raw)
            value = text[len(label_el.get_text(" ", strip=True)):].lstrip(": ").strip()

            # "AÇIKLAMALAR:" is the block's own heading, not a field.
            if label.startswith("aciklamalar"):
                current_key = None
                continue

            if label in _NOTE_LABELS:
                current_key = None
                result["notes"].append(text)
            elif label in _SPEC_KEYS:
                current_key = _SPEC_KEYS[label]
                result[current_key] = value
            elif value:
                current_key = None
                result["extra"][label_raw] = value
            else:
                current_key = None
                result["notes"].append(text)
            continue

        # Bulleted continuation of the label above it.
        if block.name == "li" and current_key:
            existing = result.get(current_key) or ""
            result[current_key] = f"{existing} {text}".strip()
            continue

        # Unlabelled prose that isn't Quill's blank-line filler.
        if text and text != " ":
            result["notes"].append(text)

    return result


# ---------------------------------------------------------------------------
# Top-level normalization
# ---------------------------------------------------------------------------


def normalize_options(
    raw_options: Optional[Iterable[dict[str, Any]]],
    description: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """
    Annotate captured options with a dimension key, and fill in domains from the
    description prose when the DOM couldn't supply them.

    ``values`` stays None when the domain is genuinely unknown. It is never
    back-filled from a VariationPreset — that assumption is what produces
    variations the supplier does not stock.
    """
    description = description or {}
    normalized: list[dict[str, Any]] = []

    for raw in raw_options or []:
        name = (raw.get("name") or "").strip()
        if not name:
            continue
        key = classify_option(name)
        values = raw.get("values")
        if values is not None:
            values = [str(v) for v in values]

        if values is None:
            # The prose sometimes states the domain the closed DOM can't show.
            if key == "finish":
                values = parse_color_domain(description.get("colors")) or None
            elif key == "length":
                lengths = parse_length_domain(description.get("chain_lengths"))
                values = [f'{n}"' for n in lengths] or None

        normalized.append(
            {
                "name": name,
                "key": key,
                "selected": raw.get("selected"),
                "values": values,
                # Where the domain came from, so a later audit can tell a
                # confirmed single-value domain from an unresolved one.
                "values_source": (
                    "api"
                    if raw.get("values") is not None
                    else ("description" if values is not None else None)
                ),
            }
        )

    return normalized


def build_attributes(
    options: Optional[Iterable[dict[str, Any]]],
    description: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Collapse options + description into the flat attribute set the build step
    consumes. Selected dropdown values win over prose; prose fills the gaps.

    Keys map onto existing Product columns that already have readers:
    ``material_type`` (drives preset selection), ``color``, ``chain_style``,
    ``style``, ``size_info`` — the last three are read by
    ``description_generator._product_summary`` and
    ``payload_builder._build_attributes``, which today always find NULL.
    """
    description = description or {}
    by_key = {o.get("key"): o for o in (options or []) if o.get("key")}

    def selected(key: str) -> Optional[str]:
        opt = by_key.get(key)
        return (opt or {}).get("selected")

    material_type = parse_material(selected("material")) or parse_material(
        description.get("material")
    )

    # Size: the dropdown gives the selected length; the prose gives the real
    # spec, including the '16+2 inch' extender form and physical dimensions.
    size_parts: list[str] = []
    if description.get("dimensions"):
        size_parts.append(str(description["dimensions"]))
    if description.get("chain_lengths"):
        size_parts.append(str(description["chain_lengths"]))
    elif selected("length"):
        size_parts.append(str(selected("length")))

    return {
        "material_type": material_type,
        "material_raw": selected("material") or description.get("material"),
        "color": selected("finish"),
        "chain_style": selected("chain_type") or description.get("chain_type"),
        "style": description.get("style"),
        "size_info": " | ".join(size_parts) or None,
        "count_selected": _as_int(selected("count")),
        "recyclable": parse_bool_tr(description.get("recyclable")),
        "packaging": description.get("packaging"),
        "care": description.get("care"),
    }


def _as_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    m = re.search(r"\d+", str(value))
    return int(m.group(0)) if m else None


def normalize_capture(
    options: Optional[Iterable[dict[str, Any]]] = None,
    description_html: Optional[str] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    One-shot entry point: returns ``(options, attributes)`` ready to persist into
    ``SourcingAnalysis.rexven_options`` / ``.rexven_attributes``.
    """
    description = parse_description_block(description_html)
    normalized = normalize_options(options, description)
    attributes = build_attributes(normalized, description)
    attributes["description"] = description
    return normalized, attributes


# ---------------------------------------------------------------------------
# Preset reconciliation
# ---------------------------------------------------------------------------


def reconcile_preset(
    options: Optional[Iterable[dict[str, Any]]],
    preset_finishes: Optional[Iterable[str]],
    preset_lengths: Optional[Iterable[int]],
) -> list[str]:
    """
    Report variations the preset offers that the supplier does not stock.

    This does **not** change the matrix — ``VariationMatrixBuilder`` still builds
    from the preset. It exists so the mismatch is recorded from day one: on
    REX-922 the ``necklace_brass_standard`` preset offers a Silver finish while
    the supplier lists Gold only, so that listing carries a variation nobody can
    fulfil. Accumulating these decides whether to later derive the matrix from
    the supplier or keep the preset and warn.

    A supplier option with ``values=None`` (domain unknown) is skipped rather
    than reported — absence of evidence is not a mismatch.
    """
    problems: list[str] = []
    by_key = {o.get("key"): o for o in (options or []) if o.get("key")}

    finish_opt = by_key.get("finish")
    if finish_opt and finish_opt.get("values"):
        supplier = {canon_finish(v) for v in finish_opt["values"]}
        for finish in preset_finishes or []:
            if canon_finish(finish) not in supplier:
                problems.append(
                    f"preset offers finish {finish!r} but supplier lists "
                    f"{sorted(finish_opt['values'])}"
                )

    length_opt = by_key.get("length")
    if length_opt and length_opt.get("values"):
        supplier_lengths = {
            parse_length_inches(v) for v in length_opt["values"]
        } - {None}
        for length in preset_lengths or []:
            if length not in supplier_lengths:
                problems.append(
                    f"preset offers length {length}\" but supplier lists "
                    f"{sorted(v for v in supplier_lengths if v is not None)}"
                )
    elif length_opt is None and preset_lengths:
        problems.append(
            f"preset offers lengths {sorted(preset_lengths)} but the supplier "
            f"page has no length option at all"
        )

    return problems
