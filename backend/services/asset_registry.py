"""
Asset Registry — single source of truth for the tradable asset universe.

Every user-visible asset list (which coins the overview shows, which stocks the
NASDAQ page ranks, which pairs the WebSocket streams) is resolved here from a
live API instead of a hardcoded literal, so a newly launched coin or a stock
that climbs into the top ranks shows up without a code change.

Resolution order for every getter:
    1. in-memory TTL cache
    2. on-disk cache (data/registry/*.json) — survives restarts and API outages
    3. a tiny emergency seed — just enough for the app to render if a cold start
       coincides with an API outage

Data sources:
    - CoinGecko  /coins/markets      → crypto universe (id, symbol, name, logo)
    - CoinGecko  /search             → symbol → coin id for anything off the list
    - NASDAQ     /api/screener/stocks→ stock universe (symbol, name, sector)
    - Binance    /api/v3/ticker/24hr → most liquid spot pairs, by quote volume
    - OKX        /market/tickers     → spot pairs where Binance is unreachable,
                                       and the most liquid perpetuals by notional
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Optional

import httpx

from services.cache import ServiceCache

logger = logging.getLogger(__name__)

registry_cache = ServiceCache(maxsize=32)

# ── TTLs ────────────────────────────────────────────────────────────────────
CRYPTO_UNIVERSE_TTL = 3600  # 1 hour — market-cap ranking moves slowly
STOCK_UNIVERSE_TTL = 86400  # 24 hours — the NASDAQ listing changes rarely
# Quotes come off the same screener payload as the universe but expire far
# sooner: the ranking is stable for a day, the prices in it are not.
STOCK_QUOTES_TTL = 300  # 5 minutes
SPOT_PAIRS_TTL = 3600  # 1 hour
OKX_SWAPS_TTL = 3600  # 1 hour

# ── Endpoints ───────────────────────────────────────────────────────────────
COINGECKO_API = "https://api.coingecko.com/api/v3"
NASDAQ_SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks"
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"
OKX_TICKERS_URL = "https://www.okx.com/api/v5/market/tickers"
OKX_INSTRUMENTS_URL = "https://www.okx.com/api/v5/public/instruments"
# OKX instCategory: "1" crypto, "3" tokenised equities, "4" commodities.
OKX_CRYPTO_INST_CATEGORY = "1"

# Both nasdaq.com and stockanalysis.com reject requests without a browser UA.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# ── Disk cache ──────────────────────────────────────────────────────────────
# Anchored to the backend package rather than the working directory. These paths
# used to be CWD-relative, so launching from the repo root and from `backend/`
# silently produced two separate caches — every stored score, sector and symbol
# map written under one of them was invisible to the other.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_BACKEND_DIR, "data")
REGISTRY_DIR = os.path.join(DATA_DIR, "registry")
CRYPTO_UNIVERSE_FILE = os.path.join(REGISTRY_DIR, "crypto_universe.json")
STOCK_UNIVERSE_FILE = os.path.join(REGISTRY_DIR, "stock_universe.json")
STOCK_QUOTES_FILE = os.path.join(REGISTRY_DIR, "stock_quotes.json")
SPOT_PAIRS_FILE = os.path.join(REGISTRY_DIR, "spot_pairs.json")
OKX_SWAPS_FILE = os.path.join(REGISTRY_DIR, "okx_swaps.json")
LISTED_BASES_FILE = os.path.join(REGISTRY_DIR, "listed_bases.json")
US_EQUITY_INDEX_FILE = os.path.join(REGISTRY_DIR, "us_equities.json")
# Shared with the legacy watchlist resolver, which already populates this file.
SYMBOL_MAP_FILE = os.path.join(DATA_DIR, "crypto_symbol_map.json")

# ── Emergency seeds ─────────────────────────────────────────────────────────
# Deliberately tiny. These exist so a cold start during an API outage renders
# *something* rather than an empty page — they are not a maintained asset list.
_SEED_CRYPTO: list[dict[str, Any]] = [
    {"id": "bitcoin", "symbol": "BTC", "name": "Bitcoin", "logo": "", "market_cap": 0, "rank": 1},
    {"id": "ethereum", "symbol": "ETH", "name": "Ethereum", "logo": "", "market_cap": 0, "rank": 2},
    {"id": "tether", "symbol": "USDT", "name": "Tether", "logo": "", "market_cap": 0, "rank": 3},
    {"id": "binancecoin", "symbol": "BNB", "name": "BNB", "logo": "", "market_cap": 0, "rank": 4},
    {"id": "solana", "symbol": "SOL", "name": "Solana", "logo": "", "market_cap": 0, "rank": 5},
    {"id": "ripple", "symbol": "XRP", "name": "XRP", "logo": "", "market_cap": 0, "rank": 6},
]

_SEED_STOCKS: list[dict[str, Any]] = [
    {"symbol": "NVDA", "name": "NVIDIA Corporation", "sector": "Technology", "market_cap": 0},
    {"symbol": "AAPL", "name": "Apple Inc.", "sector": "Technology", "market_cap": 0},
    {"symbol": "MSFT", "name": "Microsoft Corporation", "sector": "Technology", "market_cap": 0},
    {"symbol": "GOOGL", "name": "Alphabet Inc.", "sector": "Technology", "market_cap": 0},
    {
        "symbol": "AMZN",
        "name": "Amazon.com Inc.",
        "sector": "Consumer Discretionary",
        "market_cap": 0,
    },
    {"symbol": "META", "name": "Meta Platforms Inc.", "sector": "Technology", "market_cap": 0},
]

_SEED_PAIRS: list[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

_SEED_PERP_SYMBOLS: list[str] = ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "ADA", "LTC"]

# Quote-side / pegged assets that would otherwise dominate a volume ranking with
# a flat ~$1 price. This is a currency filter, not an asset list — a newly
# launched token never needs to be added here.
#
# USDT belongs here even though the pair filters below never see it as a base:
# on Binance it is always the quote side. Consumers that rank assets directly
# rather than through trading pairs — the heatmap board — do meet it, and it is
# the one they most need to recognise.
STABLECOIN_BASES = frozenset(
    {
        "USDT",
        "USDC",
        "FDUSD",
        "TUSD",
        "BUSD",
        "DAI",
        "USD1",
        "USDP",
        "EUR",
        "EURI",
        "AEUR",
        "USDE",
    }
)

# ── Global indices ──────────────────────────────────────────────────────────
# A fixed taxonomy rather than a dynamic universe: the world's benchmark indices
# do not change month to month. Defined once here because it previously existed
# in two places with diverging contents.
GLOBAL_INDICES: dict[str, dict[str, str]] = {
    "^GSPC": {"name": "S&P 500", "region": "US"},
    "^IXIC": {"name": "NASDAQ", "region": "US"},
    "^DJI": {"name": "Dow Jones", "region": "US"},
    "^FTSE": {"name": "FTSE 100", "region": "UK"},
    "^GDAXI": {"name": "DAX", "region": "DE"},
    "^N225": {"name": "Nikkei 225", "region": "JP"},
    "^HSI": {"name": "Hang Seng", "region": "HK"},
    "^STOXX50E": {"name": "Euro Stoxx 50", "region": "EU"},
    "^FCHI": {"name": "CAC 40", "region": "FR"},
    "^AXJO": {"name": "ASX 200", "region": "AU"},
    # Not an equity index, but it belongs to the same board: the dollar is the
    # denominator every other row on the macro page is quoted in.
    "DX-Y.NYB": {"name": "US Dollar Index", "region": "US"},
    "XU100.IS": {"name": "BIST 100", "region": "TR"},
}


# ── Macro commodities ───────────────────────────────────────────────────────
# The same kind of fixed taxonomy as GLOBAL_INDICES: front-month futures for the
# benchmarks a macro reader watches. There is no API to resolve this from, and
# it is not a ranked universe, so it is a literal rather than a registry cache.
#
# `unit` is the unit the quote arrives in, NOT a conversion instruction. Yahoo
# returns grains and softs in USX (US cents per bushel/pound) and metals in USD.
# The number is displayed in its native unit with this label beside it, rather
# than silently divided by 100 — a coffee price of 325.90 is 325.90 US cents,
# and rewriting it as 3.26 would be a claim the upstream never made.
MACRO_COMMODITIES: dict[str, dict[str, str]] = {
    # Precious and industrial metals
    "GC=F": {"name": "Gold", "group": "metals", "unit": "USD/oz"},
    "SI=F": {"name": "Silver", "group": "metals", "unit": "USD/oz"},
    "PL=F": {"name": "Platinum", "group": "metals", "unit": "USD/oz"},
    "PA=F": {"name": "Palladium", "group": "metals", "unit": "USD/oz"},
    "HG=F": {"name": "Copper", "group": "metals", "unit": "USD/lb"},
    # Energy
    "CL=F": {"name": "WTI Crude", "group": "energy", "unit": "USD/bbl"},
    "BZ=F": {"name": "Brent Crude", "group": "energy", "unit": "USD/bbl"},
    "NG=F": {"name": "Natural Gas", "group": "energy", "unit": "USD/MMBtu"},
    # Agriculture
    "ZW=F": {"name": "Wheat", "group": "agriculture", "unit": "USc/bu"},
    "ZC=F": {"name": "Corn", "group": "agriculture", "unit": "USc/bu"},
    "ZS=F": {"name": "Soybeans", "group": "agriculture", "unit": "USc/bu"},
    "KC=F": {"name": "Coffee", "group": "agriculture", "unit": "USc/lb"},
    "SB=F": {"name": "Sugar #11", "group": "agriculture", "unit": "USc/lb"},
    "CT=F": {"name": "Cotton", "group": "agriculture", "unit": "USc/lb"},
}


# ═══════════════════════════════════════════════════════════════════════════
# Disk cache helpers
# ═══════════════════════════════════════════════════════════════════════════


def _legacy_path(path: str) -> Optional[str]:
    """
    The pre-migration, working-directory-relative location of `path`.

    Returns None once `path` is no longer under the backend data directory, so
    callers passing an unrelated path get no surprise second lookup.
    """
    try:
        relative = os.path.relpath(path, _BACKEND_DIR)
    except ValueError:  # different drive on Windows
        return None
    if relative.startswith(os.pardir):
        return None
    return relative


def read_json_cache(path: str) -> Optional[Any]:
    """Read a JSON disk-cache file, or None if missing/corrupt."""
    if not os.path.exists(path):
        # These files used to live wherever the process happened to be started
        # from. Read that copy once so an upgrade does not throw away a cache
        # that took hours of rate-limited requests to build; the next write
        # lands at the canonical path.
        legacy = _legacy_path(path)
        if not legacy or not os.path.exists(legacy):
            return None
        logger.info("Registry cache found at legacy path %s — migrating to %s", legacy, path)
        path = legacy
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data or None
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Registry disk cache unreadable (%s): %s", path, e)
        return None


def write_json_cache(path: str, data: Any) -> None:
    """
    Persist a registry payload so restarts and API outages stay covered.

    Written to a sibling temporary file and moved into place, because the
    previous truncate-then-dump left a half-written file behind whenever two
    writers overlapped or the process died mid-dump — and `read_json_cache`
    discards a corrupt file wholesale, blanking every score stored in it.
    `os.replace` is atomic within a filesystem, so a reader sees either the old
    payload or the new one.
    """
    directory = os.path.dirname(path) or "."
    tmp_path = f"{path}.tmp"
    try:
        os.makedirs(directory, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)
    except OSError as e:
        logger.warning("Could not persist registry cache (%s): %s", path, e)
        try:
            os.remove(tmp_path)
        except OSError:
            pass


async def _resolve(
    cache_key: str,
    disk_path: str,
    ttl: int,
    fetch: Any,
    seed: Any,
    label: str,
) -> Any:
    """
    Run the shared three-layer resolution: memory → live API → disk → seed.

    `fetch` is an async callable returning the fresh payload, or None on failure.
    """
    cached = registry_cache.get(cache_key)
    if cached:
        return cached

    try:
        fresh = await fetch()
    except Exception as e:  # network, parsing, rate limiting — all non-fatal
        logger.error("%s fetch failed: %s", label, e)
        fresh = None

    if fresh:
        registry_cache.set(cache_key, fresh, ttl)
        write_json_cache(disk_path, fresh)
        return fresh

    stale = registry_cache.get_with_fallback(cache_key)
    if stale:
        logger.warning("%s: serving stale in-memory data", label)
        return stale

    from_disk = read_json_cache(disk_path)
    if from_disk:
        logger.warning("%s: serving disk cache (%s)", label, disk_path)
        registry_cache.set(cache_key, from_disk, ttl)
        return from_disk

    logger.error("%s: falling back to emergency seed", label)
    return seed


# ═══════════════════════════════════════════════════════════════════════════
# Crypto universe
# ═══════════════════════════════════════════════════════════════════════════


async def _fetch_crypto_universe() -> Optional[list[dict[str, Any]]]:
    """Fetch the top coins by market cap from CoinGecko."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{COINGECKO_API}/coins/markets",
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 250,
                "page": 1,
                "sparkline": "false",
            },
        )
        if response.status_code != 200:
            logger.warning("CoinGecko markets returned HTTP %s", response.status_code)
            return None

        coins = response.json()
        return [
            {
                "id": coin["id"],
                "symbol": (coin.get("symbol") or "").upper(),
                "name": coin.get("name") or coin.get("id"),
                "logo": coin.get("image") or "",
                "market_cap": coin.get("market_cap") or 0,
                "rank": coin.get("market_cap_rank") or 0,
            }
            for coin in coins
            if coin.get("id") and coin.get("symbol")
        ]


