"""
Restating a lira figure from the quarter it was reported in into today's lira.

Every line of a Turkish financial statement is stated in the price level of its
own period. Over the twelve quarters the Bilanço board draws, that is most of
the number: a company whose nominal revenue tripled between 2023 and 2026 may
have sold slightly less. A quarterly revenue chart drawn from the published
figures is therefore a chart of inflation with a company-shaped wobble on it,
which is why the board deflates by default rather than behind a switch.

**This is not `real_return.deflate`, and the difference is not cosmetic.** That
function applies the Fisher relation to a *return* — two numbers describing the
same money at two moments. This module restates a *level*: one number, moved
from its own price frame into another, which is a multiplication by a ratio of
index values. Using the return formula on a level, or this one on a return,
produces a plausible number that is wrong, and both mistakes read as arithmetic
that already happened. `real_return.deflate` is still the right tool for a
post-IPO return; it is the wrong tool here.

The index is TCMB's TÜFE (`TP.FG.J0`, 2003=100), monthly, fetched by
`macro_service.fetch_cpi_series`. Two properties of that series shape everything
below:

* **It ends before the statements do.** CPI for a month lands early in the next
  one, while a quarter's statements land up to forty days after the quarter
  closes. The newest quarter on the board is therefore routinely one or two
  months past the newest CPI month.
* **It is empty without an API key**, which `macro_service` documents as a
  supported state rather than a failure. Since the deflated view is the board's
  default, "no key" has to be a stated, visible condition — never a quiet
  fallback to nominal figures still labelled real.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

QUARTER_END_MONTH: dict[int, str] = {1: "03", 2: "06", 3: "09", 4: "12"}

_PERIOD_RE = re.compile(r"^(\d{4})Q([1-4])$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{1,2})$")

REASON_KEY_MISSING = "cpi_key_missing"
"""No `TCMB_EVDS_API_KEY`. The only one of the three an operator can fix."""

REASON_UNAVAILABLE = "cpi_unavailable"
"""A key is configured and EVDS still returned nothing — an outage, not a setup gap."""

REASON_TOO_SHORT = "cpi_too_short"
"""A series arrived but does not reach the base quarter, so there is no frame to restate into."""

MAX_CARRY_FORWARD_MONTHS = 4
"""
How far past the newest CPI month the base quarter may sit and still be deflated.

