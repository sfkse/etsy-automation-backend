"""
Google Sheets sync helpers (Phase 10).

DB → Sheets: upsert_product_row() called inline after every status change.
Sheets → DB: sync_sheets_to_db() run by the scheduler every 15 minutes,
             updating only the editable manual-input fields (DB is source
             of truth for status and all generated/final content).
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable

import structlog
from sqlalchemy.orm import Session

from src.db.models import Product
from src.modules.sheets.client import SHEET_HEADERS, SheetsClient

if TYPE_CHECKING:
    from src.config.settings import Settings

_log = structlog.get_logger(__name__)

# Fields that the user is allowed to edit in Sheets and have synced back to DB.
# Status and all generated/final content columns are excluded (DB is authoritative).
_EDITABLE_FIELDS = {
    "material",
    "color",
    "has_stone",
    "stone_type",
    "shape",
    "style",
    "occasion",
    "recipient",
    "size_info",
    "cost",
    "selling_price",
}


# ── DB → Sheets ───────────────────────────────────────────────────────────────


def product_to_row(product: Product) -> list[Any]:
    """Serialise a Product ORM object to a flat list matching SHEET_HEADERS order."""

    def _str(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, (list, dict)):
            return json.dumps(v, ensure_ascii=False)
        return str(v)

    return [
        _str(product.sku),
        _str(product.carrier_pillar),
        _str(product.status),
        _str(product.material),
        _str(product.color),
        _str(product.has_stone),
        _str(product.stone_type),
        _str(product.shape),
        _str(product.style),
        _str(product.occasion),
        _str(product.recipient),
        _str(product.size_info),
        _str(product.cost),
        _str(product.selling_price),
        _str(product.final_title),
        _str(product.final_tags),
        _str(product.final_description),
        _str(product.etsy_listing_id),
        _str(product.etsy_section_id),
        _str(product.created_at),
        _str(product.approved_at),
        _str(product.published_at),
    ]


def upsert_product_row(product: Product, settings: "Settings") -> None:
    """Push one product row to Sheets.

    Safe to call anywhere — returns silently if Sheets is disabled or
    credentials are missing; catches and logs all exceptions so it never
    propagates to the caller.
    """
    if not settings.GOOGLE_SHEETS_ENABLED:
        return
    if not settings.GOOGLE_SERVICE_ACCOUNT_FILE or not settings.GOOGLE_SHEETS_ID:
        _log.warning(
            "sheets_upsert_skipped",
            reason="missing GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_SHEETS_ID",
            sku=product.sku,
        )
        return

    try:
        client = SheetsClient(
            service_account_file=settings.GOOGLE_SERVICE_ACCOUNT_FILE,
            spreadsheet_id=settings.GOOGLE_SHEETS_ID,
        )
        client.upsert_row(sku=product.sku, values=product_to_row(product))
        _log.info("sheets_upsert_ok", sku=product.sku, status=product.status)
    except Exception as exc:
        _log.error("sheets_upsert_error", sku=product.sku, error=str(exc))


# ── Sheets → DB ───────────────────────────────────────────────────────────────


def sync_sheets_to_db(
    session_factory: Callable[[], Session],
    settings: "Settings",
) -> dict[str, int]:
    """Read all Sheets rows and update editable manual-input fields in the DB.

    Returns a summary dict: {"checked": N, "updated": N, "skipped": N, "errors": N}.
    DB is source of truth; only _EDITABLE_FIELDS are written back.
    """
    summary = {"checked": 0, "updated": 0, "skipped": 0, "errors": 0}

    if not settings.GOOGLE_SHEETS_ENABLED:
        return summary
    if not settings.GOOGLE_SERVICE_ACCOUNT_FILE or not settings.GOOGLE_SHEETS_ID:
        _log.warning(
            "sheets_sync_skipped",
            reason="missing GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_SHEETS_ID",
        )
        return summary

    try:
        client = SheetsClient(
            service_account_file=settings.GOOGLE_SERVICE_ACCOUNT_FILE,
            spreadsheet_id=settings.GOOGLE_SHEETS_ID,
        )
        rows = client.get_all_rows()
    except Exception as exc:
        _log.error("sheets_sync_fetch_error", error=str(exc))
        summary["errors"] += 1
        return summary

    if not rows or len(rows) < 2:
        _log.info("sheets_sync_no_data_rows")
        return summary

    header = rows[0]
    col_index = {name: i for i, name in enumerate(header)}

    with session_factory() as session:
        for row in rows[1:]:
            summary["checked"] += 1
            try:
                sku = _cell(row, col_index, "sku")
                if not sku:
                    summary["skipped"] += 1
                    continue

                product = session.query(Product).filter_by(sku=sku).first()
                if product is None:
                    _log.warning("sheets_sync_unknown_sku", sku=sku)
                    summary["skipped"] += 1
                    continue

                changed = False
                for field in _EDITABLE_FIELDS:
                    if field not in col_index:
                        continue
                    sheet_val = _cell(row, col_index, field)
                    db_val = getattr(product, field)
                    coerced = _coerce(field, sheet_val, db_val)
                    if coerced != db_val:
                        setattr(product, field, coerced)
                        changed = True

                if changed:
                    session.commit()
                    summary["updated"] += 1
                    _log.info("sheets_sync_product_updated", sku=sku)
                else:
                    summary["skipped"] += 1

            except Exception as exc:
                _log.error("sheets_sync_row_error", error=str(exc))
                session.rollback()
                summary["errors"] += 1

    _log.info("sheets_sync_complete", **summary)
    return summary


# ── Helpers ───────────────────────────────────────────────────────────────────


def _cell(row: list[str], col_index: dict[str, int], field: str) -> str:
    """Safely retrieve a cell value from a row list."""
    idx = col_index.get(field)
    if idx is None or idx >= len(row):
        return ""
    return row[idx].strip()


def _coerce(field: str, sheet_val: str, db_val: Any) -> Any:
    """Convert a sheet string value to the appropriate Python type."""
    if sheet_val == "":
        return db_val  # treat blank as "no change"

    if field == "has_stone":
        return sheet_val.upper() in ("TRUE", "1", "YES")

    if field in ("cost", "selling_price"):
        try:
            return Decimal(sheet_val)
        except Exception:
            return db_val

    return sheet_val
