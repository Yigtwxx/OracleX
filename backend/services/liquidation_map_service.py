"""
Liquidation Map Service.

Rebuilds a Coinglass-style "liquidation heatmap" from free public OKX data.

Coinglass keeps that chart behind a paid API tier, but nothing in it is
proprietary market data — it is a *model* over inputs that OKX publishes for
free. This module reimplements the model:

  * `/api/v5/market/candles`                          — OHLCV
  * `/api/v5/rubik/stat/contracts/open-interest-volume` — open interest, in USD
  * `/api/v5/rubik/stat/contracts/long-short-account-ratio` — directional bias

What the map shows is therefore an **estimate of where leveraged positions
would be force-closed**, not a record of liquidations that happened. The
realised-liquidation feed lives in `liquidation_service` and is a different
thing entirely.

Model
-----
For every candle:

1. Estimate the notional of leveraged exposure opened during that candle as
   `max(ΔOI, 0) + VOLUME_OPEN_RATIO * quote volume`. Rising open interest is
   unambiguously new exposure; the volume term accounts for positions that
   opened and closed against each other without moving OI.
2. Split it into longs and shorts using the long/short account ratio.
3. Spread each side across a fixed distribution of leverage tiers and place the
   resulting liquidation price into a price bin:
       long  liq = entry * (1 - 1/L + mmr)
       short liq = entry * (1 + 1/L - mmr)
4. Carry the resulting book forward in time. A level stays on the map until
   price actually trades through it, at which point it is consumed — that is
   what produces the characteristic bands that stop dead where price swept them.
5. Snapshot the book after each candle. Those snapshots are the heatmap columns.

Every number the model invents is a named constant below, so the assumptions
are inspectable rather than buried in the arithmetic.
"""

import asyncio
import logging
from bisect import bisect_right
from typing import Any, Dict, List, Optional, Sequence, Tuple

from services.cache import ServiceCache
from services.http_client import get_json
from services.liquidation_service import liquidation_service
from services.okx_market import OKX_MAX_CANDLES, to_okx_inst_id

logger = logging.getLogger(__name__)

OKX_RUBIK_URL = "https://www.okx.com/api/v5/rubik/stat/contracts"

MINUTE_MS = 60_000

# Length of one candle at each interval the map accepts, used to work out how
# far back the requested window reaches.
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

# OKX publishes the aggregate statistics at three resolutions only, and serves a
# fixed number of rows per resolution regardless of the `limit` we ask for
# (measured: 5m → 576 rows, 1H → 720, 1D → 180). So each period reaches back a
# fixed distance and no further, finest first.
RUBIK_WINDOW_MS: Tuple[Tuple[str, int], ...] = (
    ("5m", 576 * 5 * MINUTE_MS),  # 2 days
    ("1H", 720 * 60 * MINUTE_MS),  # 30 days
    ("1D", 180 * 1440 * MINUTE_MS),  # 180 days
)

# ── Model constants ──────────────────────────────────────────────────────────

# Share of a candle's traded notional assumed to become newly opened leveraged
# exposure. Most volume is churn between existing positions, so this is small;
# it only matters for candles where open interest is flat or falling.
VOLUME_OPEN_RATIO = 0.06

# How the opened notional is assumed to distribute over leverage. Skewed toward
# mid leverage: 100x exists but carries far less size than the 10–50x band.
LEVERAGE_TIERS: Tuple[Tuple[int, float], ...] = (
    (10, 0.28),
    (25, 0.30),
    (50, 0.26),
    (100, 0.16),
)

# Maintenance margin rate for a major USDT perpetual at retail position size.
# It pulls the liquidation price slightly toward the entry.
MAINTENANCE_MARGIN_RATE = 0.004

# How far the least-leveraged tier sits from its entry. The grid is padded by at
# least this much on both sides, because levels landing outside it are dropped
# rather than clamped: pad by a fraction of the price *range* instead and the
# 10x band gets cut off on whichever side price is closer to, which reads as an
# absence of liquidity there rather than as the clipping it is.
MAX_LEVERAGE_DISTANCE = 1.0 / min(leverage for leverage, _ in LEVERAGE_TIERS) - (
    MAINTENANCE_MARGIN_RATE
)

# Columns simulated before the first emitted one, so the visible map starts with
# an already-populated book instead of fading in from empty.
WARMUP_COLUMNS = 60

# Cells weaker than this fraction of the strongest cell are omitted from the
# payload — they are invisible at any sane colour ramp and dominate the size.
CELL_FLOOR = 0.004

CACHE_TTL_SECONDS = 120

_map_cache = ServiceCache(maxsize=32)


# ── OKX statistics ───────────────────────────────────────────────────────────


