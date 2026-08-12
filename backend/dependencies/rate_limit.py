"""
Per-IP request throttling, as a FastAPI dependency.

There is one endpoint on this backend a stranger can call repeatedly to learn
something — `POST /api/auth/email/precheck`, which answers whether an address is
already registered. That answer is deliberate (a duplicate sign-up should say so
rather than pretend to succeed), and this module is the price of it: without a
cap, the same endpoint is a cheap oracle for enumerating the user table.

Usage:

    from dependencies.rate_limit import RateLimit

    _limit = RateLimit(name="email-precheck", limit=10, window_seconds=600)

    @router.post("/api/auth/email/precheck", dependencies=[Depends(_limit)])
    async def precheck(...): ...

Scope worth stating: the counters live in this process's memory. Behind two
workers a caller gets two buckets, and a restart clears them. That is the right
trade for a courtesy check in front of Supabase's own limits — a shared store
would add a dependency to make a nuisance-level limit exact.
"""

import logging
import time
from typing import Optional

from cachetools import TTLCache
from fastapi import Depends, HTTPException, Request, status

from config import settings
from dependencies.auth import AuthUser, get_current_user

logger = logging.getLogger(__name__)


class _SlidingWindow:
    """
    The bookkeeping both limiters share: `limit` hits per `window_seconds`, per
    arbitrary key.

    Split out of `RateLimit` when `UserRateLimit` needed the identical window
    against a different identity. It holds no opinion about what a key is.
    """

    def __init__(
        self,
        *,
        name: str,
        limit: int,
        window_seconds: int,
        max_keys: int,
        detail: str,
    ) -> None:
        self._name = name
        self._limit = limit
        self._window = window_seconds
        self._detail = detail
        # Hit timestamps per key, not a counter. `TTLCache.__setitem__` resets an
        # entry's TTL, so incrementing a counter on every request would keep
        # pushing the expiry out and lock a busy caller out permanently. Storing
        # the timestamps and pruning them means the window really does slide.
        #
        # The cache TTL is twice the window so an entry survives long enough to
        # be pruned rather than silently forgotten mid-window; `max_keys` bounds
        # the memory a flood of distinct callers can cost.
        self._hits: TTLCache = TTLCache(maxsize=max_keys, ttl=window_seconds * 2)

    def hit(self, identity: str) -> None:
        """Record one request, or raise 429 if `identity` is over its budget."""
        key = f"{self._name}:{identity}"
        now = time.monotonic()
        cutoff = now - self._window

        recent = [t for t in self._hits.get(key, ()) if t > cutoff]
        if len(recent) >= self._limit:
            retry_after = max(1, int(recent[0] + self._window - now))
            logger.warning("rate limit: %s exhausted its %s budget", key, self._name)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=self._detail,
                headers={"Retry-After": str(retry_after)},
            )

        recent.append(now)
        self._hits[key] = recent

    def reset(self) -> None:
        self._hits.clear()


class RateLimit:
    """
    A fixed sliding window of `limit` requests per `window_seconds` per caller.

    Instantiate once at module scope and pass the instance to `Depends`; a fresh
    instance per request would carry no history at all.
    """

    def __init__(
        self,
        *,
        name: str,
        limit: int,
        window_seconds: int,
        max_keys: int = 10_000,
    ) -> None:
        self._window_state = _SlidingWindow(
            name=name,
            limit=limit,
            window_seconds=window_seconds,
            max_keys=max_keys,
            detail="Too many attempts. Try again in a few minutes.",
        )

    async def __call__(self, request: Request) -> None:
        self._window_state.hit(_client_ip(request))

    def reset(self) -> None:
        """Forget every counter. For tests, so their order cannot matter."""
        self._window_state.reset()


class UserRateLimit:
    """
    The same window, budgeted per *account* rather than per address.

    For actions where the cost is the account's to bear: a DM send is throttled
    because one person may only message so much, and keying that on IP would
    both punish everyone behind a shared address and hand a free reset to
    anyone who changes networks.

    Only usable on routes that already authenticate — it resolves the caller
    through `get_current_user`, so an unauthenticated request is refused with
    that dependency's 401 before any counting happens.
    """

    def __init__(
        self,
        *,
        name: str,
        limit: int,
        window_seconds: int,
        max_keys: int = 10_000,
        detail: str = "You have sent too many messages. Try again later.",
    ) -> None:
        self._window_state = _SlidingWindow(
            name=name,
            limit=limit,
            window_seconds=window_seconds,
            max_keys=max_keys,
            detail=detail,
        )

    async def __call__(self, user: AuthUser = Depends(get_current_user)) -> None:
        self._window_state.hit(user.id)

    def reset(self) -> None:
        """Forget every counter. For tests, so their order cannot matter."""
        self._window_state.reset()


def _client_ip(request: Request) -> str:
    """
    The caller's address.

    `X-Forwarded-For` is read only when `TRUST_PROXY_HEADERS` is on. Any client
    can set that header, so believing it unconditionally would let one caller
    mint a fresh identity per request and make every limit here decorative.
    """
    if settings.TRUST_PROXY_HEADERS:
        forwarded: Optional[str] = request.headers.get("x-forwarded-for")
        if forwarded:
            # Left-most entry is the original client; the rest are the proxies.
            first = forwarded.split(",")[0].strip()
            if first:
                return first

    client = request.client
    return client.host if client else "unknown"
