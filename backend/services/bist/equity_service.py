"""
The Borsa İstanbul equity board.

One upstream request produces the whole listing, so unlike the fund side there
is no cheap-board / expensive-detail split: opening a company costs nothing the
screener has not already paid for. What the detail page adds is a price history,
which does come from somewhere else.

Sector performance is derived here rather than read from the sector indices
(XUSIN, XUTEK, XGIDA…). Those exist at Borsa İstanbul but not in the quote
source, and deriving them from the constituents is both available and closer to
what a heatmap is asking: how the money in a sector moved, weighted by how much
of it there is.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Optional

from services.bist.tradingview_client import (
    EquityRow,
    IndexRow,
    TradingViewUnavailable,
    fetch_equities,
    fetch_indices,
)
from services.bist.text import contains
from services.cache import bist_cache
from services.http_client import get_json_impersonated

logger = logging.getLogger(__name__)

# The exchange delays its feed by a quarter of an hour, so a shorter TTL would
# buy nothing but load. Two minutes matches the poll the frontend already uses
# for the US board.
TTL_BOARD = 120
TTL_CANDLES = 5 * 60

# Long, and deliberately so. Borsa İstanbul trades 10:00–18:00 on weekdays: for
# two-thirds of every day and all weekend the correct thing to show is the last
# close, not an error. Four days covers a long weekend plus a public holiday.
MAX_STALE_BOARD = 4 * 24 * 60 * 60

# Every BIST quote in this app is at least this far behind the exchange. Carried
# on the payload so no page has to hardcode it into a caption.
DELAY_MINUTES = 15

SORTABLE_FIELDS = (
    "market_cap",
    "change_pct",
    "volume",
    "traded_value",
    "pe",
    "pb",
    "ev_ebitda",
    "perf_ytd",
    "perf_1y",
    "rsi",
    "relative_volume",
)


class EquityDataUnavailable(RuntimeError):
    """No live equity data and no fallback recent enough to stand in for it."""


@dataclass(frozen=True)
class SectorStat:
    """One sector's share of the market and how it moved."""

    sector: str
    count: int
    market_cap: float
    weight: float
    """Share of total listed market capitalisation, as a fraction."""
    change_pct: Optional[float]
    """Capitalisation-weighted move, as a fraction."""
    advancers: int
    decliners: int


@dataclass(frozen=True)
class EquityBoard:
    equities: list[EquityRow]
    indices: list[IndexRow]
    stale: bool
    as_of: str


def _breadth_bucket(row: EquityRow) -> int:
    """+1 up, -1 down, 0 unchanged or unknown."""
    if row.change_pct is None:
        return 0
    if row.change_pct > 0:
        return 1
    if row.change_pct < 0:
        return -1
    return 0


def sector_performance(equities: list[EquityRow]) -> list[SectorStat]:
    """
    Capitalisation-weighted move per sector, largest sector first.

    Weighted rather than averaged: an equal-weighted sector move is dominated by
    its smallest, most volatile members, and a reader looking at a heatmap is
    asking where the money went rather than where the percentages went.

    A company with no capitalisation figure still counts toward the sector's
    advancer/decliner tally but contributes no weight — it is a real listing
    whose size is unknown, and dropping it would understate how broad a move was.
    """
    buckets: dict[str, list[EquityRow]] = {}
    for row in equities:
        if not row.sector:
            continue
        buckets.setdefault(row.sector, []).append(row)

    total_cap = sum(row.market_cap for row in equities if row.market_cap and row.market_cap > 0)

    stats: list[SectorStat] = []
    for sector, rows in buckets.items():
        cap = sum(row.market_cap for row in rows if row.market_cap and row.market_cap > 0)
        weighted = [
            (row.market_cap, row.change_pct)
            for row in rows
            if row.market_cap and row.market_cap > 0 and row.change_pct is not None
        ]
        weight_sum = sum(cap_value for cap_value, _ in weighted)
        change = (
            sum(cap_value * move for cap_value, move in weighted) / weight_sum
            if weight_sum > 0
            else None
        )
        buckets_by_direction = [_breadth_bucket(row) for row in rows]
        stats.append(
            SectorStat(
                sector=sector,
                count=len(rows),
                market_cap=cap,
                weight=(cap / total_cap) if total_cap > 0 else 0.0,
                change_pct=change,
                advancers=sum(1 for b in buckets_by_direction if b > 0),
                decliners=sum(1 for b in buckets_by_direction if b < 0),
            )
        )

    stats.sort(key=lambda stat: stat.market_cap, reverse=True)
    return stats


def screen_equities(
    equities: list[EquityRow],
    *,
    index: Optional[str] = None,
    sector: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = "market_cap",
    descending: bool = True,
    limit: Optional[int] = None,
) -> list[EquityRow]:
    """
    Filter and rank the listing.

    Rows with no value for the sorted field sort last in either direction. That
    is the one rule worth stating: ascending by P/E should surface the cheapest
    company, not the eighty that have no earnings and therefore no ratio.
    """
    if sort_by not in SORTABLE_FIELDS:
        raise ValueError(f"sort_by must be one of {SORTABLE_FIELDS}, got {sort_by!r}")

    rows = equities
    if index:
        wanted = index.strip().upper()
        rows = [row for row in rows if wanted in row.indices]
    if sector:
        rows = [row for row in rows if row.sector == sector]
    if search:
        needle = search.strip()
        if needle:
            rows = [
                row for row in rows if contains(row.ticker, needle) or contains(row.name, needle)
            ]

    def key(row: EquityRow):
        value = getattr(row, sort_by)
        # Missing last in both directions, so the sign flip below cannot drag
        # unpriced rows to the top of an ascending sort.
        if value is None:
            return (1, 0.0)
        return (0, -value if descending else value)

    rows = sorted(rows, key=key)
    return rows[:limit] if limit is not None else rows


