"""
The TEFAS fund board: screening, ranking and per-fund risk statistics.

Two access shapes, because the upstream has two and they cost very different
amounts:

**The board** is one request for every fund TEFAS lists, with the period returns
it publishes. Cheap, cached for half an hour, and what the screener renders.

**A fund's statistics** need its price series, and the price endpoint is
per-fund with no bulk form. Computing Sharpe for the whole list would be a
thousand HTTP requests, so it happens on demand — opening a fund, or comparing a
handful — and never as a side effect of loading the table.

That split is why the screener shows TEFAS's own published returns rather than
ones derived here. They agree; deriving them would just cost a thousand requests
to arrive at the same numbers.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
from dataclasses import dataclass
from typing import Optional

from services.bist import fund_metrics
from services.bist.tefas_client import (
    FUND_TYPE_LABELS,
    FUND_TYPES,
    FundRow,
    TefasUnavailable,
    fetch_fund_prices,
    fetch_fund_rows,
)
from services.bist.text import contains
from services.cache import bist_cache

logger = logging.getLogger(__name__)

# TEFAS prices once a day, after the close. Half an hour is short enough to pick
# up the evening publish without asking again for every reader in between.
TTL_BOARD = 30 * 60
TTL_DETAIL = 60 * 60

# Three days of stale tolerance. A long weekend plus a public holiday is the
# real case this covers — the exchange is shut, TEFAS publishes nothing, and
# Friday's figures are the correct thing to show on Sunday rather than an error.
MAX_STALE_BOARD = 3 * 24 * 60 * 60
MAX_STALE_DETAIL = 3 * 24 * 60 * 60

# TEFAS's own umbrella label for money-market funds. Used to estimate the
# risk-free rate; see `estimate_risk_free_rate`.
MONEY_MARKET_UMBRELLA = "Para Piyasası Şemsiye Fonu"

# How many funds a single compare request may name. Each one is an HTTP round
# trip to a per-fund endpoint, and past a handful the wait stops reading as a
# page loading and starts reading as a page that is broken.
MAX_COMPARE = 8


class FundDataUnavailable(RuntimeError):
    """No live fund data and no fallback recent enough to stand in for it."""


@dataclass(frozen=True)
class FundBoard:
    """Every fund of one type, plus what the set as a whole implies."""

    fund_type: str
    fund_type_label: str
    funds: list[FundRow]
    risk_free_rate: Optional[float]
    """Annual, as a fraction. Estimated from the board — see below."""
    stale: bool


def estimate_risk_free_rate(funds: list[FundRow]) -> Optional[float]:
    """
    The lira risk-free rate, read off the money-market funds themselves.

    A Sharpe ratio needs a risk-free rate, and in Turkey that rate is large
    enough that getting it wrong is worse than not reporting the ratio at all.
    The obvious source is the central bank's policy rate, which needs an EVDS
    API key — so on a fresh install, with no key, the single most useful column
    on the board would be empty.

    It does not have to be. TEFAS lists fifty money-market funds whose entire
    business is holding short-dated lira paper, and the median of their trailing
    one-year returns *is* the realised risk-free rate, net of the fees a real
    investor would actually have paid to earn it. Measured against the published
    policy rate it sits within a point or two, and it arrives in the same request
    that built the board.

    The median rather than the mean: the range runs from roughly 43% to 60%, and
    the top of that is funds holding paper a money-market fund arguably should
    not. One outlier should not move the denominator of every ratio on the page.

    Returns None when fewer than five such funds report a one-year figure, which
    is the case on the pension and ETF books rather than a failure.
    """
    returns = [
        fund.returns["1y"]
        for fund in funds
        if fund.umbrella == MONEY_MARKET_UMBRELLA and fund.returns.get("1y") is not None
    ]
    if len(returns) < 5:
        return None
    return statistics.median(returns)  # type: ignore[arg-type]


async def fetch_fund_board(fund_type: str = "YAT") -> FundBoard:
    """
    Every fund of one type, with its published returns and the implied cash rate.

    Raises `FundDataUnavailable` when TEFAS is down and no recent enough
    snapshot survives. It never returns an empty board on failure: a screener
    showing no funds reads as "nothing matched your filters", which is a
    different and much more misleading statement.
    """
    if fund_type not in FUND_TYPES:
        raise ValueError(f"fund_type must be one of {FUND_TYPES}, got {fund_type!r}")

    key = f"board:{fund_type}"
    cached = bist_cache.get(key)
    if cached is not None:
        return _board_from(fund_type, cached, stale=False)

    try:
        funds = await fetch_fund_rows(fund_type)
    except TefasUnavailable as e:
        stale = bist_cache.get_with_fallback(key, max_age=MAX_STALE_BOARD)
        if stale is not None:
            logger.warning("TEFAS board unavailable, serving stale snapshot: %s", e)
            return _board_from(fund_type, stale, stale=True)
        raise FundDataUnavailable(f"TEFAS fund board unavailable: {e}") from e

    if not funds:
        # A genuinely empty list from a successful call. Treated as a failure
        # for the same reason a null result list is inside the client: TEFAS
        # lists a thousand funds, and zero means something is wrong upstream.
        stale = bist_cache.get_with_fallback(key, max_age=MAX_STALE_BOARD)
        if stale is not None:
            return _board_from(fund_type, stale, stale=True)
        raise FundDataUnavailable("TEFAS returned no funds")

    bist_cache.set(key, funds, TTL_BOARD)
    return _board_from(fund_type, funds, stale=False)


def _board_from(fund_type: str, funds: list[FundRow], *, stale: bool) -> FundBoard:
    return FundBoard(
        fund_type=fund_type,
        fund_type_label=FUND_TYPE_LABELS.get(fund_type, fund_type),
        funds=funds,
        risk_free_rate=estimate_risk_free_rate(funds),
        stale=stale,
    )


@dataclass(frozen=True)
class FundDetail:
    """One fund's price history and everything derived from it."""

    code: str
    title: str
    umbrella: str
    risk_value: Optional[int]
    tradable: bool
    category_rank: Optional[int]
    category_size: Optional[int]
    months: int
    published_returns: dict[str, Optional[float]]
    """TEFAS's own period returns, kept beside the derived ones."""
    series: list[dict]
    """`{"date": "YYYY-MM-DD", "price": float}`, oldest first."""
    metrics: fund_metrics.FundMetrics
    risk_free_rate: Optional[float]


