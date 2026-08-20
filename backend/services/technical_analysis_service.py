"""
Technical Analysis Service — multi-timeframe structure, zones, RSI and trend.

Three things shape this module.

**Three timeframes, not one.** A 4h read alone answers "where is price now"
and nothing about where it sits in its own history, so every asset is read on
4h, 1d and 1w and each horizon keeps its own indicators. Short-, medium- and
long-term levels are then labelled by the timeframe that produced them rather
than by how far they happen to be from spot.

**Two years, and no further.** The weekly series is capped at
`WEEKLY_LOOKBACK` bars. For an asset with a decade of history, a level from
2017 is archaeology: it describes a market with different participants, and it
crowds out the levels price has actually traded against recently.

**Zones, not prices.** Support is a band that price reversed in several times,
not a single decimal. Quoting `$107,412.83` as support implies a precision the
method does not have, and it is also what made this service inconsistent: one
new candle moved the number and the report read as though the level had moved.
A band with a touch count and a strength score survives the next candle, which
is what "consistent" means here. Pivot-derived S1/S2/R1/R2 are no longer mixed
into the level list for the same reason — they are recomputed from the last
bar every time and drift daily. The classic pivot is still reported on its own.

Nothing is invented. When a timeframe has too little history it is dropped and
named in `coverage`, and when no timeframe survives the function returns `None`
so the caller reports a gap. A level produced by a formula applied to no data
reads exactly like a real level once it reaches the UI or an LLM prompt, which
is the failure this module exists to avoid.
"""

import asyncio
import logging
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from services.cache import market_cache
from services.okx_market import fetch_candles, fetch_ticker_24h

logger = logging.getLogger(__name__)

# Candles pulled per timeframe. 4h is the primary read; 1h is the fallback for
# pairs listed too recently to have 4h history.
CANDLE_LIMIT = 100
# Below this many candles the indicators are not meaningful, so no analysis is
# produced at all.
MIN_CANDLES = 20
# 4h is preferred only when it carries at least this much history.
MIN_PRIMARY_CANDLES = 50

# Two years of weekly bars. The cap is the point: see the module docstring.
WEEKLY_LOOKBACK = 104
# OKX serves at most 300 rows in one page, which is 50 days of 4h bars and ten
# months of daily ones. The two-year picture comes from the weekly series, so
# paging further back for dailies would buy resolution nobody reads at the cost
# of six more requests per symbol.
OKX_PAGE = 300


class Timeframe(NamedTuple):
    """One horizon of the same chart, and how to fetch it."""

    label: str  # what the payload and the UI call it
    interval: str  # what the upstream calls it
    limit: int  # bars requested
    horizon: str  # short | medium | long
    range_: Optional[str] = None  # Yahoo's period parameter, equities only


# 4h ≈ 50 days, 1d ≈ 10 months, 1w = 2 years.
CRYPTO_TIMEFRAMES: Tuple[Timeframe, ...] = (
    Timeframe("4h", "4h", OKX_PAGE, "short"),
    Timeframe("1d", "1d", OKX_PAGE, "medium"),
    Timeframe("1w", "1w", WEEKLY_LOOKBACK, "long"),
)

# Yahoo publishes no 4h bar, so the short horizon for an equity is hourly. It is
# labelled "1h" rather than dressed up as something it is not. Intraday history
# is capped at 730 days upstream; 3mo is what the short read needs.
STOCK_TIMEFRAMES: Tuple[Timeframe, ...] = (
    Timeframe("1h", "1h", 0, "short", range_="3mo"),
    Timeframe("1d", "1d", 0, "medium", range_="2y"),
    Timeframe("1w", "1wk", 0, "long", range_="2y"),
)

# The horizon whose indicators fill the flat, backward-compatible fields
# (`rsi_value`, `atr`, `trend`). Daily is the standard chart read; the other two
# are one key away in `timeframes`.
PRIMARY_HORIZON = "medium"

# How long a computed analysis is served before it is recomputed. Consistency is
# the reason as much as cost: two panels rendering the same asset seconds apart
# must not disagree because a candle closed between them.
CACHE_TTL_CRYPTO = 180
CACHE_TTL_STOCK = 600

SECONDS_PER_DAY = 86_400


# ═══════════════════════════════════════════════════════════════════════════════
# INDICATORS
# ═══════════════════════════════════════════════════════════════════════════════


def calculate_atr(candles: List[Dict[str, Any]], period: int = 14) -> Optional[float]:
    """
    Average True Range — the volatility input for target ranges and zone width.

    Returns None when there are not enough candles to compute one; callers must
    treat that as "no volatility estimate", not as zero volatility.
    """
    if len(candles) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return sum(true_ranges) / len(true_ranges) if true_ranges else None

    # Wilder's smoothing.
    atr = sum(true_ranges[:period]) / period
    for i in range(period, len(true_ranges)):
        atr = (atr * (period - 1) + true_ranges[i]) / period

    return atr


