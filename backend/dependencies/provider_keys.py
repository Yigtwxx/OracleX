"""
Bind the caller's own data-provider keys for the duration of one request.

Attached at router level to the surfaces whose upstreams accept a per-reader key
(BIST and derivatives). Anonymous callers cost nothing: `get_optional_user`
returns None without a token, and this yields before touching the database.
"""

import logging
from typing import AsyncIterator, Optional

from fastapi import Depends

from dependencies.auth import AuthUser, get_optional_user
from services import data_provider_settings_service, provider_keys

logger = logging.getLogger(__name__)


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
        keys = await data_provider_settings_service.get_keys(user.id)
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