def _rubik_period(interval: str, candles: int) -> str:
    """
    Pick the finest statistics resolution that still spans the whole window.

    A fine period on a long chart simply runs out partway back, and every candle
    older than that gets no open-interest or long/short sample at all — the model
    then falls back to volume alone with a neutral split. A coarser period
    samples each candle less precisely but covers the entire window, which is the
    better trade. When even the coarsest falls short, use it anyway and let
    `stats_from_column` mark how much of the map is left uncovered.
    """
    span_ms = candles * INTERVAL_MS.get(interval, 60 * MINUTE_MS)
    for period, window_ms in RUBIK_WINDOW_MS:
        if window_ms >= span_ms:
            return period
    return RUBIK_WINDOW_MS[-1][0]


async def _fetch_rubik_series(
    endpoint: str, ccy: str, period: str, value_index: int
) -> List[Tuple[int, float]]:
    """
    Fetch one OKX "rubik" statistics series as chronological (timestamp, value).

    Returns an empty list on any failure; the caller degrades to a neutral
    assumption rather than failing the whole map.
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


def _align_to_candles(
    series: Sequence[Tuple[int, float]], candle_times_ms: Sequence[int]
) -> List[Optional[float]]:
    """
    Sample `series` at each candle, taking the last value at or before it.

    The statistics endpoints run on their own (coarser) clock, so this is a
    step-wise lookup rather than an index-for-index join.
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


# ── Model ────────────────────────────────────────────────────────────────────


def _opened_notional(
    candles: Sequence[Dict[str, Any]], open_interest: Sequence[Optional[float]]
) -> List[float]:
    """Estimate newly opened leveraged notional per candle, in USD."""
    opened: List[float] = []
    previous_oi: Optional[float] = None

    for candle, oi in zip(candles, open_interest):
        growth = 0.0
        if oi is not None and previous_oi is not None:
            growth = max(oi - previous_oi, 0.0)
        if oi is not None:
            previous_oi = oi

        turnover = candle.get("volume_usd") or 0.0
        opened.append(growth + VOLUME_OPEN_RATIO * turnover)

    return opened


def _long_shares(ratios: Sequence[Optional[float]]) -> List[float]:
    """
    Convert the long/short *account* ratio into a long share of new notional.

    A ratio of 1.33 means 1.33 long accounts per short one, i.e. 57% long. When
    OKX has no sample the split falls back to neutral.
    """
    shares: List[float] = []
    for ratio in ratios:
        if ratio is None or ratio <= 0:
            shares.append(0.5)
        else:
            shares.append(ratio / (1.0 + ratio))
    return shares


def _price_grid(candles: Sequence[Dict[str, Any]], bins: int) -> Tuple[float, float, float]:
    """
    Return (price_min, price_max, bin_size) covering every level the model places.

    The grid reaches a full `MAX_LEVERAGE_DISTANCE` beyond the traded range, so a
    10x position opened at either extreme still has its liquidation price on the
    map. Anything narrower silently drops that tier — the heaviest one — on the
    side price happens to be sitting near.
    """
    low = min(candle["low"] for candle in candles)
    high = max(candle["high"] for candle in candles)

    price_min = max(low * (1.0 - MAX_LEVERAGE_DISTANCE), 0.0)
    price_max = high * (1.0 + MAX_LEVERAGE_DISTANCE)

    return price_min, price_max, (price_max - price_min) / bins


def _bin_index(price: float, price_min: float, bin_size: float, bins: int) -> Optional[int]:
    """Grid row for `price`, or None when it falls outside the window."""
    if bin_size <= 0:
        return None
    index = int((price - price_min) / bin_size)
    return index if 0 <= index < bins else None