def calculate_pivot_points(high: float, low: float, close: float) -> Dict[str, float]:
    """Classic floor-trader pivots for the period given."""
    pivot = (high + low + close) / 3

    s1 = (2 * pivot) - high
    s2 = pivot - (high - low)
    s3 = low - 2 * (high - pivot)

    r1 = (2 * pivot) - low
    r2 = pivot + (high - low)
    r3 = high + 2 * (pivot - low)

    return {"pivot": pivot, "s1": s1, "s2": s2, "s3": s3, "r1": r1, "r2": r2, "r3": r3}


def rsi_series(closes: Sequence[float], period: int = 14) -> List[Optional[float]]:
    """
    RSI at every close, aligned to `closes`, with None where it is undefined.

    The series exists so divergence can be measured at the same bars the swing
    detector found. `calculate_rsi` is the last element of this.
    """
    out: List[Optional[float]] = [None] * len(closes)
    if len(closes) < period + 1:
        return out

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [c if c > 0 else 0.0 for c in changes]
    losses = [-c if c < 0 else 0.0 for c in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def value(gain: float, loss: float) -> float:
        if loss == 0:
            return 100.0
        rs = gain / loss
        return round(100 - (100 / (1 + rs)), 2)

    out[period] = value(avg_gain, avg_loss)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i + 1] = value(avg_gain, avg_loss)

    return out


def calculate_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """
    Relative Strength Index at the last close.

    Returns None below `period + 1` closes. A "neutral 50" would be a reading
    the market never produced.
    """
    if len(closes) < period + 1:
        return None
    return rsi_series(closes, period)[-1]


def get_rsi_signal(rsi: Optional[float]) -> Optional[str]:
    """Interpret RSI value as a signal, or None when there is no RSI."""
    if rsi is None:
        return None
    if rsi >= 70:
        return "Overbought"
    elif rsi <= 30:
        return "Oversold"
    elif rsi >= 60:
        return "Bullish Momentum"
    elif rsi <= 40:
        return "Bearish Momentum"
    else:
        return "Neutral"


def calculate_trend(
    closes: List[float], short_period: int = 10, long_period: int = 30
) -> Optional[str]:
    """Trend from an EMA crossover, or None below `long_period` closes."""
    if len(closes) < long_period:
        return None

    short_ema = _ema(closes, short_period)
    long_ema = _ema(closes, long_period)

    if short_ema > long_ema * 1.01:
        return "bullish"
    elif short_ema < long_ema * 0.99:
        return "bearish"
    else:
        return "neutral"


def _ema(data: Sequence[float], period: int) -> float:
    multiplier = 2 / (period + 1)
    ema_val = sum(data[:period]) / period
    for price in data[period:]:
        ema_val = (price - ema_val) * multiplier + ema_val
    return ema_val


def _sma(closes: Sequence[float], period: int) -> Optional[float]:
    """Simple moving average, or None when the series is shorter than the window."""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def format_price(price: float) -> str:
    """Format price with appropriate precision."""
    if price >= 10000:
        return f"${price:,.0f}"
    elif price >= 1000:
        return f"${price:,.2f}"
    elif price >= 1:
        return f"${price:.4f}"
    elif price >= 0.01:
        return f"${price:.5f}"
    else:
        return f"${price:.8f}"


# ═══════════════════════════════════════════════════════════════════════════════
# SWINGS AND ZONES
# ═══════════════════════════════════════════════════════════════════════════════


class Swing(NamedTuple):
    """A bar price reversed at."""

    index: int
    price: float
    volume: float
    time: int
    kind: str  # "high" | "low"


def _swing_span(length: int) -> int:
    """
    Bars either side that must be lower (higher) for a bar to count as a swing.

    Scaled to the series so a 104-bar weekly chart is not held to the same
    strictness as a 300-bar 4h one, where a 2-bar fractal fires on noise.
    """
    return 2 if length < 120 else 3


def _swing_points(candles: List[Dict[str, Any]], span: Optional[int] = None) -> List[Swing]:
    """
    Fractal swing highs and lows.

    Strict on the left and permissive on the right, which is the standard
    convention and also means a flat top registers once, at its first bar,
    instead of once per bar of the plateau.
    """
    span = span or _swing_span(len(candles))
    if len(candles) < span * 2 + 1:
        return []

    swings: List[Swing] = []
    for i in range(span, len(candles) - span):
        bar = candles[i]
        left = candles[i - span : i]
        right = candles[i + 1 : i + span + 1]

        if bar["high"] > max(c["high"] for c in left) and bar["high"] >= max(
            c["high"] for c in right
        ):
            swings.append(
                Swing(i, bar["high"], bar.get("volume") or 0.0, bar.get("time") or 0, "high")
            )
        if bar["low"] < min(c["low"] for c in left) and bar["low"] <= min(c["low"] for c in right):
            swings.append(
                Swing(i, bar["low"], bar.get("volume") or 0.0, bar.get("time") or 0, "low")
            )

    return swings


