"""
Binance USD-M futures market data, for the liquidation model only.

`okx_market` is deliberately the single source for prices, candles and trades,
and that has not changed: its module docstring explains why, and Binance is
unreachable from some networks this app runs on. This module exists for one
narrow reason — the liquidation map is a *per-venue* answer. A book modelled
from OKX describes OKX's book, and showing it next to a second venue is the
whole point of the comparison, so the second venue has to be fetched from the
second venue.

Everything here is public and unauthenticated. Nothing invents a value: a failed
or empty response returns `[]` and the caller decides what to say about the gap.
"""

import logging
from typing import Any, Dict, List, Tuple

from services.http_client import get_json

logger = logging.getLogger(__name__)

KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
OPEN_INTEREST_URL = "https://fapi.binance.com/futures/data/openInterestHist"
LONG_SHORT_URL = "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"

EXCHANGE = "Binance"

# The statistics endpoints accept a narrower set of periods than the kline one,
# and they only reach back thirty days. Anything finer than 5m is unavailable,
# so a request below it is served by the nearest period the endpoint has rather
# than by nothing — the series is aligned to candle timestamps downstream, which
# is where a coarser sample is absorbed.
STAT_PERIODS = ("5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d")

# Binance caps both statistics endpoints at 500 rows per request.
MAX_STAT_ROWS = 500


def to_binance_symbol(symbol: str) -> str:
    """
    Normalise whatever shape the caller had into Binance's `BTCUSDT`.

    Accepts the same spellings the rest of the app passes around — venue
    prefixes, slashes, and OKX's swap instrument ids.
    """
    cleaned = symbol.upper().split(":")[-1].replace("/", "").replace("_", "")
    if cleaned.endswith("-SWAP"):
        cleaned = cleaned[: -len("-SWAP")]
    cleaned = cleaned.replace("-", "")
    return cleaned


# Minutes per unit, for reading a candle interval `STAT_PERIODS` does not list.
_UNIT_MINUTES = {"m": 1, "h": 60, "d": 1440, "w": 10080}


def _minutes(interval: str) -> int:
    """Length of a candle interval in minutes, or 0 when it cannot be read."""
    text = interval.strip().lower()
    unit = _UNIT_MINUTES.get(text[-1:])
    if unit is None:
        return 0
    try:
        return int(text[:-1]) * unit
    except ValueError:
        return 0


def _stat_period(interval: str) -> str:
    """
    The statistics period to use for a candle interval, never finer than 5m.

    A candle the list does not spell gets the coarsest period that still fits
    inside it, because the samples are aligned onto candles with a "last value
    at or before" rule and a finer series is correct there, only shorter in
    reach. Weekly is the case that matters: it used to fall back to one hour,
    and five hundred hourly rows cover three weeks of a chart that spans years,
    so nearly every column was modelled from volume alone.
    """
    wanted = interval.lower()
    if wanted in STAT_PERIODS:
        return wanted

    minutes = _minutes(wanted)
    fitting = [period for period in STAT_PERIODS if _minutes(period) <= minutes]
    # Nothing fits only when the candle is finer than the finest sample, and
    # there the finest is still the right answer.
    return fitting[-1] if fitting else STAT_PERIODS[0]


async def fetch_candles(
    symbol: str, interval: str = "1h", limit: int = 200
) -> List[Dict[str, Any]]:
    """
    OHLCV in the same shape `okx_market.fetch_candles` returns, oldest first.

    `volume_usd` comes from the quote-asset volume Binance already reports
    rather than from `close * volume`: the exchange's own figure sums each trade
    at its own price, which is the number the model wants.
    """
    try:
        rows = await get_json(
            KLINES_URL,
            params={
                "symbol": to_binance_symbol(symbol),
                "interval": interval.lower(),
                "limit": max(1, min(limit, 1500)),
            },
        )
    except Exception as exc:
        logger.warning("Binance candles failed for %s: %s", symbol, type(exc).__name__)
        return []

    if not isinstance(rows, list):
        return []

    candles: List[Dict[str, Any]] = []
    for row in rows:
        try:
            candles.append(
                {
                    "time": int(row[0]) // 1000,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "volume_usd": float(row[7]),
                }
            )
        except (IndexError, TypeError, ValueError):
            continue

    return candles


async def fetch_open_interest(symbol: str, interval: str, limit: int) -> List[Tuple[int, float]]:
    """Open interest in USD, as `(timestamp_ms, value)` oldest first."""
    return await _fetch_stat(OPEN_INTEREST_URL, symbol, interval, limit, "sumOpenInterestValue")


async def fetch_long_share(symbol: str, interval: str, limit: int) -> List[Tuple[int, float]]:
    """The share of accounts holding longs, as `(timestamp_ms, share)` oldest first."""
    return await _fetch_stat(LONG_SHORT_URL, symbol, interval, limit, "longAccount")


async def _fetch_stat(
    url: str, symbol: str, interval: str, limit: int, field: str
) -> List[Tuple[int, float]]:
    try:
        rows = await get_json(
            url,
            params={
                "symbol": to_binance_symbol(symbol),
                "period": _stat_period(interval),
                "limit": max(1, min(limit, MAX_STAT_ROWS)),
            },
        )
    except Exception as exc:
        logger.warning("Binance %s failed for %s: %s", field, symbol, type(exc).__name__)
        return []

    if not isinstance(rows, list):
        return []

    series: List[Tuple[int, float]] = []
    for row in rows:
        try:
            series.append((int(row["timestamp"]), float(row[field])))
        except (KeyError, TypeError, ValueError):
            continue

    series.sort(key=lambda point: point[0])
    return series
