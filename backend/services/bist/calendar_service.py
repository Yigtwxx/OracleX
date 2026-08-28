"""
Dated events on Borsa İstanbul: results announcements and dividends.

Derived from the equity board rather than fetched separately — the scanner
carries the dates in the same response as the quotes, so the calendar costs
nothing beyond what the screener already paid.

**What is here and what is not.** Scheduled results dates and upcoming
ex-dividend dates are published and reliable. Rights issues and bonus issues
(*bedelli* and *bedelsiz sermaye artırımı*) are not: they are announced through
KAP as prose, with no structured date field anywhere, and the ones this terminal
can show come through the disclosure tape as filings rather than as calendar
rows. The distinction is kept visible instead of being papered over with a
partial list that looks complete.

The calendar is also genuinely sparse — around one listing in ten has announced
a results date at any moment, and fewer have declared a dividend. An empty week
is an empty week, not a failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal, Optional

from services.bist.tradingview_client import EquityRow

EventKind = Literal["earnings", "dividend"]


@dataclass(frozen=True)
class CalendarEvent:
    kind: EventKind
    day: str
    """ISO date."""
    ticker: str
    symbol: str
    name: str
    sector: str
    market_cap: Optional[float]
    amount: Optional[float]
    """Dividend per share. None for a results date."""
    yield_pct: Optional[float]
    """Trailing dividend yield, as a fraction. None for a results date."""


def build_calendar(
    equities: list[EquityRow],
    *,
    days_ahead: int = 90,
    days_back: int = 14,
    kinds: Optional[frozenset[str]] = None,
    today: Optional[date] = None,
) -> list[CalendarEvent]:
    """
    Every dated event inside the window, soonest first.

    `days_back` exists because a results date that has just passed is still what
    a reader is looking for — "did they report yet" is the same question as
    "when do they report", asked a day later.

    `today` is injectable so the window can be tested without freezing the clock.
    """
    now = today or date.today()
    first = now - timedelta(days=days_back)
    last = now + timedelta(days=days_ahead)
    wanted = kinds or frozenset({"earnings", "dividend"})

    events: list[CalendarEvent] = []
    for row in equities:
        if "earnings" in wanted and row.next_earnings:
            events.append(_event("earnings", row.next_earnings, row))
        if "dividend" in wanted and row.ex_dividend_date:
            events.append(_event("dividend", row.ex_dividend_date, row))

    inside = [event for event in events if first.isoformat() <= event.day <= last.isoformat()]
    # Date first, then size: two companies reporting on the same morning should
    # be ordered by which one moves the index.
    inside.sort(key=lambda event: (event.day, -(event.market_cap or 0.0)))
    return inside


def _event(kind: EventKind, day: str, row: EquityRow) -> CalendarEvent:
    return CalendarEvent(
        kind=kind,
        day=day,
        ticker=row.ticker,
        symbol=row.symbol,
        name=row.name,
        sector=row.sector,
        market_cap=row.market_cap,
        amount=row.dividend_amount if kind == "dividend" else None,
        yield_pct=row.dividend_yield if kind == "dividend" else None,
    )


def group_by_day(events: list[CalendarEvent]) -> list[dict]:
    """The same events as dated buckets, which is how a calendar renders."""
    days: dict[str, list[CalendarEvent]] = {}
    for event in events:
        days.setdefault(event.day, []).append(event)
    return [{"day": day, "events": days[day], "count": len(days[day])} for day in sorted(days)]
