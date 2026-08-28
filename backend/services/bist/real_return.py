"""
What a Turkish return actually was.

A nominal figure quoted in lira describes the number of lira, not what they
bought. Over the windows this terminal reports on — a year, three years, five —
the difference between those two statements is most of the number. So every
return this package serves carries a real one beside it, and the arithmetic
lives here rather than being inlined at each call site.

Two reference frames, because they answer different questions:

**Against inflation (TÜFE)** is the one that matters to somebody spending the
money in Turkey. It is the honest default.

**Against the dollar** is the one that matters to somebody comparing this
against a foreign asset, and it is what most Turkish investors actually
benchmark against in practice — rightly or not.

Neither is a correction of the other and neither replaces the nominal figure.
All three are reported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ReturnTriplet:
    """One return, in the three frames a Turkish reader needs it in."""

    nominal: float
    """As quoted, in lira."""

    real: Optional[float]
    """Deflated by consumer prices. None when the inflation figure is missing."""

    usd: Optional[float]
    """Restated in dollars. None when the exchange rates are missing."""


def deflate(nominal: float, inflation: float) -> Optional[float]:
    """
    Strip inflation out of a nominal return over the same window.

    The Fisher relation, not the subtraction people reach for first: at 148%
    nominal against 89% inflation, subtracting gives 59% and the true figure is
    31%. The gap between those two answers grows with the rate, which is exactly
    why the shortcut is unusable here.

    Returns None for an inflation rate of -100% or worse, where the ratio is
    undefined — a guard rather than a real case, but a silent ZeroDivisionError
    inside a screener is worse than a missing cell.
    """
    if inflation <= -1:
        return None
    return (1 + nominal) / (1 + inflation) - 1


def in_usd(nominal: float, fx_start: float, fx_end: float) -> Optional[float]:
    """
    Restate a lira return in dollars, given USDTRY at both ends of the window.

    `fx_start` and `fx_end` are lira per dollar — the quote convention every
    Turkish source uses. A lira that weakened means `fx_end > fx_start`, which
    reduces the return, which is the direction this has to get right.
    """
    if fx_start <= 0 or fx_end <= 0:
        return None
    return (1 + nominal) * (fx_start / fx_end) - 1


def triplet(
    nominal: float,
    *,
    inflation: Optional[float] = None,
    fx_start: Optional[float] = None,
    fx_end: Optional[float] = None,
) -> ReturnTriplet:
    """
    Build the three-frame view of one return.

    Missing inputs produce None fields rather than an exception: the macro
    series and the FX series fail independently of the fund data, and losing
    one should cost one column rather than the row.
    """
    real = deflate(nominal, inflation) if inflation is not None else None
    usd = in_usd(nominal, fx_start, fx_end) if fx_start is not None and fx_end is not None else None
    return ReturnTriplet(nominal=nominal, real=real, usd=usd)


def cumulative_inflation(monthly_rates: list[float]) -> float:
    """
    Compound a run of monthly inflation rates into one figure for the window.

    Compounded rather than summed. Twelve months of 3% is 42.6%, not 36%, and
    at Turkish rates that error is larger than most of the returns it would be
    applied to.
    """
    total = 1.0
    for rate in monthly_rates:
        total *= 1 + rate
    return total - 1


def annualise(total: float, months: int) -> Optional[float]:
    """
    Convert a whole-window return into an annual rate.

    Used to put a six-month figure and a three-year figure on the same axis.
    Returns None for a total loss or worse, where the root is undefined.
    """
    if months <= 0 or total <= -1:
        return None
    return (1 + total) ** (12 / months) - 1


# ── Applying the frames to a board ─────────────────────────────────────────
# Still pure: the callers hand in the deflators and the exchange rates they
# resolved, and get back the three-frame view of every window. Keeping the I/O
# out means the ranking logic can be tested without a network.


def rate_months_ago(series: list[dict], months: int) -> Optional[float]:
    """
    The exchange rate roughly `months` before the end of a daily series.

    Positional rather than by calendar date: the series is trading days, so
    counting back 21 per month lands within a day or two of the anniversary and
    never falls into a weekend or a holiday gap the way a date lookup does. The
    small imprecision is immaterial against a currency that moved 17% over the
    same year, and it cannot fail to find a row.
    """
    if not series:
        return None
    offset = round(months * 21)
    index = len(series) - 1 - offset
    if index < 0:
        return None
    rate = series[index].get("rate")
    return float(rate) if isinstance(rate, (int, float)) and rate > 0 else None


def enrich_returns(
    returns: dict[str, Optional[float]],
    *,
    deflators: dict[str, Optional[float]],
    fx_series: Optional[list[dict]] = None,
    window_months: Optional[dict[str, int]] = None,
) -> dict[str, dict]:
    """
    Turn a map of nominal returns into the three-frame view of each.

    Every window that has a nominal figure appears in the result, whether or not
    it could be deflated — a missing real column has to be visibly missing
    rather than absent, or a reader cannot tell "we do not know" from "there is
    nothing here".
    """
    months = window_months or {}
    fx_end = fx_series[-1].get("rate") if fx_series else None

    out: dict[str, dict] = {}
    for window, nominal in returns.items():
        if nominal is None:
            continue
        fx_start = None
        if fx_series and fx_end and window in months:
            fx_start = rate_months_ago(fx_series, months[window])
        frames = triplet(
            nominal,
            inflation=deflators.get(window),
            fx_start=fx_start,
            fx_end=fx_end if fx_start is not None else None,
        )
        out[window] = {
            "nominal": frames.nominal,
            "real": frames.real,
            "usd": frames.usd,
        }
    return out


@dataclass(frozen=True)
class RealLossSummary:
    """
    How much of a board gained in lira and lost in purchasing power.

    The single most useful number this package can produce, and it only means
    anything as a proportion: one fund that trailed inflation is an anecdote,
    a third of them is the market.
    """

    window: str
    measured: int
    """Rows that had both a nominal figure and a deflator for this window."""
    count: int
    """Of those, how many were a nominal gain and a real loss."""
    example_key: Optional[str] = None
    """The most legible case — the largest nominal gain that still ended negative."""
    example_nominal: Optional[float] = None
    example_real: Optional[float] = None


def summarise_real_losses(
    rows: list[tuple[str, dict[str, dict]]],
    window: str = "1y",
) -> RealLossSummary:
    """
    Count the rows whose nominal gain did not survive inflation.

    `rows` is `(key, framed_returns)` pairs — the shape both the fund board and
    the equity board already hold, so neither has to be reshaped to be counted.

    The example is chosen as the *largest* nominal gain that is still a real
    loss rather than the worst case. A fund up 31% that returned nothing after
    inflation makes the point far better than one up 2% that lost 28%: the
    second looks like a bad fund, and the first looks like a good one right up
    until the second column.
    """
    measured = 0
    losers: list[tuple[str, float, float]] = []

    for key, framed in rows:
        entry = framed.get(window)
        if not entry:
            continue
        nominal = entry.get("nominal")
        real = entry.get("real")
        if nominal is None or real is None:
            continue
        measured += 1
        if nominal > 0 and real < 0:
            losers.append((key, nominal, real))

    if not losers:
        return RealLossSummary(window=window, measured=measured, count=0)

    key, nominal, real = max(losers, key=lambda row: row[1])
    return RealLossSummary(
        window=window,
        measured=measured,
        count=len(losers),
        example_key=key,
        example_nominal=nominal,
        example_real=real,
    )
