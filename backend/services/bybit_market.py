"""
Bybit linear-perpetual market data, for the liquidation model only.

Here for the same narrow reason as `binance_market`: a liquidation book belongs
to the exchange that clears it, so an aggregate is only an aggregate if each
part was fetched from its own venue. `okx_market` remains the single source for
everything else this app draws.

One wrinkle worth knowing before reading `fetch_open_interest`: Bybit reports
open interest in contracts, where OKX and Binance both report a USD value. The
conversion needs a price per sample and this module has none, so the series
comes back in base units and `liquidation_map_service` multiplies it through the
candle closes it has already aligned to.
"""

import logging
from typing import Any, Dict, List, Tuple

from services.http_client import get_json

logger = logging.getLogger(__name__)

KLINE_URL = "https://api.bybit.com/v5/market/kline"
OPEN_INTEREST_URL = "https://api.bybit.com/v5/market/open-interest"
ACCOUNT_RATIO_URL = "https://api.bybit.com/v5/market/account-ratio"

EXCHANGE = "Bybit"

# Bybit spells candle intervals as bare minute counts, and the two statistics
# endpoints spell the same spans differently again.
KLINE_INTERVALS = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "4h": "240",
    "1d": "D",
    "1w": "W",
}
STAT_INTERVALS = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h"}

# Minutes per unit, for reading a candle interval that neither table spells.
_UNIT_MINUTES = {"m": 1, "h": 60, "d": 1440, "w": 10080}

# The open-interest endpoint caps a page at 200 rows, well under the candle
# one. Columns older than the last sample fall back to the volume-only path,
# which the payload already reports through `stats_from_column`.
MAX_OI_ROWS = 200
MAX_RATIO_ROWS = 500


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


def _stat_span(interval: str) -> str:
    """
    The span to ask the statistics endpoints for, given a candle interval.

    The two statistics endpoints stop at four hours where the candle endpoint
    runs to a week, so a daily or weekly candle has no span of its own. It gets
    the coarsest one that still fits inside it rather than nothing: every caller
    aligns these samples onto candles with a "last value at or before" rule, so
    a finer series lands on a coarser candle correctly. It costs reach — the row
    cap then covers fewer candles — and `stats_from_column` already reports
    exactly that. Returning an empty list instead would drop Bybit out of the
    model entirely at the intervals the longest windows are read at.
    """
    exact = STAT_INTERVALS.get(interval.lower())
    if exact is not None:
        return exact

    wanted = _minutes(interval)
    fitting = [span for key, span in STAT_INTERVALS.items() if _minutes(key) <= wanted]
    # Nothing fits only when the candle is finer than the finest sample, and
    # there the finest is still the right answer.
    return fitting[-1] if fitting else next(iter(STAT_INTERVALS.values()))


def to_bybit_symbol(symbol: str) -> str:
    """Normalise whatever shape the caller had into Bybit's `BTCUSDT`."""
    cleaned = symbol.upper().split(":")[-1].replace("/", "").replace("_", "")
    if cleaned.endswith("-SWAP"):
        cleaned = cleaned[: -len("-SWAP")]
    return cleaned.replace("-", "")


def _rows(payload: Any) -> List[Any]:
    """The `result.list` Bybit wraps every answer in, or nothing."""
    if not isinstance(payload, dict) or payload.get("retCode") != 0:
        return []
    result = payload.get("result")
    rows = result.get("list") if isinstance(result, dict) else None
    return rows if isinstance(rows, list) else []


async def fetch_candles(
    symbol: str, interval: str = "1h", limit: int = 200
) -> List[Dict[str, Any]]:
    """OHLCV in the same shape `okx_market.fetch_candles` returns, oldest first."""
    bar = KLINE_INTERVALS.get(interval.lower())
    if bar is None:
        return []

    try:
        payload = await get_json(
            KLINE_URL,
            params={
                "category": "linear",
                "symbol": to_bybit_symbol(symbol),
                "interval": bar,
                "limit": max(1, min(limit, 1000)),
            },
        )
    except Exception as exc:
        logger.warning("Bybit candles failed for %s: %s", symbol, type(exc).__name__)
        return []

    candles: List[Dict[str, Any]] = []
    for row in _rows(payload):
        try:
            candles.append(
                {
                    "time": int(row[0]) // 1000,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    # `turnover`, which is the quote-currency total the exchange
                    # itself summed trade by trade.
                    "volume_usd": float(row[6]),
                }
            )
        except (IndexError, TypeError, ValueError):
            continue

    # Bybit answers newest first; every consumer here expects oldest first.
    candles.sort(key=lambda candle: candle["time"])
    return candles


async def fetch_open_interest(symbol: str, interval: str, limit: int) -> List[Tuple[int, float]]:
    """
    Open interest in **base units**, as `(timestamp_ms, contracts)` oldest first.

    Not USD, unlike the other two venues — see the module docstring.
    """
    span = _stat_span(interval)

    try:
        payload = await get_json(
            OPEN_INTEREST_URL,
            params={
                "category": "linear",
                "symbol": to_bybit_symbol(symbol),
                "intervalTime": span,
                "limit": max(1, min(limit, MAX_OI_ROWS)),
            },
        )
    except Exception as exc:
        logger.warning("Bybit open interest failed for %s: %s", symbol, type(exc).__name__)
        return []

    return _series(_rows(payload), "openInterest")


async def fetch_long_share(symbol: str, interval: str, limit: int) -> List[Tuple[int, float]]:
    """The share of accounts holding longs, as `(timestamp_ms, share)` oldest first."""
    span = _stat_span(interval)

    try:
        payload = await get_json(
            ACCOUNT_RATIO_URL,
            params={
                "category": "linear",
                "symbol": to_bybit_symbol(symbol),
                "period": span,
                "limit": max(1, min(limit, MAX_RATIO_ROWS)),
            },
        )
    except Exception as exc:
        logger.warning("Bybit account ratio failed for %s: %s", symbol, type(exc).__name__)
        return []

    return _series(_rows(payload), "buyRatio")


def _series(rows: List[Any], field: str) -> List[Tuple[int, float]]:
    series: List[Tuple[int, float]] = []
    for row in rows:
        try:
            series.append((int(row["timestamp"]), float(row[field])))
        except (KeyError, TypeError, ValueError):
            continue
    series.sort(key=lambda point: point[0])
    return series
