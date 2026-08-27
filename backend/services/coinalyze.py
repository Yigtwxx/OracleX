"""
Single entry point for Coinalyze requests.

This exists for one thing the exchanges cannot give us: depth. Binance's
`openInterestHist` keeps about thirty days, Bybit's `open-interest` tops out at
two hundred rows with no daily period, and OKX's rubik series reaches a hundred
and eighty days. Coinalyze states outright that it never deletes its *daily*
series, which makes the multi-year open-interest chart reachable on a free key
instead of a paid Coinglass plan.

Two smaller things fall out of using it, and both remove code rather than add
it: `convert_to_usd=true` means Bybit's contract-denominated open interest
arrives already in dollars, and `/ohlcv-history` returns price on the very same
timestamps as the open interest, so pairing the two is an index join rather than
the step-wise alignment the venue path needs.

The key is optional on purpose. `has_key()` is false on a fresh clone and the
open-interest board falls back to the exchange endpoints, so nothing here is a
hard dependency — see `services/open_interest_service.py`.

Only the two history endpoints are wrapped so far. The same key also serves
`/liquidation-history`, `/funding-rate-history` and `/long-short-ratio-history`,
each in the identical `[{symbol, history: [...]}]` envelope, so adding them
later is a matter of one more `_history` call.
"""

import logging
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from config import settings
from services import http_client
from services.cache import ServiceCache

logger = logging.getLogger(__name__)

BASE_URL = "https://api.coinalyze.net/v1"

DEFAULT_TIMEOUT = 15.0

# Coinalyze allows twenty symbols per request but bills each one as its own
# call against a 40/min budget, so the catalog is cached hard and the board
# asks for one perp per venue rather than every market a base asset has.
MAX_SYMBOLS_PER_REQUEST = 20

# Points a single history request comes back with, whatever window is asked for.
# The documented retention is "1500 to 2000 for intraday, daily never deleted",
# but the response caps at the same figure on every interval — asking for two
# thousand daily bars returns fifteen hundred of open interest against two
# thousand of price, and the difference arrives as five hundred bars of nothing
# on the left of the chart. Callers trim to what actually reported.
MAX_HISTORY_POINTS = 1500

# Which stablecoin book to keep when a base asset has more perps than one
# request may carry. USDT is the deep one everywhere; the rest are listed in
# roughly descending liquidity, and anything unlisted sorts last.
QUOTE_PRIORITY: Dict[str, int] = {"USDT": 0, "USDC": 1, "USD": 2, "USD1": 3}

# The market catalog is effectively static; re-fetching it would spend the
# request budget on data that changes when an exchange lists a new contract.
MARKETS_TTL_SECONDS = 6 * 60 * 60

_cache = ServiceCache(maxsize=32)

_MARKETS_KEY = "future-markets"
_EXCHANGES_KEY = "exchanges"

# Coinalyze's interval vocabulary, keyed by the intervals this app speaks.
# Nothing else is accepted: an unmapped interval is a caller bug, not something
# to approximate, because a silently coarser series would be indistinguishable
# from a flat one.
INTERVALS: Dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1hour",
    "2h": "2hour",
    "4h": "4hour",
    "6h": "6hour",
    "12h": "12hour",
    "1d": "daily",
}


def has_key() -> bool:
    """Whether a key is configured; false means callers must use their fallback."""
    return bool(settings.COINALYZE_API_KEY)


def _key_headers() -> Dict[str, str]:
    """
    The auth header.

    Coinalyze accepts the key as a query parameter too. It goes in the header
    here so it never reaches a log line, an exception message or a cache key.
    """
    key = settings.COINALYZE_API_KEY
    return {"api_key": key} if key else {}