def _zone_tolerance(current_price: float, atr: Optional[float]) -> float:
    """
    How far apart two reversals can be and still describe the same level.

    ATR-relative rather than a fixed percentage: half an average bar's range is
    what "the same area of the chart" means on a chart that moves that much. The
    percentage floor and ceiling only stop the band collapsing to nothing in a
    dead market or swallowing the whole chart after a volatility spike.
    """
    floor = current_price * 0.004
    ceiling = current_price * 0.03
    if atr is None or atr <= 0:
        return floor
    return max(floor, min(atr * 0.6, ceiling))


def _cluster_swings(swings: Sequence[Swing], tolerance: float) -> List[List[Swing]]:
    """
    Group reversals that happened at the same price into bands.

    Single pass over price-sorted swings, with a width cap so a chain of
    near-misses cannot grow into a band that covers everything and therefore
    says nothing.
    """
    clusters: List[List[Swing]] = []
    for swing in sorted(swings, key=lambda s: s.price):
        if clusters:
            current = clusters[-1]
            within_gap = swing.price - current[-1].price <= tolerance
            within_width = swing.price - current[0].price <= tolerance * 2
            if within_gap and within_width:
                current.append(swing)
                continue
        clusters.append([swing])
    return clusters


def _zone_strength(cluster: Sequence[Swing], series_length: int, mean_volume: float) -> int:
    """
    A 0-100 score for how much attention a band has earned.

    Four inputs, each capped so no single one can carry a zone on its own:
    how often price reversed there (40), how recently (25), how much volume
    traded into those reversals (20), and whether the band has acted as both
    support and resistance (15) — a flipped level is the one traders watch.
    """
    touches = min(len(cluster), 4) / 4 * 40

    newest = max(s.index for s in cluster)
    recency = (1 - (series_length - 1 - newest) / max(series_length - 1, 1)) * 25

    volumes = [s.volume for s in cluster if s.volume]
    volume_score = 0.0
    if volumes and mean_volume > 0:
        volume_score = min(sum(volumes) / len(volumes) / mean_volume, 2.0) / 2 * 20

    kinds = {s.kind for s in cluster}
    flip = 15 if len(kinds) > 1 else 0

    return int(round(touches + recency + volume_score + flip))


