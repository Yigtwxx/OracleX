"""
What a past event actually did to the price, measured over several horizons.

The store used to record one number per event: the change across a fixed ±7-day
window. That number answers the wrong question. Two worked examples, both of
which a seven-day — or even a ninety-day — window labels backwards:

The SEC sued Ripple on 2020-12-22. XRP fell from $0.75 to $0.17 within weeks and
US exchanges delisted it, then traded up to $1.96 by April 2021 while the case
was still live. The peak came roughly 113 days after the event.

DeepSeek's model release knocked 17% off NVDA on 2025-01-27 — the largest
single-day market-cap loss in US history — which it recovered 8.9% of the next
session. It then made a ten-month low in April before recovering over $1T;
buying on the crash date was up 58% a year later. Down at one day, up at two,
down again at ninety, strongly up at three hundred and sixty-five.

So an outcome here is a set of endpoints plus the path between them. The
endpoints say where it settled; `max_drawdown_pct` and `max_runup_pct` say how
far it travelled, which is the part a single endpoint hides. Nothing is
extrapolated: a horizon the data does not reach stays `None` rather than
borrowing the nearest value it can find.

One asymmetry worth knowing about. A horizon is the last session at or before
`event date + N days`, and the two venues stamp their sessions differently: OKX
dates a daily bar at midnight UTC, Yahoo at the opening bell. So for an equity
the one-day horizon lands on the event's own session (NVDA's DeepSeek day reads
-17.0%, the figure the coverage quoted), while for crypto it lands on the
following close. Both are within a day of the event, and the event session's own
extreme is captured by the drawdown either way, so this is left as it is rather
than papered over with a venue-specific offset.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Optional, Sequence

from config import settings
from services.rag_scoring import direction_from_pct

logger = logging.getLogger(__name__)

# A horizon is measured from the last close at or before its target date. Markets
# shut for weekends and holidays, so the target rarely lands on a session; this
# is how far back the search may reach before it gives up and reports nothing.
# Five days covers a long weekend either side of a US market holiday.
TOLERANCE_DAYS = 5

# Slack before the event, so the pre-event baseline close can be found even when
# the event falls after a holiday weekend.
BASELINE_LOOKBACK_DAYS = 10

# Which horizons speak for the first reaction and which for the settled verdict.
# Everything between the two is transition and is reported without being voted on.
IMMEDIATE_MAX_DAYS = 7
DURABLE_MIN_DAYS = 90

_SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class EventOutcome:
    """One event's measured aftermath."""

    baseline: float
    horizons: Dict[int, float]
    max_drawdown_pct: Optional[float] = None
    max_runup_pct: Optional[float] = None
    immediate_direction: Optional[str] = None
    durable_direction: Optional[str] = None
    inverted: bool = False

    @property
    def abs_impact(self) -> Optional[float]:
        """The largest absolute move the event produced, over any horizon or the path."""
        candidates = [abs(v) for v in self.horizons.values()]
        for value in (self.max_drawdown_pct, self.max_runup_pct):
            if value is not None:
                candidates.append(abs(value))
        return max(candidates) if candidates else None

    def as_metadata(self) -> Dict[str, Any]:
        """
        Chroma-safe metadata for this outcome.

        Unknown values are omitted rather than written as `None` — Chroma
        rejects null metadata, and an absent key already reads as "not
        measured" to everything downstream.
        """
        metadata: Dict[str, Any] = {"inverted": self.inverted}

        for days, pct in self.horizons.items():
            metadata[f"price_change_{days}d"] = round(pct, 4)

        if self.max_drawdown_pct is not None:
            metadata["max_drawdown_pct"] = round(self.max_drawdown_pct, 4)
        if self.max_runup_pct is not None:
            metadata["max_runup_pct"] = round(self.max_runup_pct, 4)
        if self.abs_impact is not None:
            metadata["abs_impact"] = round(self.abs_impact, 4)
        if self.immediate_direction:
            metadata["immediate_direction"] = self.immediate_direction
        if self.durable_direction:
            metadata["durable_direction"] = self.durable_direction

        return metadata


def _last_close_at_or_before(
    candles: Sequence[Dict[str, Any]], target_ts: int, tolerance_days: int
) -> Optional[Dict[str, Any]]:
    """
    The most recent candle at or before `target_ts`, if one is close enough.

    Returning the nearest candle regardless of distance is what would let a
    series that ends in March answer a question about December — silently, and
    with a number that looks like a measurement.
    """
    best = None
    for candle in candles:
        if candle["time"] <= target_ts:
            best = candle
        else:
            break

    if best is None:
        return None
    if target_ts - best["time"] > tolerance_days * _SECONDS_PER_DAY:
        return None
    return best


def _direction_over(horizons: Dict[int, float], days: Sequence[int]) -> Optional[str]:
    """Direction implied by the measured horizons in a group, or None if none were."""
    values = [horizons[d] for d in days if d in horizons]
    if not values:
        return None
    return direction_from_pct(sum(values) / len(values))


def _settled_direction(horizons: Dict[int, float], days: Sequence[int]) -> Optional[str]:
    """
    Direction at the longest horizon that was actually measured.

    Averaging the long horizons instead would hand the verdict to whichever one
    happens to be largest: bitcoin's 365-day change after the 2020 Covid crash is
    +828%, which swamps every other term and turns the mean into a statement
    about the bull market rather than about the event. "Durable" means what
    lasted, so it is read off the far end and the shorter horizons are reported
    alongside as the path taken to get there.
    """
    measured = sorted(d for d in days if d in horizons)
    if not measured:
        return None
    return direction_from_pct(horizons[measured[-1]])


