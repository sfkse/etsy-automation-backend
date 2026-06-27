"""
Rate-limited Etsy API v3 client (Step 8.2).

- Applies token-bucket (10 req/s) before every call
- Injects Bearer token + x-api-key header
- Handles 429 responses with Retry-After back-off
- Daily call counter tracked (10 k/day)
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from src.modules.etsy.rate_limiter import DailyCounter, TokenBucket
from src.modules.etsy.token_manager import TokenManager

_log = structlog.get_logger(__name__)

BASE_URL = "https://openapi.etsy.com/v3"

# Singleton rate-limit objects shared across all client instances in one process
_bucket = TokenBucket(capacity=10, refill_rate=10)
_daily = DailyCounter()


class EtsyClient:
    def __init__(self, token_manager: TokenManager, shop_id: str, api_key: str) -> None:
        self.token_manager = token_manager
        self.shop_id = shop_id
        self._api_key = api_key

    # ── Low-level request ──────────────────────────────────────────────────────

    async def request(
        self,
        method: str,
        endpoint: str,
        *,
        json: dict | None = None,
        data: dict | None = None,
        files: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        await _bucket.acquire()
        await _daily.increment()

        token = await self.token_manager.get_valid_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "x-api-key": self._api_key,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.request(
                method,
                f"{BASE_URL}{endpoint}",
                headers=headers,
                json=json,
                data=data,
                files=files,
                params=params,
            )

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            _log.warning("Etsy rate-limited, backing off", retry_after=retry_after)
            await asyncio.sleep(retry_after)
            return await self.request(
                method, endpoint, json=json, data=data, files=files, params=params
            )

        resp.raise_for_status()
        if resp.content:
            return resp.json()
        return {}

    # ── Convenience wrappers ───────────────────────────────────────────────────

    async def get(self, endpoint: str, **kwargs: Any) -> Any:
        return await self.request("GET", endpoint, **kwargs)

    async def post(self, endpoint: str, **kwargs: Any) -> Any:
        return await self.request("POST", endpoint, **kwargs)

    async def patch(self, endpoint: str, **kwargs: Any) -> Any:
        return await self.request("PATCH", endpoint, **kwargs)

    async def delete(self, endpoint: str, **kwargs: Any) -> Any:
        return await self.request("DELETE", endpoint, **kwargs)

    # ── Shop helpers ───────────────────────────────────────────────────────────

    async def get_shop(self) -> dict:
        return await self.get(f"/application/shops/{self.shop_id}")

    async def get_shop_sections(self) -> list[dict]:
        resp = await self.get(f"/application/shops/{self.shop_id}/sections")
        return resp.get("results", [])

    async def get_taxonomy_attributes(self, taxonomy_id: int) -> list[dict]:
        resp = await self.get(
            f"/application/seller-taxonomy/nodes/{taxonomy_id}/properties"
        )
        return resp.get("results", [])

    # ── Phase 9: Stats & Renewal ───────────────────────────────────────────────

    async def get_listing_stats(
        self,
        listing_id: str,
        start_date: str,
        end_date: str,
    ) -> dict:
        """Fetch daily stats for a listing.

        Args:
            listing_id: Etsy listing ID string.
            start_date: ISO date string "YYYY-MM-DD".
            end_date:   ISO date string "YYYY-MM-DD".

        Returns Etsy stats payload (visits, views, transactions, revenue keys).
        """
        return await self.get(
            f"/application/shops/{self.shop_id}/listings/{listing_id}/stats",
            params={"start_date": start_date, "end_date": end_date},
        )

    async def renew_listing(self, listing_id: str) -> dict:
        """Renew a listing, resetting its 4-month expiry timer.

        Calls POST /application/shops/{shop_id}/listings/{listing_id}/renew.
        Returns the updated listing dict on success.
        """
        return await self.post(
            f"/application/shops/{self.shop_id}/listings/{listing_id}/renew"
        )
