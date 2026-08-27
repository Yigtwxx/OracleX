"""
OKX market data — the one place the backend reads prices, candles and trades.

Every other exchange this project used to call is unreachable from at least one
network it runs on (Binance answers nothing at all from some countries), so OKX
is the single source for market data and this module is its only client.

Nothing here invents a value. A failed or empty upstream response returns `None`
or `[]` and the caller decides what to say about the gap — a neutral-looking
default (a "50" RSI, a "0" price) would be indistinguishable from a real reading
once it reaches the UI or an LLM prompt.

Symbols arrive in whatever shape the caller already had — "BINANCE:BTCUSDT",
"BTCUSDT", "BTC/USDT", "BTC-USDT-SWAP" — and `to_okx_spot_id` / `to_okx_inst_id`
normalise them.
"""

import asyncio
import logging
from bisect import bisect_right
from itertools import groupby
from typing import Any, Dict, List, Optional, Sequence, Tuple

from services.http_client import get_json

logger = logging.getLogger(__name__)

OKX_CANDLES_URL = "https://www.okx.com/api/v5/market/candles"
OKX_HISTORY_CANDLES_URL = "https://www.okx.com/api/v5/market/history-candles"
OKX_TICKER_URL = "https://www.okx.com/api/v5/market/ticker"
OKX_TICKERS_URL = "https://www.okx.com/api/v5/market/tickers"
OKX_TRADES_URL = "https://www.okx.com/api/v5/market/trades"

# Frontend interval → OKX `bar`. OKX spells units of an hour and above in
# uppercase ("1H", "4H", "1D"); minutes stay lowercase.
OKX_BAR_BY_INTERVAL = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1H",
    "2h": "2H",
    "4h": "4H",
    "6h": "6H",
    "12h": "12H",
    "1d": "1D",
    "1w": "1W",
}

# OKX caps a single /market/candles page at 300 rows, /history-candles at 100.
OKX_MAX_CANDLES = 300
OKX_MAX_HISTORY_CANDLES = 100
# And /market/trades at 500.
OKX_MAX_TRADES = 500

# Quote currencies we can split off a concatenated pair, longest first so that
# "BTCUSDT" is not matched as base "BTCUSD" + quote "T".
_QUOTE_CURRENCIES = ("USDT", "USDC", "USD")

_CANDLE_TIMEOUT = 15.0
_TICKER_TIMEOUT = 10.0


# ── Symbol normalisation ─────────────────────────────────────────────────────


def split_symbol(symbol: str) -> Tuple[str, str]:
    """
    Split any of the symbol shapes this app passes around into (base, quote).

    "BINANCE:BTCUSDT", "BTCUSDT", "BTC/USDT" and "BTC-USDT-SWAP" all yield
    ("BTC", "USDT"). A bare base with no recognisable quote defaults to USDT,
    which is what every OKX pair the app touches is quoted in.
    """
    cleaned = symbol.split(":")[-1].replace("/", "-").upper().strip()

    if cleaned.endswith("-SWAP"):
        cleaned = cleaned[: -len("-SWAP")]

    if "-" in cleaned:
        base, _, quote = cleaned.partition("-")
    else:
        for candidate in _QUOTE_CURRENCIES:
            if cleaned.endswith(candidate) and len(cleaned) > len(candidate):
                base, quote = cleaned[: -len(candidate)], candidate
                break
        else:
            base, quote = cleaned, "USDT"

    # OKX quotes the pairs this app uses in USDT.
    if quote in ("USD", "USDC"):
        quote = "USDT"

    return base, quote


def to_okx_inst_id(symbol: str) -> str:
    """Normalise a UI symbol into an OKX *perpetual* id, e.g. "BTC-USDT-SWAP"."""
    base, quote = split_symbol(symbol)
    return f"{base}-{quote}-SWAP"


def to_okx_spot_id(symbol: str) -> str:
    """Normalise a UI symbol into an OKX *spot* id, e.g. "BTC-USDT"."""
    base, quote = split_symbol(symbol)
    return f"{base}-{quote}"