def summarize_outcome(
    candles: Sequence[Dict[str, Any]],
    event_date: datetime,
    *,
    horizons: Optional[Sequence[int]] = None,
    tolerance_days: int = TOLERANCE_DAYS,
) -> Optional[EventOutcome]:
    """
    Turn a candle series into an `EventOutcome`, or None if it cannot be measured.

    Endpoints are read from closes — where the market settled. The path
    statistics are read from intraday lows and highs, because "fell 73% and came
    back" is a different fact from "closed 9% lower", and only the first one
    explains why a headline felt like the end of the world.
    """
    if not candles:
        return None

    horizon_days = sorted(set(horizons if horizons is not None else settings.rag_outcome_horizons))
    if not horizon_days:
        return None

    ordered = sorted(candles, key=lambda c: c["time"])
    # UTC, explicitly. Candle timestamps are UTC epochs, and deriving the event
    # instant from the host's local midnight instead shifts the whole comparison
    # by the machine's offset — enough, west of UTC, to let the event's own
    # session be read as the "before" price and invert the measurement.
    event_ts = int(
        datetime(event_date.year, event_date.month, event_date.day, tzinfo=UTC).timestamp()
    )

    # The baseline is the last close *before* the event — the price the market
    # held while the news was still unknown.
    prior = [c for c in ordered if c["time"] < event_ts]
    baseline_candle = _last_close_at_or_before(prior, event_ts, BASELINE_LOOKBACK_DAYS)
    if baseline_candle is None:
        return None

    baseline = float(baseline_candle["close"])
    if baseline <= 0:
        return None

    measured: Dict[int, float] = {}
    for days in horizon_days:
        target = event_ts + days * _SECONDS_PER_DAY
        candle = _last_close_at_or_before(ordered, target, tolerance_days)
        # A candle at or before the event is not a measurement of what followed.
        if candle is None or candle["time"] < event_ts:
            continue
        measured[days] = (float(candle["close"]) - baseline) / baseline * 100.0

    max_drawdown = max_runup = None
    window_end = event_ts + max(horizon_days) * _SECONDS_PER_DAY
    after = [c for c in ordered if event_ts <= c["time"] <= window_end]
    if after:
        lowest = min(float(c["low"]) for c in after)
        highest = max(float(c["high"]) for c in after)
        max_drawdown = (lowest - baseline) / baseline * 100.0
        max_runup = (highest - baseline) / baseline * 100.0

    immediate = _direction_over(measured, [d for d in horizon_days if d <= IMMEDIATE_MAX_DAYS])
    durable_days = [d for d in horizon_days if d >= DURABLE_MIN_DAYS]
    if not durable_days:
        # A shortened horizon set still deserves a verdict; the longest one it
        # has is the closest thing to a settled outcome available.
        durable_days = horizon_days[-1:]
    durable = _settled_direction(measured, durable_days)

    inverted = bool(
        immediate and durable and immediate != durable and "neutral" not in (immediate, durable)
    )

    return EventOutcome(
        baseline=baseline,
        horizons=measured,
        max_drawdown_pct=max_drawdown,
        max_runup_pct=max_runup,
        immediate_direction=immediate,
        durable_direction=durable,
        inverted=inverted,
    )


async def fetch_outcome_candles(
    symbol: str, event_date: datetime, asset_type: str, horizons: Sequence[int]
) -> List[Dict[str, Any]]:
    """Daily bars spanning an event's baseline and its longest horizon."""
    start = event_date - timedelta(days=BASELINE_LOOKBACK_DAYS)
    end = event_date + timedelta(days=max(horizons) + TOLERANCE_DAYS)
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)

    try:
        if asset_type == "stock":
            from services.stock_market_service import fetch_stock_candles_between

            return await fetch_stock_candles_between(symbol, start_ms, end_ms)

        from services.okx_market import fetch_candles_between

        # "1Dutc", not "1D": OKX closes its plain daily candle at 00:00 UTC+8,
        # so a "19 May" bar actually spans 18 May 16:00 UTC to 19 May 16:00 UTC.
        # Compared against a UTC event instant that puts the crash session on the
        # wrong side of the event — measured on China's 2021 mining ban it made
        # the crash day itself the baseline and reported the next day's bounce as
        # a +11% one-day gain, when bitcoin had in fact fallen about 30%.
        candles = await fetch_candles_between(symbol, start_ms, end_ms, bar="1Dutc")
        if candles:
            return candles
        # Not every instrument serves the UTC-aligned bar; an eight-hour offset
        # beats no history at all.
        return await fetch_candles_between(symbol, start_ms, end_ms, bar="1D")
    except Exception as e:
        logger.warning(
            "Outcome candles unavailable for %s around %s: %s",
            symbol,
            event_date.date(),
            e,
        )
        return []


async def measure_event_outcome(
    symbol: str, event_date: datetime, asset_type: str = "crypto"
) -> Optional[EventOutcome]:
    """
    Measure what an event did to its asset, or None when the history is missing.

    None is a real answer here and is treated as one: OKX does not carry every
    pair back to 2020, and Yahoo sometimes returns nothing for a long-past
    window. An unmeasured event is still indexed — it simply falls back to its
    class prior for importance instead of claiming a move that was never seen.
    """
    horizons = settings.rag_outcome_horizons
    if not horizons:
        return None

    candles = await fetch_outcome_candles(symbol, event_date, asset_type, horizons)
    if not candles:
        return None

    return summarize_outcome(candles, event_date, horizons=horizons)
