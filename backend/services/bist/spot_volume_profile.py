"""
Volume by price for a BIST listing, from observed intraday bars.

The counterpart layer to the VİOP margin map, and the honest half of the page:
the map places positions where a published parameter says their scan range
runs out, while this places traded volume where it was actually traded. Nothing
here is modelled.

**The interval is hourly over two years**, which is the longest history Yahoo
serves at any intraday granularity — about 6,500 bars for a liquid name. Finer
intervals are available but only over sixty days, and the map's window is longer
than that: two layers drawn on one axis that disagree about which stretch of
history they cover would be worse than one layer.

**A bar's volume is spread across the bins its range covers, not dropped on one
price.** An hourly bar on a Turkish mid-cap spans several bins, and assigning
the whole hour to a single typical price produces a comb — spikes at each bar's
midpoint with troughs between them — which reads as structure in the market
rather than as an artefact of the assignment. Spreading is itself an
approximation (the exchange does not publish where inside the bar the volume
traded), and it is the smaller of the two.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Sequence

from services.bist.equity_service import fetch_candles

logger = logging.getLogger(__name__)

PROFILE_INTERVAL = "60m"
PROFILE_RANGE = "730d"


@dataclass(frozen=True)
class VolumeProfile:
    bins: list[float]
    """Volume per bin, indexed the same as the margin map's grid."""
    total: float
    bars: int
    interval: str
    first_day: Optional[str]
    last_day: Optional[str]


def _spread(
    bins: list[float],
    low: float,
    high: float,
    volume: float,
    price_min: float,
    bin_size: float,
) -> None:
    """Add `volume` evenly across the bins the bar's range covers."""
    count = len(bins)
    if bin_size <= 0 or volume <= 0:
        return

    start = int((low - price_min) / bin_size)
    end = int((high - price_min) / bin_size)
    if end < start:
        start, end = end, start
    start = max(start, 0)
    end = min(end, count - 1)
    if end < start:
        return

    share = volume / (end - start + 1)
    for index in range(start, end + 1):
        bins[index] += share


def build_profile(
    candles: Sequence[dict],
    *,
    price_min: float,
    bin_size: float,
    bins: int,
    first_day: Optional[str] = None,
    last_day: Optional[str] = None,
) -> VolumeProfile:
    """
    Volume by price over the bars that fall inside the map's window.

    The grid is passed in rather than derived, because the profile is drawn
    beside the margin map on a shared axis. Computing its own bounds is how two
    panels end up a few pixels out of register — and a volume bar sitting next
    to the price it does not belong to is worse than no volume bar.
    """
    buckets = [0.0] * bins
    used = 0

    for candle in candles:
        volume = candle.get("volume")
        high = candle.get("high")
        low = candle.get("low")
        close = candle.get("close")
        if not volume or close is None:
            continue

        day = candle.get("date")
        if first_day and day and day < first_day:
            continue
        if last_day and day and day > last_day:
            continue

        top = high if high is not None else close
        bottom = low if low is not None else close
        _spread(buckets, bottom, top, float(volume), price_min, bin_size)
        used += 1

    return VolumeProfile(
        bins=buckets,
        total=sum(buckets),
        bars=used,
        interval=PROFILE_INTERVAL,
        first_day=first_day,
        last_day=last_day,
    )


async def fetch_profile(
    ticker: str,
    *,
    price_min: float,
    bin_size: float,
    bins: int,
    first_day: Optional[str] = None,
    last_day: Optional[str] = None,
) -> Optional[VolumeProfile]:
    """
    The profile for one listing, or None when Yahoo has no intraday history.

    None rather than an exception: the margin map is the page's subject and it
    is built from entirely different upstreams. Losing this layer costs one
    column of the chart, and the page says so rather than failing.
    """
    candles = await fetch_candles(ticker, range_=PROFILE_RANGE, interval=PROFILE_INTERVAL)
    if not candles:
        return None
    return build_profile(
        candles,
        price_min=price_min,
        bin_size=bin_size,
        bins=bins,
        first_day=first_day,
        last_day=last_day,
    )