CPI trails the calendar by about a month and statements trail their quarter by up
to forty days, so a base three months ahead of the index is ordinary. Beyond that
the series is not merely trailing, it is stale — and carrying an index forward
across a Turkish year would understate every restatement by tens of percent while
still producing a full set of finite, monotone, entirely wrong factors.
"""


@dataclass(frozen=True)
class Deflation:
    """
    Whether a set of periods can be restated, and by how much.

    Carries its own unavailability rather than being `None` when it fails: the
    board has to say *why* the deflated view is off, and three reasons need
    three different sentences.
    """

    available: bool
    reason: Optional[str] = None
    base_period: Optional[str] = None
    base_month: Optional[str] = None
    cpi_latest_month: Optional[str] = None
    factors: dict[str, float] = field(default_factory=dict)
    """Period → the multiplier that carries it into `base_period` lira."""
    provisional: tuple[str, ...] = ()
    """Periods newer than the newest published CPI month; see `build_deflation`."""
    uncovered: tuple[str, ...] = ()
    """Periods older than the series. No factor, and no guess."""


def period_month(period: str) -> Optional[str]:
    """`2026Q2` → `2026-06`, the month whose price level that quarter closed at."""
    match = _PERIOD_RE.match(period.strip().upper())
    if match is None:
        return None
    return f"{match.group(1)}-{QUARTER_END_MONTH[int(match.group(2))]}"


def index_by_month(series: list[dict[str, Any]]) -> dict[str, float]:
    """
    The CPI series as a month → index lookup, with the month keys zero-padded.

    EVDS states a monthly `Tarih` as `2026-6`, not `2026-06`, and nothing
    downstream would raise on the mismatch — every lookup would simply miss and
    every quarter would come back uncovered, which reads as "inflation data
    unavailable" rather than as a parsing bug. That makes this the most likely
    silent failure in the feature, so it normalises rather than trusting the
    upstream shape, and it has its own test.
    """
    out: dict[str, float] = {}
    for row in series or []:
        raw_month = str(row.get("month") or "")
        match = _MONTH_RE.match(raw_month.strip())
        if match is None:
            continue
        try:
            value = float(row.get("index"))
        except (TypeError, ValueError):
            continue
        if value <= 0:
            # A zero or negative price index is not a price index. Dividing by
            # it would produce an infinity that renders as a plausible bar.
            continue
        out[f"{match.group(1)}-{int(match.group(2)):02d}"] = value
    return out


def _months_between(earlier: str, later: str) -> int:
    """Whole months from one `YYYY-MM` to another. Negative when `later` precedes."""
    ey, em = (int(part) for part in earlier.split("-"))
    ly, lm = (int(part) for part in later.split("-"))
    return (ly - ey) * 12 + (lm - em)


def build_deflation(
    periods: list[str],
    cpi_series: list[dict[str, Any]],
    *,
    key_configured: bool,
) -> Deflation:
    """
    Factors that carry each period into the newest period's lira.

    The base is the newest period asked about, not the newest CPI month, so the
    board's figures are quoted in the lira of the quarter the reader is looking
    at rather than in the lira of whichever month the central bank last
    published. That makes the newest bar's factor exactly 1.0 and keeps the
    chart's own axis label honest.

    **Carry forward at the new end, never back at the old one, and only so
    far.** A period up to `MAX_CARRY_FORWARD_MONTHS` newer than
    `cpi_latest_month` takes the index at `cpi_latest_month` and is listed in
    `provisional`: CPI trails the calendar by about a month and statements trail
    their quarter by up to forty days, so the newest quarter is routinely a
    little ahead of the index, and dropping it would delete the newest bar from
    a board whose whole subject is the newest quarter. Past that bound the
    period lands in `uncovered` instead — carrying an index across half a year
    of Turkish inflation would understate the restatement by tens of percent
    while still producing a finite, plausible factor. A period *older* than the
    series is `uncovered` for the same reason in the other direction:
    extrapolating an index backwards is inventing a price level.

    **The base is the newest period the index can actually reach**, which is not
    always the newest period asked about. EVDS runs months behind on occasion —
    it was eight months behind when this was written — and pinning the base to a
    quarter the index cannot cover would take the entire board nominal over one
    unreachable bar. Falling back one or two quarters keeps ten of eleven bars
    honestly restated and marks the rest; the base period travels in the payload
    so the axis can say which lira these figures are in.
    """
    index = index_by_month(cpi_series)

    if not index:
        return Deflation(
            available=False,
            reason=REASON_KEY_MISSING if not key_configured else REASON_UNAVAILABLE,
        )

    known = sorted(index)
    oldest_month, latest_month = known[0], known[-1]

    ordered = sorted(p for p in periods if period_month(p) is not None)
    if not ordered:
        return Deflation(available=False, reason=REASON_TOO_SHORT, cpi_latest_month=latest_month)

    def reachable(period: str) -> bool:
        month = period_month(period)
        if month is None or month < oldest_month:
            return False
        return _months_between(latest_month, month) <= MAX_CARRY_FORWARD_MONTHS

    # The newest period the index can actually reach, which is not always the
    # newest period asked about — see the docstring on why falling back beats
    # taking the whole board nominal.
    candidates = [period for period in ordered if reachable(period)]
    if not candidates:
        return Deflation(
            available=False,
            reason=REASON_TOO_SHORT,
            base_period=ordered[-1],
            base_month=period_month(ordered[-1]),
            cpi_latest_month=latest_month,
        )

    base_period = candidates[-1]
    base_month = period_month(base_period)
    assert base_month is not None  # guarded by `reachable`

    base_index = index.get(base_month, index[latest_month])

    factors: dict[str, float] = {}
    provisional: list[str] = []
    uncovered: list[str] = []

    for period in ordered:
        month = period_month(period)
        assert month is not None
        if not reachable(period):
            uncovered.append(period)
            continue
        if month > latest_month:
            factors[period] = base_index / index[latest_month]
            provisional.append(period)
            continue
        factors[period] = base_index / index[month]

    return Deflation(
        available=True,
        reason=None,
        base_period=base_period,
        base_month=base_month,
        cpi_latest_month=latest_month,
        factors=factors,
        provisional=tuple(provisional),
        uncovered=tuple(uncovered),
    )


def restate(value: Optional[float], factor: Optional[float]) -> Optional[float]:
    """
    One figure in base-period lira, or None when either half is missing.

    Both halves are routinely absent — a company that does not report a line, a
    quarter the index does not reach — and the two cases are indistinguishable
    to a reader, so both produce the same empty cell rather than a zero that
    would plot.
    """
    if value is None or factor is None:
        return None
    return value * factor