def build_zones(
    candles: List[Dict[str, Any]],
    current_price: float,
    *,
    timeframe: str,
    horizon: str,
    atr: Optional[float] = None,
    per_side: int = 3,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Support and resistance bands for one series, strongest first.

    A band is kept on the side of spot its price sits on. Bands straddling spot
    are dropped rather than reported as both: price inside a level is a fact
    about the level, not two levels.
    """
    if len(candles) < MIN_CANDLES or current_price <= 0:
        return {"support": [], "resistance": []}

    swings = _swing_points(candles)
    if not swings:
        return {"support": [], "resistance": []}

    tolerance = _zone_tolerance(current_price, atr)
    volumes = [c.get("volume") or 0.0 for c in candles]
    mean_volume = sum(volumes) / len(volumes) if volumes else 0.0

    supports: List[Dict[str, Any]] = []
    resistances: List[Dict[str, Any]] = []

    for cluster in _cluster_swings(swings, tolerance):
        low = min(s.price for s in cluster)
        high = max(s.price for s in cluster)
        if low <= current_price <= high:
            continue

        newest = max(cluster, key=lambda s: s.index)
        zone = {
            "low": low,
            "high": high,
            "mid": round((low + high) / 2, 8),
            "touches": len(cluster),
            "flip": len({s.kind for s in cluster}) > 1,
            "strength": _zone_strength(cluster, len(candles), mean_volume),
            "age_bars": len(candles) - 1 - newest.index,
            "last_touch_at": newest.time,
            "timeframe": timeframe,
            "horizon": horizon,
            "distance_percent": round(((low + high) / 2 - current_price) / current_price * 100, 2),
            "confluence": [],
        }
        (supports if high < current_price else resistances).append(zone)

    def rank(zones: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Strength first, then proximity — and the price itself last, so two
        # equal zones always come back in the same order.
        zones.sort(key=lambda z: (-z["strength"], abs(z["distance_percent"]), z["mid"]))
        return zones[:per_side]

    return {"support": rank(supports), "resistance": rank(resistances)}


def _mark_confluence(zones: Sequence[Dict[str, Any]]) -> None:
    """
    Note, on each zone, which other timeframes agree with it.

    A 4h band that lands on top of a weekly one is a different proposition from
    one that does not, and it is the single most useful thing the multi-timeframe
    read produces. Recorded rather than folded into the score so a reader can see
    why a zone matters.
    """
    for zone in zones:
        agreeing = set()
        for other in zones:
            if other is zone or other["timeframe"] == zone["timeframe"]:
                continue
            if zone["low"] <= other["high"] and other["low"] <= zone["high"]:
                agreeing.add(other["timeframe"])
        zone["confluence"] = sorted(agreeing)


# Longest wins when merged bands disagree about which horizon they belong to: a
# level the weekly chart also respects is a long-term level, whatever else found it.
_HORIZON_ORDER = {"single": 0, "short": 1, "medium": 2, "long": 3}


def _absorb(target: Dict[str, Any], other: Dict[str, Any]) -> None:
    """Fold `other` into `target` in place. Both describe one band."""
    target["low"] = min(target["low"], other["low"])
    target["high"] = max(target["high"], other["high"])
    target["touches"] += other["touches"]
    target["flip"] = target["flip"] or other["flip"]
    target["timeframes"] = sorted(set(target["timeframes"]) | {other["timeframe"]})

    if other.get("last_touch_at", 0) > target.get("last_touch_at", 0):
        target["last_touch_at"] = other["last_touch_at"]
        target["age_bars"] = other["age_bars"]
        target["age_timeframe"] = other["timeframe"]

    if _HORIZON_ORDER.get(other["horizon"], 0) > _HORIZON_ORDER.get(target["horizon"], 0):
        target["horizon"] = other["horizon"]
        target["timeframe"] = other["timeframe"]

    # The confluence bonus is the whole reason to merge: three timeframes
    # reversing in one band is a stronger claim than the best of them alone.
    target["strength"] = min(
        100, max(target["strength"], other["strength"]) + 5 * (len(target["timeframes"]) - 1)
    )


def _merge_zones(zones: Sequence[Dict[str, Any]], current_price: float) -> List[Dict[str, Any]]:
    """
    Fold overlapping bands from different timeframes into one band each.

    Without this, one level arrives three times — once per timeframe, each a few
    dollars wide of the others — and a reader has no way to tell that it is one
    level rather than three. Merging is capped at 1.5x the widest contributing
    band so a chain of overlaps cannot grow into a band that covers everything
    and therefore says nothing.
    """
    merged: List[Dict[str, Any]] = []
    for zone in sorted(zones, key=lambda z: (z["low"], z["high"])):
        candidate = dict(zone, timeframes=[zone["timeframe"]], age_timeframe=zone["timeframe"])
        if merged:
            last = merged[-1]
            widest = max(last["high"] - last["low"], zone["high"] - zone["low"])
            overlaps = zone["low"] <= last["high"]
            within_width = max(last["high"], zone["high"]) - last["low"] <= widest * 1.5
            if overlaps and within_width:
                _absorb(last, candidate)
                continue
        merged.append(candidate)

    for zone in merged:
        zone["mid"] = round((zone["low"] + zone["high"]) / 2, 8)
        zone["distance_percent"] = round((zone["mid"] - current_price) / current_price * 100, 2)
        zone["confluence"] = [tf for tf in zone["timeframes"] if tf != zone["timeframe"]]
    return merged


# ═══════════════════════════════════════════════════════════════════════════════
# THE VIEW FROM A DISTANCE
# ═══════════════════════════════════════════════════════════════════════════════


def _swing_structure(candles: List[Dict[str, Any]]) -> Optional[str]:
    """
    Whether the last two swing highs and lows are stepping up or down.

    The plainest statement of trend structure there is, and one an indicator
    crossover cannot make: EMAs say where price has been, this says whether the
    market is still willing to pay more than it did last time.
    """
    swings = _swing_points(candles)
    highs = [s.price for s in swings if s.kind == "high"][-2:]
    lows = [s.price for s in swings if s.kind == "low"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return None

    rising_highs, rising_lows = highs[1] > highs[0], lows[1] > lows[0]
    if rising_highs and rising_lows:
        return "higher highs & higher lows"
    if not rising_highs and not rising_lows:
        return "lower highs & lower lows"
    return "mixed — no clean swing structure"


def _alignment(trends: Dict[str, Optional[str]]) -> Optional[str]:
    """
    One sentence on whether the three timeframes tell the same story.

    Computed rather than left to the model, because "the timeframes disagree" is
    exactly the kind of claim that gets asserted without checking.
    """
    named = {tf: t for tf, t in trends.items() if t}
    if not named:
        return None

    distinct = set(named.values())
    if len(distinct) == 1:
        return f"aligned {distinct.pop()} across {', '.join(named)}"
    return "conflicting: " + ", ".join(f"{tf} {trend}" for tf, trend in named.items())


def _rsi_divergence(
    candles: List[Dict[str, Any]], rsis: Sequence[Optional[float]]
) -> Optional[str]:
    """
    Regular divergence between the last two swings and RSI at those same bars.

    Only the last two swings of one kind are compared, and only when both carry
    an RSI reading. Anything looser finds a divergence on every chart.
    """
    swings = _swing_points(candles)

    def readings(kind: str) -> List[Tuple[float, float]]:
        out = []
        for swing in swings:
            if swing.kind != kind:
                continue
            rsi = rsis[swing.index] if swing.index < len(rsis) else None
            if rsi is not None:
                out.append((swing.price, rsi))
        return out[-2:]

    highs = readings("high")
    if len(highs) == 2 and highs[1][0] > highs[0][0] and highs[1][1] < highs[0][1]:
        return "bearish — price made a higher high, RSI did not"

    lows = readings("low")
    if len(lows) == 2 and lows[1][0] < lows[0][0] and lows[1][1] > lows[0][1]:
        return "bullish — price made a lower low, RSI did not"

    return None


def _covered_days(candles: List[Dict[str, Any]]) -> Optional[int]:
    """Calendar days the series spans, from its own timestamps."""
    if len(candles) < 2:
        return None
    span = (candles[-1].get("time") or 0) - (candles[0].get("time") or 0)
    return round(span / SECONDS_PER_DAY) if span > 0 else None


def _timeframe_read(candles: List[Dict[str, Any]], timeframe: str, horizon: str) -> Dict[str, Any]:
    """Indicators, RSI detail and coverage for one series."""
    closes = [c["close"] for c in candles]
    rsis = rsi_series(closes, 14)
    rsi = rsis[-1]
    atr = calculate_atr(candles, 14)

    # RSI five bars ago, so "rising" means over the last stretch rather than
    # since the previous bar, which flips on noise.
    previous = rsis[-6] if len(rsis) >= 6 else None
    change = round(rsi - previous, 2) if rsi is not None and previous is not None else None

    return {
        "timeframe": timeframe,
        "horizon": horizon,
        "bars": len(candles),
        "covers_days": _covered_days(candles),
        "trend": calculate_trend(closes, 10, 30),
        "atr": atr,
        "atr_percent": (round(atr / closes[-1] * 100, 2) if atr and closes[-1] else None),
        "rsi": {
            "value": rsi,
            "signal": get_rsi_signal(rsi),
            "period": 14,
            "change_5_bars": change,
            "slope": (
                None
                if change is None
                else "rising"
                if change > 1
                else "falling"
                if change < -1
                else "flat"
            ),
            "divergence": _rsi_divergence(candles, rsis),
        },
    }


def _structure(
    series: Dict[str, List[Dict[str, Any]]], current_price: float, trends: Dict[str, Optional[str]]
) -> Dict[str, Any]:
    """
    Where this price sits in its own two-year history.

    The zoomed-out read: the long-horizon range and where in it price is
    trading, the daily moving averages, and whether the swing structure agrees
    with the moving averages. Every field is None when the history behind it is
    missing — a 30%-of-range reading computed from six weeks of candles would be
    a statement about nothing.
    """
    long_series = series.get("1w") or series.get("1d") or []
    daily = series.get("1d") or []

    structure: Dict[str, Any] = {
        "range_high": None,
        "range_low": None,
        "range_bars": len(long_series) or None,
        "range_timeframe": "1w" if series.get("1w") else ("1d" if daily else None),
        "position_percent": None,
        "distance_to_high_percent": None,
        "distance_to_low_percent": None,
        "sma50": None,
        "sma200": None,
        "price_vs_sma200_percent": None,
        "swing_structure": _swing_structure(daily) if daily else None,
        "timeframe_alignment": _alignment(trends),
    }

    if long_series:
        high = max(c["high"] for c in long_series)
        low = min(c["low"] for c in long_series)
        span = high - low
        structure["range_high"] = high
        structure["range_low"] = low
        if span > 0:
            structure["position_percent"] = round((current_price - low) / span * 100, 1)
        if high > 0:
            structure["distance_to_high_percent"] = round((current_price - high) / high * 100, 2)
        if low > 0:
            structure["distance_to_low_percent"] = round((current_price - low) / low * 100, 2)

    if daily:
        closes = [c["close"] for c in daily]
        structure["sma50"] = _sma(closes, 50)
        structure["sma200"] = _sma(closes, 200)
        if structure["sma200"]:
            structure["price_vs_sma200_percent"] = round(
                (current_price - structure["sma200"]) / structure["sma200"] * 100, 2
            )

    return structure


# ═══════════════════════════════════════════════════════════════════════════════
# ASSEMBLY
# ═══════════════════════════════════════════════════════════════════════════════


def analyse_candles(
    candles: List[Dict[str, Any]], current_price: float, timeframe: str
) -> Optional[Dict[str, Any]]:
    """
    Compute every level from one OHLCV series. Asset-class agnostic.

    The single-timeframe entry point, kept for callers that have their own
    series — the chart tool reads whatever interval the question asked about.
    `analyse_timeframes` is what the multi-timeframe path uses.
    """
    if len(candles) < MIN_CANDLES:
        return None

    atr = calculate_atr(candles, 14)
    zones = build_zones(
        candles, current_price, timeframe=timeframe, horizon="single", atr=atr, per_side=3
    )

    recent = candles[-min(24, len(candles)) :]
    pivots = calculate_pivot_points(
        max(c["high"] for c in recent), min(c["low"] for c in recent), candles[-1]["close"]
    )

    read = _timeframe_read(candles, timeframe, "single")
    supports = [z["mid"] for z in _by_distance(zones["support"])]
    resistances = [z["mid"] for z in _by_distance(zones["resistance"])]

    return {
        "current_price": current_price,
        "support_levels": [format_zone(z) for z in _by_distance(zones["support"])[:2]],
        "resistance_levels": [format_zone(z) for z in _by_distance(zones["resistance"])[:2]],
        "support_zones": zones["support"],
        "resistance_zones": zones["resistance"],
        "rsi_signal": read["rsi"]["signal"],
        "rsi_value": read["rsi"]["value"],
        "rsi": read["rsi"],
        "pivot_point": format_price(pivots["pivot"]),
        "target_price": calculate_target_price(
            current_price, atr, read["trend"], read["rsi"]["value"], supports, resistances
        ),
        "atr": atr,
        "trend": read["trend"],
        "timeframe": timeframe,
        "bars": len(candles),
        "covers_days": _covered_days(candles),
    }


def format_zone(zone: Dict[str, Any]) -> str:
    """
    A band as one display string, both bounds.

    The flat `support_levels` / `resistance_levels` lists are what the news panel
    and the older prompts read, and they used to carry a single price each. They
    carry the band now: the same list, the same strings, but no longer implying
    that support is one decimal. A zero-width band (one reversal, one price)
    prints as that price rather than as "$100 – $100".
    """
    low, high = zone["low"], zone["high"]
    return format_price(low) if low == high else f"{format_price(low)} – {format_price(high)}"


def _by_distance(zones: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Zones ordered by how close they are to spot, nearest first."""
    return sorted(zones, key=lambda z: (abs(z["distance_percent"]), z["mid"]))


# How many bands per side survive into the payload.
ZONES_PER_SIDE = 5


def _rank(zones: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Strength first, then proximity, then price — the same order every time."""
    return sorted(zones, key=lambda z: (-z["strength"], abs(z["distance_percent"]), z["mid"]))


def _strongest(zones: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    The bands worth reporting on one side of spot.

    Strength alone would answer a question nobody asked. The strongest bands
    cluster around spot — that is where the recent bars are — so a plain top-five
    hands back five versions of "just above here" and nothing about the level
    that stopped the last rally. Each horizon therefore gets its best band first,
    and only then is the rest of the list filled by strength. A reader asking for
    short-, medium- and long-term levels gets one of each where one exists.
    """
    picked: List[Dict[str, Any]] = []
    for horizon in ("short", "medium", "long", "single"):
        best = _rank([z for z in zones if z["horizon"] == horizon])
        if best:
            picked.append(best[0])

    for zone in _rank(zones):
        if len(picked) >= ZONES_PER_SIDE:
            break
        if zone not in picked:
            picked.append(zone)

    return picked[:ZONES_PER_SIDE]


def analyse_timeframes(
    series: Dict[str, List[Dict[str, Any]]],
    current_price: float,
    timeframes: Sequence[Timeframe],
) -> Optional[Dict[str, Any]]:
    """
    The full multi-timeframe read, or None when no timeframe had enough history.

    Every timeframe that arrived is analysed on its own terms and then the zones
    are pooled so confluence can be marked across them. The flat fields at the
    top of the payload are the primary horizon's, unchanged in shape from when
    this service read one timeframe, so existing callers keep working.
    """
    reads: Dict[str, Dict[str, Any]] = {}
    all_zones: List[Dict[str, Any]] = []
    coverage: Dict[str, Any] = {}

    for spec in timeframes:
        candles = series.get(spec.label) or []
        if len(candles) < MIN_CANDLES:
            coverage[spec.label] = {
                "bars": len(candles),
                "available": False,
                "reason": "not enough history",
            }
            continue

        read = _timeframe_read(candles, spec.label, spec.horizon)
        atr = read["atr"]
        zones = build_zones(
            candles,
            current_price,
            timeframe=spec.label,
            horizon=spec.horizon,
            atr=atr,
            per_side=3,
        )
        read["support_zones"] = zones["support"]
        read["resistance_zones"] = zones["resistance"]
        reads[spec.label] = read
        all_zones += zones["support"] + zones["resistance"]
        coverage[spec.label] = {
            "bars": read["bars"],
            "covers_days": read["covers_days"],
            "available": True,
        }

    if not reads:
        return None

    _mark_confluence(all_zones)

    primary = next(
        (
            reads[spec.label]
            for spec in timeframes
            if spec.horizon == PRIMARY_HORIZON and spec.label in reads
        ),
        None,
    ) or next(iter(reads.values()))

    merged = _merge_zones(all_zones, current_price)
    # Strongest few per side, then ordered by proximity — a reader wants the
    # levels that matter, in the order price would reach them.
    supports = _by_distance(_strongest([z for z in merged if z["high"] < current_price]))
    resistances = _by_distance(_strongest([z for z in merged if z["low"] > current_price]))
    # A band price is trading inside is neither support nor resistance yet, and
    # dropping it silently would hide the most immediate fact on the chart.
    inside = [z for z in merged if z["low"] <= current_price <= z["high"]]

    trends = {label: read["trend"] for label, read in reads.items()}
    structure = _structure(
        {label: series.get(label) or [] for label in reads}, current_price, trends
    )

    recent = (series.get(primary["timeframe"]) or [])[-24:]
    pivots = (
        calculate_pivot_points(
            max(c["high"] for c in recent), min(c["low"] for c in recent), recent[-1]["close"]
        )
        if recent
        else None
    )

    return {
        # ── The shape this service has always returned ──────────────────────
        "current_price": current_price,
        "support_levels": [format_zone(z) for z in supports[:3]],
        "resistance_levels": [format_zone(z) for z in resistances[:3]],
        "rsi_signal": primary["rsi"]["signal"],
        "rsi_value": primary["rsi"]["value"],
        "pivot_point": format_price(pivots["pivot"]) if pivots else None,
        "target_price": calculate_target_price(
            current_price,
            primary["atr"],
            primary["trend"],
            primary["rsi"]["value"],
            [z["mid"] for z in supports],
            [z["mid"] for z in resistances],
        ),
        "atr": primary["atr"],
        "trend": primary["trend"],
        "timeframe": primary["timeframe"],
        # ── The multi-timeframe read ────────────────────────────────────────
        "primary_timeframe": primary["timeframe"],
        "timeframes": reads,
        "zones": {"support": supports, "resistance": resistances, "inside": inside},
        "structure": structure,
        "coverage": coverage,
    }


def calculate_target_price(
    current_price: float,
    atr: Optional[float],
    trend: Optional[str],
    rsi: Optional[float],
    supports: List[float],
    resistances: List[float],
) -> Optional[str]:
    """
    Project a target range from ATR, trend and the nearest key level.

    Returns None unless all three inputs exist. The previous version substituted
    2% of spot for a missing ATR, which turned "we could not measure volatility"
    into a concrete-looking price range.
    """
    if atr is None or atr <= 0 or trend is None or rsi is None:
        return None

    if trend == "bullish":
        multiplier = 1.5 if rsi < 60 else 1.0  # Less upside if already overbought
    elif trend == "bearish":
        multiplier = -1.5 if rsi > 40 else -1.0  # Less downside if already oversold
    else:
        multiplier = 0.5 if rsi > 50 else -0.5

    if multiplier > 0:
        base_target = current_price + (atr * multiplier)
        if resistances:
            nearest_resistance = resistances[0]
            if nearest_resistance < base_target * 1.5:
                target_low = current_price + (atr * 0.5)
                target_high = nearest_resistance
            else:
                target_low = current_price + (atr * 0.5)
                target_high = base_target
        else:
            target_low = current_price + (atr * 0.5)
            target_high = base_target
    else:
        base_target = current_price + (atr * multiplier)
        if supports:
            nearest_support = supports[0]
            if nearest_support > base_target * 0.5:
                target_low = nearest_support
                target_high = current_price - (atr * 0.5)
            else:
                target_low = base_target
                target_high = current_price - (atr * 0.5)
        else:
            target_low = base_target
            target_high = current_price - (atr * 0.5)

    if target_low > target_high:
        target_low, target_high = target_high, target_low

    return f"{format_price(target_low)} - {format_price(target_high)}"


def find_significant_levels(
    candles: List[Dict[str, Any]], current_price: float, num_levels: int = 3
) -> Tuple[List[float], List[float]]:
    """
    Swing supports and resistances as plain prices, nearest first.

    Superseded by `build_zones` for anything user-facing — a band with a touch
    count says more than a decimal — but kept because it is the cheapest way to
    ask "where did price turn" and callers outside this module use it.
    """
    if len(candles) < MIN_CANDLES:
        return [], []

    atr = calculate_atr(candles, 14)
    zones = build_zones(
        candles,
        current_price,
        timeframe="single",
        horizon="single",
        atr=atr,
        per_side=num_levels,
    )
    supports = [z["mid"] for z in _by_distance(zones["support"])]
    resistances = [z["mid"] for z in _by_distance(zones["resistance"])]
    return supports[:num_levels], resistances[:num_levels]


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINTS
# ═══════════════════════════════════════════════════════════════════════════════


async def get_technical_analysis(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Complete technical analysis for a symbol, or None when it cannot be computed.

    Args:
        symbol: TradingView format symbol (e.g., BINANCE:BTCUSDT, NASDAQ:AAPL).
            The exchange prefix is only a hint about asset class — crypto data
            comes from OKX, equity data from Yahoo.

    Returns:
        The multi-timeframe read, or None when no timeframe had enough history.
        Callers must treat None as "no levels exist for this asset" and never
        substitute their own.
    """
    parts = symbol.split(":")
    exchange = parts[0] if len(parts) > 1 else ""
    clean_symbol = parts[-1]

    is_crypto = exchange.upper() in ("BINANCE", "OKX") or clean_symbol.endswith("USDT")
    cache_key = f"ta_{'crypto' if is_crypto else 'stock'}_{clean_symbol.upper()}"

    cached = market_cache.get(cache_key)
    if cached is not None:
        return cached

    result = (
        await get_crypto_analysis(clean_symbol)
        if is_crypto
        else await get_stock_analysis(clean_symbol)
    )
    if result:
        market_cache.set(cache_key, result, CACHE_TTL_CRYPTO if is_crypto else CACHE_TTL_STOCK)
    return result


async def _gather_series(
    fetchers: Sequence[Tuple[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Await one candle fetch per timeframe, dropping the ones that failed.

    A timeframe that could not be fetched is absent from the result, which is
    the same thing as a timeframe with no history: named in `coverage`, never
    filled in from a neighbouring interval.
    """
    results = await asyncio.gather(*(coro for _, coro in fetchers), return_exceptions=True)

    series: Dict[str, List[Dict[str, Any]]] = {}
    for (label, _), result in zip(fetchers, results):
        if isinstance(result, BaseException):
            logger.warning("Candle fetch failed for the %s series: %s", label, result)
            continue
        series[label] = result or []
    return series


async def get_crypto_analysis(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Multi-timeframe technical analysis for a crypto pair from OKX candles.

    4h, 1d and 1w are fetched together. A pair listed too recently to have 4h
    history falls back to 1h for the short horizon, as it always did; the other
    two horizons are simply reported as unavailable when they are.
    """
    try:
        series = await _gather_series(
            [
                (spec.label, fetch_candles(symbol, spec.interval, spec.limit, spot=True))
                for spec in CRYPTO_TIMEFRAMES
            ]
        )

        specs = list(CRYPTO_TIMEFRAMES)
        if len(series.get("4h") or []) < MIN_PRIMARY_CANDLES:
            hourly = await fetch_candles(symbol, "1h", OKX_PAGE, spot=True)
            if len(hourly) > len(series.get("4h") or []):
                series["1h"] = hourly
                series.pop("4h", None)
                specs[0] = Timeframe("1h", "1h", OKX_PAGE, "short")

        if all(len(series.get(spec.label) or []) < MIN_CANDLES for spec in specs):
            logger.info("Not enough OKX candles for %s — no analysis produced.", symbol)
            return None

        # Prefer the live ticker; the last close comes from the same series and
        # is a real observation too, so it is a legitimate stand-in.
        ticker = await fetch_ticker_24h(symbol)
        current_price = ticker["price"] if ticker else _last_close(series, specs)
        if not current_price:
            return None

        return analyse_timeframes(series, current_price, specs)

    except Exception as e:
        logger.error("Crypto analysis error for %s: %s", symbol, e)
        return None


def _last_close(
    series: Dict[str, List[Dict[str, Any]]], specs: Sequence[Timeframe]
) -> Optional[float]:
    """The most recent close available, preferring the shortest timeframe."""
    for spec in specs:
        candles = series.get(spec.label) or []
        if candles:
            return candles[-1]["close"]
    return None


async def get_stock_analysis(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Multi-timeframe technical analysis for an equity or index from Yahoo bars.

    Yahoo publishes no 4h bar, so the short horizon is hourly and is labelled as
    such. Daily and weekly both request two years, which is the window this
    service reads — long enough to place a price in its own history, short
    enough that the levels describe the market that exists now.
    """
    try:
        from services.stock_market_service import fetch_stock_candles

        series = await _gather_series(
            [
                (
                    spec.label,
                    fetch_stock_candles(symbol, interval=spec.interval, range_=spec.range_),
                )
                for spec in STOCK_TIMEFRAMES
            ]
        )

        if all(len(series.get(spec.label) or []) < MIN_CANDLES for spec in STOCK_TIMEFRAMES):
            logger.info("Not enough Yahoo bars for %s — no analysis produced.", symbol)
            return None

        current_price = _last_close(series, STOCK_TIMEFRAMES)
        if not current_price:
            return None

        return analyse_timeframes(series, current_price, STOCK_TIMEFRAMES)

    except Exception as e:
        logger.error("Stock analysis error for %s: %s", symbol, e)
        return None
