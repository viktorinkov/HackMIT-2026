"""A very small in-process async TTL cache with per-key single flight.

The graph page polls every five seconds and a demo has several tabs open at once,
so the point is not hit rate: it is that ten concurrent requests for the same
device run one Elasticsearch query, not ten. Per-key `asyncio.Lock` does that.

Nothing here is shared between processes and nothing is persisted. It is sized
so a runaway key space cannot grow without bound.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

MAX_ENTRIES = 256


class TTLCache:
    def __init__(self, *, max_entries: int = MAX_ENTRIES) -> None:
        self._max = max(1, max_entries)
        self._values: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, key: str) -> Any | None:
        found = self._values.get(key)
        if found is None:
            return None
        expires, value = found
        if expires <= time.monotonic():
            self._values.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl_s: float) -> None:
        if ttl_s <= 0:
            return
        if key not in self._values and len(self._values) >= self._max:
            self._evict()
        self._values[key] = (time.monotonic() + ttl_s, value)

    def invalidate(self, key: str) -> None:
        self._values.pop(key, None)

    def clear(self) -> None:
        self._values.clear()
        self._locks.clear()

    async def get_or_set(
        self,
        key: str,
        ttl_s: float,
        factory: Callable[[], Awaitable[Any]],
        *,
        fresh: bool = False,
    ) -> Any:
        if not fresh:
            cached = self.get(key)
            if cached is not None:
                return cached
        lock = self._locks.get(key)
        if lock is None:
            if len(self._locks) >= self._max:
                self._locks = {k: v for k, v in self._locks.items() if v.locked()}
            lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # A waiter that queued behind the flight takes its result.
            if not fresh:
                cached = self.get(key)
                if cached is not None:
                    return cached
            value = await factory()
            self.set(key, value, ttl_s)
            return value

    def _evict(self) -> None:
        now = time.monotonic()
        for key, (expires, _) in list(self._values.items()):
            if expires <= now:
                self._values.pop(key, None)
        while len(self._values) >= self._max:
            self._values.pop(next(iter(self._values)))