async def fetch_fund_detail(code: str, months: int = 12) -> FundDetail:
    """
    One fund: its net asset value series and the statistics computed from it.

    Raises `FundDataUnavailable` when the code does not resolve. A fund code
    that TEFAS does not know is a 404 rather than an empty chart — the same rule
    `/api/price` follows, and for the same reason.
    """
    code = code.strip().upper()
    if not code:
        raise ValueError("fund code is required")

    key = f"detail:{code}:{months}"
    cached = bist_cache.get(key)
    if cached is not None:
        return cached

    # The board is almost always warm by the time a fund is opened, and it
    # carries the umbrella, the risk grade and the published returns that the
    # price endpoint does not. A board failure is survivable here — the chart
    # and every derived statistic still work without it.
    board: Optional[FundBoard] = None
    try:
        board = await fetch_fund_board("YAT")
    except (FundDataUnavailable, ValueError):
        logger.debug("fund board unavailable while building detail for %s", code)

    row = next((f for f in board.funds if f.code == code), None) if board else None

    try:
        prices = await fetch_fund_prices(code, months)
    except TefasUnavailable as e:
        stale = bist_cache.get_with_fallback(key, max_age=MAX_STALE_DETAIL)
        if stale is not None:
            return stale
        raise FundDataUnavailable(f"fund {code} unavailable: {e}") from e

    if not prices.points:
        raise FundDataUnavailable(f"no price history for fund {code}")

    risk_free = board.risk_free_rate if board else None
    values = [point.price for point in prices.points]
    detail = FundDetail(
        code=code,
        title=prices.title or (row.title if row else code),
        umbrella=row.umbrella if row else "",
        risk_value=row.risk_value if row else None,
        tradable=row.tradable if row else True,
        category_rank=prices.category_rank,
        category_size=prices.category_size,
        months=months,
        published_returns=row.returns if row else {},
        series=[{"date": p.day.isoformat(), "price": p.price} for p in prices.points],
        # Zero only when the rate is genuinely unknown, which leaves Sharpe and
        # Sortino as raw return-per-unit-risk rather than excess-return figures.
        # They are still ordered correctly against each other; they are just not
        # comparable to a published Sharpe, and the frontend says so.
        metrics=fund_metrics.compute(values, risk_free if risk_free is not None else 0.0),
        risk_free_rate=risk_free,
    )

    bist_cache.set(key, detail, TTL_DETAIL)
    return detail


