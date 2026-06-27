"""
Google Sheets API client (Phase 10).

Wraps the Sheets v4 API with service-account authentication.
SKU (column A) is the unique key used for upsert operations.
"""
from __future__ import annotations

from typing import Any

import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

_log = structlog.get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Column headers — order must match product_to_row() in sync.py
SHEET_HEADERS = [
    "sku",
    "carrier_pillar",
    "status",
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
    "final_title",
    "final_tags",
    "final_description",
    "etsy_listing_id",
    "etsy_section_id",
    "created_at",
    "approved_at",
    "published_at",
]

# Range that covers all data rows (no upper bound on rows)
_DATA_RANGE = "Sheet1!A:V"
_HEADER_RANGE = "Sheet1!A1:V1"


class SheetsClient:
    """Thin wrapper around the Google Sheets v4 API."""

    def __init__(self, service_account_file: str, spreadsheet_id: str) -> None:
        creds = service_account.Credentials.from_service_account_file(
            service_account_file,
            scopes=SCOPES,
        )
        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self._spreadsheet_id = spreadsheet_id
        self._sheets = self._service.spreadsheets()

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_header(self) -> list[str]:
        """Return the header row, creating it if the sheet is empty."""
        result = (
            self._sheets.values()
            .get(spreadsheetId=self._spreadsheet_id, range=_HEADER_RANGE)
            .execute()
        )
        values: list[list] = result.get("values", [])
        if not values:
            self._write_header()
            return SHEET_HEADERS
        return values[0]

    def get_all_rows(self) -> list[list[str]]:
        """Return all rows (including header as row 0)."""
        result = (
            self._sheets.values()
            .get(spreadsheetId=self._spreadsheet_id, range=_DATA_RANGE)
            .execute()
        )
        return result.get("values", [])

    def upsert_row(self, sku: str, values: list[Any]) -> None:
        """Update the row whose SKU matches, or append a new row."""
        rows = self.get_all_rows()

        # Ensure header exists
        if not rows:
            self._write_header()
            rows = [SHEET_HEADERS]

        # Find the 1-based sheet row index for this SKU (skip header at index 0)
        target_row: int | None = None
        for i, row in enumerate(rows):
            if row and row[0] == sku:
                target_row = i + 1  # 1-based
                break

        str_values = [str(v) if v is not None else "" for v in values]

        if target_row is not None:
            range_notation = f"Sheet1!A{target_row}:V{target_row}"
            self._sheets.values().update(
                spreadsheetId=self._spreadsheet_id,
                range=range_notation,
                valueInputOption="USER_ENTERED",
                body={"values": [str_values]},
            ).execute()
            _log.debug("sheets_row_updated", sku=sku, row=target_row)
        else:
            self._sheets.values().append(
                spreadsheetId=self._spreadsheet_id,
                range="Sheet1!A:A",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": [str_values]},
            ).execute()
            _log.debug("sheets_row_appended", sku=sku)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _write_header(self) -> None:
        self._sheets.values().update(
            spreadsheetId=self._spreadsheet_id,
            range=_HEADER_RANGE,
            valueInputOption="RAW",
            body={"values": [SHEET_HEADERS]},
        ).execute()
        _log.info("sheets_header_written", spreadsheet_id=self._spreadsheet_id)