async def get_crypto_universe(limit: int = 250) -> list[dict[str, Any]]:
    """Top `limit` coins by market cap: id, symbol, name, logo, market_cap, rank."""
    universe = await _resolve(
        cache_key="crypto_universe",
        disk_path=CRYPTO_UNIVERSE_FILE,
        ttl=CRYPTO_UNIVERSE_TTL,
        fetch=_fetch_crypto_universe,
        seed=_SEED_CRYPTO,
        label="Crypto universe",
    )
    return universe[:limit]


async def get_crypto_symbols(limit: int = 50) -> list[str]:
    """Ticker symbols of the top `limit` coins, market-cap ordered."""
    return [coin["symbol"] for coin in await get_crypto_universe(limit)]


async def get_crypto_metadata(limit: int = 250) -> dict[str, dict[str, Any]]:
    """Symbol → coin record, for name/logo lookups."""
    return {coin["symbol"]: coin for coin in await get_crypto_universe(limit)}


# ═══════════════════════════════════════════════════════════════════════════
# Symbol → CoinGecko id
# ═══════════════════════════════════════════════════════════════════════════


async def _search_coingecko_id(symbol: str, client: httpx.AsyncClient) -> Optional[str]:
    """Look a symbol up via CoinGecko's search endpoint, preferring exact matches."""
    response = await client.get(
        f"{COINGECKO_API}/search",
        params={"query": symbol},
        headers={"User-Agent": "Oracle-X/1.0"},
    )
    if response.status_code != 200:
        return None

    coins = response.json().get("coins", [])
    if not coins:
        return None

    # Results are roughly market-cap ordered; prefer an exact ticker match.
    for coin in coins:
        if (coin.get("symbol") or "").upper() == symbol:
            return coin.get("id")
    return coins[0].get("id")