# ── Candles ──────────────────────────────────────────────────────────────────


def _parse_candles(rows: Any, *, is_swap: bool) -> List[Dict[str, Any]]:
    """
    Turn OKX candle rows into dicts, oldest-first.

    OKX row: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm].
    Which column holds the base coin differs by instrument type: on a swap `vol`
    counts contracts and `volCcy` is the coin, while on spot `vol` already is the
    coin and `volCcy` is the quote currency. Getting this wrong would report a
    dollar figure as a coin count, so the index is chosen per instrument type
    rather than assumed. `volume_usd` is the quote currency either way — the
    liquidation map needs that notional, chart consumers only read time/OHLC.
    """
    base_index = 6 if is_swap else 5

    candles: List[Dict[str, Any]] = []
    for row in rows or []:
        try:
            candles.append(
                {
                    # Seconds — lightweight-charts and the existing consumers expect that.
                    "time": int(row[0]) // 1000,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[base_index]),
                    "volume_usd": float(row[7]),
                }
            )
        except (IndexError, TypeError, ValueError):
            continue

    # OKX returns newest-first; every consumer wants chronological order.
    candles.reverse()
    return candles


async def _get_okx(url: str, params: Dict[str, str], label: str, timeout: float) -> Optional[list]:
    """GET an OKX endpoint and return its `data` array, or None on any failure."""
    try:
        payload = await get_json(url, params=params, timeout=timeout)
    except Exception as e:
        logger.warning("OKX %s failed (%s): %s", label, type(e).__name__, e or "no detail")
        return None

    if not isinstance(payload, dict) or payload.get("code") != "0":
        logger.warning("OKX %s returned: %s", label, payload)
        return None

    return payload.get("data") or []


async def fetch_candles(
    symbol: str, interval: str = "1h", limit: int = 168, *, spot: bool = False
) -> List[Dict[str, Any]]:
    """
    Fetch OHLCV candles, oldest-first. Empty list when OKX has nothing.

    `spot=True` reads the spot pair and falls back to the perpetual when the
    pair is not listed — support/resistance should be quoted against the price
    the rest of the app displays, but plenty of long-tail coins only have a perp.
    """
    bar = OKX_BAR_BY_INTERVAL.get(interval.lower())
    if not bar:
        logger.warning("Unsupported candle interval '%s' — falling back to 1h.", interval)
        bar = "1H"

    inst_ids = (
        [to_okx_spot_id(symbol), to_okx_inst_id(symbol)] if spot else [to_okx_inst_id(symbol)]
    )

    for inst_id in inst_ids:
        rows = await _get_okx(
            OKX_CANDLES_URL,
            {"instId": inst_id, "bar": bar, "limit": str(min(max(limit, 1), OKX_MAX_CANDLES))},
            f"candles {inst_id}",
            _CANDLE_TIMEOUT,
        )
        candles = _parse_candles(rows, is_swap=inst_id.endswith("-SWAP"))
        if candles:
            return candles

    return []


async def fetch_history_candles(
    symbol: str, bar: str = "1D", limit: int = 365, *, spot: bool = True
) -> List[Dict[str, Any]]:
    """
    Fetch up to `limit` historical candles, oldest-first, paging backwards.

    `/market/history-candles` returns at most 100 rows per call, so anything
    longer than that walks backwards with `after` (an exclusive upper bound on
    the timestamp). Stops early when OKX runs out of history.
    """
    inst_ids = (
        [to_okx_spot_id(symbol), to_okx_inst_id(symbol)] if spot else [to_okx_inst_id(symbol)]
    )

    # One page per 100 rows, plus slack for short pages, so a misbehaving
    # upstream cannot spin this loop indefinitely.
    max_pages = limit // OKX_MAX_HISTORY_CANDLES + 3

    for inst_id in inst_ids:
        collected: List[Dict[str, Any]] = []
        after: Optional[str] = None

        for _ in range(max_pages):
            if len(collected) >= limit:
                break
            params = {
                "instId": inst_id,
                "bar": bar,
                "limit": str(min(limit - len(collected), OKX_MAX_HISTORY_CANDLES)),
            }
            if after:
                params["after"] = after

            rows = await _get_okx(
                OKX_HISTORY_CANDLES_URL, params, f"history-candles {inst_id}", _CANDLE_TIMEOUT
            )
            page = _parse_candles(rows, is_swap=inst_id.endswith("-SWAP"))
            if not page:
                break

            # Pages arrive newest-first between calls, so prepend to stay chronological.
            collected = page + collected
            after = str(page[0]["time"] * 1000)

        if collected:
            return collected[-limit:]

    return []


