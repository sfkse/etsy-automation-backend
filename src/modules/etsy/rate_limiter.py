"""
Token-bucket rate limiter for the Etsy API (Step 8.2).

Limits:
- 10 requests / second (burst capacity = 10)
- 10 000 requests / day
"""
from __future__ import annotations

import asyncio
import time
from datetime import date

import structlog

_log = structlog.get_logger(__name__)


class TokenBucket:
    """Async token-bucket: capacity tokens, refilled at refill_rate per second."""

    def __init__(self, capacity: float = 10, refill_rate: float = 10) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._tokens: float = capacity
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now

    async def acquire(self) -> None:
        """Block until a token is available."""
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait = (1 - self._tokens) / self.refill_rate
                await asyncio.sleep(wait)


class DailyCounter:
    """Track daily API call count; resets at midnight."""

    DAILY_LIMIT = 10_000

    def __init__(self) -> None:
        self._count: int = 0
        self._day: date = date.today()
        self._lock = asyncio.Lock()

    async def increment(self) -> None:
        async with self._lock:
            today = date.today()
            if today != self._day:
                self._count = 0
                self._day = today
            self._count += 1
            if self._count > self.DAILY_LIMIT:
                _log.warning(
                    "Etsy daily API limit exceeded",
                    count=self._count,
                    limit=self.DAILY_LIMIT,
                )

    @property
    def remaining_today(self) -> int:
        today = date.today()
        if today != self._day:
            return self.DAILY_LIMIT
        return max(0, self.DAILY_LIMIT - self._count)
