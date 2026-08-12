"""Market Overview service using CoinGecko and Binance APIs."""

import asyncio
import logging
from datetime import datetime

import httpx

from services.cache import market_cache
from services.series import downsample

logger = logging.getLogger(__name__)

# TTL constants
CACHE_DURATION_SECONDS = 300  # 5 minutes (to avoid rate limiting)

# Number of top coins to display. 250 is CoinGecko's per-page ceiling, so this
# still costs exactly one request — going higher would mean paginating.
TOP_COINS_COUNT = 250


async def fetch_market_overview() -> dict:
    """
    Fetch market overview data from CoinGecko API (primary) with optional Binance volume data.
    Returns coin prices, 24h changes, logos, names, market caps, and market stats.
    """
    # Check cache
    cached = market_cache.get("market_overview")
    if cached is not None:
        return cached

    coins_data = []
    total_volume_24h = 0

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Fetch coins and global data in parallel
            coins_response, global_data = await asyncio.gather(
                client.get(
                    "https://api.coingecko.com/api/v3/coins/markets",
                    params={
                        "vs_currency": "usd",
                        "order": "market_cap_desc",
                        "per_page": TOP_COINS_COUNT,
                        "page": 1,
                        "sparkline": True,
                        "price_change_percentage": "24h,7d",
                    },
                    timeout=15.0,
                ),
                _fetch_global_market_data(client),
            )

            if coins_response.status_code == 200:
                coins = coins_response.json()

                for coin in coins:
                    symbol = coin.get("symbol", "").upper()
                    market_cap = coin.get("market_cap", 0) or 0
                    volume_24h = coin.get("total_volume", 0) or 0

                    total_volume_24h += volume_24h

                    # CoinGecko returns ~168 hourly points per coin. Note the
                    # singular key: the series is nested under
                    # `sparkline_in_7d.price`, not `.prices`.
                    sparkline = (coin.get("sparkline_in_7d") or {}).get("price") or []

                    coins_data.append(
                        {
                            "symbol": symbol,
                            "name": coin.get("name", symbol),
                            "logo": coin.get("image", ""),
                            "price": coin.get("current_price", 0) or 0,
                            "change_24h": coin.get("price_change_percentage_24h", 0) or 0,
                            # Left as None when CoinGecko has no 7d reading —
                            # coercing it to 0 would render as a flat week.
                            "change_7d": coin.get("price_change_percentage_7d_in_currency"),
                            "sparkline": downsample(sparkline),
                            "volume_24h": volume_24h,
                            "high_24h": coin.get("high_24h", 0) or 0,
                            "low_24h": coin.get("low_24h", 0) or 0,
                            "market_cap": market_cap,
                            "market_cap_rank": coin.get("market_cap_rank", 0) or 0,
                        }
                    )
            else:
                raise Exception(f"CoinGecko API returned status {coins_response.status_code}")

            result = {
                "coins": coins_data,
                "total_volume_24h": total_volume_24h,
                "total_market_cap": global_data.get("total_market_cap", 0),
                "btc_dominance": global_data.get("btc_dominance", 0),
                "eth_dominance": global_data.get("eth_dominance", 0),
                "active_cryptocurrencies": global_data.get("active_cryptocurrencies", 0),
                "timestamp": datetime.now().isoformat(),
            }

            # Update cache
            market_cache.set("market_overview", result, CACHE_DURATION_SECONDS)

            return result

    except Exception as e:
        logger.error("Error fetching market overview: %s", e)

    # Return stale data if available, otherwise return empty result
    stale = market_cache.get_with_fallback("market_overview")
    if stale:
        return stale

    # Fallback: return empty result when API fails and no cache
    return {
        "coins": [],
        "total_volume_24h": 0,
        "total_market_cap": 0,
        "btc_dominance": 0,
        "eth_dominance": 0,
        "active_cryptocurrencies": 0,
        "timestamp": datetime.now().isoformat(),
    }


async def _fetch_global_market_data(client: httpx.AsyncClient) -> dict:
    """Fetch global market data from CoinGecko."""
    try:
        response = await client.get("https://api.coingecko.com/api/v3/global", timeout=5.0)
        if response.status_code == 200:
            data = response.json().get("data", {})
            return {
                "total_market_cap": data.get("total_market_cap", {}).get("usd", 0),
                "btc_dominance": data.get("market_cap_percentage", {}).get("btc", 0),
                "eth_dominance": data.get("market_cap_percentage", {}).get("eth", 0),
                "active_cryptocurrencies": data.get("active_cryptocurrencies", 0),
            }
    except Exception as e:
        logger.warning("CoinGecko global API failed (non-critical): %s", e)

    return {}
