"""
Single entry point for CoinGecko requests.

The base URL used to be a literal repeated across five services, so switching
plans or adding an API key meant finding every copy. Worse, none of those call
sites sent a User-Agent — CoinGecko throttles anonymous clients harder, which is
a large part of why the free tier felt unusably rate-limited here.

Routing to the paid host is a property of the key, not of the call site: a demo
key on `pro-api.coingecko.com` is rejected, and a pro key on the public host is
ignored. Both are read from settings so no key ever reaches the source tree.
"""

import logging
from typing import Any, Optional

from config import settings
from services import http_client

logger = logging.getLogger(__name__)

PUBLIC_BASE_URL = "https://api.coingecko.com/api/v3"
PRO_BASE_URL = "https://pro-api.coingecko.com/api/v3"

DEFAULT_TIMEOUT = 15.0


def is_pro() -> bool:
    """True when a paid key is configured; the host and header both follow."""
    return bool(settings.COINGECKO_API_KEY) and settings.COINGECKO_API_PLAN.lower() == "pro"


def base_url() -> str:
    return PRO_BASE_URL if is_pro() else PUBLIC_BASE_URL


def key_headers() -> dict[str, str]:
    """The auth header for the configured plan, or nothing when no key is set."""
    key = settings.COINGECKO_API_KEY
    if not key:
        return {}
    return {"x-cg-pro-api-key": key} if is_pro() else {"x-cg-demo-api-key": key}


def has_key() -> bool:
    """Whether callers may spend a larger per-refresh request budget."""
    return bool(settings.COINGECKO_API_KEY)


async def get_json(
    path: str,
    *,
    params: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """
    GET a CoinGecko endpoint (`path` is relative, e.g. `/coins/markets`).

    Raises on non-2xx and on transport failures, exactly like
    `http_client.get_json` — callers decide whether to fall back to cache.
    """
    url = f"{base_url()}{path if path.startswith('/') else '/' + path}"
    return await http_client.get_json(
        url,
        params=params,
        headers=key_headers(),
        timeout=timeout,
    )
