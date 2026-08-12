"""
Account suspensions.

This module sits on the hot path: `dependencies/auth.py` asks it about every
authenticated request, so it deliberately depends on nothing but the database
wrapper. It must never import `dependencies.auth` — the dependency goes the
other way.

A suspension is one column, `profiles.banned_until`:

    NULL              not suspended
    past timestamp    the suspension has already lifted (no cron job needed)
    future timestamp  suspended until then
    PERMANENT_UNTIL   a permanent ban

Storing a permanent ban as a far-future date rather than a second boolean means
one comparison answers the question in every case.
"""

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any, Optional

from cachetools import TTLCache

from . import _db

logger = logging.getLogger(__name__)

TABLE = "profiles"

# A ban with no end date. Far enough out to be unmistakable in the database and
# still a valid timestamptz.
PERMANENT_UNTIL = datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)

CACHE_TTL_SECONDS = 60
_CACHE_MAX_ENTRIES = 4096

# A plain bounded TTLCache rather than `services/cache.py`: that module's outer
# dict is keyed per cache entry with no eviction, which a per-user key space
# would grow without bound, and its fallback path serves stale values
# indefinitely — the opposite of what an authorization decision wants.
#
# With more than one uvicorn worker the cache is per process, so lifting a ban
# can take up to CACHE_TTL_SECONDS to be seen by the other workers.
_cache: TTLCache = TTLCache(maxsize=_CACHE_MAX_ENTRIES, ttl=CACHE_TTL_SECONDS)
_lock = threading.Lock()

_MISS = object()


@dataclass(frozen=True)
class BanState:
    """An active suspension. Absent (`None`) means the account is in good standing."""

    until: datetime
    reason: Optional[str] = None

    @property
    def is_permanent(self) -> bool:
        return self.until >= PERMANENT_UNTIL


async def check(user_id: str) -> Optional[BanState]:
    """
    The caller's active suspension, or None.

    Fails **open**: if the lookup itself errors, the caller is let through and
    the failure is logged. A Postgres blip must not 403 every signed-in user on
    the site; the worst case of failing open is a suspended account posting
    during an outage, and the worst case of failing closed is a self-inflicted
    site-wide outage. Errors are not cached, so recovery is immediate.
    """
    with _lock:
        cached = _cache.get(user_id, _MISS)
    if cached is not _MISS:
        return _still_active(cached)

    try:
        data = await _db.table_op(
            lambda client: (
                client.table(TABLE).select("banned_until, ban_reason").eq("id", user_id).execute()
            ),
            what="load ban state",
        )
    except Exception as exc:
        logger.error("admin: ban lookup failed for %s, failing open: %s", user_id, exc)
        return None

    state = _parse(data[0]) if data else None
    with _lock:
        _cache[user_id] = state
    return _still_active(state)


async def invalidate(user_id: str) -> None:
    """
    Drop a cached decision so a ban or unban takes effect immediately rather
    than up to CACHE_TTL_SECONDS later.
    """
    with _lock:
        _cache.pop(user_id, None)


def clear_cache() -> None:
    """Drop every cached decision. For tests and for a manual reset."""
    with _lock:
        _cache.clear()


def _parse(row: dict) -> Optional[BanState]:
    until = parse_timestamp(row.get("banned_until"))
    if until is None:
        return None
    return BanState(until=until, reason=row.get("ban_reason"))


def _still_active(state: Optional[BanState]) -> Optional[BanState]:
    """
    Re-check the expiry on every read.

    The cache can hold a suspension that ends during its own TTL, and a lifted
    ban that keeps blocking for another minute is worse than one extra
    comparison.
    """
    if state is None:
        return None
    return state if state.until > datetime.now(UTC) else None


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse a PostgREST timestamptz. Anything unparseable is treated as absent."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        logger.warning("admin: unparseable banned_until %r, treating as not banned", value)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
