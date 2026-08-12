"""
Watchlist Service
Handles CRUD operations for user watchlists and fetches real-time prices
for both Crypto (CoinGecko) and Stocks (Yahoo Finance).
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Dict, List, Optional

import httpx

from services import asset_registry
from services.stock_market_service import fetch_single_stock

logger = logging.getLogger(__name__)

DATA_FILE = "data/watchlist.json"


# In-memory cache for simple persistence
def _load_db():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _save_db(data):
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


async def get_watchlists():
    """
    Get all watchlists with current market data.
    """
    watchlists = _load_db()
    if not watchlists:
        return []

    # Collect all symbols to fetch
    # For this MVP, we will try to detect type or store type in the watchlist item.

    # We'll assume the structure is:
    # { "id": "uuid", "name": "Tech", "items": [ {"symbol": "AAPL", "type": "STOCK"}, {"symbol": "BTC", "type": "CRYPTO"} ] }

    return await _hydrate_prices(watchlists)


async def create_watchlist(name: str, items: List[Dict[str, str]]):
    """
    Create a new watchlist.
    items: List of {"symbol": "BTC", "type": "CRYPTO"}
    """
    db = _load_db()
    new_list = {
        # A positional id collides with an existing list as soon as one is
        # deleted, which would make the next delete remove the wrong watchlist.
        "id": uuid.uuid4().hex,
        "name": name,
        "items": items,
    }
    db.append(new_list)
    _save_db(db)
    return await _hydrate_prices([new_list])


async def delete_watchlist(list_id: str):
    db = _load_db()
    new_db = [w for w in db if w["id"] != list_id]
    _save_db(new_db)
    return {"status": "success"}


# -----------------------------------------------------------------------------
# Smart Crypto Resolver
# -----------------------------------------------------------------------------


class CryptoSymbolResolver:
    """Thin adapter kept for call-site compatibility; the registry does the work."""

    async def resolve(self, symbol: str, client: httpx.AsyncClient) -> Optional[str]:
        return await asset_registry.resolve_coingecko_id(symbol, client)


# Simple robust cache for crypto prices to prevent 429s
_crypto_price_cache = {"data": {}, "timestamp": 0}
CACHE_DURATION = 60  # seconds
# How stale a cached quote may be when CoinGecko is rate-limiting us. Past this
# the symbol is reported as unpriced rather than shown at a long-dead price.
MAX_STALE_CRYPTO = 15 * 60  # seconds


def _fallback_crypto_prices(now: float) -> Dict[str, Dict]:
    """Last known crypto quotes, but only while they are still recent enough."""
    if now - _crypto_price_cache["timestamp"] > MAX_STALE_CRYPTO:
        logger.warning("Watchlist crypto cache too stale to serve; reporting no price")
        return {}
    return _crypto_price_cache["data"]


async def _hydrate_prices(watchlists):
    """
    Fetch current prices for all items in the watchlists.
    """
    # 1. Identify all unique assets
    unique_stocks = set()
    unique_cryptos = set()

    for w in watchlists:
        for item in w.get("items", []):
            if item["type"] == "STOCK":
                unique_stocks.add(item["symbol"])
            elif item["type"] == "CRYPTO":
                unique_cryptos.add(item["symbol"].upper())

    # 2. Fetch Data
    stock_data = {}
    crypto_data = {}

    resolver = CryptoSymbolResolver()

    async with httpx.AsyncClient() as client:
        # Stocks (Concurrent)
        tasks = [fetch_single_stock(client, sym) for sym in unique_stocks]
        stock_results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in stock_results:
            if isinstance(res, dict):
                stock_data[res["symbol"]] = res

        # Crypto with Caching
        if unique_cryptos:
            current_time = time.time()

            # The cache is only a shortcut when it is both fresh *and* covers every
            # symbol asked for. Serving a fresh-but-incomplete cache used to drop
            # the missing symbols to a $0.00 price.
            use_cache = _crypto_price_cache[
                "timestamp"
            ] > current_time - CACHE_DURATION and unique_cryptos.issubset(
                _crypto_price_cache["data"].keys()
            )

            if use_cache:
                crypto_data = _crypto_price_cache["data"]
            else:
                try:
                    # Resolve IDs first
                    ids_to_fetch = set()
                    symbol_id_map = {}  # SYMBOL -> ID

                    for sym in unique_cryptos:
                        c_id = await resolver.resolve(sym, client)
                        if c_id:
                            ids_to_fetch.add(c_id)
                            symbol_id_map[sym] = c_id

                    if ids_to_fetch:
                        response = await client.get(
                            "https://api.coingecko.com/api/v3/coins/markets",
                            params={
                                "vs_currency": "usd",
                                "ids": ",".join(ids_to_fetch),
                                "per_page": 250,
                                "sparkline": "false",
                                "order": "market_cap_desc",
                            },
                            headers={
                                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                                "Accept": "application/json",
                            },
                            # Slightly longer timeout
                            timeout=20,
                        )

                        if response.status_code == 200:
                            coins = response.json()
                            id_coin_map = {c["id"]: c for c in coins}

                            new_crypto_data = {}
                            for sym, c_id in symbol_id_map.items():
                                if c_id in id_coin_map:
                                    coin = id_coin_map[c_id]
                                    new_crypto_data[sym] = {
                                        # A quote CoinGecko omitted stays None; the
                                        # widget shows "—" instead of a $0.00 price.
                                        "price": coin.get("current_price"),
                                        "change_24h": coin.get("price_change_percentage_24h"),
                                        "market_cap": coin.get("market_cap"),
                                        "logo": coin.get("image", ""),
                                        "name": coin.get("name", sym),
                                    }

                            # Update Cache
                            _crypto_price_cache["data"] = new_crypto_data
                            _crypto_price_cache["timestamp"] = current_time
                            crypto_data = new_crypto_data
                        elif response.status_code == 429:
                            logger.warning(
                                "Watchlist crypto fetch rate limited (429). Using cache/fallback."
                            )
                            crypto_data = _fallback_crypto_prices(current_time)
                        else:
                            logger.error(
                                f"Watchlist crypto fetch failed with status: {response.status_code}"
                            )
                            crypto_data = _fallback_crypto_prices(current_time)

                except Exception as e:
                    logger.error(f"Watchlist crypto fetch error: {e}")
                    # Fallback to cache on error
                    crypto_data = _fallback_crypto_prices(current_time)

    # 3. Merge Data back
    # Logo/name fallbacks come from the live registry rather than a static map,
    # so an asset added to a watchlist today still renders correctly.
    crypto_meta = await asset_registry.get_crypto_metadata()

    hydrated_lists = []
    for w in watchlists:
        hydrated_items = []
        for item in w.get("items", []):
            sym = item["symbol"]
            # price/change stay None until a real quote resolves. Seeding them with
            # 0 rendered an unresolved symbol as "$0.00" next to a green "+0.00%".
            obj = {
                "symbol": sym,
                "type": item["type"],
                "price": None,
                "change_24h": None,
                "logo": "",
                "name": sym,
            }

            if item["type"] == "STOCK":
                if sym in stock_data:
                    d = stock_data[sym]
                    obj.update(
                        {
                            "price": d["price"],
                            "change_24h": d["change_24h"],
                            "logo": d.get("logo", ""),
                            "name": d.get("name", sym),
                        }
                    )
                if not obj["logo"]:
                    obj["logo"] = asset_registry.build_stock_logo_url(sym)

            elif item["type"] == "CRYPTO":
                c_sym = sym.upper()
                # Check current fetch OR cache
                if c_sym in crypto_data:
                    d = crypto_data[c_sym]
                    obj.update(
                        {
                            "price": d["price"],
                            "change_24h": d["change_24h"],
                            "logo": d["logo"],
                            "name": d["name"],
                        }
                    )
                elif c_sym in _fallback_crypto_prices(time.time()):
                    # Fallback to a still-recent cached quote if the fetch missed it
                    d = _crypto_price_cache["data"][c_sym]
                    obj.update(
                        {
                            "price": d["price"],
                            "change_24h": d["change_24h"],
                            "logo": d["logo"],
                            "name": d["name"],
                        }
                    )

                if not obj["logo"] and c_sym in crypto_meta:
                    meta = crypto_meta[c_sym]
                    obj["logo"] = meta.get("logo", "")
                    if obj["name"] == c_sym:
                        obj["name"] = meta.get("name", c_sym)

            hydrated_items.append(obj)

        hydrated_lists.append({"id": w["id"], "name": w["name"], "items": hydrated_items})

    return hydrated_lists
