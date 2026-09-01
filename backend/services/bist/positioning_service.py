"""
Positioning: who is leaning which way, from what the market actually publishes.

**This is not the board it was meant to be, and the difference matters.** The
intent was a fund-to-stock cross index — invert every TEFAS portfolio and answer
"which funds moved into this name last month", the Turkish counterpart of the
13F board on the global realm. That is still not buildable, though for a
narrower reason than it first appeared. TEFAS does publish a fund's split by
*asset class* — see `fund_allocation`, which draws it on the fund board — but
nothing public names the individual securities behind "hisse senedi %58", and
KAP publishes fund holdings as prose attachments with no structured field to
read. A class weight cannot be inverted into a per-stock index.

So this board answers a narrower question from data that does exist:

* **Free float** — how much of the company can actually trade. A 20% float means
  a small flow moves the price a long way, and it is the single most useful
  number on a Turkish small cap.
* **Relative volume** — today against its own ten-day norm. Unusual interest,
  before the price has finished expressing it.
* **Position in the 52-week range** — where the stock sits between its own
  extremes, which is the context a raw price does not carry.
* **VİOP open interest** — the one place in this market where positioning is
  *published* rather than inferred. Roughly forty names have futures, and a
  build in open interest against a flat price is a real signal.

Everything here is derived from boards already fetched. The service adds a join
and a ranking, not an upstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.bist.tradingview_client import EquityRow
from services.bist.viop_service import ViopContract


@dataclass(frozen=True)
class PositioningRow:
    ticker: str
    symbol: str
    name: str
    sector: str
    price: Optional[float]
    change_pct: Optional[float]
    market_cap: Optional[float]
    free_float_pct: Optional[float]
    relative_volume: Optional[float]
    range_position: Optional[float]
    """Where the price sits in its 52-week range: 0.0 at the low, 1.0 at the high."""
    beta: Optional[float]
    rsi: Optional[float]
    open_interest: Optional[float]
    """Summed across every VİOP expiry on this underlying. None if it has no futures."""
    open_interest_change: Optional[float]
    crowding: Optional[float]
    """See `_crowding`. Higher means more unusual activity against less free float."""


def range_position(row: EquityRow) -> Optional[float]:
    """How far up its own year the price is, as a fraction."""
    if row.price is None or row.week52_high is None or row.week52_low is None:
        return None
    span = row.week52_high - row.week52_low
    if span <= 0:
        return None
    return max(0.0, min(1.0, (row.price - row.week52_low) / span))


# Below this, a "free float" is not a float. Borsa İstanbul lists holding
# structures and recently-converted companies whose tradeable share is under a
# percent; dividing by that produces a crowding score in the hundreds for a
# stock nobody is trading, which is how the first version of this ranked a bank
# with a 0.4% float above every genuinely busy name on the board.
MIN_FREE_FLOAT = 0.05

# Volume has to actually be elevated for "unusual volume" to mean anything.
# A stock at half its normal turnover is not crowded, however tight its float.
MIN_RELATIVE_VOLUME = 1.0


def _crowding(relative_volume: Optional[float], free_float_pct: Optional[float]) -> Optional[float]:
    """
    Unusual volume weighted by how little of the company is available to trade.

    Deliberately a simple ratio rather than a scored composite. It is a sorting
    aid — "look at these first" — and dressing it up as a proprietary index
    would invite it to be read as a verdict, which it is not.

    None rather than a number whenever the inputs make the ratio meaningless:
    an unmeasured float, a float too small to trade, or volume that is not
    elevated at all. A row with no score sorts outside the ranking rather than
    at the bottom of it.
    """
    if relative_volume is None or free_float_pct is None:
        return None
    if free_float_pct < MIN_FREE_FLOAT or relative_volume < MIN_RELATIVE_VOLUME:
        return None
    return relative_volume / free_float_pct


def build_positioning(
    equities: list[EquityRow],
    viop: Optional[list[ViopContract]] = None,
) -> list[PositioningRow]:
    """Join the equity board to the futures board and rank by crowding."""
    open_interest: dict[str, float] = {}
    open_interest_change: dict[str, float] = {}
    for contract in viop or []:
        if contract.open_interest is not None:
            open_interest[contract.underlying] = (
                open_interest.get(contract.underlying, 0.0) + contract.open_interest
            )
        if contract.open_interest_change is not None:
            open_interest_change[contract.underlying] = (
                open_interest_change.get(contract.underlying, 0.0) + contract.open_interest_change
            )

    rows = [
        PositioningRow(
            ticker=row.ticker,
            symbol=row.symbol,
            name=row.name,
            sector=row.sector,
            price=row.price,
            change_pct=row.change_pct,
            market_cap=row.market_cap,
            free_float_pct=row.free_float_pct,
            relative_volume=row.relative_volume,
            range_position=range_position(row),
            beta=row.beta,
            rsi=row.rsi,
            open_interest=open_interest.get(row.ticker),
            open_interest_change=open_interest_change.get(row.ticker),
            crowding=_crowding(row.relative_volume, row.free_float_pct),
        )
        for row in equities
    ]

    # Unmeasurable last, in both directions — same rule the equity screener
    # follows, and for the same reason.
    rows.sort(key=lambda r: (r.crowding is None, -(r.crowding or 0.0)))
    return rows


def futures_positioning(rows: list[PositioningRow]) -> list[PositioningRow]:
    """Only the names that have futures, ranked by how much open interest moved."""
    with_futures = [row for row in rows if row.open_interest]
    with_futures.sort(key=lambda r: abs(r.open_interest_change or 0.0), reverse=True)
    return with_futures