async def fetch_candles_between(
    symbol: str, start_ms: int, end_ms: int, bar: str = "1D", *, spot: bool = True
) -> List[Dict[str, Any]]:
    """
    Candles inside a fixed date window, oldest-first.

    Used to look up how price behaved around a past event. Pages backwards from
    `end_ms` with OKX's `after` cursor until it reaches `start_ms`. OKX serves
    daily BTC history back to at least 2020, so this covers the events the RAG
    store indexes.
    """
    if end_ms <= start_ms:
        return []

    inst_ids = (
        [to_okx_spot_id(symbol), to_okx_inst_id(symbol)] if spot else [to_okx_inst_id(symbol)]
    )
    # Enough pages to walk the window, with slack for short pages.
    max_pages = 20

    for inst_id in inst_ids:
        collected: List[Dict[str, Any]] = []
        after = end_ms

        for _ in range(max_pages):
            rows = await _get_okx(
                OKX_HISTORY_CANDLES_URL,
                {
                    "instId": inst_id,
                    "bar": bar,
                    "after": str(after),
                    "limit": str(OKX_MAX_HISTORY_CANDLES),
                },
                f"history-candles {inst_id}",
                _CANDLE_TIMEOUT,
            )
            page = _parse_candles(rows, is_swap=inst_id.endswith("-SWAP"))
            if not page:
                break

            collected = page + collected
            after = page[0]["time"] * 1000
            if after <= start_ms:
                break

        window = [c for c in collected if start_ms <= c["time"] * 1000 <= end_ms]
        if window:
            return window

    return []


# ── Tickers ──────────────────────────────────────────────────────────────────