def _simulate(
    candles: Sequence[Dict[str, Any]],
    opened: Sequence[float],
    long_shares: Sequence[float],
    bins: int,
    emit_from: int,
) -> Dict[str, Any]:
    """
    Run the accumulate-and-sweep model and return the emitted heatmap cells.

    Columns before `emit_from` are simulated but not emitted — they only exist
    to warm the book up.
    """
    price_min, price_max, bin_size = _price_grid(candles, bins)

    long_book = [0.0] * bins
    short_book = [0.0] * bins
    cells: List[Tuple[int, int, float, float]] = []
    peak = 0.0

    for index, candle in enumerate(candles):
        # 1. Sweep — every level inside the candle's range has been reached, and
        #    a reached liquidation level is a spent one.
        low_bin = _bin_index(candle["low"], price_min, bin_size, bins)
        high_bin = _bin_index(candle["high"], price_min, bin_size, bins)
        if low_bin is not None or high_bin is not None:
            start = low_bin if low_bin is not None else 0
            end = high_bin if high_bin is not None else bins - 1
            for cell in range(start, end + 1):
                long_book[cell] = 0.0
                short_book[cell] = 0.0

        # 2. Deposit — place this candle's new exposure at its liquidation prices.
        notional = opened[index]
        if notional > 0:
            entry = (candle["high"] + candle["low"] + candle["close"]) / 3.0
            long_notional = notional * long_shares[index]
            short_notional = notional - long_notional

            for leverage, weight in LEVERAGE_TIERS:
                distance = 1.0 / leverage - MAINTENANCE_MARGIN_RATE

                target = _bin_index(entry * (1.0 - distance), price_min, bin_size, bins)
                if target is not None:
                    long_book[target] += long_notional * weight

                target = _bin_index(entry * (1.0 + distance), price_min, bin_size, bins)
                if target is not None:
                    short_book[target] += short_notional * weight

        # 3. Snapshot — the book as it stands is this column of the heatmap.
        if index < emit_from:
            continue

        column = index - emit_from
        for cell in range(bins):
            total = long_book[cell] + short_book[cell]
            if total <= 0:
                continue
            peak = max(peak, total)
            cells.append((column, cell, long_book[cell], short_book[cell]))

    # Drop the cells too faint to render, then round for a compact payload.
    floor = peak * CELL_FLOOR
    trimmed = [
        [column, cell, round(long_value), round(short_value)]
        for column, cell, long_value, short_value in cells
        if long_value + short_value >= floor
    ]

    return {
        "cells": trimmed,
        "price_min": round(price_min, 8),
        "price_max": round(price_max, 8),
        "bin_size": round(bin_size, 8),
        "bins": bins,
        "max_value": round(peak),
    }


# ── Public API ───────────────────────────────────────────────────────────────


async def get_liquidation_map(
    symbol: str,
    interval: str = "1h",
    columns: int = 160,
    bins: int = 120,
) -> Dict[str, Any]:
    """
    Build the liquidation map for `symbol`.

    Returns the emitted candles alongside a sparse cell list
    `[column, bin, long_usd, short_usd]`, plus the grid geometry needed to place
    those cells on a price/time chart. Results are cached briefly because the
    simulation replays the whole window on every call.
    """
    inst_id = to_okx_inst_id(symbol)
    interval = interval.lower()
    columns = max(20, min(columns, OKX_MAX_CANDLES - 20))
    bins = max(20, min(bins, 200))

    cache_key = f"{inst_id}:{interval}:{columns}:{bins}"
    cached = _map_cache.get(cache_key)
    if cached is not None:
        return cached

    requested = min(columns + WARMUP_COLUMNS, OKX_MAX_CANDLES)
    base_currency = inst_id.split("-")[0]
    rubik_period = _rubik_period(interval, requested)

    candles, oi_series, ratio_series = await asyncio.gather(
        liquidation_service.fetch_candles(inst_id, interval=interval, limit=requested),
        _fetch_rubik_series("open-interest-volume", base_currency, rubik_period, 1),
        _fetch_rubik_series("long-short-account-ratio", base_currency, rubik_period, 1),
    )

    if not candles:
        # No candles means no grid — an empty map is the honest answer, and the
        # frontend renders it as "no data" rather than a broken chart.
        empty = {
            "symbol": inst_id,
            "interval": interval,
            "candles": [],
            "cells": [],
            "bins": bins,
            "price_min": 0.0,
            "price_max": 0.0,
            "bin_size": 0.0,
            "max_value": 0,
            "interval_ms": 0,
            "leverage_tiers": [tier for tier, _ in LEVERAGE_TIERS],
            "stats_from_column": 0,
        }
        stale = _map_cache.get_with_fallback(cache_key)
        return stale if stale is not None else empty

    candle_times_ms = [candle["time"] * 1000 for candle in candles]
    oi_aligned = _align_to_candles(oi_series, candle_times_ms)
    ratio_aligned = _align_to_candles(ratio_series, candle_times_ms)

    opened = _opened_notional(candles, oi_aligned)
    long_shares = _long_shares(ratio_aligned)

    emit_from = max(len(candles) - columns, 0)

    # Columns older than both statistics series are modelled from volume alone
    # with a neutral long/short split — same grid, weaker inputs. Report where
    # the full model starts so the frontend can say so rather than presenting
    # every column with equal confidence.
    covered_from = next(
        (
            index
            for index in range(emit_from, len(candles))
            if oi_aligned[index] is not None and ratio_aligned[index] is not None
        ),
        len(candles),
    )
    stats_from_column = covered_from - emit_from

    result = _simulate(candles, opened, long_shares, bins, emit_from)

    emitted = candles[emit_from:]
    interval_ms = (emitted[1]["time"] - emitted[0]["time"]) * 1000 if len(emitted) > 1 else 0

    result.update(
        {
            "symbol": inst_id,
            "interval": interval,
            "candles": emitted,
            "interval_ms": interval_ms,
            "leverage_tiers": [tier for tier, _ in LEVERAGE_TIERS],
            "stats_from_column": stats_from_column,
        }
    )

    _map_cache.set(cache_key, result, CACHE_TTL_SECONDS)
    return result