def distinct_sectors(equities: list[EquityRow]) -> list[str]:
    return sorted({row.sector for row in equities if row.sector})


async def fetch_equity_board() -> EquityBoard:
    """
    The whole listing plus the headline indices.

    Raises `EquityDataUnavailable` rather than returning an empty board: a
    screener showing no companies reads as "your filters matched nothing".
    """
    cached = bist_cache.get("equity_board")
    if cached is not None:
        return cached

    try:
        equities = await fetch_equities()
    except TradingViewUnavailable as e:
        stale = bist_cache.get_with_fallback("equity_board", max_age=MAX_STALE_BOARD)
        if stale is not None:
            logger.warning("BIST equity board unavailable, serving stale: %s", e)
            return EquityBoard(
                equities=stale.equities, indices=stale.indices, stale=True, as_of=stale.as_of
            )
        raise EquityDataUnavailable(f"BIST equity board unavailable: {e}") from e

    if not equities:
        stale = bist_cache.get_with_fallback("equity_board", max_age=MAX_STALE_BOARD)
        if stale is not None:
            return EquityBoard(
                equities=stale.equities, indices=stale.indices, stale=True, as_of=stale.as_of
            )
        raise EquityDataUnavailable("BIST returned no listings")

    # Index values are a separate request and a lesser loss: the board is still
    # a board without the XU100 strip across the top of it.
    try:
        indices = await fetch_indices()
    except TradingViewUnavailable as e:
        logger.info("BIST indices unavailable, board continues without them: %s", e)
        indices = []

    board = EquityBoard(
        equities=equities,
        indices=indices,
        stale=False,
        as_of=datetime.now(UTC).isoformat(),
    )
    bist_cache.set("equity_board", board, TTL_BOARD)
    return board


async def fetch_equity(ticker: str) -> EquityRow:
    """
    One company.

    Raises `EquityDataUnavailable` when the ticker is not listed. A 404 rather
    than an empty page, the same rule `/api/price` follows — an unlisted code in
    a trading terminal must not render as a company worth nothing.
    """
    wanted = ticker.strip().upper()
    if not wanted:
        raise ValueError("ticker is required")
    # `BIST:THYAO` and `THYAO` both resolve; the venue prefix is how symbols
    # travel elsewhere in this codebase, so accepting it costs one line.
    if ":" in wanted:
        wanted = wanted.rsplit(":", 1)[1]

    board = await fetch_equity_board()
    row = next((r for r in board.equities if r.ticker == wanted), None)
    if row is None:
        raise EquityDataUnavailable(f"{wanted} is not listed on Borsa İstanbul")
    return row


async def fetch_candles(ticker: str, *, range_: str = "1y", interval: str = "1d") -> list[dict]:
    """
    Daily bars for one company, from Yahoo's chart endpoint.

    A second upstream, because the scanner serves a snapshot rather than a
    series. Yahoo carries Borsa İstanbul under a `.IS` suffix — `THYAO.IS` —
    which is a different convention from the `BIST:` prefix this codebase uses
    internally, so the translation happens here at the boundary and nowhere else.

    Returns an empty list rather than raising when Yahoo has nothing: the
    company page still has a quote, fundamentals and filings to show, and a
    missing chart should not take the rest of it down.
    """
    wanted = ticker.strip().upper()
    if ":" in wanted:
        wanted = wanted.rsplit(":", 1)[1]
    if not wanted:
        raise ValueError("ticker is required")

    key = f"candles:{wanted}:{range_}:{interval}"
    cached = bist_cache.get(key)
    if cached is not None:
        return cached

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{wanted}.IS"
    try:
        body = await get_json_impersonated(
            url, params={"range": range_, "interval": interval}, timeout=20.0
        )
    except Exception as e:  # noqa: BLE001
        logger.info("no chart for %s: %s", wanted, e)
        stale = bist_cache.get_with_fallback(key, max_age=MAX_STALE_BOARD)
        return stale if stale is not None else []

    try:
        result = body["chart"]["result"][0]
        stamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError):
        return []

    candles: list[dict] = []
    for position, stamp in enumerate(stamps):
        close = quote.get("close", [None] * len(stamps))[position]
        if close is None:
            # Yahoo pads holidays with nulls. Carrying them through would draw a
            # chart that dips to zero on every public holiday.
            continue
        candles.append(
            {
                "date": datetime.fromtimestamp(stamp, tz=UTC).date().isoformat(),
                "open": quote.get("open", [None] * len(stamps))[position],
                "high": quote.get("high", [None] * len(stamps))[position],
                "low": quote.get("low", [None] * len(stamps))[position],
                "close": close,
                "volume": quote.get("volume", [None] * len(stamps))[position],
            }
        )

    if candles:
        bist_cache.set(key, candles, TTL_CANDLES)
    return candles
