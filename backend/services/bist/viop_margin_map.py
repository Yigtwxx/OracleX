"""
Where VİOP positions sit, and how far they are from their scan range.

The shape is borrowed from `services/liquidation_map_service.py` — accumulate
and sweep, one column per session — but almost every input it has to invent,
this one reads:

| | crypto map | here |
|---|---|---|
| exposure opened | `max(ΔOI, 0) + 0.06 × volume` | `ACIK POZISYON DEGISIMI` — published |
| entry price | `(high + low + close) / 3` | `AGIRLIKLI ORTALAMA FIYAT` — published |
| swept range | the candle's own high/low | the contract's high/low — published |
| band distance | ten invented leverage tiers | Takasbank's scan range — published |
| direction | the venue's long/short account ratio | **inferred** — the one gap |

**The direction rule, and why this one.** Open interest rising on a session
whose settlement rose is read as longs opening; rising against a falling
settlement, as shorts. That is the standard futures reading and, more to the
point, it is the reading this codebase already commits to elsewhere:
`frontend/lib/bist-positioning.ts` draws exactly these four quadrants on the
positioning board. Using a different rule here would mean the terminal asserts
two incompatible things about the same data.

A session where settlement did not move gets **no cohort at all**, rather than
a hedged split across both sides. A flat close is the absence of the signal the
rule reads, not a weak version of it — the same call `quadrantOf` makes by
returning null on the axis. What is dropped is counted and reported, so the
page can say how much of the window went unclassified instead of quietly
shrinking.

**Everything is drawn on a spot price axis.** Three expiries trade at three
different prices for the same underlying, and at Turkish rates a three-month
future can carry an eight to ten percent premium. Stacked without adjustment,
one wall of positioning smears into three. Each contract price is therefore
divided by that session's own basis — its settlement over the spot close — so
the axis means one thing, and the spot volume profile drawn beside it indexes
the same grid.

**What the band is not.** It is the price at which a position's initial margin
has absorbed the move the clearing house sized it for. It is *not* a margin
call: Takasbank publishes no maintenance rate for VİOP, so the trigger cannot
be computed and is not claimed. See `takasbank_psr`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Sequence

from services.bist.takasbank_psr import PsrSnapshot
from services.bist.viop_bulletin import SsfRow

logger = logging.getLogger(__name__)

DEFAULT_BINS = 120

# Sessions whose spot close is missing borrow the last known basis, for at most
# this many in a row. Basis moves slowly and mechanically, so a short carry is
# sound; a long one would be a guess wearing a measurement's clothes, and rows
# past the limit are dropped and counted instead.
MAX_BASIS_CARRY = 5

# Below this an underlying's book is a handful of sessions and the map reads as
# noise. ASELS carries under 200k contracts against SASA's 15 million, so the
# floor is what keeps a thin name from being drawn as though it were a thick one.
MIN_OPEN_INTEREST_CONTRACTS = 5_000

# Where Takasbank's own risk array stresses a position, as fractions of the
# scan range, paired with how much of the initial margin each one consumes.
#
# Read out of the file rather than chosen: `AKBNK` carries a contract value of
# 7326.00 and a 15.7% scan range, and its `<ra>` scenario losses come back as
# 383.394 / 766.788 / 1150.182 — exactly a third, two thirds and all of it.
# This is the published counterpart of the ten invented leverage tiers in
# `services/liquidation_map_service.py`, and the reason the field can have
# texture near price without anything being made up: a position is stressed at
# every one of these points, not only at the far end.
#
# The weights are the margin each scenario consumes, normalised — 1:2:3 — so
# the full scan range, where the margin is actually exhausted, stays the
# heaviest mark.
SCAN_SCENARIOS: tuple[tuple[float, float], ...] = (
    (1.0 / 3.0, 1.0 / 6.0),
    (2.0 / 3.0, 2.0 / 6.0),
    (1.0, 3.0 / 6.0),
)

# Cells fainter than this share of the strongest are dropped from the payload.
# They are invisible at any sane ramp and dominate the response size.
CELL_FLOOR = 0.004

SIDE_LONG = 0
SIDE_SHORT = 1


@dataclass(frozen=True)
class MarginCell:
    """
    What stood on one price bin at the close of one session.

    A *snapshot*, not an event: a level that survives ten sessions appears in
    ten cells. That repetition is the point — it is what draws the horizontal
    streak a reader follows across the map, and what makes the moment price
    finally sweeps a level visible as the streak stopping dead.
    """

    column: int
    bin_index: int
    long_try: float
    short_try: float


@dataclass(frozen=True)
class MarginMap:
    underlying: str
    sessions: list[str]
    price_min: float
    price_max: float
    bin_size: float
    bins: int
    cells: list[MarginCell]
    max_value: float
    """Strongest cell on the board, for the ramp to normalise against."""
    psr: float
    thin: bool
    open_interest: float
    undirected_sessions: int
    undirected_notional: float
    basis_carried_sessions: int
    dropped_sessions: int
    contract_multiplier: int
    expiries: list[str]


def direction(oi_change: float, settlement: float, previous: Optional[float]) -> Optional[int]:
    """
    Which side opened, or None when the session does not say.

    Mirrors `quadrantOf` in `frontend/lib/bist-positioning.ts`, including its
    treatment of the axis: an unchanged settlement is not a faint long and not a
    faint short, so nothing is placed. Falling open interest places nothing
    either — a position closing is not a position opening, and unlike the crypto
    model there is no volume term here inventing exposure the exchange did not
    report.
    """
    if oi_change <= 0 or previous is None:
        return None
    if settlement > previous:
        return SIDE_LONG
    if settlement < previous:
        return SIDE_SHORT
    return None


def _bin_index(price: float, price_min: float, bin_size: float, bins: int) -> Optional[int]:
    if bin_size <= 0:
        return None
    index = int((price - price_min) / bin_size)
    if index < 0 or index >= bins:
        return None
    return index


def _price_grid(prices: Sequence[float], psr: float, bins: int) -> tuple[float, float, float]:
    """
    The spot price axis, padded by a full band on each side.

    Padded by the scan range rather than by a fraction of the traded range: a
    band that falls outside the grid is dropped, and dropping the deepest bands
    on whichever side price sits closer to would read as an absence of
    positioning there rather than as the clipping it is.
    """
    low = min(prices)
    high = max(prices)
    if high <= low:
        high = low * 1.01 if low > 0 else low + 1.0
    pad = high * psr
    price_min = max(low - pad, 0.0)
    price_max = high + pad
    return price_min, price_max, (price_max - price_min) / bins


@dataclass
class _Cohort:
    """
    One session's opened exposure on one contract, in spot terms.

    Placed at the session's weighted average, which is the price the exchange
    publishes for it, and placed as a *point*. Spreading it across the day's
    traded range was tried and reverted: it merged neighbouring levels into
    slabs, and a slab claims a level at every price inside it when what is
    known is the mean. The field's texture comes from having many sessions and
    three scenario rungs, not from smearing each one.
    """

    entry: float
    notional: float
    side: int


def build_margin_map(
    rows: Sequence[SsfRow],
    psr_snapshot: PsrSnapshot,
    spot_closes: dict[str, float],
    *,
    underlying: str,
    bins: int = DEFAULT_BINS,
    emit_from: int = 0,
) -> Optional[MarginMap]:
    """
    The book for one underlying, session by session.

    `rows` are that underlying's contracts across every session held; every
    expiry is folded onto the one spot axis. `spot_closes` maps an ISO day to
    that day's spot close and is what makes the fold possible.

    Returns None when the underlying has no scan range published — the band
    distance is a published number and there is no version of this that
    substitutes one.
    """
    rate = psr_snapshot.get(underlying)
    if rate is None:
        return None
    psr = rate.psr

    sessions = sorted({row.day for row in rows})
    if not sessions:
        return None

    by_day: dict[str, list[SsfRow]] = {}
    for row in rows:
        by_day.setdefault(row.day, []).append(row)

    # Basis first, because every price below is expressed through it.
    basis_by_day: dict[str, float] = {}
    carried = 0
    carried_sessions = 0
    dropped_sessions = 0
    last_basis: Optional[float] = None
    for day in sessions:
        close = spot_closes.get(day)
        front = min(by_day[day], key=lambda row: row.expiry)
        if close and close > 0 and front.settlement > 0:
            last_basis = front.settlement / close
            basis_by_day[day] = last_basis
            carried = 0
            continue
        if last_basis is not None and carried < MAX_BASIS_CARRY:
            carried += 1
            carried_sessions += 1
            basis_by_day[day] = last_basis
            continue
        dropped_sessions += 1

    usable = [day for day in sessions if day in basis_by_day]
    if not usable:
        return None

    # Cohorts and sweep ranges, both already in spot terms.
    cohorts_by_day: dict[str, list[_Cohort]] = {day: [] for day in usable}
    sweep_by_day: dict[str, tuple[float, float]] = {}
    spot_prices: list[float] = []
    undirected_sessions = 0
    undirected_notional = 0.0

    for day in usable:
        basis = basis_by_day[day]
        lows: list[float] = []
        highs: list[float] = []
        undirected_here = False

        for row in by_day[day]:
            entry_contract = row.weighted_average or row.settlement
            entry = entry_contract / basis
            spot_prices.append(entry)

            low = (row.low / basis) if row.low else entry
            high = (row.high / basis) if row.high else entry
            lows.append(low)
            highs.append(high)

            side = direction(row.open_interest_change, row.settlement, row.previous_settlement)
            if row.open_interest_change > 0 and side is None:
                undirected_here = True
                undirected_notional += row.open_interest_change * row.multiplier * entry_contract
                continue
            if side is None:
                continue

            cohorts_by_day[day].append(
                _Cohort(
                    entry=entry,
                    notional=row.open_interest_change * row.multiplier * entry_contract,
                    side=side,
                )
            )

        if undirected_here:
            undirected_sessions += 1
        sweep_by_day[day] = (min(lows), max(highs))
        spot_prices.extend((min(lows), max(highs)))

    price_min, price_max, bin_size = _price_grid(spot_prices, psr, bins)

    # Accumulate, sweep, snapshot. `book[(bin, side)]` holds the notional
    # standing on that level right now.
    book: dict[tuple[int, int], float] = {}
    cells: list[MarginCell] = []
    peak = 0.0

    for index, day in enumerate(usable):
        column = index - emit_from

        # 1. Sweep. A level the contract traded through has been reached, and a
        #    reached level is a spent one.
        low, high = sweep_by_day[day]
        low_bin = _bin_index(low, price_min, bin_size, bins)
        high_bin = _bin_index(high, price_min, bin_size, bins)
        if low_bin is not None or high_bin is not None:
            start = low_bin if low_bin is not None else 0
            end = high_bin if high_bin is not None else bins - 1
            for cell in range(start, end + 1):
                book.pop((cell, SIDE_LONG), None)
                book.pop((cell, SIDE_SHORT), None)

        # 2. Deposit this session's cohorts at each published scenario rung.
        #
        #    One mark per rung, at the price the rung implies. Takasbank stresses
        #    a position at a third, two thirds and all of the scan range, so a
        #    single session leaves three levels on each side rather than one —
        #    which is what puts heat near price instead of only at the far end.
        for cohort in cohorts_by_day[day]:
            for fraction, weight in SCAN_SCENARIOS:
                reach = psr * fraction
                shift = (1.0 - reach) if cohort.side == SIDE_LONG else (1.0 + reach)
                target = _bin_index(cohort.entry * shift, price_min, bin_size, bins)
                if target is None:
                    continue
                key = (target, cohort.side)
                book[key] = book.get(key, 0.0) + cohort.notional * weight

        # 3. Snapshot. The book as it stands is this column of the map.
        if column < 0:
            continue
        standing: dict[int, list[float]] = {}
        for (cell, side), notional in book.items():
            pair = standing.setdefault(cell, [0.0, 0.0])
            pair[side] += notional
        for cell, (long_try, short_try) in standing.items():
            total = long_try + short_try
            if total <= 0:
                continue
            peak = max(peak, total)
            cells.append(
                MarginCell(column=column, bin_index=cell, long_try=long_try, short_try=short_try)
            )

    floor = peak * CELL_FLOOR
    cells = [cell for cell in cells if cell.long_try + cell.short_try >= floor]

    latest = usable[-1]
    open_interest = sum(row.open_interest for row in by_day[latest])

    return MarginMap(
        underlying=underlying,
        sessions=usable[emit_from:] if emit_from else usable,
        price_min=price_min,
        price_max=price_max,
        bin_size=bin_size,
        bins=bins,
        cells=cells,
        max_value=peak,
        psr=psr,
        thin=open_interest < MIN_OPEN_INTEREST_CONTRACTS,
        open_interest=open_interest,
        undirected_sessions=undirected_sessions,
        undirected_notional=undirected_notional,
        basis_carried_sessions=carried_sessions,
        dropped_sessions=dropped_sessions,
        contract_multiplier=by_day[latest][0].multiplier,
        expiries=sorted({row.expiry for row in by_day[latest]}),
    )