async def get_json(
    path: str,
    *,
    params: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """
    GET a Coinalyze endpoint (`path` is relative, e.g. `/future-markets`).

    Raises on non-2xx and on transport failures, exactly like
    `http_client.get_json` — callers decide whether to fall back to cache.
    """
    url = f"{BASE_URL}{path if path.startswith('/') else '/' + path}"
    return await http_client.get_json(
        url,
        params=params,
        headers=_key_headers(),
        timeout=timeout,
    )


async def fetch_future_markets() -> List[Dict[str, Any]]:
    """
    The futures catalog, cached for six hours. Empty list on any failure.

    Every symbol Coinalyze knows carries its exchange code as a suffix
    (`BTCUSDT_PERP.A`), and the mapping from suffix to exchange is not
    documented anywhere but this catalog — which is why symbols are resolved
    from it rather than assembled from a hardcoded table.
    """
    cached = _cache.get(_MARKETS_KEY)
    if cached is not None:
        return cached

    try:
        markets = await get_json("/future-markets")
    except Exception as exc:
        logger.warning("Coinalyze future-markets failed: %s", type(exc).__name__)
        # A stale catalog is still a correct catalog; only a cold cache gives up.
        return _cache.get_with_fallback(_MARKETS_KEY) or []

    if not isinstance(markets, list):
        return []

    _cache.set(_MARKETS_KEY, markets, MARKETS_TTL_SECONDS)
    return markets


async def fetch_exchange_names() -> Dict[str, str]:
    """
    Exchange code → display name, cached for six hours. Empty on failure.

    The catalog identifies a venue only by a one-letter code, and that mapping
    is published nowhere else — so the board reads it rather than shipping a
    guessed table that would silently mislabel a chart if Coinalyze ever
    reassigned a letter.
    """
    cached = _cache.get(_EXCHANGES_KEY)
    if cached is not None:
        return cached

    try:
        rows = await get_json("/exchanges")
    except Exception as exc:
        logger.warning("Coinalyze exchanges failed: %s", type(exc).__name__)
        return _cache.get_with_fallback(_EXCHANGES_KEY) or {}

    if not isinstance(rows, list):
        return {}

    names = {
        str(row["code"]): str(row["name"])
        for row in rows
        if isinstance(row, dict) and row.get("code") and row.get("name")
    }
    _cache.set(_EXCHANGES_KEY, names, MARKETS_TTL_SECONDS)
    return names


class PerpMarket(NamedTuple):
    """One stablecoin-margined perpetual, as the board needs to address it."""

    symbol: str
    exchange: str
    quote: str


async def resolve_perp_symbols(
    base: str, exchanges: Optional[Tuple[str, ...]] = None
) -> List[PerpMarket]:
    """
    Every stablecoin-margined perpetual for `base` on the requested exchanges.

    All of them, not one per venue. A venue's open interest in an asset is the
    sum of its books: Binance alone lists BTC against USDT, USDC, USD1 and U,
    and picking a single contract makes the answer depend on which one the
    catalog happened to name first — that choice landed on the thin USDC book,
    whose open-interest history came back empty, and the venue was dropped from
    the chart as though it had gone quiet.

    Coin-margined contracts stay excluded: they are the same exposure in a
    second denomination, and adding them to a dollar total counts it twice.
    """
    markets, names = await fetch_future_markets(), await fetch_exchange_names()
    wanted = base.upper()

    found: List[PerpMarket] = []
    for market in markets:
        try:
            if not market.get("is_perpetual"):
                continue
            if str(market.get("base_asset", "")).upper() != wanted:
                continue
            if str(market.get("margined", "")).upper() != "STABLE":
                continue
            code = str(market["exchange"])
            symbol = str(market["symbol"])
            quote = str(market.get("quote_asset") or "")
        except (KeyError, TypeError, ValueError):
            continue

        exchange = names.get(code, code)
        if exchanges is not None and exchange not in exchanges:
            continue
        found.append(PerpMarket(symbol=symbol, exchange=exchange, quote=quote.upper()))

    if len(found) > MAX_SYMBOLS_PER_REQUEST:
        # Say what was dropped rather than letting a truncated total read as the
        # venue's whole book. Deepest quotes first, so the tail that goes is the
        # tail that matters least.
        found.sort(key=lambda market: (QUOTE_PRIORITY.get(market.quote, 99), market.symbol))
        logger.warning(
            "Coinalyze: %s has %d stable perps, keeping %d",
            wanted,
            len(found),
            MAX_SYMBOLS_PER_REQUEST,
        )
        found = found[:MAX_SYMBOLS_PER_REQUEST]

    return found


async def fetch_open_interest_history(
    symbols: List[str], interval: str, start: int, end: int
) -> Dict[str, List[Tuple[int, float]]]:
    """
    Open interest in USD per symbol, as `(timestamp_seconds, value)` oldest first.

    `convert_to_usd` is always on: without it Bybit answers in contracts and
    Binance in dollars, and the sum of those two is meaningless.
    """
    return await _history(
        "/open-interest-history",
        symbols,
        interval,
        start,
        end,
        extra={"convert_to_usd": "true"},
    )


async def fetch_price_history(
    symbol: str, interval: str, start: int, end: int
) -> List[Dict[str, Any]]:
    """
    OHLCV for one market, in the candle shape the rest of the app passes around.

    `time` is Unix seconds, oldest first — identical to `okx_market.fetch_candles`,
    so downstream code cannot tell which provider produced it.
    """
    period = INTERVALS.get(interval.lower())
    if period is None:
        return []

    try:
        payload = await get_json(
            "/ohlcv-history",
            params={
                "symbols": symbol,
                "interval": period,
                "from": start,
                "to": end,
            },
        )
    except Exception as exc:
        logger.warning("Coinalyze ohlcv failed for %s: %s", symbol, type(exc).__name__)
        return []

    candles: List[Dict[str, Any]] = []
    for entry in _entries(payload):
        for row in entry.get("history") or []:
            try:
                close = float(row["c"])
                volume = float(row.get("v") or 0.0)
                candles.append(
                    {
                        "time": int(row["t"]),
                        "open": float(row["o"]),
                        "high": float(row["h"]),
                        "low": float(row["l"]),
                        "close": close,
                        "volume": volume,
                        # Coinalyze reports base-asset volume only, so unlike the
                        # exchange clients this figure is derived rather than the
                        # venue's own trade-by-trade sum. The board never reads
                        # it; it is here so the candle shape stays uniform.
                        "volume_usd": volume * close,
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue

    candles.sort(key=lambda candle: candle["time"])
    return candles


async def _history(
    path: str,
    symbols: List[str],
    interval: str,
    start: int,
    end: int,
    *,
    extra: Optional[Dict[str, str]] = None,
) -> Dict[str, List[Tuple[int, float]]]:
    """
    One `[{symbol, history: [{t, c}]}]` endpoint, reduced to close-value series.

    Every history endpoint Coinalyze serves shares this envelope, so this is the
    only place that has to know its shape.
    """
    period = INTERVALS.get(interval.lower())
    if period is None or not symbols:
        return {}

    params: Dict[str, Any] = {
        "symbols": ",".join(symbols[:MAX_SYMBOLS_PER_REQUEST]),
        "interval": period,
        "from": start,
        "to": end,
    }
    params.update(extra or {})

    try:
        payload = await get_json(path, params=params)
    except Exception as exc:
        logger.warning("Coinalyze %s failed: %s", path, type(exc).__name__)
        return {}

    series: Dict[str, List[Tuple[int, float]]] = {}
    for entry in _entries(payload):
        symbol = entry.get("symbol")
        if not isinstance(symbol, str):
            continue
        points: List[Tuple[int, float]] = []
        for row in entry.get("history") or []:
            try:
                points.append((int(row["t"]), float(row["c"])))
            except (KeyError, TypeError, ValueError):
                continue
        if points:
            points.sort(key=lambda point: point[0])
            series[symbol] = points

    return series


def _entries(payload: Any) -> List[Dict[str, Any]]:
    """The response's list of per-symbol envelopes, or nothing recognisable."""
    if not isinstance(payload, list):
        return []
    return [entry for entry in payload if isinstance(entry, dict)]
