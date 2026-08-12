"""Fear and Greed Index service using alternative.me API."""

import logging
from datetime import datetime
from typing import Optional

from services.cache import home_cache
from services.http_client import get_json

logger = logging.getLogger(__name__)

CACHE_DURATION_SECONDS = 240  # 4 minutes
_CACHE_KEY = "fear_greed_crypto"


async def fetch_fear_greed_index() -> Optional[dict]:
    """
    Fetch Fear & Greed Index from alternative.me API.
    Returns cached data if available and fresh.
    """
    cached = home_cache.get(_CACHE_KEY)
    if cached is not None:
        return cached

    try:
        # Get current value and last 7 days for trend
        data = await get_json("https://api.alternative.me/fng/", params={"limit": 7})

        if data.get("data"):
            current = data["data"][0]
            history = data["data"][:7]

            result = {
                "value": int(current["value"]),
                "classification": current["value_classification"],
                "timestamp": datetime.fromtimestamp(int(current["timestamp"])).isoformat(),
                "history": [
                    {
                        "value": int(h["value"]),
                        "classification": h["value_classification"],
                        "date": datetime.fromtimestamp(int(h["timestamp"])).strftime("%Y-%m-%d"),
                    }
                    for h in history
                ],
            }

            home_cache.set(_CACHE_KEY, result, CACHE_DURATION_SECONDS)
            return result
    except Exception as e:
        logger.error("Error fetching Fear & Greed Index: %s", e)

    # Return stale data if available, otherwise None
    return home_cache.get_with_fallback(_CACHE_KEY)