async def compare_funds(codes: list[str], months: int = 12) -> list[FundDetail]:
    """
    Several funds at once, fetched concurrently.

    A code that fails is dropped rather than failing the comparison: three funds
    charted beside a note that the fourth did not resolve is more useful than an
    error page, and the caller can see which ones came back.
    """
    unique = list(dict.fromkeys(code.strip().upper() for code in codes if code.strip()))
    if not unique:
        raise ValueError("at least one fund code is required")
    if len(unique) > MAX_COMPARE:
        raise ValueError(f"at most {MAX_COMPARE} funds can be compared at once")

    results = await asyncio.gather(
        *(fetch_fund_detail(code, months) for code in unique),
        return_exceptions=True,
    )

    details: list[FundDetail] = []
    for code, result in zip(unique, results):
        if isinstance(result, FundDetail):
            details.append(result)
        else:
            logger.info("compare: dropping %s (%s)", code, result)
    return details


# ── Screening ──────────────────────────────────────────────────────────────
# Pure, and here rather than in the router because it is business logic: which
# fund outranks which is the screener's whole answer, and it wants a test that
# does not stand up a web server.

SORTABLE_PERIODS = ("1a", "3a", "6a", "1y", "3y", "5y", "yb")


def screen_funds(
    funds: list[FundRow],
    *,
    umbrella: Optional[str] = None,
    search: Optional[str] = None,
    tradable_only: bool = True,
    max_risk: Optional[int] = None,
    sort_by: str = "1y",
    limit: Optional[int] = None,
) -> list[FundRow]:
    """
    Filter and rank the board.

    `sort_by` is a period key. Funds with no figure for that period sort last
    rather than as zero — a fund launched two months ago has no one-year return,
    and placing it mid-table beside funds that genuinely returned nothing would
    be inventing a result for it.
    """
    if sort_by not in SORTABLE_PERIODS:
        raise ValueError(f"sort_by must be one of {SORTABLE_PERIODS}, got {sort_by!r}")

    rows = funds
    if tradable_only:
        rows = [f for f in rows if f.tradable]
    if umbrella:
        rows = [f for f in rows if f.umbrella == umbrella]
    if max_risk is not None:
        # A fund with no published grade is kept. TEFAS leaves it blank for
        # roughly one fund in nine, and dropping those would silently shrink
        # the board whenever a risk filter was touched.
        rows = [f for f in rows if f.risk_value is None or f.risk_value <= max_risk]
    if search:
        needle = search.strip()
        if needle:
            rows = [f for f in rows if contains(f.code, needle) or contains(f.title, needle)]

    # Two-key sort: presence first, then value. `None` cannot be compared to a
    # float, and mapping it to -inf would put unrated funds *below* the worst
    # real performer rather than outside the ranking.
    rows = sorted(
        rows,
        key=lambda f: (f.returns.get(sort_by) is None, -(f.returns.get(sort_by) or 0.0)),
    )
    return rows[:limit] if limit is not None else rows


def distinct_umbrellas(funds: list[FundRow]) -> list[str]:
    """Umbrella types present on the board, alphabetical, for the filter menu."""
    return sorted({f.umbrella for f in funds if f.umbrella})
