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
from itertools import chain, zip_longest
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from services import binance_market, bybit_market
from services.cache import ServiceCache
from services.http_client import get_json
from services.liquidation_service import liquidation_service
from services.okx_market import OKX_MAX_CANDLES, to_okx_inst_id

logger = logging.getLogger(__name__)

OKX_RUBIK_URL = "https://www.okx.com/api/v5/rubik/stat/contracts"

# Named in the payload rather than left for the client to assume. Both views are
# a *model*, and which venue's book they model is part of reading them: OKX's
# open interest is not Binance's, and a chart that shows neither invites the
# reader to compare it against whichever exchange they happen to have open.
EXCHANGE = "OKX"

# Venues the profile can be modelled for.
#
# Only the profile is multi-venue, and deliberately so. The heatmap and the
# levels view are read as this terminal's picture of the book, and giving them a
# venue switch would multiply the upstream load of the two heaviest payloads to
# answer a question nobody asks of them. A profile is three kilobytes and the
# comparison is its whole point.
OKX_VENUE = "okx"
BINANCE_VENUE = "binance"
BYBIT_VENUE = "bybit"
COMBINED_VENUE = "all"

VENUE_LABELS = {
    OKX_VENUE: EXCHANGE,
    BINANCE_VENUE: binance_market.EXCHANGE,
    BYBIT_VENUE: bybit_market.EXCHANGE,
}

# Which venues the aggregate sums, in the order its label names them — so the
# label reads the same from one refresh to the next.
AGGREGATED_VENUES = (BINANCE_VENUE, OKX_VENUE, BYBIT_VENUE)

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

# One emitted span: (start_column, end_column, bin, leverage, side, notional).
# `side` is 0 for longs and 1 for shorts.
LineRecord = Tuple[int, int, int, int, int, float]

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

