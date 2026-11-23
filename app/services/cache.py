from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from typing import Any


class TTLCache:
    """Small bounded in-process cache. Safe for a single worker."""

    def __init__(self, ttl_seconds: int, max_entries: int) -> None:
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = asyncio.Lock()

    @staticmethod
    def key(value: Any) -> str:
        raw = json.dumps(value, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def get(self, key: str) -> Any | None:
        if self.ttl <= 0:
            return None
        async with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            created_at, value = item
            if time.monotonic() - created_at > self.ttl:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return value

    async def set(self, key: str, value: Any) -> None:
        if self.ttl <= 0:
            return
        async with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)
