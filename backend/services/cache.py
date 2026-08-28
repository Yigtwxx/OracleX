"""
Centralized Cache Module using cachetools.
Provides TTLCache with stale-data fallback for all backend services.
"""

import threading
import time
from typing import Any, Optional

from cachetools import TTLCache


class ServiceCache:
    """
    A thread-safe cache with per-key TTL support and stale-data fallback.

    Usage:
        cache = ServiceCache(maxsize=128)
        cache.set("funding", data, ttl=60)
        result = cache.get("funding")
    """

    def __init__(self, maxsize: int = 256):
        self._lock = threading.Lock()
        self._maxsize = maxsize
        self._caches: dict[str, TTLCache] = {}
        # Stale fallback: keeps the last known good value even after TTL expires,
        # alongside the wall-clock time it was written so callers can bound how
        # old a fallback they are willing to serve.
        self._fallback: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        """Get cached value or None if expired/missing."""
        with self._lock:
            ttl_cache = self._caches.get(key)
            if ttl_cache and key in ttl_cache:
                return ttl_cache[key]
        return None

    def get_with_fallback(self, key: str, max_age: Optional[float] = None) -> Optional[Any]:
        """
        Get cached value, falling back to stale data if the TTL expired.

        `max_age` (seconds) bounds how old that stale value may be — past it the
        cache reports a miss instead of passing off day-old data as current.
        Left as None, any surviving fallback is returned.
        """
        result = self.get(key)
        if result is not None:
            return result

        with self._lock:
            entry = self._fallback.get(key)
        if entry is None:
            return None

        value, stored_at = entry
        if max_age is not None and (time.time() - stored_at) > max_age:
            return None
        return value

    def get_fallback_age(self, key: str) -> Optional[float]:
        """Seconds since the fallback for `key` was written, or None if absent."""
        with self._lock:
            entry = self._fallback.get(key)
        return None if entry is None else time.time() - entry[1]

    def set(self, key: str, value: Any, ttl: int) -> None:
        """Set a value with a specific TTL (in seconds)."""
        with self._lock:
            # Create or replace TTLCache for this key
            self._caches[key] = TTLCache(maxsize=1, ttl=ttl)
            self._caches[key][key] = value
            # Also store in fallback
            self._fallback[key] = (value, time.time())

    def is_valid(self, key: str) -> bool:
        """Check if a key has a non-expired value."""
        with self._lock:
            ttl_cache = self._caches.get(key)
            return ttl_cache is not None and key in ttl_cache

    def invalidate(self, key: str) -> None:
        """Force-expire a cached key."""
        with self._lock:
            ttl_cache = self._caches.get(key)
            if ttl_cache and key in ttl_cache:
                del ttl_cache[key]

    def clear(self) -> None:
        """Clear all caches."""
        with self._lock:
            self._caches.clear()
            self._fallback.clear()


# Singleton instances for each service domain
home_cache = ServiceCache(maxsize=64)
market_cache = ServiceCache(maxsize=64)
news_cache = ServiceCache(maxsize=64)
# The ownership board is rebuilt once a day, so its TTLs are measured in hours
# rather than seconds. The stale fallback matters more here than anywhere else:
# a source that fails at noon must replay yesterday's figures rather than let an
# entity render as holding nothing.
ownership_cache = ServiceCache(maxsize=64)
# Borsa İstanbul. Sized well above the others because the per-fund price
# endpoint has no bulk form — a screener pass over a thousand funds is a
# thousand cache keys, and evicting them means fetching them again. The stale
# fallback carries more weight here than anywhere: the exchange is shut
# sixteen hours a day and every weekend, and a closed market should show
# yesterday's close rather than an error.
bist_cache = ServiceCache(maxsize=2048)