async def resolve_coingecko_id(
    symbol: str, client: Optional[httpx.AsyncClient] = None
) -> Optional[str]:
    """
    Resolve a ticker to its CoinGecko id.

    Checks the live top-250 universe first, then the learned on-disk map, then
    falls back to CoinGecko search — persisting whatever it learns so the same
    symbol resolves offline next time.
    """
    symbol = symbol.upper()

    universe = await get_crypto_universe()
    for coin in universe:
        if coin["symbol"] == symbol:
            return coin["id"]

    learned: dict[str, str] = read_json_cache(SYMBOL_MAP_FILE) or {}
    if symbol in learned:
        return learned[symbol]

    try:
        if client is not None:
            coin_id = await _search_coingecko_id(symbol, client)
        else:
            async with httpx.AsyncClient(timeout=10.0) as own_client:
                coin_id = await _search_coingecko_id(symbol, own_client)
    except Exception as e:
        logger.error("CoinGecko search failed for %s: %s", symbol, e)
        return None

    if coin_id:
        learned[symbol] = coin_id
        write_json_cache(SYMBOL_MAP_FILE, learned)
    return coin_id


# ═══════════════════════════════════════════════════════════════════════════
# Stock universe
# ═══════════════════════════════════════════════════════════════════════════


def _parse_money(value: Any) -> float:
    """Parse a screener currency field: comma-grouped, dollar-prefixed strings."""
    if value is None:
        return 0.0
    try:
        return float(str(value).replace(",", "").replace("$", "").strip() or 0)
    except ValueError:
        return 0.0


