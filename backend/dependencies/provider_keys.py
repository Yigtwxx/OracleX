"""
Bind the caller's own data-provider keys for the duration of one request.

Attached at router level to the surfaces whose upstreams accept a per-reader key
(BIST and derivatives). Anonymous callers cost nothing: `get_optional_user`
returns None without a token, and this yields before touching the database.
"""

import logging
import time
from typing import AsyncIterator, Dict, Optional, Tuple

from fastapi import Depends

from dependencies.auth import AuthUser, get_optional_user
from services import data_provider_settings_service, provider_keys

logger = logging.getLogger(__name__)

# A signed-in reader loading a BIST board fires many requests through this
# dependency, and each one was a synchronous Supabase round trip plus a Fernet
# decrypt per provider — on the event loop, because supabase-py is blocking.
# These keys change when someone edits a form, not between two requests of the
# same page load, so a short memory is the right shape.
#
# Deliberately short: a reader who removes a key expects the boards to stop
# using it promptly, and thirty seconds is well inside "promptly" while still
# collapsing a page load into one lookup.
_CACHE_TTL_SECONDS = 30.0
_cache: Dict[str, Tuple[float, Dict[str, str]]] = {}


def invalidate(user_id: str) -> None:
    """Forget a reader's cached keys. Called when they save or delete one."""
    _cache.pop(user_id, None)


def clear() -> None:
    """Forget every reader's cached keys. For tests, so their order cannot matter."""
    _cache.clear()


async def _keys_for(user_id: str) -> Dict[str, str]:
    cached = _cache.get(user_id)
    now = time.monotonic()
    if cached is not None and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    keys = await data_provider_settings_service.get_keys(user_id)
    _cache[user_id] = (now, keys)
    return keys


async def use_caller_provider_keys(
    user: Optional[AuthUser] = Depends(get_optional_user),
) -> AsyncIterator[None]:
    """
    Prefer the signed-in caller's keys over the server's for this request.

    The tokens are reset in a `finally` because the worker's task may be reused:
    a leaked binding would hand one reader's key to whoever the event loop serves
    next, which is the one way this pattern can leak a credential.
    """
    if user is None:
        yield
        return

    tokens = []
    try:
        keys = await _keys_for(user.id)
    except Exception as e:  # noqa: BLE001
        # A settings lookup must never take down a market-data route; the
        # server's own key is a working answer.
        logger.warning("Could not resolve caller data provider keys: %s", e)
        keys = {}

    for provider, key in keys.items():
        token = provider_keys.bind(provider, key)
        if token is not None:
            tokens.append((provider, token))

    try:
        yield
    finally:
        for provider, token in tokens:
            provider_keys.reset(provider, token)
