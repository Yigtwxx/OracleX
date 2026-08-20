"""
Watchlist Service
Handles CRUD operations for user watchlists and fetches real-time prices
for both Crypto (CoinGecko) and Stocks (Yahoo Finance).

**Watchlists are per user.** They used to live in a single
`backend/data/watchlist.json` with no `user_id` anywhere in this module, and
`routers/watchlist.py` exposed every endpoint with no auth dependency — so
every account saw, and could delete, every other account's lists. That was
survivable while nothing else read them; it stopped being survivable the moment
chat, which is authenticated, wanted one as a tool.

Storage is the `watchlists` table, which has been in the schema since migration
001 — with a `user_id`, RLS policies and an index — and which this module simply
never used. There was no missing table; there was a service that ignored the one
that already existed. Every function now takes the user id the caller's JWT was
verified against.

The JSON file is not read on any request path. `import_legacy_file` exists for
an operator who wants to hand the old lists to one account on purpose, because
the old store has no user to attribute them to.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from services import asset_registry
from services.stock_market_service import fetch_single_stock

logger = logging.getLogger(__name__)

# The pre-migration store. Read only by `import_legacy_file`, never on a
# request path — see the module docstring.
LEGACY_DATA_FILE = "data/watchlist.json"

# One user cannot have unbounded lists or unbounded symbols in them. Not a
# security boundary — RLS is — but a bound on what one account can make the
# price hydrator fetch on every poll.
MAX_LISTS_PER_USER = 20
MAX_ITEMS_PER_LIST = 100

VALID_ASSET_TYPES = ("STOCK", "CRYPTO")


def _load_legacy() -> List[Dict]:
    if not os.path.exists(LEGACY_DATA_FILE):
        return []
    try:
        with open(LEGACY_DATA_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def _clean_items(raw: Any) -> List[Dict[str, str]]:
    """
    The `items` column, reduced to entries this code will actually price.

    It is `jsonb` with no shape enforced by the database, and it has been
    writable by any authenticated client since migration 001 — so what comes out
    is treated like anything else that crossed a trust boundary: an unknown
    asset type is dropped rather than handed to a price fetcher, and duplicates
    are collapsed so one list cannot make the hydrator fetch the same quote
    fifty times.
    """
    if not isinstance(raw, list):
        return []

    cleaned: List[Dict[str, str]] = []
    seen: set = set()
    for entry in raw[:MAX_ITEMS_PER_LIST]:
        if not isinstance(entry, dict):
            continue
        symbol = str(entry.get("symbol") or "").strip().upper()
        asset_type = str(entry.get("type") or "CRYPTO").strip().upper()
        if not symbol or symbol in seen or asset_type not in VALID_ASSET_TYPES:
            continue
        seen.add(symbol)
        cleaned.append({"symbol": symbol, "type": asset_type})
    return cleaned


def _rows_to_lists(rows: List[Dict]) -> List[Dict]:
    """Table rows in the shape the price hydrator and the UI expect."""
    return [
        {
            "id": row["id"],
            "name": row.get("name") or "Watchlist",
            "items": _clean_items(row.get("items")),
        }
        for row in rows
    ]


async def get_watchlists(user_id: str) -> List[Dict]:
    """This user's watchlists, with current market data."""
    if not user_id:
        return []

    from services.supabase_service import get_supabase

    client = get_supabase()
    if client is None:
        logger.warning("Supabase is not configured; watchlists are unavailable")
        return []

    rows = (
        client.table("watchlists")
        .select("id, name, items")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .limit(MAX_LISTS_PER_USER)
        .execute()
    ).data or []
    if not rows:
        return []

    return await _hydrate_prices(_rows_to_lists(rows))


async def create_watchlist(user_id: str, name: str, items: List[Dict[str, str]]) -> List[Dict]:
    """
    Create a watchlist owned by `user_id`.

    items: List of {"symbol": "BTC", "type": "CRYPTO"}
    """
    if not user_id:
        raise PermissionError("a watchlist needs an owner")

    from services.supabase_service import get_supabase

    client = get_supabase()
    if client is None:
        raise RuntimeError("Supabase is not configured")

    # Cleaned before the insert rather than after the read, so the column never
    # comes to hold an entry this code would refuse to price.
    created = (
        client.table("watchlists")
        .insert(
            {
                "user_id": user_id,
                "name": (name or "").strip()[:80] or "Watchlist",
                "items": _clean_items(items),
            }
        )
        .execute()
    ).data
    if not created:
        raise RuntimeError("the watchlist could not be created")

    return await _hydrate_prices(_rows_to_lists(created))


async def delete_watchlist(user_id: str, list_id: str) -> Dict[str, str]:
    """
    Delete one of this user's watchlists.

    The `user_id` filter is the deletion's authorisation, not a convenience:
    the backend holds the service-role key, which bypasses RLS, so a delete
    without it would take any list whose id was guessed.
    """
    if not user_id:
        raise PermissionError("a watchlist needs an owner")

    from services.supabase_service import get_supabase

    client = get_supabase()
    if client is None:
        raise RuntimeError("Supabase is not configured")

    client.table("watchlists").delete().eq("id", list_id).eq("user_id", user_id).execute()
    return {"status": "success"}


async def watchlist_symbols(user_id: str) -> List[str]:
    """
    Just the symbols, for callers that do not need prices.

    `services.ownership.consensus.watchlist_overlap` and the chat tool both want
    this; hydrating prices for them would be a round of network work thrown away.
    """
    if not user_id:
        return []

    from services.supabase_service import get_supabase

    client = get_supabase()
    if client is None:
        return []

    rows = (client.table("watchlists").select("items").eq("user_id", user_id).execute()).data or []

    return sorted({item["symbol"] for row in rows for item in _clean_items(row.get("items"))})


async def import_legacy_file(user_id: str) -> Dict[str, int]:
    """
    Hand the pre-migration `data/watchlist.json` lists to one account.

    Not called from anywhere: the old store has no user to attribute its lists
    to, so which account should receive them is a decision an operator makes,
    not one this module can infer. Run it from a shell when that decision has
    been made.
    """
    legacy = _load_legacy()
    imported = 0
    for entry in legacy[:MAX_LISTS_PER_USER]:
        await create_watchlist(user_id, entry.get("name") or "Imported", entry.get("items") or [])
        imported += 1
    return {"imported": imported, "found": len(legacy)}


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
