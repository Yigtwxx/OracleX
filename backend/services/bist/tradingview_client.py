"""
Raw access to TradingView's public market scanner, for Borsa İstanbul.

Shape adaptation only. One POST returns every listed BIST stock with price,
volume, market capitalisation, the valuation multiples and the index
memberships — which is why this is the equity source rather than the four
separate ones the plan originally called for.

**Why not KAP or Borsa İstanbul directly.** KAP's company list moved behind a
Next.js app whose API answers an empty array to every request an ordinary client
can construct, and borsaistanbul.com publishes constituents as dated files
rather than as a queryable surface. Both are the right source for *filings*, and
`kap_service` uses KAP for exactly that; neither is a workable source for a
quote board.

**Prices are delayed.** TradingView serves BIST at the exchange's own delay —
at least fifteen minutes. Everything built on this module has to say so, which
is what the `delayed` flag on the board is for.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any, Optional, Sequence

from services.http_client import post_json

logger = logging.getLogger(__name__)

SCANNER_URL = "https://scanner.tradingview.com/turkey/scan"

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}

# The venue prefix Borsa İstanbul symbols carry everywhere in this codebase.
# TradingView returns `BIST:THYAO` in its `s` field, which is already the shape
# `symbol_detection_service` uses for NASDAQ and Binance — so it passes through
# unchanged rather than being reassembled.
VENUE = "BIST"

# Ordered, because the scanner answers with a positional array rather than an
# object. The index of a name in this tuple is where its value lands in `d`.
_STOCK_COLUMNS: tuple[str, ...] = (
    "name",
    "description",
    "close",
    "change",
    "change_abs",
    "volume",
    "Value.Traded",
    "market_cap_basic",
    "price_earnings_ttm",
    "price_book_fq",
    "enterprise_value_ebitda_ttm",
    "float_shares_percent_current",
    "sector.tr",
    "indexes",
    "Perf.YTD",
    "Perf.Y",
    # The shorter horizons and the two moving averages feed the sentiment
    # index's slower components: a session's advance-decline line resets every
    # morning, and an index built only from it swung thirty points a day.
    "Perf.W",
    "Perf.1M",
    "SMA50",
    "SMA200",
    "price_52_week_high",
    "price_52_week_low",
    "RSI",
    # Both relative-volume columns, because they answer different questions and
    # only one of them is right during the session. `relative_volume_10d_calc`
    # divides today's volume *so far* by a full day's average, so at 10:30 every
    # listing reads a tenth of normal and the crowding score — which needs
    # turnover at least at par — scores five names out of six hundred. The
    # `_intraday` column compares cumulative volume with the average cumulative
    # volume at the same time of day, which is what "unusual volume" means at
    # any hour; it converges on the plain figure at the close.
    "relative_volume_intraday|5",
    "relative_volume_10d_calc",
    "beta_1_year",
    # Calendar. Unix seconds, and sparsely populated — TradingView carries an
    # upcoming earnings date for roughly one listing in ten and an upcoming
    # ex-dividend date for fewer. That is the calendar actually being sparse
    # rather than the field being unreliable: most companies have not announced.
    "earnings_release_next_date",
    "earnings_release_date",
    "dividend_ex_date_upcoming",
    "dividend_amount_recent",
    "dividends_yield",
    # Fundamentals and the analyst consensus, for the Radar. Percentages arrive
    # as percentages (12.66 for a 12.66% ROE) and are turned into fractions like
    # every other ratio in this package; the price targets are lira.
    "industry.tr",
    "return_on_equity",
    "debt_to_equity",
    "total_revenue_yoy_growth_ttm",
    "net_income_yoy_growth_ttm",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "current_ratio",
    # `recommendation_mark` runs 1 (strong buy) to 5 (strong sell) and
    # `recommendation_total` is the number of analysts behind it. Both are
    # sparse outside the XU030.
    "recommendation_mark",
    "recommendation_total",
    "price_target_average",
    "price_target_high",
    "price_target_low",
)

_INDEX_COLUMNS: tuple[str, ...] = (
    "name",
    "description",
    "close",
    "change",
    "change_abs",
    "volume",
    "Perf.YTD",
    "Perf.Y",
)

# The headline indices, verified present in TradingView's Turkish index
# universe. The sector indices (XUSIN, XUTEK, XGIDA…) are deliberately absent:
# the scanner does not carry them, and `equity_service` derives sector
# performance from the constituents instead — which is both available and
# closer to what a heatmap actually wants.
HEADLINE_INDICES: tuple[str, ...] = (
    "XU100",
    "XU030",
    "XU050",
    "XUTUM",
    "XBANK",
    "XKTUM",
    "XK100",
)


class TradingViewUnavailable(RuntimeError):
    """The scanner did not answer, or answered with something unusable."""


@dataclass(frozen=True)
class EquityRow:
    """One listed company, as the scanner describes it."""

    ticker: str
    """Bare code — `THYAO`."""
    symbol: str
    """Venue-qualified — `BIST:THYAO`."""
    name: str
    price: Optional[float]
    change_pct: Optional[float]
    change_abs: Optional[float]
    volume: Optional[float]
    traded_value: Optional[float]
    market_cap: Optional[float]
    pe: Optional[float]
    pb: Optional[float]
    ev_ebitda: Optional[float]
    free_float_pct: Optional[float]
    sector: str
    """Turkish sector label, straight from the scanner."""
    indices: tuple[str, ...] = field(default_factory=tuple)
    """Bare index codes this stock belongs to — `("XU100", "XU030", …)`."""
    perf_ytd: Optional[float] = None
    perf_1y: Optional[float] = None
    perf_1w: Optional[float] = None
    perf_1m: Optional[float] = None
    sma50: Optional[float] = None
    """Fifty-day simple moving average of the close, in price units."""
    sma200: Optional[float] = None
    week52_high: Optional[float] = None
    week52_low: Optional[float] = None
    rsi: Optional[float] = None
    relative_volume: Optional[float] = None
    beta: Optional[float] = None
    next_earnings: Optional[str] = None
    """ISO date of the next scheduled results announcement."""
    last_earnings: Optional[str] = None
    ex_dividend_date: Optional[str] = None
    dividend_amount: Optional[float] = None
    dividend_yield: Optional[float] = None
    industry: str = ""
    """Turkish industry label — finer than `sector`: `Bölgesel bankalar`."""
    roe: Optional[float] = None
    """Return on equity, trailing, as a fraction."""
    debt_to_equity: Optional[float] = None
    revenue_growth: Optional[float] = None
    """Trailing-twelve-month revenue against the year before, nominal fraction."""
    net_income_growth: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    current_ratio: Optional[float] = None
    analyst_mark: Optional[float] = None
    """Consensus rating, 1 = strong buy … 5 = strong sell."""
    analyst_count: Optional[int] = None
    target_avg: Optional[float] = None
    target_high: Optional[float] = None
    target_low: Optional[float] = None


@dataclass(frozen=True)
class IndexRow:
    code: str
    name: str
    value: Optional[float]
    change_pct: Optional[float]
    change_abs: Optional[float]
    volume: Optional[float]
    perf_ytd: Optional[float]
    perf_1y: Optional[float]


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    # NaN survives float() and then poisons every comparison it touches —
    # sorting a column containing one produces an order that depends on the
    # input order rather than on the values.
    return None if result != result else result


def _count(value: Any) -> Optional[int]:
    """A whole number, or None. Zero analysts is a real answer and is kept."""
    number = _number(value)
    return None if number is None or number < 0 else int(number)


def _pct(value: Any) -> Optional[float]:
    """A percentage from the scanner as a fraction."""
    number = _number(value)
    return None if number is None else number / 100


def _epoch_date(value: Any) -> Optional[str]:
    """A unix timestamp from the scanner as an ISO date, or None."""
    seconds = _number(value)
    if seconds is None or seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=UTC).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _index_codes(cell: Any) -> tuple[str, ...]:
    """
    Bare BIST index codes from the scanner's `indexes` cell.

    The cell is a list of `{"name": …, "proname": "BIST:XU100"}`. Foreign
    indices appear in it too — STOXX carries several BIST names — and they are
    dropped here rather than downstream, because "is this in the XU100" is the
    only question this field is ever asked.
    """
    if not isinstance(cell, list):
        return ()
    codes: list[str] = []
    for entry in cell:
        proname = entry.get("proname") if isinstance(entry, dict) else None
        if not isinstance(proname, str) or not proname.startswith(f"{VENUE}:"):
            continue
        codes.append(proname.split(":", 1)[1])
    return tuple(codes)


def _relative_volume(cell: dict) -> Optional[float]:
    """
    Turnover against the usual turnover *at this time of day*.

    The time-of-day column is preferred and the full-day one is the fallback
    rather than the other way round: at the close the two agree, and during the
    session only the first says anything about whether a name is busy. The
    fallback is there because the intraday column has only been observed with
    the market open; if it comes back empty outside the session, the full-day
    figure is the right answer at that hour anyway.
    """
    at_time = _number(cell.get("relative_volume_intraday|5"))
    if at_time is not None:
        return at_time
    return _number(cell.get("relative_volume_10d_calc"))


async def _scan(payload: dict) -> list[dict]:
    try:
        body = await post_json(SCANNER_URL, payload=payload, headers=_HEADERS, timeout=30.0)
    except Exception as e:  # noqa: BLE001 — transport, status and decode mean the same thing here
        raise TradingViewUnavailable(f"scanner request failed: {e}") from e

    if not isinstance(body, dict):
        raise TradingViewUnavailable("scanner returned an unexpected body")
    rows = body.get("data")
    if not isinstance(rows, list):
        raise TradingViewUnavailable("scanner returned no data array")
    return rows


def _cells(row: dict, columns: Sequence[str]) -> dict[str, Any]:
    """Positional response array back into a name → value mapping."""
    values = row.get("d")
    if not isinstance(values, list):
        return {}
    return dict(zip(columns, values))


async def fetch_equities() -> list[EquityRow]:
    """Every stock listed on Borsa İstanbul, with its fundamentals."""
    payload = {
        "filter": [{"left": "type", "operation": "equal", "right": "stock"}],
        "options": {"lang": "tr"},
        "markets": ["turkey"],
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": list(_STOCK_COLUMNS),
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        # Well above the ~620 listings. A hard cap rather than pagination: the
        # whole board is one request, and a partial one would silently drop the
        # small caps off the end of every screen.
        "range": [0, 2000],
    }
    rows = await _scan(payload)

    equities: list[EquityRow] = []
    for row in rows:
        cell = _cells(row, _STOCK_COLUMNS)
        ticker = (cell.get("name") or "").strip().upper()
        if not ticker:
            continue
        equities.append(
            EquityRow(
                ticker=ticker,
                symbol=f"{VENUE}:{ticker}",
                name=(cell.get("description") or "").strip(),
                price=_number(cell.get("close")),
                change_pct=_pct(cell.get("change")),
                change_abs=_number(cell.get("change_abs")),
                volume=_number(cell.get("volume")),
                traded_value=_number(cell.get("Value.Traded")),
                market_cap=_number(cell.get("market_cap_basic")),
                pe=_number(cell.get("price_earnings_ttm")),
                pb=_number(cell.get("price_book_fq")),
                ev_ebitda=_number(cell.get("enterprise_value_ebitda_ttm")),
                free_float_pct=_pct(cell.get("float_shares_percent_current")),
                sector=(cell.get("sector.tr") or "").strip(),
                indices=_index_codes(cell.get("indexes")),
                perf_ytd=_pct(cell.get("Perf.YTD")),
                perf_1y=_pct(cell.get("Perf.Y")),
                perf_1w=_pct(cell.get("Perf.W")),
                perf_1m=_pct(cell.get("Perf.1M")),
                sma50=_number(cell.get("SMA50")),
                sma200=_number(cell.get("SMA200")),
                week52_high=_number(cell.get("price_52_week_high")),
                week52_low=_number(cell.get("price_52_week_low")),
                rsi=_number(cell.get("RSI")),
                relative_volume=_relative_volume(cell),
                beta=_number(cell.get("beta_1_year")),
                next_earnings=_epoch_date(cell.get("earnings_release_next_date")),
                last_earnings=_epoch_date(cell.get("earnings_release_date")),
                ex_dividend_date=_epoch_date(cell.get("dividend_ex_date_upcoming")),
                dividend_amount=_number(cell.get("dividend_amount_recent")),
                dividend_yield=_pct(cell.get("dividends_yield")),
                industry=(cell.get("industry.tr") or "").strip(),
                roe=_pct(cell.get("return_on_equity")),
                debt_to_equity=_number(cell.get("debt_to_equity")),
                revenue_growth=_pct(cell.get("total_revenue_yoy_growth_ttm")),
                net_income_growth=_pct(cell.get("net_income_yoy_growth_ttm")),
                gross_margin=_pct(cell.get("gross_margin")),
                operating_margin=_pct(cell.get("operating_margin")),
                net_margin=_pct(cell.get("net_margin")),
                current_ratio=_number(cell.get("current_ratio")),
                analyst_mark=_number(cell.get("recommendation_mark")),
                analyst_count=_count(cell.get("recommendation_total")),
                target_avg=_number(cell.get("price_target_average")),
                target_high=_number(cell.get("price_target_high")),
                target_low=_number(cell.get("price_target_low")),
            )
        )
    return equities


async def fetch_indices(codes: Sequence[str] = HEADLINE_INDICES) -> list[IndexRow]:
    """The headline BIST indices, by explicit ticker."""
    payload = {
        "symbols": {
            "tickers": [f"{VENUE}:{code}" for code in codes],
            "query": {"types": ["index"]},
        },
        "columns": list(_INDEX_COLUMNS),
        "options": {"lang": "tr"},
    }
    rows = await _scan(payload)

    indices: list[IndexRow] = []
    for row in rows:
        cell = _cells(row, _INDEX_COLUMNS)
        code = (cell.get("name") or "").strip().upper()
        if not code:
            continue
        indices.append(
            IndexRow(
                code=code,
                name=(cell.get("description") or "").strip(),
                value=_number(cell.get("close")),
                change_pct=_pct(cell.get("change")),
                change_abs=_number(cell.get("change_abs")),
                volume=_number(cell.get("volume")),
                perf_ytd=_pct(cell.get("Perf.YTD")),
                perf_1y=_pct(cell.get("Perf.Y")),
            )
        )
    return indices