def _parse_percent(value: Any) -> float:
    """Parse the screener's `pctchange`, e.g. "0.095%" or "" for untraded rows."""
    if value is None:
        return 0.0
    try:
        return float(str(value).replace("%", "").replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def _parse_volume(value: Any) -> float:
    """Parse the screener's share volume, which arrives as a plain digit string."""
    if value is None:
        return 0.0
    try:
        return float(str(value).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


async def _fetch_screener_rows(
    exchange: str, client: Optional[httpx.AsyncClient] = None
) -> Optional[list[dict[str, Any]]]:
    """Raw rows from the NASDAQ screener for one exchange (NASDAQ, NYSE, AMEX)."""

    async def _get(c: httpx.AsyncClient) -> Optional[list[dict[str, Any]]]:
        response = await c.get(
            NASDAQ_SCREENER_URL,
            params={
                "tableonly": "false",
                "limit": 5000,
                "offset": 0,
                "exchange": exchange,
                "download": "true",
            },
            headers=_BROWSER_HEADERS,
        )
        if response.status_code != 200:
            logger.warning("%s screener returned HTTP %s", exchange, response.status_code)
            return None
        return (response.json().get("data") or {}).get("rows") or []

    if client is not None:
        return await _get(client)
    async with httpx.AsyncClient(timeout=25.0) as own_client:
        return await _get(own_client)


async def _fetch_stock_universe() -> Optional[list[dict[str, Any]]]:
    """Fetch NASDAQ-listed stocks from the exchange's own screener API."""
    rows = await _fetch_screener_rows("NASDAQ")
    if not rows:
        return None

    stocks = [
        {
            "symbol": row["symbol"].strip().upper(),
            "name": _clean_company_name(row.get("name") or row["symbol"]),
            "sector": (row.get("sector") or "").strip() or "Other",
            "market_cap": _parse_money(row.get("marketCap")),
        }
        for row in rows
        if row.get("symbol") and _parse_money(row.get("marketCap")) > 0
    ]
    if not stocks:
        return None

    stocks.sort(key=lambda s: s["market_cap"], reverse=True)
    # The full listing is ~4000 rows; only the head is ever displayed.
    return stocks[:250]


def _clean_company_name(raw: str) -> str:
    """Strip the screener's share-class boilerplate from a company name."""
    name = raw.strip()
    for suffix in (
        " Common Stock",
        " Capital Stock",
        " Ordinary Shares",
        " Class A",
        " Class C",
        " Class B",
    ):
        name = name.replace(suffix, "")
    return name.strip() or raw.strip()


async def get_stock_universe(limit: int = 50) -> list[dict[str, Any]]:
    """Top `limit` NASDAQ stocks by market cap: symbol, name, sector, market_cap."""
    universe = await _resolve(
        cache_key="stock_universe",
        disk_path=STOCK_UNIVERSE_FILE,
        ttl=STOCK_UNIVERSE_TTL,
        fetch=_fetch_stock_universe,
        seed=_SEED_STOCKS,
        label="Stock universe",
    )
    return universe[:limit]


async def get_stock_symbols(limit: int = 30) -> list[str]:
    """Ticker symbols of the top `limit` NASDAQ stocks, market-cap ordered."""
    return [stock["symbol"] for stock in await get_stock_universe(limit)]


async def get_stock_metadata(limit: int = 250) -> dict[str, dict[str, Any]]:
    """Symbol → stock record, for name/sector lookups."""
    return {stock["symbol"]: stock for stock in await get_stock_universe(limit)}


# ── Stock quotes ────────────────────────────────────────────────────────────
#
# The screener response already carries a price, a percent change and a share
# volume for every row, so quoting the whole top-250 costs the same single
# request the universe already makes. This is what makes a 250-row overview
# affordable — the alternative is one per-ticker request each refresh.
#
# Separate from `stock_universe` only because of TTL: the ranking is cached for
# a day, these numbers for five minutes.


async def _fetch_stock_quotes() -> Optional[dict[str, dict[str, float]]]:
    """Latest price/change/volume per NASDAQ symbol, from the exchange screener."""
    rows = await _fetch_screener_rows("NASDAQ")
    if not rows:
        return None

    quotes: dict[str, dict[str, float]] = {}
    for row in rows:
        symbol = (row.get("symbol") or "").strip().upper()
        price = _parse_money(row.get("lastsale"))
        if not symbol or price <= 0:
            continue
        quotes[symbol] = {
            "price": price,
            "change_pct": _parse_percent(row.get("pctchange")),
            # `volume` is in shares; the overview reports dollar volume.
            "volume": _parse_volume(row.get("volume")),
        }
    return quotes or None


async def get_stock_quotes() -> dict[str, dict[str, float]]:
    """Symbol → {price, change_pct, volume} for every quoted NASDAQ listing."""
    return await _resolve(
        cache_key="stock_quotes",
        disk_path=STOCK_QUOTES_FILE,
        ttl=STOCK_QUOTES_TTL,
        fetch=_fetch_stock_quotes,
        # No seed: a missing quote leaves a row to fall back on its other
        # sources, which is better than inventing a price.
        seed={},
        label="Stock quotes",
    )


# ═══════════════════════════════════════════════════════════════════════════
# US equity index — the *validation* listing, not a ranking
# ═══════════════════════════════════════════════════════════════════════════
#
# `get_stock_universe` above is a top-250 NASDAQ ranking: it answers "what
# should the NASDAQ page show". That is the wrong question for attribution,
# which needs "is NYSE:JPM a real ticker, and which exchange is it on" — a
# question the ranking cannot answer at all for the NYSE half of the market.
# Hence a second, wider listing keyed by symbol.

# Ordinary common-stock tickers. The screener also returns warrants, units and
# preferred shares ("AACT^U", "BRK/B"), which are not what a news headline
# means when it names a company.
_TICKER_RE = re.compile(r"^[A-Z][A-Z.]{0,5}$")


def _normalise_ticker(raw: str) -> str:
    """
    Screener ticker → the form TradingView and Yahoo use.

    Share classes come back slash-separated ("BRK/B"); everywhere else in this
    app, and on the venues themselves, they are dotted.
    """
    return raw.strip().upper().replace("/", ".")


async def _fetch_us_equity_index() -> Optional[dict[str, dict[str, Any]]]:
    """Symbol → {name, exchange, market_cap} across the NASDAQ and NYSE listings."""
    async with httpx.AsyncClient(timeout=25.0) as client:
        results = await asyncio.gather(
            _fetch_screener_rows("NASDAQ", client),
            _fetch_screener_rows("NYSE", client),
            return_exceptions=True,
        )

    index: dict[str, dict[str, Any]] = {}
    for exchange, rows in zip(("NASDAQ", "NYSE"), results):
        if isinstance(rows, Exception):
            logger.warning("%s listing unavailable: %s", exchange, rows)
            continue
        for row in rows or []:
            symbol = _normalise_ticker(row.get("symbol") or "")
            if not _TICKER_RE.match(symbol) or symbol in index:
                continue
            index[symbol] = {
                "name": _clean_company_name(row.get("name") or symbol),
                "exchange": exchange,
                # Carried so name matching can prefer the company a headline is
                # overwhelmingly more likely to mean: "Apple" is Apple Inc., not
                # Apple Hospitality REIT.
                "market_cap": _parse_money(row.get("marketCap")),
            }

    return index or None


async def get_us_equity_index() -> Optional[dict[str, dict[str, Any]]]:
    """
    Every NASDAQ- and NYSE-listed common stock, as symbol → record.

    Returns None when the listing could not be resolved from any layer. That is
    deliberately distinct from an empty dict: callers must be able to tell "this
    ticker is not listed" from "we currently cannot tell", and answer the second
    case differently from the first.
    """
    return await _resolve(
        cache_key="us_equity_index",
        disk_path=US_EQUITY_INDEX_FILE,
        ttl=STOCK_UNIVERSE_TTL,
        fetch=_fetch_us_equity_index,
        seed=None,
        label="US equity index",
    )


async def equity_exchange(symbol: str) -> Optional[str]:
    """
    The exchange a US ticker trades on ("NASDAQ" / "NYSE"), or None.

    None means either "not a listed common stock" or "listing unavailable" —
    use `get_us_equity_index() is None` to tell the two apart.
    """
    index = await get_us_equity_index()
    if not index:
        return None
    record = index.get(symbol.upper())
    return record["exchange"] if record else None


async def is_known_stock(symbol: str) -> bool:
    """True if the symbol is a US listing or a tracked global index."""
    symbol = symbol.upper()
    if symbol in GLOBAL_INDICES:
        return True
    if await equity_exchange(symbol):
        return True
    return symbol in await get_stock_metadata()


def build_stock_logo_url(symbol: str) -> str:
    """Logo URL for a stock ticker, with a generated avatar as the fallback."""
    if not symbol:
        return ""
    # Indices, futures (GC=F) and foreign listings (XU100.IS) have no company
    # logo on the stock-image host; asking for one only yields a 404 the browser
    # renders as a broken image, so they go straight to the generated avatar.
    if symbol.startswith("^") or "=" in symbol or "." in symbol:
        return _avatar_url(symbol.lstrip("^").split("=")[0].split(".")[0])
    return f"https://financialmodelingprep.com/image-stock/{symbol.upper()}.png"


def _avatar_url(label: str) -> str:
    return f"https://ui-avatars.com/api/?name={label}&background=4f46e5&color=fff&size=64&bold=true"


# ═══════════════════════════════════════════════════════════════════════════
# Spot pairs
# ═══════════════════════════════════════════════════════════════════════════


async def _fetch_binance_pairs() -> Optional[dict[str, list[str]]]:
    """Rank Binance spot pairs by 24h quote volume, grouped by quote currency."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(BINANCE_TICKER_URL)
        if response.status_code != 200:
            logger.warning("Binance ticker returned HTTP %s", response.status_code)
            return None

        tickers = response.json()

    by_quote: dict[str, list[tuple[str, float]]] = {}
    for ticker in tickers:
        symbol = ticker.get("symbol") or ""
        for quote in ("USDT", "USDC", "BTC"):
            if not symbol.endswith(quote):
                continue
            base = symbol[: -len(quote)]
            if not base or base in STABLECOIN_BASES:
                break
            try:
                volume = float(ticker.get("quoteVolume") or 0)
            except (TypeError, ValueError):
                volume = 0.0
            by_quote.setdefault(quote, []).append((symbol, volume))
            break

    if not by_quote:
        return None

    return {
        quote: [symbol for symbol, _ in sorted(pairs, key=lambda p: p[1], reverse=True)[:100]]
        for quote, pairs in by_quote.items()
    }


async def _fetch_okx_spot_pairs() -> Optional[dict[str, list[str]]]:
    """
    Rank OKX spot pairs by 24h quote volume, grouped by quote currency.

    Unlike the swap endpoint, `volCcy24h` is already denominated in the quote
    currency for spot, so it is a USD figure for -USDT pairs and can be ranked
    on directly.

    OKX also lists tokenised equities (XSNDK, XSPCX…) and commodities (XAUT) as
    ordinary -USDT spot pairs, and several rank inside the top fifteen by
    volume. They are excluded by `instCategory`, which only the instruments
    endpoint carries — the same filter the perpetuals ranking uses.
    """
    async with httpx.AsyncClient(timeout=20.0) as client:
        tickers_response, instruments_response = await asyncio.gather(
            client.get(OKX_TICKERS_URL, params={"instType": "SPOT"}),
            client.get(OKX_INSTRUMENTS_URL, params={"instType": "SPOT"}),
        )

    for label, response in (("tickers", tickers_response), ("instruments", instruments_response)):
        if response.status_code != 200:
            logger.warning("OKX spot %s returned HTTP %s", label, response.status_code)
            return None

    payload = tickers_response.json()
    instruments = instruments_response.json()
    if payload.get("code") != "0" or instruments.get("code") != "0":
        logger.warning("OKX rejected the spot listing request")
        return None

    crypto_inst_ids = {
        instrument.get("instId")
        for instrument in instruments.get("data") or []
        if instrument.get("instCategory") == OKX_CRYPTO_INST_CATEGORY
    }

    by_quote: dict[str, list[tuple[str, float]]] = {}
    for ticker in payload.get("data") or []:
        inst_id = ticker.get("instId") or ""
        if inst_id not in crypto_inst_ids:
            continue
        base, _, quote = inst_id.partition("-")
        if quote not in ("USDT", "USDC", "BTC") or not base or base in STABLECOIN_BASES:
            continue
        try:
            volume = float(ticker.get("volCcy24h") or 0)
        except (TypeError, ValueError):
            volume = 0.0
        # Stored without the separator so the shape matches the Binance source.
        by_quote.setdefault(quote, []).append((f"{base}{quote}", volume))

    if not by_quote:
        return None

    return {
        quote: [symbol for symbol, _ in sorted(pairs, key=lambda p: p[1], reverse=True)[:100]]
        for quote, pairs in by_quote.items()
    }


async def _fetch_spot_pairs() -> Optional[dict[str, list[str]]]:
    """
    The most liquid spot pairs, from whichever exchange answers.

    Binance is the richer listing and stays the first choice, but it is
    unreachable from some networks entirely — where it is, falling through to
    OKX keeps a live volume ranking rather than dropping to the emergency seed,
    which is five symbols and not a maintained list.
    """
    for label, fetch in (("Binance", _fetch_binance_pairs), ("OKX", _fetch_okx_spot_pairs)):
        try:
            pairs = await fetch()
        except Exception as e:  # unreachable host, TLS failure, malformed body
            # A blocked host raises ConnectError with an empty message, so the
            # type is what actually identifies the failure here.
            logger.warning(
                "%s spot pairs unavailable (%s: %s) — trying the next source",
                label,
                type(e).__name__,
                e or "no detail",
            )
            continue
        if pairs:
            return pairs
        logger.warning("%s returned no usable spot pairs — trying the next source", label)
    return None


async def get_top_spot_pairs(
    limit: int = 15, quote: str = "USDT", slash: bool = False
) -> list[str]:
    """
    Most liquid spot pairs for a quote currency, by 24h volume.

    `slash=True` returns CCXT-style "BTC/USDT" instead of "BTCUSDT".
    """
    seed = {"USDT": _SEED_PAIRS}
    ranked = await _resolve(
        cache_key="spot_pairs",
        disk_path=SPOT_PAIRS_FILE,
        ttl=SPOT_PAIRS_TTL,
        fetch=_fetch_spot_pairs,
        seed=seed,
        label="Spot pairs",
    )
    pairs = (ranked.get(quote) or ranked.get("USDT") or _SEED_PAIRS)[:limit]
    if slash:
        return [f"{p[: -len(quote)]}/{quote}" for p in pairs]
    return list(pairs)


# ═══════════════════════════════════════════════════════════════════════════
# Listed spot bases — the *validation* listing, not a ranking
# ═══════════════════════════════════════════════════════════════════════════
#
# `get_top_spot_pairs` answers "what is trading heaviest right now" and folds
# both exchanges into one list, keeping only the top hundred. Attribution needs
# the opposite: the complete listing, per exchange, so a detected ticker can be
# confirmed to exist and be pointed at an exchange that actually carries it.
# Without this, everything not in a seven-token hardcoded set was labelled
# BINANCE: and charted as an invalid symbol whenever Binance did not list it.


async def _fetch_binance_bases() -> list[str]:
    """Base assets of every Binance USDT spot pair."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(BINANCE_TICKER_URL)
        if response.status_code != 200:
            logger.warning("Binance ticker returned HTTP %s", response.status_code)
            return []
        tickers = response.json()

    bases: set[str] = set()
    for ticker in tickers:
        symbol = ticker.get("symbol") or ""
        if not symbol.endswith("USDT"):
            continue
        base = symbol[: -len("USDT")]
        if base and base not in STABLECOIN_BASES:
            bases.add(base)
    return sorted(bases)


async def _fetch_okx_bases() -> list[str]:
    """
    Base assets of every OKX USDT spot pair, crypto only.

    `instCategory` filters out the tokenised equities and commodities OKX also
    lists as ordinary -USDT spot pairs — without it, `XAUT` or `XSNDK` would
    validate as coins.
    """
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(OKX_INSTRUMENTS_URL, params={"instType": "SPOT"})
        if response.status_code != 200:
            logger.warning("OKX instruments returned HTTP %s", response.status_code)
            return []
        payload = response.json()

    if payload.get("code") != "0":
        logger.warning("OKX rejected the spot instruments request")
        return []

    bases: set[str] = set()
    for instrument in payload.get("data") or []:
        if instrument.get("instCategory") != OKX_CRYPTO_INST_CATEGORY:
            continue
        if instrument.get("quoteCcy") != "USDT":
            continue
        base = (instrument.get("baseCcy") or "").upper()
        if base and base not in STABLECOIN_BASES:
            bases.add(base)
    return sorted(bases)


async def _fetch_listed_bases() -> Optional[dict[str, list[str]]]:
    """
    Listed USDT spot bases per exchange, from whichever exchanges answer.

    One exchange being unreachable is normal — Binance resets the connection
    from some networks — so a partial result is still returned and used.
    """
    results = await asyncio.gather(
        _fetch_binance_bases(), _fetch_okx_bases(), return_exceptions=True
    )

    listed: dict[str, list[str]] = {}
    for exchange, bases in zip(("BINANCE", "OKX"), results):
        if isinstance(bases, Exception):
            logger.warning(
                "%s spot listing unavailable (%s: %s)",
                exchange,
                type(bases).__name__,
                bases or "no detail",
            )
            continue
        if bases:
            listed[exchange] = bases

    return listed or None


async def get_listed_bases() -> Optional[dict[str, list[str]]]:
    """
    Exchange → listed USDT spot base assets, e.g. `{"OKX": ["BTC", "ETH", …]}`.

    Returns None when no exchange listing could be resolved from any layer, so
    callers can distinguish "this coin is not listed" from "we cannot tell".
    """
    return await _resolve(
        cache_key="listed_bases",
        disk_path=LISTED_BASES_FILE,
        ttl=SPOT_PAIRS_TTL,
        fetch=_fetch_listed_bases,
        seed=None,
        label="Listed spot bases",
    )


async def exchange_for_crypto(base: str) -> Optional[str]:
    """
    The exchange to chart a coin on ("BINANCE" / "OKX"), or None if unlisted.

    Binance wins when both carry the pair: it is the deeper book and the default
    TradingView users expect. None means either "no exchange lists this" or
    "listings unavailable" — `get_listed_bases() is None` tells them apart.
    """
    listed = await get_listed_bases()
    if not listed:
        return None
    base = base.upper()
    for exchange in ("BINANCE", "OKX"):
        if base in (listed.get(exchange) or ()):
            return exchange
    return None


# ═══════════════════════════════════════════════════════════════════════════
# OKX perpetuals
# ═══════════════════════════════════════════════════════════════════════════


async def _fetch_okx_swaps() -> Optional[list[str]]:
    """
    Rank OKX USDT-margined crypto perpetuals by 24h USD notional.

    `volCcy24h` is denominated in the base coin, so ranking on it raw puts the
    cheapest tokens on top — it has to be multiplied by `last` to become a USD
    figure. OKX also lists tokenised equities (AAPL, NVDA…) and commodities
    (XAU, CL…) as `-USDT-SWAP`, so instruments are filtered by `instCategory`,
    which only the instruments endpoint carries.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        tickers_response, instruments_response = await asyncio.gather(
            client.get(OKX_TICKERS_URL, params={"instType": "SWAP"}),
            client.get(OKX_INSTRUMENTS_URL, params={"instType": "SWAP"}),
        )

    for label, response in (("tickers", tickers_response), ("instruments", instruments_response)):
        if response.status_code != 200:
            logger.warning("OKX %s returned HTTP %s", label, response.status_code)
            return None

    tickers = tickers_response.json()
    instruments = instruments_response.json()
    if tickers.get("code") != "0" or instruments.get("code") != "0":
        logger.warning("OKX rejected the swap listing request")
        return None

    crypto_inst_ids = {
        instrument.get("instId")
        for instrument in instruments.get("data") or []
        if instrument.get("instCategory") == OKX_CRYPTO_INST_CATEGORY
    }

    ranked: list[tuple[str, float]] = []
    for ticker in tickers.get("data") or []:
        inst_id = ticker.get("instId") or ""
        if not inst_id.endswith("-USDT-SWAP") or inst_id not in crypto_inst_ids:
            continue

        base = inst_id[: -len("-USDT-SWAP")]
        if base in STABLECOIN_BASES:
            continue

        try:
            notional = float(ticker.get("volCcy24h") or 0) * float(ticker.get("last") or 0)
        except (TypeError, ValueError):
            continue

        ranked.append((base, notional))

    if not ranked:
        return None

    ranked.sort(key=lambda pair: pair[1], reverse=True)
    return [base for base, _ in ranked[:100]]


async def get_top_perp_symbols(limit: int = 8) -> list[str]:
    """
    Base symbols of the most liquid OKX perpetuals, e.g. `["BTC", "ETH", …]`.

    Used by the Home funding-rate widget, which appends `-USDT-SWAP` itself.
    """
    ranked = await _resolve(
        cache_key="okx_swaps",
        disk_path=OKX_SWAPS_FILE,
        ttl=OKX_SWAPS_TTL,
        fetch=_fetch_okx_swaps,
        seed=_SEED_PERP_SYMBOLS,
        label="OKX perpetuals",
    )
    return list(ranked[:limit])


# ═══════════════════════════════════════════════════════════════════════════
# Startup
# ═══════════════════════════════════════════════════════════════════════════


async def warm_up() -> None:
    """
    Prime the registry at application startup.

    Keeps the first user request off the cold path and gives the synchronous
    consumers a populated cache to read from.
    """
    results = await asyncio.gather(
        get_crypto_universe(),
        get_stock_universe(),
        get_top_spot_pairs(),
        get_top_perp_symbols(),
        # The two validation listings news attribution resolves every headline
        # against. Priming them keeps the first news fetch off the cold path.
        get_listed_bases(),
        get_us_equity_index(),
        return_exceptions=True,
    )
    labels = (
        "crypto universe",
        "stock universe",
        "spot pairs",
        "OKX perpetuals",
        "listed spot bases",
        "US equity index",
    )
    for label, result in zip(labels, results):
        if isinstance(result, Exception):
            logger.error("Registry warm-up failed for %s: %s", label, result)
        elif result is None:
            # The validation listings have no emergency seed on purpose.
            logger.warning("Registry warm-up: %s unavailable", label)
        else:
            logger.info("Registry warm-up: %s ready (%d entries)", label, len(result))