# The same distribution at the resolution the levels view draws at.
#
# `LEVERAGE_TIERS` is deliberately coarse: the heatmap sums every tier into one
# cell, so four sample points already spend the whole grid. A span, though, *is*
# its tier — four of them draw four bands where the market has a continuum, and
# the chart then reads as a diagram of the model's assumptions rather than as
# the book. Ten tiers cost nothing (the simulation is per candle, not per tier)
# and put the picture back.
#
# Grouped, the weights reproduce `LEVERAGE_TIERS`: 10-20x carries 0.29 against
# its 0.28, 25-40x 0.30 against 0.30, 50-75x 0.25 against 0.26, and 100-125x
# 0.16 against 0.16. The floor stays at 10x on purpose — `MAX_LEVERAGE_DISTANCE`
# is derived from the coarse table, so a 5x tier would liquidate outside the
# shared price grid and be dropped in silence, and widening the grid here would
# break the one geometry both views are pinned to.
LINE_LEVERAGE_TIERS: Tuple[Tuple[int, float], ...] = (
    (10, 0.12),
    (15, 0.09),
    (20, 0.08),
    (25, 0.11),
    (30, 0.10),
    (40, 0.09),
    (50, 0.14),
    (75, 0.11),
    (100, 0.09),
    (125, 0.07),
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

# The same idea for the line view, but measured against the strongest line *in
# the same leverage tier* rather than against the strongest line overall. The
# tiers' peaks differ by roughly 2.6x — the 100x band carries the smallest
# weight and gets swept before it can accumulate much — so a global floor trims
# high leverage about three times as hard as low. That band is exactly what the
# high-leverage filter exposes, which would leave this module quietly emptying a
# filter the moment a user switched it on.
#
# Lower than CELL_FLOOR because the two quantities are not comparable: a cell
# value is the book at one instant, while a line's notional accumulates over its
# whole life. The distribution is wider, and 0.002 of a tier's peak is already
# below one pixel of opacity.
LINE_FLOOR = 0.002

# Safety valve on the payload. The structural bound is
# `simulated candles * len(LINE_LEVERAGE_TIERS) * 2`, 6000 at OKX's candle
# limit, and a realistic window measures around half that. Set where the picture
# is still dense enough to read as a book rather than as a sample of one: at
# roughly 23 bytes a span this is under 100 KB, a third of what the heatmap's
# cell list already ships.
MAX_LINES = 4000

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


def _simulate_lines(
    candles: Sequence[Dict[str, Any]],
    opened: Sequence[float],
    long_shares: Sequence[float],
    bins: int,
    emit_from: int,
) -> Dict[str, Any]:
    """
    Run the same accumulate-and-sweep model, but keep each level's identity.

    `_simulate` snapshots a `[bins]` float book once per column, and that
    snapshot throws away the two things a line needs: which leverage tier
    produced a level, and which candle it was opened at. Here the book holds one
    record per open level instead — keyed by leverage and side within its bin —
    so a swept level is emitted as a single span rather than as a trail of
    identical cells across every column it survived.

    The sweep still runs before the deposit, exactly as in `_simulate`. A level
    placed inside its own candle's range therefore lives exactly one column,
    which is why the 100x tier is mostly stubs. That is the model being honest
    about how fast high leverage dies; re-ordering it here would leave the two
    views disagreeing about the same market, which is worse than either ordering
    on its own.
    """
    price_min, price_max, bin_size = _price_grid(candles, bins)

    # bin -> {(leverage, side): [open_index, notional_usd]}. Indexed by bin
    # rather than held as one flat dict so a sweep stays O(bins touched) instead
    # of walking every open level in the book.
    book: List[Dict[Tuple[int, int], List[float]]] = [{} for _ in range(bins)]
    closed: List[LineRecord] = []

    def emit(cell: int, key: Tuple[int, int], record: List[float], close_index: int) -> None:
        # Opened *and* swept before the visible window: never drawable, and in a
        # normal window that is a fifth of everything the model produces.
        if close_index < emit_from:
            return
        leverage, side = key
        closed.append(
            (
                # Clamped, not left negative. A negative column would place a
                # point before the first candle, and the chart's time axis fits
                # its domain to the data — the candles would compress into the
                # right of the canvas. Clamping also says the right thing:
                # column 0 means the level was already standing when the window
                # opened.
                max(int(record[0]) - emit_from, 0),
                close_index - emit_from,
                cell,
                leverage,
                side,
                record[1],
            )
        )

    for index, candle in enumerate(candles):
        # 1. Sweep — every level inside the candle's range has been reached, and
        #    a reached level is a spent one. Hundreds of spans ending on one
        #    column is the intended read, not noise: that wall is price eating
        #    through a shelf of liquidity.
        low_bin = _bin_index(candle["low"], price_min, bin_size, bins)
        high_bin = _bin_index(candle["high"], price_min, bin_size, bins)
        if low_bin is not None or high_bin is not None:
            start = low_bin if low_bin is not None else 0
            end = high_bin if high_bin is not None else bins - 1
            for cell in range(start, end + 1):
                if not book[cell]:
                    continue
                for key, record in book[cell].items():
                    emit(cell, key, record, index)
                book[cell] = {}

        # 2. Deposit — place this candle's new exposure at its liquidation
        #    prices, merging into whatever already stands at that level.
        notional = opened[index]
        if notional > 0:
            entry = (candle["high"] + candle["low"] + candle["close"]) / 3.0
            long_notional = notional * long_shares[index]
            short_notional = notional - long_notional

            for leverage, weight in LINE_LEVERAGE_TIERS:
                distance = 1.0 / leverage - MAINTENANCE_MARGIN_RATE

                for side, price, amount in (
                    (0, entry * (1.0 - distance), long_notional),
                    (1, entry * (1.0 + distance), short_notional),
                ):
                    target = _bin_index(price, price_min, bin_size, bins)
                    if target is None:
                        continue
                    record = book[target].get((leverage, side))
                    if record is None:
                        book[target][(leverage, side)] = [float(index), amount * weight]
                    else:
                        # Only the notional grows. The span stays anchored to
                        # when the level came into being rather than to its last
                        # top-up, which is what the level's origin means and
                        # what the chart draws the left edge as.
                        record[1] += amount * weight

    # 3. Whatever price never came back for. These run to the right edge, which
    #    is what marks them as the levels still standing.
    for cell in range(bins):
        for key, record in book[cell].items():
            emit(cell, key, record, len(candles) - 1)

    tiers = [tier for tier, _ in LINE_LEVERAGE_TIERS]
    tier_max: Dict[int, float] = dict.fromkeys(tiers, 0.0)
    for line in closed:
        tier_max[line[3]] = max(tier_max[line[3]], line[5])

    kept = [line for line in closed if line[5] >= tier_max[line[3]] * LINE_FLOOR]

    if len(kept) > MAX_LINES:
        # Take from the tiers in turn rather than off one global ranking. A
        # global ranking hands the whole budget to whichever tier carries the
        # largest absolute numbers, and the tier that loses is reliably the 100x
        # band — the one the high-leverage filter exists to show. Interleaving
        # costs a little fidelity in the crowded tiers and keeps every tier on
        # the chart, which is the trade the filter needs.
        by_tier: Dict[int, List[LineRecord]] = {}
        for line in kept:
            by_tier.setdefault(line[3], []).append(line)
        for tier_lines in by_tier.values():
            tier_lines.sort(key=lambda line: line[5], reverse=True)

        interleaved = chain.from_iterable(zip_longest(*(by_tier.get(t, []) for t in tiers)))
        kept = [line for line in interleaved if line is not None][:MAX_LINES]

    kept.sort(key=lambda line: (line[0], line[2]))

    return {
        "lines": [
            [start, end, cell, leverage, side, round(notional)]
            for start, end, cell, leverage, side, notional in kept
        ],
        "price_min": round(price_min, 8),
        "price_max": round(price_max, 8),
        "bin_size": round(bin_size, 8),
        "bins": bins,
        "max_value": round(max(tier_max.values())) if tier_max else 0,
        "tier_max": [round(tier_max[tier]) for tier in tiers],
    }


def _simulate_profile(
    candles: Sequence[Dict[str, Any]],
    opened: Sequence[float],
    long_shares: Sequence[float],
    bins: int,
) -> Dict[str, Any]:
    """
    Run the same model and return only the book as it stands at the last candle.

    The heatmap is this book once per column and the levels view is its history;
    the profile is the newest column alone, kept split by leverage tier instead
    of summed. Nothing before the last candle is emitted, so there is no warm-up
    boundary to respect here — every candle in the window is warm-up for the one
    snapshot that comes back, which is also why this reads `candles` whole while
    the other two simulations take an `emit_from`.
    """
    price_min, price_max, bin_size = _price_grid(candles, bins)

    # book[side][tier][bin]; side 0 is longs, 1 is shorts.
    book = [[[0.0] * bins for _ in LEVERAGE_TIERS] for _ in range(2)]

    for index, candle in enumerate(candles):
        # 1. Sweep — a level price has reached is a level that is gone, at every
        #    tier at once. Same order as `_simulate`: sweep, then deposit.
        low_bin = _bin_index(candle["low"], price_min, bin_size, bins)
        high_bin = _bin_index(candle["high"], price_min, bin_size, bins)
        if low_bin is not None or high_bin is not None:
            start = low_bin if low_bin is not None else 0
            end = high_bin if high_bin is not None else bins - 1
            for side_book in book:
                for tier_book in side_book:
                    for cell in range(start, end + 1):
                        tier_book[cell] = 0.0

        # 2. Deposit — this candle's new exposure at its liquidation prices.
        notional = opened[index]
        if notional <= 0:
            continue

        entry = (candle["high"] + candle["low"] + candle["close"]) / 3.0
        long_notional = notional * long_shares[index]
        short_notional = notional - long_notional

        for tier, (leverage, weight) in enumerate(LEVERAGE_TIERS):
            distance = 1.0 / leverage - MAINTENANCE_MARGIN_RATE

            target = _bin_index(entry * (1.0 - distance), price_min, bin_size, bins)
            if target is not None:
                book[0][tier][target] += long_notional * weight

            target = _bin_index(entry * (1.0 + distance), price_min, bin_size, bins)
            if target is not None:
                book[1][tier][target] += short_notional * weight

    levels: List[List[float]] = []
    bin_totals = [0.0] * bins
    totals = [0.0, 0.0]

    for side, side_book in enumerate(book):
        for tier, tier_book in enumerate(side_book):
            for cell, value in enumerate(tier_book):
                if value <= 0:
                    continue
                levels.append([cell, tier, side, round(value)])
                bin_totals[cell] += value
                totals[side] += value

    # No floor here, unlike the other two: a profile is at most
    # `bins * len(LEVERAGE_TIERS) * 2` entries however long the window is, so
    # there is nothing to trim, and a bar the client stacks is wrong if any part
    # of it was dropped for being small.
    levels.sort(key=lambda entry: (entry[0], entry[1], entry[2]))

    return {
        "levels": levels,
        "price_min": round(price_min, 8),
        "price_max": round(price_max, 8),
        "bin_size": round(bin_size, 8),
        "bins": bins,
        "max_value": round(max(bin_totals) if bin_totals else 0.0),
        "total_long": round(totals[0]),
        "total_short": round(totals[1]),
    }


# ── Shared inputs ────────────────────────────────────────────────────────────


class _MapInputs(NamedTuple):
    """Everything both simulations need, fetched and aligned once."""

    inst_id: str
    candles: List[Dict[str, Any]]
    opened: List[float]
    long_shares: List[float]
    emit_from: int
    stats_from_column: int
    interval_ms: int


async def _load_inputs(
    inst_id: str, interval: str, columns: int, venue: str = OKX_VENUE
) -> Optional[_MapInputs]:
    """
    Fetch and align the model's inputs, or None when OKX has no candles.

    Cached under its own key and shared by both public entry points. `okx_market`
    has no cache of its own, so without this the second view would repeat all
    three upstream calls on every miss. The bigger reason is correctness: both
    views derive their price grid from this candle list, so they cannot drift
    apart and the chart cannot jump when a user switches between them.
    """
    cache_key = f"inputs:{venue}:{inst_id}:{interval}:{columns}"
    cached = _map_cache.get(cache_key)
    if cached is not None:
        return cached

    requested = min(columns + WARMUP_COLUMNS, OKX_MAX_CANDLES)

    if venue == BYBIT_VENUE:
        candles, oi_series, ratio_series = await asyncio.gather(
            bybit_market.fetch_candles(inst_id, interval=interval, limit=requested),
            bybit_market.fetch_open_interest(
                inst_id, interval, min(requested, bybit_market.MAX_OI_ROWS)
            ),
            bybit_market.fetch_long_share(
                inst_id, interval, min(requested, bybit_market.MAX_RATIO_ROWS)
            ),
        )
    elif venue == BINANCE_VENUE:
        # Binance publishes the same three inputs under its own names, and caps
        # both statistics endpoints well below the candle one — asking for more
        # rows than that is an error rather than a short answer.
        rows = min(requested, binance_market.MAX_STAT_ROWS)
        candles, oi_series, ratio_series = await asyncio.gather(
            binance_market.fetch_candles(inst_id, interval=interval, limit=requested),
            binance_market.fetch_open_interest(inst_id, interval, rows),
            binance_market.fetch_long_share(inst_id, interval, rows),
        )
    else:
        base_currency = inst_id.split("-")[0]
        rubik_period = _rubik_period(interval, requested)

        candles, oi_series, ratio_series = await asyncio.gather(
            liquidation_service.fetch_candles(inst_id, interval=interval, limit=requested),
            _fetch_rubik_series("open-interest-volume", base_currency, rubik_period, 1),
            _fetch_rubik_series("long-short-account-ratio", base_currency, rubik_period, 1),
        )

    if not candles:
        return None

    candle_times_ms = [candle["time"] * 1000 for candle in candles]
    oi_aligned = _align_to_candles(oi_series, candle_times_ms)

    if venue == BYBIT_VENUE:
        # Bybit reports open interest in contracts where the others report a USD
        # value, and the model weighs it against traded notional. Converting
        # here rather than in the client is what lets each sample use the close
        # of the candle it was aligned to, instead of one price for the window.
        oi_aligned = [
            value * candles[index]["close"] if value is not None else None
            for index, value in enumerate(oi_aligned)
        ]
    ratio_aligned = _align_to_candles(ratio_series, candle_times_ms)

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

    emitted = candles[emit_from:]
    inputs = _MapInputs(
        inst_id=inst_id,
        candles=candles,
        opened=_opened_notional(candles, oi_aligned),
        long_shares=_long_shares(ratio_aligned),
        emit_from=emit_from,
        stats_from_column=covered_from - emit_from,
        interval_ms=(emitted[1]["time"] - emitted[0]["time"]) * 1000 if len(emitted) > 1 else 0,
    )

    _map_cache.set(cache_key, inputs, CACHE_TTL_SECONDS)
    return inputs


def _empty_result(inst_id: str, interval: str, bins: int) -> Dict[str, Any]:
    """
    The fields every payload carries, with the geometry zeroed.

    No candles means no grid, and an empty answer is the honest one — the
    frontend renders it as "no data" rather than as a broken chart. Every key is
    still present, because an omitted field reads to the client as a lookup that
    never happened rather than as an emptiness that was measured.
    """
    return {
        "symbol": inst_id,
        "exchange": EXCHANGE,
        "interval": interval,
        "candles": [],
        "bins": bins,
        "price_min": 0.0,
        "price_max": 0.0,
        "bin_size": 0.0,
        "max_value": 0,
        "interval_ms": 0,
        "leverage_tiers": [tier for tier, _ in LEVERAGE_TIERS],
        "stats_from_column": 0,
    }


def _clamp(interval: str, columns: int, bins: int) -> Tuple[str, int, int]:
    """Normalise the request bounds both entry points share."""
    return (
        interval.lower(),
        max(20, min(columns, OKX_MAX_CANDLES - 20)),
        max(20, min(bins, 200)),
    )


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
    interval, columns, bins = _clamp(interval, columns, bins)

    cache_key = f"map:{inst_id}:{interval}:{columns}:{bins}"
    cached = _map_cache.get(cache_key)
    if cached is not None:
        return cached

    inputs = await _load_inputs(inst_id, interval, columns)

    if inputs is None:
        empty = _empty_result(inst_id, interval, bins)
        empty["cells"] = []
        stale = _map_cache.get_with_fallback(cache_key)
        return stale if stale is not None else empty

    result = _simulate(inputs.candles, inputs.opened, inputs.long_shares, bins, inputs.emit_from)

    result.update(
        {
            "symbol": inst_id,
            "exchange": EXCHANGE,
            "interval": interval,
            "candles": inputs.candles[inputs.emit_from :],
            "interval_ms": inputs.interval_ms,
            "leverage_tiers": [tier for tier, _ in LEVERAGE_TIERS],
            "stats_from_column": inputs.stats_from_column,
        }
    )

    _map_cache.set(cache_key, result, CACHE_TTL_SECONDS)
    return result


async def get_liquidation_lines(
    symbol: str,
    interval: str = "1h",
    columns: int = 160,
    bins: int = 120,
) -> Dict[str, Any]:
    """
    Build the same map as spans rather than as a grid.

    Same model, same inputs, same geometry as `get_liquidation_map` — only the
    shape of the answer differs. Each entry is
    `[start_col, end_col, bin, leverage, side, notional_usd]`, running from the
    column the level was opened at to the column price swept it; a span reaching
    the last column is a level still standing. `side` is 0 for longs and 1 for
    shorts, and `tier_max` gives each leverage tier's strongest span so a client
    can scale intensity per tier instead of flattening the high-leverage band.
    """
    inst_id = to_okx_inst_id(symbol)
    interval, columns, bins = _clamp(interval, columns, bins)

    cache_key = f"lines:{inst_id}:{interval}:{columns}:{bins}"
    cached = _map_cache.get(cache_key)
    if cached is not None:
        return cached

    inputs = await _load_inputs(inst_id, interval, columns)

    if inputs is None:
        empty = _empty_result(inst_id, interval, bins)
        empty.update(
            {
                "lines": [],
                "leverage_tiers": [tier for tier, _ in LINE_LEVERAGE_TIERS],
                "tier_max": [0 for _ in LINE_LEVERAGE_TIERS],
            }
        )
        stale = _map_cache.get_with_fallback(cache_key)
        return stale if stale is not None else empty

    result = _simulate_lines(
        inputs.candles, inputs.opened, inputs.long_shares, bins, inputs.emit_from
    )

    result.update(
        {
            "symbol": inst_id,
            "exchange": EXCHANGE,
            "interval": interval,
            "candles": inputs.candles[inputs.emit_from :],
            "interval_ms": inputs.interval_ms,
            "leverage_tiers": [tier for tier, _ in LINE_LEVERAGE_TIERS],
            "stats_from_column": inputs.stats_from_column,
        }
    )

    _map_cache.set(cache_key, result, CACHE_TTL_SECONDS)
    return result


def _venue_inst_id(venue: str, symbol: str) -> str:
    """The instrument id a venue knows the market by."""
    if venue == BINANCE_VENUE:
        return binance_market.to_binance_symbol(symbol)
    if venue == BYBIT_VENUE:
        return bybit_market.to_bybit_symbol(symbol)
    return to_okx_inst_id(symbol)


def _empty_profile(inst_id: str, interval: str, bins: int, exchange: str) -> Dict[str, Any]:
    """The profile's shape with the geometry zeroed."""
    empty = _empty_result(inst_id, interval, bins)
    # A profile is one moment. These two would be answering a question the
    # payload does not ask, and a client that found them would draw a series the
    # numbers do not describe.
    empty.pop("candles")
    empty.pop("interval_ms")
    empty.update({"levels": [], "price": 0.0, "total_long": 0, "total_short": 0})
    empty["exchange"] = exchange
    return empty


async def _combined_profile(symbol: str, interval: str, columns: int, bins: int) -> Dict[str, Any]:
    """
    One profile from every venue's book at once.

    The parts are re-binned onto a grid spanning all of them rather than summed
    bin-for-bin: each venue derives its own grid from its own candles, so bin 40
    is not the same price on two of them, and adding the two lists directly
    would shift one venue's walls by however far the two price ranges differ.

    A venue that answers with nothing is left out of the sum *and* out of the
    label. An aggregate that silently became one exchange is the failure mode
    worth guarding here — it would read as the market having thinned out.
    """
    parts = await asyncio.gather(
        *(
            get_liquidation_profile(symbol, interval, columns, bins, venue=venue)
            for venue in AGGREGATED_VENUES
        )
    )
    contributing = [part for part in parts if part["levels"]]

    if not contributing:
        return _empty_profile(symbol.upper(), interval, bins, "—")

    price_min = min(part["price_min"] for part in contributing)
    price_max = max(part["price_max"] for part in contributing)
    bin_size = (price_max - price_min) / bins if bins else 0.0

    merged: Dict[Tuple[int, int, int], float] = {}
    for part in contributing:
        for cell, tier, side, notional in part["levels"]:
            price = part["price_min"] + (cell + 0.5) * part["bin_size"]
            target = _bin_index(price, price_min, bin_size, bins)
            if target is None:
                continue
            key = (target, tier, side)
            merged[key] = merged.get(key, 0.0) + notional

    bin_totals = [0.0] * bins
    totals = [0.0, 0.0]
    levels: List[List[float]] = []
    for (cell, tier, side), notional in sorted(merged.items()):
        levels.append([cell, tier, side, round(notional)])
        bin_totals[cell] += notional
        totals[side] += notional

    return {
        "symbol": symbol.upper(),
        "exchange": " + ".join(part["exchange"] for part in contributing),
        "interval": interval,
        # The mean, because an aggregate book has no single spot. The venues
        # track each other to a few basis points, so this never lands anywhere
        # meaningful other than between them.
        "price": sum(part["price"] for part in contributing) / len(contributing),
        "levels": levels,
        "price_min": round(price_min, 8),
        "price_max": round(price_max, 8),
        "bin_size": round(bin_size, 8),
        "bins": bins,
        "max_value": round(max(bin_totals) if bin_totals else 0.0),
        "total_long": round(totals[0]),
        "total_short": round(totals[1]),
        "leverage_tiers": [tier for tier, _ in LEVERAGE_TIERS],
        # The worst of the parts: an aggregate is only as covered as its
        # thinnest contributor, and claiming the best would hide the gap.
        "stats_from_column": max(part["stats_from_column"] for part in contributing),
    }


async def get_liquidation_profile(
    symbol: str,
    interval: str = "1h",
    columns: int = 160,
    bins: int = 120,
    venue: str = OKX_VENUE,
) -> Dict[str, Any]:
    """
    Build the standing liquidation book as a price profile.

    Where `get_liquidation_map` answers "where has liquidity been over time",
    this answers "where is it right now" — one entry per
    `[bin, tier_index, side, notional_usd]`, with `tier_index` pointing into
    `leverage_tiers`. No candles come back and there is no time axis: the whole
    payload describes a single moment, and `price` is the close that moment sits
    at, which is what separates the two sides of the chart.

    `venue` selects whose book is modelled. Every venue is fetched from itself —
    a book modelled from one exchange's open interest describes that exchange,
    and the comparison is worthless if the parts share a source.
    """
    interval, columns, bins = _clamp(interval, columns, bins)

    if venue == COMBINED_VENUE:
        cache_key = f"profile:{COMBINED_VENUE}:{symbol.upper()}:{interval}:{columns}:{bins}"
        cached = _map_cache.get(cache_key)
        if cached is not None:
            return cached
        result = await _combined_profile(symbol, interval, columns, bins)
        _map_cache.set(cache_key, result, CACHE_TTL_SECONDS)
        return result

    inst_id = _venue_inst_id(venue, symbol)
    exchange = VENUE_LABELS.get(venue, EXCHANGE)

    cache_key = f"profile:{venue}:{inst_id}:{interval}:{columns}:{bins}"
    cached = _map_cache.get(cache_key)
    if cached is not None:
        return cached

    inputs = await _load_inputs(inst_id, interval, columns, venue=venue)

    if inputs is None:
        empty = _empty_profile(inst_id, interval, bins, exchange)
        stale = _map_cache.get_with_fallback(cache_key)
        return stale if stale is not None else empty

    result = _simulate_profile(inputs.candles, inputs.opened, inputs.long_shares, bins)

    result.update(
        {
            "symbol": inst_id,
            "exchange": exchange,
            "interval": interval,
            "price": inputs.candles[-1]["close"],
            "leverage_tiers": [tier for tier, _ in LEVERAGE_TIERS],
            "stats_from_column": inputs.stats_from_column,
        }
    )

    _map_cache.set(cache_key, result, CACHE_TTL_SECONDS)
    return result
