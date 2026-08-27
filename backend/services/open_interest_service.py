"""
Open Interest board.

The terminal already models liquidations *from* open interest, but never showed
the input. That left the question the liquidation map most obviously raises
unanswered: was a move positions opening, or positions closing? Rising price on
rising open interest is new money; rising price on falling open interest is
shorts covering, and the two look identical on a candle chart.

Two providers, in order, because they fail differently:

* **Coinalyze** when a key is configured. It never deletes its daily series, so
  this is the only free path to the multi-year chart. It also returns price on
  the same timestamps as the open interest and converts every venue to USD, so
  this branch is an index join with no alignment step.
* **The exchanges themselves** otherwise. `binance_market`, `bybit_market` and
  `okx_market` each publish about a month, on their own coarser clocks, in their
  own denominations. This branch pays for that with a step-wise alignment and a
  contracts-to-dollars conversion.

Both emit the identical payload and set `source`, so the frontend can say which
one it is looking at rather than leaving a short chart unexplained. Neither
invents a value: a venue that answers with nothing is dropped from `venues` and
omitted from `series`, and `coverage_from` marks where every listed venue is
actually present. Without that flag a venue's first sample reads as a sudden
inflow of open interest, which is the same class of plausible-wrong-number the
rest of this codebase refuses to print.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from services import binance_market, bybit_market, coinalyze, okx_market
from services.asset_registry import get_crypto_universe
from services.cache import ServiceCache

logger = logging.getLogger(__name__)

# The venues the board names, in the order the chart stacks them. Coinalyze
# knows dozens more; three keeps the legend readable and matches the venues the
# fallback path can serve, so switching providers does not silently change which
# exchanges the aggregate covers.
VENUES: Tuple[str, ...] = ("Binance", "OKX", "Bybit")

SOURCE_COINALYZE = "coinalyze"
SOURCE_VENUES = "venues"

# What the router accepts. No weekly: neither Coinalyze nor any exchange
# statistics endpoint publishes one, and a control that always degraded to daily
# would be a claim about resolution the data cannot honour. The daily series
# reaches years back and the chart's slider covers reading it at that span.
INTERVALS: Tuple[str, ...] = ("1h", "4h", "1d")

VENUE_FALLBACK_INTERVAL = "1d"

# Seconds per bar, used to work out how far back to ask Coinalyze for.
INTERVAL_SECONDS: Dict[str, int] = {
    "1h": 3_600,
    "4h": 14_400,
    "1d": 86_400,
}

# A daily bar does not move every two minutes, and the Coinalyze budget is 40
# calls a minute shared with everything else on the key.
CACHE_TTL_SECONDS = 120
CACHE_TTL_DAILY_SECONDS = 900

SUPPLY_TTL_SECONDS = 3_600

_cache = ServiceCache(maxsize=32)


async def get_open_interest(symbol: str, interval: str = "1d", limit: int = 400) -> Dict[str, Any]:
    """
    Open interest per venue against price, aligned index-for-index with candles.

    Returns an empty-but-complete payload rather than raising when no provider
    answers — every key is present with empty arrays, so the client renders an
    empty state instead of crashing on a missing field.
    """
    base, _ = okx_market.split_symbol(symbol)
    if not base:
        return _empty_result(symbol, interval)

    interval = interval.lower()
    if interval not in INTERVALS:
        interval = VENUE_FALLBACK_INTERVAL

    cache_key = f"oi:{base}:{interval}:{limit}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        result = await _build(base, interval, limit)
    except Exception as exc:
        logger.warning("Open interest failed for %s: %s", base, type(exc).__name__)
        result = None

    if result is None or not result["candles"]:
        # Stale beats empty here: the board is a shape over weeks, so a
        # two-hour-old copy still answers the question the user is asking.
        stale = _cache.get_with_fallback(cache_key)
        return stale if stale is not None else _empty_result(base, interval)

    ttl = CACHE_TTL_DAILY_SECONDS if interval == "1d" else CACHE_TTL_SECONDS
    _cache.set(cache_key, result, ttl)
    return result


async def _build(base: str, interval: str, limit: int) -> Optional[Dict[str, Any]]:
    """Run the provider chain and attach market cap to whichever answered."""
    result: Optional[Dict[str, Any]] = None

    if coinalyze.has_key():
        result = await _from_coinalyze(base, interval, limit)

    if result is None or not result["candles"]:
        result = await _from_venues(base, interval, limit)

    if result is None or not result["candles"]:
        return None

    supply = await _circulating_supply(base, result["candles"][-1]["close"])
    result["circulating_supply"] = supply
    result["market_cap"] = (
        [candle["close"] * supply for candle in result["candles"]] if supply else []
    )
    return result


# ── Provider: Coinalyze ──────────────────────────────────────────────────────


async def _from_coinalyze(base: str, interval: str, limit: int) -> Optional[Dict[str, Any]]:
    """
    The deep path: one open-interest call per venue plus one price call.

    Coinalyze samples every market on the same grid, so the per-venue series and
    the candles share timestamps exactly and joining them is a dictionary lookup
    rather than the step-wise search the exchange path needs.
    """
    markets = await coinalyze.resolve_perp_symbols(base, VENUES)
    if not markets:
        return None

    span = INTERVAL_SECONDS.get(interval, 86_400) * max(limit, 1)
    end = int(time.time())
    start = end - span

    symbols = [market.symbol for market in markets]
    oi_by_symbol, candles = await asyncio.gather(
        coinalyze.fetch_open_interest_history(symbols, interval, start, end),
        coinalyze.fetch_price_history(_reference_market(markets), interval, start, end),
    )

    if not candles or not oi_by_symbol:
        return None

    candles = candles[-limit:]
    times = [candle["time"] for candle in candles]

    # A venue's open interest is the sum of its books, so its contracts are
    # added bar by bar. A bar no contract reported stays None rather than
    # becoming zero — the venue was silent there, not empty.
    totals: Dict[str, List[Optional[float]]] = {}
    for market in markets:
        points = oi_by_symbol.get(market.symbol)
        if not points:
            continue
        by_time = dict(points)
        column = totals.setdefault(market.exchange, [None] * len(times))
        for index, timestamp in enumerate(times):
            value = by_time.get(timestamp)
            if value is None:
                continue
            column[index] = (column[index] or 0.0) + value

    series = {
        exchange: column
        for exchange, column in totals.items()
        if any(value is not None for value in column)
    }

    if not series:
        return None

    # Price reaches further back than open interest does — Coinalyze caps a
    # history request at `MAX_HISTORY_POINTS` while OHLCV keeps coming — so a
    # generous `limit` buys leading bars with a price line and no chart under
    # it. Cut to where the first venue starts reporting: the board is about open
    # interest, and dead space on its left is not context, it is a gap the eye
    # reads as a collapse to zero.
    opening = min(
        next(index for index, value in enumerate(column) if value is not None)
        for column in series.values()
    )
    if opening:
        candles = candles[opening:]
        series = {exchange: column[opening:] for exchange, column in series.items()}

    return _assemble(base, interval, SOURCE_COINALYZE, candles, series)


def _reference_market(markets: Sequence[coinalyze.PerpMarket]) -> str:
    """
    The market whose candles become the board's price line.

    One venue's perp, not an average: the price axis exists to be read against
    the open-interest area, and a synthetic mid nobody trades would be harder to
    reconcile with any chart the user has open elsewhere. The deepest book wins,
    which in practice means a USDT pair on the largest venue present.
    """
    ranked = sorted(
        markets,
        key=lambda market: (
            VENUES.index(market.exchange) if market.exchange in VENUES else len(VENUES),
            coinalyze.QUOTE_PRIORITY.get(market.quote, 99),
            market.symbol,
        ),
    )
    return ranked[0].symbol


# ── Provider: the exchanges ──────────────────────────────────────────────────


async def _from_venues(base: str, interval: str, limit: int) -> Optional[Dict[str, Any]]:
    """
    The always-available path: each exchange's own statistics endpoint.

    Roughly thirty days deep and on three different clocks, which is why every
    series goes through `align_to_candles` rather than being zipped positionally.
    """
    if interval not in okx_market.INTERVAL_MS:
        interval = VENUE_FALLBACK_INTERVAL

    inst_id = okx_market.to_okx_inst_id(base)
    # Binance and Bybit are asked per *contract*, so a bare base asset is not a
    # symbol they recognise — `to_binance_symbol("BTC")` is "BTC", which they
    # answer with nothing at all rather than an error. OKX's statistics are
    # published per currency, which is why only these two need the pair.
    perp = f"{base}USDT"
    requested = min(limit, okx_market.OKX_MAX_CANDLES)

    candles, binance_oi, bybit_oi, okx_oi = await asyncio.gather(
        okx_market.fetch_candles(inst_id, interval=interval, limit=requested),
        binance_market.fetch_open_interest(
            perp, interval, min(requested, binance_market.MAX_STAT_ROWS)
        ),
        bybit_market.fetch_open_interest(perp, interval, min(requested, bybit_market.MAX_OI_ROWS)),
        okx_market.fetch_open_interest(base, interval, requested),
    )

    if not candles:
        return None

    times_ms = [candle["time"] * 1000 for candle in candles]
    raw = {"Binance": binance_oi, "OKX": okx_oi, "Bybit": bybit_oi}

    series: Dict[str, List[Optional[float]]] = {}
    for exchange in VENUES:
        points = raw.get(exchange) or []
        if not points:
            continue
        column = okx_market.align_to_candles(points, times_ms)
        if exchange == "Bybit":
            # Bybit reports contracts where the other two report dollars.
            # Converting per candle rather than at one price for the window is
            # what keeps a month-long chart from drifting against the others.
            column = [
                value * candles[index]["close"] if value is not None else None
                for index, value in enumerate(column)
            ]
        if any(value is not None for value in column):
            series[exchange] = column

    if not series:
        return None

    return _assemble(base, interval, SOURCE_VENUES, candles, series)


# ── Shared assembly ──────────────────────────────────────────────────────────


def _assemble(
    base: str,
    interval: str,
    source: str,
    candles: List[Dict[str, Any]],
    series: Dict[str, List[Optional[float]]],
) -> Dict[str, Any]:
    """Both providers converge here, so the payload cannot differ between them."""
    venues = [exchange for exchange in VENUES if exchange in series]
    ordered = {exchange: series[exchange] for exchange in venues}

    # The first bar where every listed venue has a sample.
    coverage_from = next(
        (
            index
            for index in range(len(candles))
            if all(ordered[exchange][index] is not None for exchange in venues)
        ),
        len(candles),
    )

    # The aggregate exists only where every venue does. Summing a changing
    # number of books produces a line that is not a time series of anything: on
    # the fallback path Binance keeps thirty days where OKX keeps a hundred and
    # eighty, and carrying the sum across that boundary drew a 290% jump in
    # open interest on the bar Binance's history began. Ending the series
    # instead is the same refusal `/api/price` makes for an unresolved symbol —
    # the per-venue pane still shows each book's full history, so nothing is
    # hidden, only the number that would have been wrong.
    aggregate: List[Optional[float]] = []
    for index in range(len(candles)):
        if index < coverage_from:
            aggregate.append(None)
            continue
        present = [ordered[exchange][index] for exchange in venues]
        known = [value for value in present if value is not None]
        aggregate.append(sum(known) if known else None)

    return {
        "symbol": base,
        "interval": interval,
        "source": source,
        "venues": venues,
        "candles": candles,
        "series": ordered,
        "aggregate": aggregate,
        "market_cap": [],
        "circulating_supply": None,
        "coverage_from": coverage_from,
    }


def _empty_result(symbol: str, interval: str) -> Dict[str, Any]:
    """
    Every key present, every array empty.

    A partial dict would make the client guard each field individually; an
    absent one would crash it. The empty state is a shape, not a hole.
    """
    return {
        "symbol": symbol.upper(),
        "interval": interval,
        "source": SOURCE_VENUES,
        "venues": [],
        "candles": [],
        "series": {},
        "aggregate": [],
        "market_cap": [],
        "circulating_supply": None,
        "coverage_from": 0,
    }


async def _circulating_supply(base: str, latest_close: float) -> Optional[float]:
    """
    Circulating supply, inferred from the cached universe. None when unknown.

    Deliberately not its own CoinGecko call. `asset_registry.get_crypto_universe`
    already holds the top 250 by market cap, refreshed hourly and persisted to
    disk, and the anonymous free tier throttles hard enough that a dedicated
    request for one number answers 429 most of the time — which is how this pane
    first shipped permanently blank. Dividing that market cap by the newest close
    gives supply for free and keeps working while CoinGecko is refusing calls.

    Market cap is then derived per candle as `close * supply` rather than fetched
    as a second time series: supply moves by fractions of a percent over the
    windows this board draws, and the ratio it feeds is read for its trend. The
    approximation is deliberate, and it is why the pane is labelled as derived.
    """
    if latest_close <= 0:
        return None

    cache_key = f"supply:{base}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        universe = await get_crypto_universe(250)
    except Exception as exc:
        logger.warning("Crypto universe failed for %s: %s", base, type(exc).__name__)
        return _cache.get_with_fallback(cache_key)

    wanted = base.upper()
    market_cap = next(
        (float(coin.get("market_cap") or 0) for coin in universe if coin.get("symbol") == wanted),
        0.0,
    )
    if market_cap <= 0:
        return None

    supply = market_cap / latest_close
    _cache.set(cache_key, supply, SUPPLY_TTL_SECONDS)
    return supply