def _parse_ticker(row: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """
    Turn one OKX ticker row into the 24h summary the callers expect.

    OKX publishes `open24h` rather than a change percentage, so the percentage
    is computed here. A row without a usable open is dropped instead of being
    reported as a 0% move.
    """
    try:
        price = float(row["last"])
        open_24h = float(row["open24h"])
    except (KeyError, TypeError, ValueError):
        return None

    if price <= 0 or open_24h <= 0:
        return None

    def _optional(key: str) -> float:
        try:
            return float(row[key])
        except (KeyError, TypeError, ValueError):
            return 0.0

    return {
        "price": price,
        "change_pct": (price - open_24h) / open_24h * 100,
        "volume": _optional("vol24h"),  # base coin
        "volume_usd": _optional("volCcy24h"),  # quote currency
        "high_24h": _optional("high24h"),
        "low_24h": _optional("low24h"),
    }


async def fetch_ticker_24h(symbol: str) -> Optional[Dict[str, float]]:
    """24h price summary for one symbol, or None when OKX does not list it."""
    rows = await _get_okx(
        OKX_TICKER_URL,
        {"instId": to_okx_spot_id(symbol)},
        f"ticker {symbol}",
        _TICKER_TIMEOUT,
    )
    if not rows:
        return None
    return _parse_ticker(rows[0])


async def fetch_tickers_24h(symbols: List[str]) -> Dict[str, Dict[str, float]]:
    """
    24h summaries for many symbols, keyed by base ("BTC", "ETH", …).

    One `/market/tickers` call covers the whole spot book, so this costs the
    same whether the caller wants two symbols or fifty. Symbols OKX does not
    list are simply absent from the result.
    """
    rows = await _get_okx(OKX_TICKERS_URL, {"instType": "SPOT"}, "tickers", _TICKER_TIMEOUT)
    if not rows:
        return {}

    wanted = {to_okx_spot_id(symbol): split_symbol(symbol)[0] for symbol in symbols}

    summaries: Dict[str, Dict[str, float]] = {}
    for row in rows:
        base = wanted.get(row.get("instId"))
        if base is None:
            continue
        summary = _parse_ticker(row)
        if summary is not None:
            summaries[base] = summary

    return summaries


# ── Trades ───────────────────────────────────────────────────────────────────


async def fetch_recent_trades(symbol: str, limit: int = OKX_MAX_TRADES) -> List[Dict[str, Any]]:
    """
    Most recent public trades for a spot pair, newest-first.

    `side` is the *taker's* direction, so "buy" means a taker lifted the offer —
    no maker/taker inversion is needed, unlike Binance's `isBuyerMaker`.
    """
    inst_id = to_okx_spot_id(symbol)
    rows = await _get_okx(
        OKX_TRADES_URL,
        {"instId": inst_id, "limit": str(min(max(limit, 1), OKX_MAX_TRADES))},
        f"trades {inst_id}",
        _TICKER_TIMEOUT,
    )
    if not rows:
        return []

    trades: List[Dict[str, Any]] = []
    for row in rows:
        try:
            trades.append(
                {
                    "trade_id": str(row["tradeId"]),
                    "price": float(row["px"]),
                    "quantity": float(row["sz"]),
                    "side": row["side"],
                    "timestamp": int(row["ts"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue

    return trades


def aggregate_taker_orders(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge consecutive fills back into the taker orders that produced them.

    OKX reports every individual fill, so one market order sweeping the book
    arrives as a run of rows sharing a timestamp and side. Binance's `aggTrades`
    — the endpoint this project used to read — did this merging server-side, so
    comparing a raw OKX fill against a size threshold tuned for aggregated
    orders finds nothing. A single $65k BTC order really does show up here as
    eighteen separate fills.

    Returns newest-first, carrying the volume-weighted average fill price.
    """
    orders: List[Dict[str, Any]] = []

    for _, group in groupby(trades, key=lambda t: (t["timestamp"], t["side"])):
        fills = list(group)
        quantity = sum(f["quantity"] for f in fills)
        if quantity <= 0:
            continue
        value = sum(f["price"] * f["quantity"] for f in fills)

        orders.append(
            {
                # The first fill's id identifies the order across polls.
                "trade_id": fills[0]["trade_id"],
                "price": value / quantity,
                "quantity": quantity,
                "value": value,
                "side": fills[0]["side"],
                "timestamp": fills[0]["timestamp"],
                "fills": len(fills),
            }
        )

    return orders


async def fetch_many_recent_trades(
    symbols: List[str], limit: int = OKX_MAX_TRADES
) -> Dict[str, List[Dict[str, Any]]]:
    """Recent trades for several pairs concurrently, keyed by the input symbol."""
    results = await asyncio.gather(
        *(fetch_recent_trades(symbol, limit) for symbol in symbols),
        return_exceptions=True,
    )
    return {symbol: trades for symbol, trades in zip(symbols, results) if isinstance(trades, list)}


# ── Derivatives statistics ("rubik") ─────────────────────────────────────────
#
# These live here rather than in the liquidation model that first needed them
# because they are not a property of that model: they are how OKX publishes
# open interest, and the open-interest board reads the same series. Keeping one
# copy is also the only way the two features cannot disagree about what OKX
# said.

OKX_RUBIK_URL = "https://www.okx.com/api/v5/rubik/stat/contracts"

MINUTE_MS = 60_000

# Length of one candle at each interval the app accepts, used to work out how
# far back a requested window reaches.
INTERVAL_MS = {
    "1m": MINUTE_MS,
    "3m": 3 * MINUTE_MS,
    "5m": 5 * MINUTE_MS,
    "15m": 15 * MINUTE_MS,
    "30m": 30 * MINUTE_MS,
    "1h": 60 * MINUTE_MS,
    "2h": 120 * MINUTE_MS,
    "4h": 240 * MINUTE_MS,
    "6h": 360 * MINUTE_MS,
    "12h": 720 * MINUTE_MS,
    "1d": 1440 * MINUTE_MS,
    "1w": 7 * 1440 * MINUTE_MS,
}

# How far back each statistics resolution reaches. OKX returns a fixed number of
# points per period rather than honouring `limit`, so the period *is* the window.
RUBIK_WINDOW_MS: Tuple[Tuple[str, int], ...] = (
    ("5m", 576 * 5 * MINUTE_MS),  # 2 days
    ("1H", 720 * 60 * MINUTE_MS),  # 30 days
    ("1D", 180 * 1440 * MINUTE_MS),  # 180 days
)


def rubik_period(interval: str, candles: int) -> str:
    """
    Pick the finest statistics resolution that still spans the whole window.

    A fine period on a long chart simply runs out partway back, and every candle
    older than that gets no sample at all. A coarser period samples each candle
    less precisely but covers the entire window, which is the better trade. When
    even the coarsest falls short, use it anyway and let the caller mark how much
    of the series is left uncovered.
    """
    span_ms = candles * INTERVAL_MS.get(interval, 60 * MINUTE_MS)
    for period, window_ms in RUBIK_WINDOW_MS:
        if window_ms >= span_ms:
            return period
    return RUBIK_WINDOW_MS[-1][0]


async def fetch_rubik_series(
    endpoint: str, ccy: str, period: str, value_index: int
) -> List[Tuple[int, float]]:
    """
    Fetch one OKX "rubik" statistics series as chronological (timestamp, value).

    Returns an empty list on any failure; the caller degrades to a neutral
    assumption rather than failing the whole chart.
    """
    try:
        payload = await get_json(
            f"{OKX_RUBIK_URL}/{endpoint}",
            # `limit` is accepted but ignored — OKX always returns the period's
            # full fixed window. Sent at its maximum for documentation value.
            params={"ccy": ccy, "period": period, "limit": "1000"},
            timeout=15.0,
        )
    except Exception as e:
        logger.warning(f"OKX {endpoint} failed for {ccy}: {e}")
        return []

    if payload.get("code") != "0":
        logger.warning(f"OKX {endpoint} for {ccy} returned: {payload.get('msg')}")
        return []

    series: List[Tuple[int, float]] = []
    for row in payload.get("data") or []:
        try:
            series.append((int(row[0]), float(row[value_index])))
        except (IndexError, TypeError, ValueError):
            continue

    series.sort(key=lambda item: item[0])
    return series


async def fetch_open_interest(symbol: str, interval: str, limit: int) -> List[Tuple[int, float]]:
    """
    Open interest in USD, as `(timestamp_ms, value)` oldest first.

    Signature matches `binance_market.fetch_open_interest` and
    `bybit_market.fetch_open_interest` so callers can fan out over the three
    venues without special-casing any of them. Unlike those two, OKX reports per
    *currency* rather than per contract, so the figure covers every one of that
    asset's OKX perpetuals rather than a single pair.
    """
    base, _ = split_symbol(symbol)
    if not base:
        return []
    return await fetch_rubik_series("open-interest-volume", base, rubik_period(interval, limit), 1)


def align_to_candles(
    series: Sequence[Tuple[int, float]], candle_times_ms: Sequence[int]
) -> List[Optional[float]]:
    """
    Sample `series` at each candle, taking the last value at or before it.

    The statistics endpoints run on their own (coarser) clock, so this is a
    step-wise lookup rather than an index-for-index join. An index join would
    not fail loudly — it would quietly attribute one candle's open interest to
    another, which is exactly the kind of plausible wrong number this codebase
    refuses to print.
    """
    if not series:
        return [None] * len(candle_times_ms)

    timestamps = [ts for ts, _ in series]
    values = [value for _, value in series]

    aligned: List[Optional[float]] = []
    for candle_ms in candle_times_ms:
        position = bisect_right(timestamps, candle_ms) - 1
        aligned.append(values[position] if position >= 0 else None)
    return aligned
