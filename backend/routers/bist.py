"""
BIST Router

Borsa İstanbul, TEFAS funds, KAP disclosures and the Turkish macro series —
everything under `/api/bist`.

Validates, calls one service, shapes the response. No upstream call happens
here.

Two conventions this surface holds to, both inherited from the rest of the API:

* **It declines rather than guesses.** A fund code TEFAS does not know is a 404,
  not an empty chart. A source that is down is a 503, not a board of zeros.
* **Nominal figures never travel alone.** Anything quoted in lira over a window
  long enough for inflation to matter carries its real counterpart, or says why
  it could not.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from dependencies.auth import AuthUser, get_optional_user

from services import analysis_jobs
from services.analysis_jobs import KIND_RADAR

from services.bist import fund_allocation, holdings_service
from services.bist.brief_note import note_for_fund, note_for_stock
from services.bist.market_note import (
    build_funds_market_facts,
    build_market_facts,
    funds_market_note,
    market_note,
)
from services.bist.night_shift_service import fetch_night_shift_index
from services.bist.sentiment_service import compute_dominance, compute_sentiment
from services.bist.fund_service import (
    MAX_COMPARE,
    SORTABLE_PERIODS,
    FundBoard,
    FundDataUnavailable,
    FundDetail,
    compare_funds,
    distinct_umbrellas,
    fetch_fund_board,
    fetch_fund_detail,
    screen_funds,
)
from services.bist.equity_service import (
    DELAY_MINUTES,
    SORTABLE_FIELDS,
    EquityDataUnavailable,
    EquityRow,
    distinct_sectors,
    fetch_candles,
    fetch_equity,
    fetch_equity_board,
    screen_equities,
    sector_performance,
)
from services.bist.tradingview_client import HEADLINE_INDICES, VENUE
from services.bist.macro_service import (
    WINDOW_MONTHS,
    MacroSnapshot,
    MacroUnavailable,
    deflator_for_window,
    fetch_cpi_series,
    fetch_macro_snapshot,
    fetch_usdtry_series,
)
from services.bist.calendar_service import CalendarEvent, build_calendar, group_by_day
from services.bist.financials_note import note_for_financials
from services.bist.halkarz_client import HalkarzUnavailable
from services.bist.ipo_note import ipo_facts, note_for_ipos
from services.bist.ipo_service import build_ipos
from services.bist.financials_service import (
    MAX_QUARTERS,
    FinancialsUnavailable,
    build_financials,
)
from services.bist.kap_materiality import classify
from services.bist.kap_note import note_for_disclosure
from services.bist.kap_service import (
    SIGNAL_CATEGORIES,
    Disclosure,
    KapUnavailable,
    fetch_disclosure,
    fetch_tape,
    filter_restrictions,
    is_rate_limited,
)
from services.bist.heatmap_service import (
    HeatmapBoard,
    HeatmapSectorGroup,
    HeatmapTile,
    build_heatmap,
)
from services.bist.macro_note import build_macro_facts, macro_note
from services.bist.positioning_note import build_positioning_facts, positioning_note
from services.bist.positioning_service import (
    PositioningRow,
    build_positioning,
    futures_positioning,
)
from services.bist.real_return import enrich_returns, summarise_real_losses
from services.bist.viop_map_note import build_viop_map_facts, viop_map_note
from services.bist.viop_note import build_viop_facts, viop_note
from services.bist.viop_service import ViopContract, ViopUnavailable, fetch_viop_board, summarise
from services.bist.viop_bulletin import BulletinUnavailable, get_history as get_bulletin_history
from services.bist.takasbank_psr import PSR_SOURCE_HOST, PsrUnavailable, fetch_psr
from services.bist.viop_margin_map import MIN_OPEN_INTEREST_CONTRACTS, build_margin_map
from services.bist.spot_volume_profile import fetch_profile
from services.bist.tefas_client import FUND_TYPES, FundRow
from services.bist.radar import scan as radar_scan
from services.bist.radar.profiles import PROFILES as RADAR_PROFILES

router = APIRouter(prefix="/api/bist", tags=["bist"])

logger = logging.getLogger(__name__)


def _unavailable(error: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=str(error))


def _allocation_detail(breakdown: Optional[fund_allocation.AllocationBreakdown]) -> Optional[dict]:
    """One fund's split, spelled out — bucket, weight and the lines under it."""
    if breakdown is None:
        return None
    return {
        "as_of": breakdown.day.isoformat(),
        # The sum of what TEFAS actually reported, never scaled to 1. The card
        # prints it when it misses, rather than stretching the bar over the gap.
        "total": breakdown.total,
        "buckets": [
            {
                "key": bucket.key,
                "label": bucket.label,
                "weight": bucket.weight,
                "lines": [
                    {"code": line.code, "label": line.label, "weight": line.weight}
                    for line in bucket.lines
                ],
            }
            for bucket in breakdown.buckets
        ],
    }


def _fund_row(
    row: FundRow, enriched: Optional[dict] = None, allocation: Optional[dict] = None
) -> dict:
    return {
        "code": row.code,
        "title": row.title,
        "umbrella": row.umbrella,
        "tradable": row.tradable,
        "risk_value": row.risk_value,
        "returns": row.returns,
        # The same nominal figures restated against inflation and the dollar.
        # Kept beside `returns` rather than replacing it: the nominal number is
        # what the reader will have seen on every other site, and hiding it
        # would make this board look like it disagreed with them rather than
        # like it was answering a different question.
        "framed_returns": enriched or {},
        # Sparse, unlabelled and weight-only: an absent bucket means the fund
        # does not hold it, and the key-to-label vocabulary is declared once on
        # the response instead of repeated for every fund on the board.
        # None is not an empty holding — it is "TEFAS published nothing here".
        "allocation": allocation,
    }


def _board_meta(board: FundBoard) -> dict:
    return {
        "fund_type": board.fund_type,
        "fund_type_label": board.fund_type_label,
        "risk_free_rate": board.risk_free_rate,
        # Named so the frontend can label the ratio honestly. A Sharpe computed
        # against an estimate is a different claim from one computed against the
        # published policy rate, and the page should not pretend otherwise.
        "risk_free_source": "money_market_median" if board.risk_free_rate is not None else None,
        "stale": board.stale,
        "total": len(board.funds),
        # None here and a null row `allocation` are different failures: this one
        # means the column could not be built at all, that one means TEFAS
        # published nothing for one fund. The frontend words them differently.
        "allocation": (
            {
                "as_of": board.allocations.day.isoformat(),
                "stale": board.allocations.stale,
                "reported": len(board.allocations.breakdowns),
                "buckets": fund_allocation.bucket_vocabulary(),
            }
            if board.allocations
            else None
        ),
    }


@router.get("/funds")
async def get_funds(
    fund_type: str = Query("YAT", description=f"One of {FUND_TYPES}"),
    umbrella: Optional[str] = Query(None, description="Şemsiye fon type, exact match"),
    search: Optional[str] = Query(None, description="Substring of the code or title"),
    tradable_only: bool = Query(True),
    max_risk: Optional[int] = Query(None, ge=1, le=7),
    sort_by: str = Query("1y", description=f"One of {SORTABLE_PERIODS}"),
    limit: int = Query(100, ge=1, le=2000),
):
    """
    The fund screener.

    Returns TEFAS's own published period returns rather than ones derived from
    the price series: the price endpoint is per-fund, so deriving them for a
    thousand funds would be a thousand round trips to reach the same figures.
    Risk statistics are on the detail endpoint, where a reader has asked for one
    fund.
    """
    try:
        board = await fetch_fund_board(fund_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FundDataUnavailable as e:
        raise _unavailable(e) from e

    try:
        rows = screen_funds(
            board.funds,
            umbrella=umbrella,
            search=search,
            tradable_only=tradable_only,
            max_risk=max_risk,
            sort_by=sort_by,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    deflators, snapshot, fx = await _real_return_context(tuple(WINDOW_MONTHS))

    # Computed across every fund on the board, not across the page the caller
    # asked for: "a third of funds lost purchasing power" is a fact about the
    # market, and slicing it to the top fifty by return would invert it.
    all_framed = [
        (
            fund.code,
            enrich_returns(
                fund.returns, deflators=deflators, fx_series=fx, window_months=WINDOW_MONTHS
            ),
        )
        for fund in board.funds
    ]
    losses = summarise_real_losses(all_framed, "1y")

    return {
        **_board_meta(board),
        "umbrellas": distinct_umbrellas(board.funds),
        "matched": len(rows),
        "real_return": _real_return_meta(snapshot, deflators),
        "real_loss": {
            "window": losses.window,
            "measured": losses.measured,
            "count": losses.count,
            "example": (
                {
                    "code": losses.example_key,
                    "nominal": losses.example_nominal,
                    "real": losses.example_real,
                    "title": next(
                        (f.title for f in board.funds if f.code == losses.example_key), ""
                    ),
                }
                if losses.example_key
                else None
            ),
        },
        "funds": [
            _fund_row(
                row,
                enrich_returns(
                    row.returns,
                    deflators=deflators,
                    fx_series=fx,
                    window_months=WINDOW_MONTHS,
                ),
                _row_allocation(board, row.code),
            )
            for row in rows
        ],
    }


def _row_allocation(board: FundBoard, code: str) -> Optional[dict]:
    if board.allocations is None:
        return None
    breakdown = board.allocations.breakdowns.get(code)
    if breakdown is None:
        return None
    return fund_allocation.bucket_weights(breakdown)


def _detail(detail: FundDetail, framed: Optional[dict] = None) -> dict:
    metrics = detail.metrics
    return {
        "code": detail.code,
        "title": detail.title,
        "umbrella": detail.umbrella,
        "risk_value": detail.risk_value,
        "tradable": detail.tradable,
        "category_rank": detail.category_rank,
        "category_size": detail.category_size,
        "months": detail.months,
        "published_returns": detail.published_returns,
        "framed_returns": framed or {},
        "risk_free_rate": detail.risk_free_rate,
        "allocation": _allocation_detail(detail.allocation),
        "series": detail.series,
        "metrics": {
            "observations": metrics.observations,
            "total_return": metrics.total_return,
            "annualised_return": metrics.annualised_return,
            "volatility": metrics.volatility,
            "sharpe": metrics.sharpe,
            "sortino": metrics.sortino,
            "calmar": metrics.calmar,
            "max_drawdown": metrics.max_drawdown,
            "recovery_days": metrics.recovery_days,
        },
    }


@router.get("/funds/compare")
async def get_fund_comparison(
    codes: str = Query(..., description=f"Comma-separated fund codes, at most {MAX_COMPARE}"),
    months: int = Query(12, ge=1, le=60),
):
    """
    Several funds on one axis.

    Declared before `/funds/{code}` on purpose: FastAPI matches in declaration
    order, and the path parameter would otherwise swallow `compare` and go
    looking for a fund by that name.
    """
    try:
        details = await compare_funds(codes.split(","), months)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FundDataUnavailable as e:
        raise _unavailable(e) from e

    resolved = [_detail(detail) for detail in details]
    requested = [code.strip().upper() for code in codes.split(",") if code.strip()]
    return {
        "months": months,
        "requested": requested,
        # Named rather than silently omitted: a fund missing from a comparison
        # chart is otherwise indistinguishable from one that flatlined.
        "unresolved": [code for code in requested if code not in {d["code"] for d in resolved}],
        "funds": resolved,
    }


@router.get("/funds/market-note")
async def get_funds_market_note(
    fund_type: str = Query("YAT", description=f"One of {FUND_TYPES}"),
    user: AuthUser | None = Depends(get_optional_user),
):
    """
    What this whole fund universe looks like, narrated.

    Declared above `/funds/{code}` deliberately: FastAPI matches in declaration
    order, and behind it this path resolves as a fund whose code is
    "market-note".

    Keyed on the fund type rather than on the caller's filters. The medians and
    the dispersion are computed across every fund of the type, because "half the
    board lost purchasing power" is a fact about the market and the same count
    over the page a reader happens to be looking at would invert it.

    Never 503s. The screener beside this is already reporting whatever went
    wrong from its own query, and a second error for a missing paragraph would
    be reporting the same outage twice.
    """
    facts = await build_funds_market_facts(fund_type)
    return {"facts": facts, "note": await funds_market_note(facts, user.id if user else None)}


@router.get("/funds/{code}")
async def get_fund(
    code: str,
    months: int = Query(12, ge=1, le=60),
    user: AuthUser | None = Depends(get_optional_user),
):
    """One fund: its net asset value history and the statistics derived from it."""
    try:
        detail = await fetch_fund_detail(code, months)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FundDataUnavailable as e:
        # 404 rather than 503: the common cause is a code that does not exist,
        # and answering "temporarily unavailable" would send a reader back to
        # retry a fund that is never going to resolve.
        raise HTTPException(status_code=404, detail=str(e)) from e

    deflators, snapshot, fx = await _real_return_context(tuple(WINDOW_MONTHS))
    framed = enrich_returns(
        detail.published_returns,
        deflators=deflators,
        fx_series=fx,
        window_months=WINDOW_MONTHS,
    )
    payload = {
        **_detail(detail, framed),
        "real_return": _real_return_meta(snapshot, deflators),
    }
    payload["ai_note"] = await note_for_fund(payload, user.id if user else None)
    return payload


@router.get("/funds/{code}/holdings")
async def get_fund_holdings(
    code: str,
    fund_type: str = Query("YAT", description=f"One of {FUND_TYPES}"),
):
    """
    Which companies the fund actually owns, from its monthly KAP filing.

    A separate route rather than a field on `/funds/{code}`, because the two
    have nothing in common but the fund. This one costs up to four upstream
    calls and a PDF parse on a cold cache, against a source that publishes once
    a month; the detail page must not wait on it to draw its chart.

    Always 200. An absent book is described by `reason` rather than by a status
    code: "no report filed yet", "the fund holds no equity" and "this filing's
    layout could not be read" are three different sentences, and a 404 would say
    the same wrong thing for all three.
    """
    try:
        outcome = await holdings_service.fetch_fund_holdings(code, fund_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    book = outcome.holdings
    return {
        "code": code.strip().upper(),
        "reason": outcome.reason,
        "stale": outcome.stale,
        "as_of": (
            {
                "year": book.year,
                "period": book.period,
                "published": book.published.isoformat() if book.published else None,
                # KAP's own flag. Worth surfacing: a late filing is the usual
                # reason the newest book on the page is two months old.
                "late": book.late,
            }
            if book
            else None
        ),
        # The filing itself, so a reader can check any figure here against it.
        "source_url": book.disclosure_url if book else None,
        # The equity book in lira, and the denominator every weight below is
        # struck against — these are shares of the fund's stocks, not of the
        # fund. The allocation card says what share of the fund that is.
        "total_value": book.total_value if book else None,
        "holdings": (
            [
                {
                    "ticker": holding.ticker,
                    "label": holding.label,
                    "value": holding.value,
                    "weight": holding.weight,
                }
                for holding in book.holdings
            ]
            if book
            else []
        ),
    }


# ══════════════════════════════════════════════════════════════════════════
# Real-return context
#
# Every board on this realm quotes returns in lira, and a lira return over a
# window long enough to matter is half an answer. These two helpers resolve the
# deflators once per request and hand them to the pure enrichment function, so
# no endpoint reimplements the arithmetic and none of them can quietly skip it.
# ══════════════════════════════════════════════════════════════════════════


async def _real_return_context(
    windows: tuple[str, ...],
) -> tuple[dict, Optional[MacroSnapshot], list[dict]]:
    """
    Deflators and exchange rates for a set of windows.

    Never raises. A macro outage costs the real and dollar columns; it must not
    cost the board they sit beside, which is still a correct nominal answer.
    """
    try:
        snapshot = await fetch_macro_snapshot()
    except MacroUnavailable:
        return dict.fromkeys(windows), None, []

    cpi = await fetch_cpi_series()
    fx = await fetch_usdtry_series("5y")
    deflators = {window: deflator_for_window(window, snapshot, cpi) for window in windows}
    return deflators, snapshot, fx


def _real_return_meta(snapshot: Optional[MacroSnapshot], deflators: dict) -> dict:
    """What the real columns were computed against, stated on the payload."""
    return {
        "inflation_yoy": snapshot.inflation_yoy if snapshot else None,
        "usdtry": snapshot.usdtry if snapshot else None,
        # Named windows rather than a boolean: without an EVDS key only the
        # trailing year can be deflated, and the page has to be able to say
        # which columns are real and which are nominal-only.
        "deflatable_windows": sorted(w for w, value in deflators.items() if value is not None),
    }


# ══════════════════════════════════════════════════════════════════════════
# Equities
# ══════════════════════════════════════════════════════════════════════════

_EQUITY_WINDOWS = ("1y",)


def _equity_row(row: EquityRow, enriched: Optional[dict] = None) -> dict:
    return {
        "ticker": row.ticker,
        "symbol": row.symbol,
        "name": row.name,
        "price": row.price,
        "change_pct": row.change_pct,
        "change_abs": row.change_abs,
        "volume": row.volume,
        "traded_value": row.traded_value,
        "market_cap": row.market_cap,
        "pe": row.pe,
        "pb": row.pb,
        "ev_ebitda": row.ev_ebitda,
        "free_float_pct": row.free_float_pct,
        "sector": row.sector,
        "indices": list(row.indices),
        "perf_ytd": row.perf_ytd,
        "perf_1y": row.perf_1y,
        "week52_high": row.week52_high,
        "week52_low": row.week52_low,
        "rsi": row.rsi,
        "relative_volume": row.relative_volume,
        "beta": row.beta,
        "returns": enriched or {},
    }


@router.get("/stocks")
async def get_stocks(
    index: Optional[str] = Query(None, description="Index code, e.g. XU100"),
    sector: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: str = Query("market_cap", description=f"One of {SORTABLE_FIELDS}"),
    descending: bool = Query(True),
    limit: int = Query(100, ge=1, le=1000),
):
    """The equity screener, with each company's one-year return in three frames."""
    try:
        board = await fetch_equity_board()
    except EquityDataUnavailable as e:
        raise _unavailable(e) from e

    try:
        rows = screen_equities(
            board.equities,
            index=index,
            sector=sector,
            search=search,
            sort_by=sort_by,
            descending=descending,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    deflators, snapshot, fx = await _real_return_context(_EQUITY_WINDOWS)
    payload_rows = [
        _equity_row(
            row,
            enrich_returns(
                {"1y": row.perf_1y},
                deflators=deflators,
                fx_series=fx,
                window_months=WINDOW_MONTHS,
            ),
        )
        for row in rows
    ]

    return {
        "as_of": board.as_of,
        "stale": board.stale,
        "delay_minutes": DELAY_MINUTES,
        "total": len(board.equities),
        "matched": len(rows),
        "sectors": distinct_sectors(board.equities),
        "real_return": _real_return_meta(snapshot, deflators),
        "stocks": payload_rows,
    }


@router.get("/stocks/{ticker}")
async def get_stock(
    ticker: str,
    range_: str = Query("1y", alias="range", description="Yahoo chart range, e.g. 6mo, 1y, 5y"),
    user: AuthUser | None = Depends(get_optional_user),
):
    """One company: quote, fundamentals, index membership and a price history."""
    try:
        row = await fetch_equity(ticker)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except EquityDataUnavailable as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    deflators, snapshot, fx = await _real_return_context(_EQUITY_WINDOWS)
    candles = await fetch_candles(row.ticker, range_=range_)

    payload = {
        "delay_minutes": DELAY_MINUTES,
        **_equity_row(
            row,
            enrich_returns(
                {"1y": row.perf_1y},
                deflators=deflators,
                fx_series=fx,
                window_months=WINDOW_MONTHS,
            ),
        ),
        "real_return": _real_return_meta(snapshot, deflators),
        "candles": candles,
    }
    # Last, and from the finished payload: the note may only speak about figures
    # this response actually carries, and building it from the payload is what
    # makes that structural rather than a convention to remember.
    payload["ai_note"] = await note_for_stock(payload, user.id if user else None)
    return payload


# ══════════════════════════════════════════════════════════════════════════
# Heatmap
# ══════════════════════════════════════════════════════════════════════════


def _heat_tile(tile: HeatmapTile) -> dict:
    return {
        "ticker": tile.ticker,
        "symbol": tile.symbol,
        "name": tile.name,
        "sector": tile.sector,
        "price": tile.price,
        "change_pct": tile.change_pct,
        "traded_value": tile.traded_value,
        "volume": tile.volume,
        "market_cap": tile.market_cap,
        "indices": list(tile.indices),
        "has_futures": tile.has_futures,
        "contracts": tile.contracts,
        "open_interest": tile.open_interest,
        "open_interest_change": tile.open_interest_change,
        "open_interest_change_pct": tile.open_interest_change_pct,
    }


def _heat_sector(group: HeatmapSectorGroup) -> dict:
    return {
        "sector": group.sector,
        "count": group.count,
        "market_cap": group.market_cap,
        "weight": group.weight,
        "change_pct": group.change_pct,
        "advancers": group.advancers,
        "decliners": group.decliners,
    }


@router.get("/heatmap")
async def get_heatmap(
    index: str = Query("XU100", description=f"One of {HEADLINE_INDICES}"),
    limit: int = Query(150, ge=10, le=1000),
):
    """
    One index as a treemap: area is market capitalisation, colour is the
    reader's choice, and VİOP open interest rides along where it exists.

    The futures board is fetched inside its own `try`. It is a scrape of a
    broker page and it will break; when it does the answer is this board minus
    one column, not a 503. `has_futures_data` says which of the two happened, so
    a tile with no open interest can be drawn as unknown rather than as zero.

    Deliberately not `_equity_row`: that payload carries valuation ratios and
    framed real returns, none of which a tile draws, and at a thousand listings
    the unused half is most of the response.
    """
    wanted = index.strip().upper()
    if wanted not in HEADLINE_INDICES:
        raise HTTPException(
            status_code=400,
            detail=f"index must be one of {', '.join(HEADLINE_INDICES)}, got {index!r}",
        )

    try:
        board = await fetch_equity_board()
    except EquityDataUnavailable as e:
        raise _unavailable(e) from e

    futures = None
    try:
        futures = await fetch_viop_board()
    except ViopUnavailable:
        futures = None

    heat: HeatmapBoard = build_heatmap(
        board.equities,
        futures.contracts if futures else None,
        index=wanted,
        limit=limit,
    )

    return {
        "as_of": board.as_of,
        "stale": board.stale,
        "delay_minutes": DELAY_MINUTES,
        "index": heat.index,
        "available_indices": list(HEADLINE_INDICES),
        "total": heat.total,
        "shown": len(heat.tiles),
        "total_market_cap": heat.total_market_cap,
        "has_futures_data": heat.has_futures_data,
        "futures_covered": heat.futures_covered,
        # Separate from the equity board's own staleness: the futures scrape has
        # its own cache and can be replaying a days-old copy while the quotes
        # are current.
        "viop_as_of": futures.as_of if futures else None,
        "viop_stale": futures.stale if futures else None,
        "sectors": [_heat_sector(group) for group in heat.sectors],
        "tiles": [_heat_tile(tile) for tile in heat.tiles],
    }


# ══════════════════════════════════════════════════════════════════════════
# Overview
# ══════════════════════════════════════════════════════════════════════════


@router.get("/overview")
async def get_overview():
    """
    The realm's landing board: indices, sector heat, breadth and the macro strip.

    Sector performance is derived from the constituents rather than read off the
    sector indices — those are published by Borsa İstanbul but absent from the
    quote source, and a capitalisation-weighted roll-up of the members is what a
    heatmap is asking for anyway.
    """
    try:
        board = await fetch_equity_board()
    except EquityDataUnavailable as e:
        raise _unavailable(e) from e

    advancers = sum(1 for row in board.equities if (row.change_pct or 0) > 0)
    decliners = sum(1 for row in board.equities if (row.change_pct or 0) < 0)

    movers = [row for row in board.equities if row.change_pct is not None]
    gainers = sorted(movers, key=lambda r: r.change_pct, reverse=True)[:10]
    losers = sorted(movers, key=lambda r: r.change_pct)[:10]
    by_value = sorted(
        (row for row in board.equities if row.traded_value is not None),
        key=lambda r: r.traded_value,
        reverse=True,
    )[:10]

    snapshot: Optional[MacroSnapshot]
    try:
        snapshot = await fetch_macro_snapshot()
    except MacroUnavailable:
        snapshot = None

    sectors = sector_performance(board.equities)
    sentiment = compute_sentiment(board.equities)
    dominance = compute_dominance(board.equities, sectors)

    return {
        "as_of": board.as_of,
        "stale": board.stale,
        "delay_minutes": DELAY_MINUTES,
        "indices": [
            {
                "code": index.code,
                "name": index.name,
                "value": index.value,
                "change_pct": index.change_pct,
                "change_abs": index.change_abs,
                "perf_ytd": index.perf_ytd,
                "perf_1y": index.perf_1y,
            }
            for index in board.indices
        ],
        "breadth": {
            "advancers": advancers,
            "decliners": decliners,
            "unchanged": len(board.equities) - advancers - decliners,
            "total": len(board.equities),
        },
        "sectors": [
            {
                "sector": stat.sector,
                "count": stat.count,
                "market_cap": stat.market_cap,
                "weight": stat.weight,
                "change_pct": stat.change_pct,
                "advancers": stat.advancers,
                "decliners": stat.decliners,
            }
            for stat in sectors
        ],
        # Both derived from the board above rather than from a feed of their
        # own: the index exists so a reader can check it, and a figure they
        # cannot find on another panel of this realm would defeat that.
        "sentiment": (
            {
                "score": sentiment.score,
                "label": sentiment.label,
                "measured": sentiment.measured,
                "components": [
                    {
                        "key": component.key,
                        "label": component.label,
                        "score": round(component.score, 1),
                        "reading": component.reading,
                        "horizon": component.horizon,
                        "weight": round(component.weight, 4),
                    }
                    for component in sentiment.components
                ],
            }
            if sentiment
            else None
        ),
        "dominance": {
            "sector": dominance.sector,
            "sector_weight": dominance.sector_weight,
            "sector_change_pct": dominance.sector_change_pct,
            "top_ticker": dominance.top_ticker,
            "top_turnover_share": dominance.top_turnover_share,
            "top5_turnover_share": dominance.top5_turnover_share,
        },
        "gainers": [_equity_row(row) for row in gainers],
        "losers": [_equity_row(row) for row in losers],
        "most_traded": [_equity_row(row) for row in by_value],
        "macro": _macro_payload(snapshot) if snapshot else None,
    }


@router.get("/market-note")
async def get_market_note(user: AuthUser | None = Depends(get_optional_user)):
    """
    What the equity board as a whole looks like, narrated.

    Deliberately not scoped to the screener's index or sector filter. The read
    is whether the index and the breadth agree, which is a property of the
    whole board — recomputing it per filter would answer a question nobody on
    the page asked and would multiply the note cache by every combination.

    `facts` carries the deterministic aggregation and renders whether or not
    the sentence arrives, which is what keeps an absent note from looking like
    a broken panel.
    """
    facts = await build_market_facts()
    return {"facts": facts, "note": await market_note(facts, user.id if user else None)}


# ══════════════════════════════════════════════════════════════════════════
# Macro
# ══════════════════════════════════════════════════════════════════════════


def _macro_payload(snapshot: MacroSnapshot) -> dict:
    return {
        "inflation_yoy": snapshot.inflation_yoy,
        "ppi_yoy": snapshot.ppi_yoy,
        "policy_rate": snapshot.policy_rate,
        "cpi_index": snapshot.cpi_index,
        "unemployment": snapshot.unemployment,
        "gdp_yoy": snapshot.gdp_yoy,
        "usdtry": snapshot.usdtry,
        "eurtry": snapshot.eurtry,
        "as_of": snapshot.as_of,
        "stale": snapshot.stale,
        # The real rate a saver actually faces. Stated here rather than left to
        # the page, because subtracting the two is the wrong arithmetic at these
        # levels and the mistake would be invisible.
        "real_policy_rate": (
            (1 + snapshot.policy_rate) / (1 + snapshot.inflation_yoy) - 1
            if snapshot.policy_rate is not None and snapshot.inflation_yoy is not None
            else None
        ),
    }


@router.get("/macro")
async def get_macro(fx_range: str = Query("5y", description="Yahoo range for the USDTRY series")):
    """
    The Turkish macro backdrop, and the deflators the rest of the realm uses.

    `cpi_series` is empty without a `TCMB_EVDS_API_KEY`, which is a supported
    state rather than a failure: the trailing-year deflator comes from the
    published year-on-year rate and needs no key, and every longer window
    reports nominal only rather than approximating.
    """
    try:
        snapshot = await fetch_macro_snapshot()
    except MacroUnavailable as e:
        raise _unavailable(e) from e

    cpi = await fetch_cpi_series()
    fx = await fetch_usdtry_series(fx_range)
    deflators = {window: deflator_for_window(window, snapshot, cpi) for window in WINDOW_MONTHS}

    return {
        **_macro_payload(snapshot),
        "cpi_series": cpi,
        "cpi_source": "evds" if cpi else None,
        "usdtry_series": fx,
        "deflators": deflators,
    }


@router.get("/macro-note")
async def get_macro_note(user: AuthUser | None = Depends(get_optional_user)):
    """
    What the backdrop as a whole says, narrated above the tiles that draw it.

    Its own route rather than a field on `/macro`, for the reason every note
    here is: the snapshot is cached for half an hour and the page refetches it
    on demand, and a paragraph welded to the payload would either be recomputed
    on every refresh or hold the tiles back to the model's cadence.

    `facts` is null when the policy rate or the inflation print could not be
    read — the two figures every other reading hangs off. The client renders
    that as an absent panel rather than as a quiet backdrop.
    """
    facts = await build_macro_facts()
    return {"facts": facts, "note": await macro_note(facts, user.id if user else None)}


# ══════════════════════════════════════════════════════════════════════════
# KAP — the disclosure tape
# ══════════════════════════════════════════════════════════════════════════


def _disclosure(item: Disclosure) -> dict:
    # Classified here rather than in `kap_service` so the tape's cache and its
    # on-disk buffer keep holding exactly what KAP filed. A rule edit then takes
    # effect on the next read instead of waiting out a week-long item cache, and
    # a `Disclosure` restored from disk never carries a stale label.
    materiality = classify(item.title, item.summary, item.category)
    return {
        "index": item.index,
        "title": item.title,
        "company": item.company,
        "ticker": item.ticker,
        "category": item.category,
        "category_label": item.category_label,
        "published_at": item.published_at,
        "summary": item.summary,
        "is_late": item.is_late,
        "url": item.url,
        # What kind of filing this is, computed without a model so it can be on
        # every row. `score` is 1-10 and `band` is derived from it, so the bar
        # and the badge cannot disagree; both are null/"unclassified" for the
        # free-text forms, which the board must draw as an absent reading rather
        # than as a low one.
        "event": materiality.event,
        "event_label": materiality.label,
        "score": materiality.score,
        "band": materiality.band,
    }


@router.get("/kap")
async def get_kap(
    limit: int = Query(40, ge=1, le=200),
    ticker: Optional[str] = Query(None),
    categories: Optional[str] = Query(
        None,
        description=(
            "Comma-separated KAP categories. Omit for the signal set "
            "(ODA, FR, DUY); pass 'all' to include fund housekeeping."
        ),
    ),
):
    """
    The most recent KAP filings.

    The default view excludes `FON` — around nine filings in ten are a portfolio
    manager reporting an overnight repo, forty of them stamped the same minute,
    and they bury the company news a reader came for.
    """
    wanted: Optional[frozenset[str]]
    if categories is None:
        wanted = None
    elif categories.strip().lower() == "all":
        wanted = frozenset()
    else:
        wanted = frozenset(part.strip().upper() for part in categories.split(",") if part.strip())

    try:
        rows = await fetch_tape(limit, ticker=ticker, categories=wanted)
    except KapUnavailable as e:
        raise _unavailable(e) from e

    return {
        "limit": limit,
        "ticker": ticker,
        "categories": sorted(wanted if wanted is not None else SIGNAL_CATEGORIES),
        "count": len(rows),
        # A thin tape has two very different causes — a quiet session, or KAP
        # refusing this address — and the rows alone cannot tell them apart.
        "rate_limited": is_rate_limited(),
        "disclosures": [_disclosure(item) for item in rows],
    }


@router.get("/kap/{index}/note")
async def get_kap_note(index: int, user: AuthUser | None = Depends(get_optional_user)):
    """
    What one filing means, narrated.

    Written on demand rather than with the tape: the board prints six hundred
    rows and a reader opens one, so generating a note per row would run a local
    model continuously to write text nobody asked for.

    The share behind the filing is looked up but never required. Around a fifth
    of the tape carries no ticker — the exchange files its own notices this way
    — and the equity board is a separate upstream that can be down, so a missing
    session is a stated gap in the prompt rather than a failed request.
    """
    disclosure = await fetch_disclosure(index)
    if disclosure is None:
        raise HTTPException(status_code=404, detail=f"KAP disclosure {index} not found")

    equity = None
    if disclosure.ticker:
        try:
            equity = await fetch_equity(disclosure.ticker)
        except (ValueError, EquityDataUnavailable) as e:
            logger.info("No equity row for KAP filing %s (%s): %s", index, disclosure.ticker, e)

    return {
        "disclosure": _disclosure(disclosure),
        "note": await note_for_disclosure(disclosure, equity, user.id if user else None),
    }


@router.get("/restrictions")
async def get_restrictions(limit: int = Query(30, ge=1, le=100)):
    """
    Exchange measures: circuit breakers, gross settlement, short-selling bans.

    Filtered out of the KAP tape rather than fetched separately — Borsa
    İstanbul files these as ordinary disclosures with fixed titles, and there is
    no feed of measures on its own.
    """
    try:
        # Read well past `limit`: measures are a thin slice of an already
        # filtered tape, and a short window returns an empty radar on a quiet
        # morning that is not actually quiet.
        rows = await fetch_tape(limit * 8, categories=frozenset({"ODA", "DUY"}))
    except KapUnavailable as e:
        raise _unavailable(e) from e

    measures = filter_restrictions(rows)[:limit]
    return {
        "count": len(measures),
        "source": "kap",
        "restrictions": [_disclosure(item) for item in measures],
    }


# ══════════════════════════════════════════════════════════════════════════
# VİOP
# ══════════════════════════════════════════════════════════════════════════


def _contract(item: ViopContract) -> dict:
    return {
        "contract": item.contract,
        "underlying": item.underlying,
        "expiry": item.expiry,
        # The label as an ISO day, or null when it could not be read. Parsed
        # once here rather than in the client because two panels order contracts
        # by time, and `31 Ağu 26` sorts alphabetically into nonsense.
        "expiry_date": item.expiry_date,
        # `future`, `call` or `put`. The board is not futures-only: a put on the
        # same underlying and expiry settles at its premium, so a client that
        # drew both on one axis would be reading 0.13 against 13.16 as a term
        # structure rather than as two different instruments.
        "kind": item.kind,
        "physical": item.physical,
        "last": item.last,
        "change_pct": item.change_pct,
        "high": item.high,
        "low": item.low,
        "open_interest": item.open_interest,
        "open_interest_change": item.open_interest_change,
        "settlement": item.settlement,
        "previous_settlement": item.previous_settlement,
        "traded_at": item.traded_at,
    }


@router.get("/viop")
async def get_viop(underlying: Optional[str] = Query(None)):
    """Futures and options, with the open interest behind each contract."""
    try:
        board = await fetch_viop_board()
    except ViopUnavailable as e:
        raise _unavailable(e) from e

    contracts = board.contracts
    if underlying:
        wanted = underlying.strip().upper()
        contracts = [c for c in contracts if c.underlying == wanted]

    return {
        "as_of": board.as_of,
        "stale": board.stale,
        "count": len(contracts),
        "summary": summarise(board.contracts),
        "contracts": [_contract(item) for item in contracts],
    }


@router.get("/viop-note")
async def get_viop_note(user: AuthUser | None = Depends(get_optional_user)):
    """
    What the derivatives board says as a whole, above the panels that draw it.

    Its own endpoint rather than a field on `/viop`, for the reason
    `positioning-note` records: that board is cached for five minutes and the
    page polls it, and a note welded to the payload would either be recomputed
    on every poll or hold the board back to the note's cadence. Split, each
    keeps its own.

    `facts` is null when the board could not be read or came back too thin to
    describe. The client must render that as an absent panel rather than as a
    quiet session — this source is a scrape, and silence here is far more often
    an outage than a market.
    """
    facts = await build_viop_facts()
    return {"facts": facts, "note": await viop_note(facts, user.id if user else None)}


# ══════════════════════════════════════════════════════════════════════════
# VİOP margin scan bands
# ══════════════════════════════════════════════════════════════════════════

# How many daily closes the basis conversion needs behind it. A year covers the
# longest window the map offers with room for holidays.
_SPOT_RANGE = "1y"

# Named because it also decides how many names the picker opens with.
_DEFAULT_UNDERLYINGS = 8


@router.get("/viop-map/underlyings")
async def get_viop_map_underlyings():
    """
    The single-stock futures universe, ranked by the newest session's turnover.

    Derived rather than listed: which names carry futures, and which of them are
    worth opening first, both change without notice, and a hardcoded list is a
    list that silently goes stale. `default` is what the picker starts with.
    """
    try:
        history = await get_bulletin_history()
    except BulletinUnavailable as e:
        raise _unavailable(e) from e

    sessions = history.sessions()
    if not sessions:
        raise _unavailable(BulletinUnavailable("no VİOP bulletin sessions held"))
    latest = sessions[-1]

    totals: dict[str, dict] = {}
    for row in history.rows:
        if row.day != latest:
            continue
        entry = totals.setdefault(
            row.underlying,
            {"ticker": row.underlying, "volume_try": 0.0, "open_interest": 0.0, "expiries": 0},
        )
        entry["volume_try"] += row.volume_try or 0.0
        entry["open_interest"] += row.open_interest
        entry["expiries"] += 1

    ranked = sorted(totals.values(), key=lambda row: row["volume_try"], reverse=True)
    for row in ranked:
        row["thin"] = row["open_interest"] < MIN_OPEN_INTEREST_CONTRACTS

    return {
        "as_of": latest,
        "sessions_held": len(sessions),
        "count": len(ranked),
        "underlyings": ranked,
        "default": [row["ticker"] for row in ranked[:_DEFAULT_UNDERLYINGS]],
    }


@router.get("/viop-map/{ticker}")
async def get_viop_map(
    ticker: str,
    sessions: int = Query(120, ge=30, le=160),
    bins: int = Query(120, ge=40, le=200),
):
    """
    One underlying's positioning, and the scan band each cohort sits behind.

    Two layers on one price axis: the VİOP book, modelled only in its direction,
    and the spot volume profile, modelled not at all. They share a grid because
    they are read against each other.

    The failure modes are deliberately unequal. Without the bulletin there is no
    book and without Takasbank's scan range there is no band, so either missing
    is a 503 — the distance is a published number and this endpoint will not
    substitute one. Losing Yahoo's intraday history costs the second layer only,
    and the map still answers.
    """
    wanted = ticker.strip().upper()
    if not wanted:
        raise HTTPException(status_code=400, detail="ticker is required")

    try:
        history = await get_bulletin_history()
    except BulletinUnavailable as e:
        raise _unavailable(e) from e

    rows = history.for_underlying(wanted)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"{wanted} has no single-stock futures on VİOP",
        )

    held = sorted({row.day for row in rows})
    window = set(held[-sessions:])
    rows = [row for row in rows if row.day in window]

    try:
        psr_snapshot = await fetch_psr()
    except PsrUnavailable as e:
        raise _unavailable(e) from e

    candles = await fetch_candles(wanted, range_=_SPOT_RANGE)
    spot_closes = {
        candle["date"]: candle["close"] for candle in candles if candle.get("close") is not None
    }

    board = build_margin_map(rows, psr_snapshot, spot_closes, underlying=wanted, bins=bins)
    if board is None:
        raise _unavailable(
            PsrUnavailable(f"no scan range published for {wanted}"),
        )

    warnings: list[str] = []
    profile = None
    if not board.thin:
        profile = await fetch_profile(
            wanted,
            price_min=board.price_min,
            bin_size=board.bin_size,
            bins=board.bins,
            first_day=board.sessions[0] if board.sessions else None,
            last_day=board.sessions[-1] if board.sessions else None,
        )
        if profile is None:
            warnings.append("spot_intraday_unavailable")

    # OHLC, not just the close: the field is read against candles the way the
    # crypto board reads its own, and a single line hides the range each session
    # actually swept — which is the mechanism that spends a level.
    spot_bars = {candle["date"]: candle for candle in candles}
    session_rows = []
    for day in board.sessions:
        bar = spot_bars.get(day)
        session_rows.append(
            {
                "day": day,
                "open": bar.get("open") if bar else None,
                "high": bar.get("high") if bar else None,
                "low": bar.get("low") if bar else None,
                "close": bar.get("close") if bar else None,
            }
        )

    return {
        "ticker": wanted,
        "symbol": f"{VENUE}:{wanted}",
        "as_of": board.sessions[-1] if board.sessions else None,
        "stale": history.stale(),
        "delay_minutes": DELAY_MINUTES,
        "thin": board.thin,
        "sessions": session_rows,
        "grid": {
            "price_min": round(board.price_min, 4),
            "price_max": round(board.price_max, 4),
            "bin_size": round(board.bin_size, 6),
            "bins": board.bins,
        },
        # `[column, bin, long, short]` — a snapshot per surviving level per
        # session, which is what makes the map a field rather than a set of
        # bars. Packed positionally: the grid is sent once and there are
        # thousands of these.
        "cells": [
            [cell.column, cell.bin_index, round(cell.long_try), round(cell.short_try)]
            for cell in board.cells
        ],
        "max_value": round(board.max_value),
        "volume_profile": (
            None
            if profile is None
            else {
                "bins": [round(value) for value in profile.bins],
                "total": round(profile.total),
                "bars": profile.bars,
                "interval": profile.interval,
                "from": profile.first_day,
                "to": profile.last_day,
            }
        ),
        "expiries": board.expiries,
        "open_interest": board.open_interest,
        "model": {
            "psr": board.psr,
            "psr_source": PSR_SOURCE_HOST,
            "psr_as_of": psr_snapshot.as_of,
            "psr_run": psr_snapshot.run,
            "psr_file": psr_snapshot.source_file,
            # Takasbank leaves the maintenance level to a General Letter and does
            # not apply it at end of day, so the price a call actually triggers
            # at cannot be computed. Named as absent rather than omitted, so the
            # page can say why it is not drawing one.
            "maintenance_margin_rate": None,
            "maintenance_source": "unpublished",
            "contract_multiplier": board.contract_multiplier,
            "direction_rule": "quadrant",
            "undirected_sessions": board.undirected_sessions,
            "undirected_notional": round(board.undirected_notional),
            "basis_adjusted": True,
            "basis_carried_sessions": board.basis_carried_sessions,
            "dropped_sessions": board.dropped_sessions,
            "sessions_covered": len(board.sessions),
            "sessions_requested": sessions,
        },
        "warnings": warnings,
    }


@router.get("/viop-map/{ticker}/note")
async def get_viop_map_note(
    ticker: str,
    sessions: int = Query(120, ge=30, le=160),
    user: AuthUser | None = Depends(get_optional_user),
):
    """
    Where this underlying's book stands against its scan range, narrated.

    Scoped the way the map is — one underlying, one window — and fingerprinted
    on both plus the newest session day, so a note about one name over one
    window is never served for another. Split from `/viop-map/{ticker}` for
    the reason every note here is: the field is polled at the equity cadence
    and the paragraph is written once a session.

    `facts` is null when the book is too thin to draw or one of its three
    upstreams did not answer. Never a 404 or a 503: the page has already drawn
    or declined the field on its own, and a note's absence is a paragraph.
    """
    facts = await build_viop_map_facts(ticker, sessions)
    return {"facts": facts, "note": await viop_map_note(facts, user.id if user else None)}


# ══════════════════════════════════════════════════════════════════════════
# Calendar
# ══════════════════════════════════════════════════════════════════════════


def _event(event: CalendarEvent) -> dict:
    return {
        "kind": event.kind,
        "day": event.day,
        "ticker": event.ticker,
        "symbol": event.symbol,
        "name": event.name,
        "sector": event.sector,
        "market_cap": event.market_cap,
        "amount": event.amount,
        "yield_pct": event.yield_pct,
    }


@router.get("/calendar")
async def get_calendar(
    days_ahead: int = Query(90, ge=1, le=365),
    days_back: int = Query(14, ge=0, le=90),
    kinds: Optional[str] = Query(None, description="Comma-separated: earnings, dividend"),
):
    """
    Results announcements and ex-dividend dates.

    Rights and bonus issues are absent on purpose: they are announced through
    KAP as prose with no structured date anywhere, so they appear on the
    disclosure tape as filings rather than here as calendar rows. A partial
    calendar that looked complete would be worse than one that says what it
    covers.
    """
    try:
        board = await fetch_equity_board()
    except EquityDataUnavailable as e:
        raise _unavailable(e) from e

    wanted = frozenset(part.strip() for part in kinds.split(",") if part.strip()) if kinds else None
    events = build_calendar(
        board.equities, days_ahead=days_ahead, days_back=days_back, kinds=wanted
    )

    return {
        "as_of": board.as_of,
        "window": {"days_back": days_back, "days_ahead": days_ahead},
        "count": len(events),
        "covers": ["earnings", "dividend"],
        "excludes": ["bedelli", "bedelsiz"],
        "days": [
            {
                "day": bucket["day"],
                "count": bucket["count"],
                "events": [_event(e) for e in bucket["events"]],
            }
            for bucket in group_by_day(events)
        ],
    }


# ══════════════════════════════════════════════════════════════════════════
# Positioning
# ══════════════════════════════════════════════════════════════════════════


def _positioning(row: PositioningRow) -> dict:
    return {
        "ticker": row.ticker,
        "symbol": row.symbol,
        "name": row.name,
        "sector": row.sector,
        "price": row.price,
        "change_pct": row.change_pct,
        "market_cap": row.market_cap,
        "free_float_pct": row.free_float_pct,
        "relative_volume": row.relative_volume,
        "range_position": row.range_position,
        "beta": row.beta,
        "rsi": row.rsi,
        "open_interest": row.open_interest,
        "open_interest_change": row.open_interest_change,
        "crowding": row.crowding,
    }


# ── Financial statements ────────────────────────────────────────────────────


@router.get("/financials/{ticker}")
async def get_financials(
    ticker: str,
    quarters: int = Query(MAX_QUARTERS, ge=4, le=MAX_QUARTERS),
):
    """
    Twelve quarters of statements, in both nominal and inflation-adjusted lira.

    404 rather than an empty board when İş Yatırım has nothing for the code. A
    company page rendered full of dashes reads as a company that reported
    nothing, which is a different and much worse claim than "this code could not
    be resolved" — and it is the claim a reader would act on.
    """
    try:
        return await build_financials(ticker, quarters=quarters)
    except FinancialsUnavailable as e:
        raise HTTPException(
            status_code=404,
            detail=f"{ticker.strip().upper()} için finansal tablo bulunamadı.",
        ) from e


@router.get("/financials/{ticker}/note")
async def get_financials_note(ticker: str, user: AuthUser | None = Depends(get_optional_user)):
    """
    The model's read of the same statements.

    Split from the board because the two have different cadences: statements
    move four times a year and the paragraph is cached against them, while the
    price header beside it refreshes on the board's own poll. Welding them would
    tie the cheap request to the expensive one.
    """
    try:
        payload = await build_financials(ticker)
    except FinancialsUnavailable as e:
        raise HTTPException(
            status_code=404,
            detail=f"{ticker.strip().upper()} için finansal tablo bulunamadı.",
        ) from e

    from services.bist.financials_note import financials_facts

    return {
        "facts": financials_facts(payload),
        "note": await note_for_financials(payload, user.id if user else None),
    }


# ── Halka arz ───────────────────────────────────────────────────────────────


@router.get("/ipos")
async def get_ipos(
    months_back: int = Query(24, ge=3, le=120),
    days_ahead: int = Query(120, ge=7, le=365),
):
    """
    The offering calendar, and what the recent listings returned.

    `months_back` is a window rather than a top-N, and it is the cutoff for the
    ranked chart as well as the list. A window is a defensible cut — a period of
    the market — while "the last forty listings" is an arbitrary one whose
    meaning drifts with issuance volume. Twenty-four months covers roughly forty
    to sixty Borsa İstanbul listings: enough to be a distribution, and recent
    enough that the rate regime is comparable.

    503 rather than an empty board when the source is unreachable. There is no
    symbol here that failed to resolve — the calendar itself is down — and an
    empty list would read as a market with no offerings.
    """
    try:
        return await build_ipos(months_back=months_back, days_ahead=days_ahead)
    except HalkarzUnavailable as e:
        raise HTTPException(
            status_code=503,
            detail="Halka arz takvimine şu anda ulaşılamıyor.",
        ) from e


@router.get("/ipos/note")
async def get_ipos_note(
    months_back: int = Query(24, ge=3, le=120),
    days_ahead: int = Query(120, ge=7, le=365),
    user: AuthUser | None = Depends(get_optional_user),
):
    """The model's read of the same board."""
    try:
        payload = await build_ipos(months_back=months_back, days_ahead=days_ahead)
    except HalkarzUnavailable as e:
        raise HTTPException(
            status_code=503,
            detail="Halka arz takvimine şu anda ulaşılamıyor.",
        ) from e

    return {
        "facts": ipo_facts(payload),
        "note": await note_for_ipos(payload, user.id if user else None),
    }


@router.get("/positioning")
async def get_positioning(limit: int = Query(50, ge=1, le=500)):
    """
    Where the crowd is: free float, unusual volume, range position, futures OI.

    Not the fund-to-stock cross index this board was originally meant to be.
    TEFAS publishes a fund's split by asset class — the fund board draws it —
    but nothing public names the securities behind it, and KAP publishes
    holdings only as prose attachments. `positioning_service` documents what was
    tried. What is here is published positioning rather than inferred, which is
    a narrower claim honestly made.
    """
    try:
        board = await fetch_equity_board()
    except EquityDataUnavailable as e:
        raise _unavailable(e) from e

    # A futures outage costs one column, not the board.
    contracts: list[ViopContract] = []
    try:
        contracts = (await fetch_viop_board()).contracts
    except ViopUnavailable:
        pass

    rows = build_positioning(board.equities, contracts)
    return {
        "as_of": board.as_of,
        "stale": board.stale,
        "delay_minutes": DELAY_MINUTES,
        "has_futures_data": bool(contracts),
        "crowded": [_positioning(row) for row in rows[:limit]],
        "futures": [_positioning(row) for row in futures_positioning(rows)[:limit]],
    }


@router.get("/positioning-note")
async def get_positioning_note(user: AuthUser | None = Depends(get_optional_user)):
    """
    What the positioning board as a whole looks like, narrated.

    Its own route rather than a field on `/positioning`, for the reason every
    note here is: the board polls every two minutes and the paragraph is written
    once, so folding them together would either hold the board behind a model
    run or refuse the note a cadence of its own.

    Deliberately not scoped to the caller's `limit`. `/positioning` returns rows
    ranked by crowding, so any limit is a biased sample by construction — the
    facts are computed across every listing instead, because "the board is at the
    top of its year" answered over the busiest hundred names is a wrong answer
    rather than a narrower one.
    """
    facts = await build_positioning_facts()
    return {"facts": facts, "note": await positioning_note(facts, user.id if user else None)}


# ══════════════════════════════════════════════════════════════════════════
# Gece Mesaisi Endeksi
# ══════════════════════════════════════════════════════════════════════════


@router.get("/night-shift")
async def get_night_shift():
    """
    How hard the state is legislating today, and whether any of it skipped the
    queue.

    Deliberately the one endpoint on this router that cannot fail, for the same
    reason `/api/macro/pizza-index` cannot: it feeds a badge in the chrome of
    every BIST page, and a government site that stopped answering must not be
    able to take those pages down with it. The service answers
    `status: "unavailable"` instead, which the badge renders as its own state.
    """
    return await fetch_night_shift_index()


# ══════════════════════════════════════════════════════════════════════════
# Radar
# ══════════════════════════════════════════════════════════════════════════


def _radar_horizon(horizon: str) -> str:
    if horizon not in RADAR_PROFILES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown horizon '{horizon}'. One of: {', '.join(RADAR_PROFILES)}",
        )
    return horizon


@router.post("/radar/scan", status_code=status.HTTP_202_ACCEPTED)
async def start_radar_scan(response: Response, horizon: str = Query("swing")):
    """
    Scan the XU100 for pullbacks inside uptrends, in the background.

    Returns the job to poll. A scan already running for this horizon is joined
    rather than duplicated; a scan that just finished is returned with a 200 so
    the client can read its result straight away.
    """
    job = await radar_scan.start_scan(_radar_horizon(horizon))
    if not job.is_active:
        response.status_code = status.HTTP_200_OK
    return job.to_dict()


@router.get("/radar/jobs/{job_id}")
async def get_radar_job(job_id: str):
    """Poll a scan for its stage, its progress and — once done — its result."""
    job = await analysis_jobs.get_job(job_id)
    if job is None or job.kind != KIND_RADAR:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return job.to_dict()


@router.get("/radar")
async def get_radar(horizon: str = Query("swing")):
    """
    The last finished scan for a horizon.

    404 rather than an empty board when none has ever run: the page then shows
    the button and says so, instead of a result that reads as "nothing passed".
    """
    result = radar_scan.last_result(_radar_horizon(horizon))
    if result is None:
        raise HTTPException(status_code=404, detail="No scan has run for this horizon yet")
    return result


@router.delete("/radar/jobs/{job_id}")
async def cancel_radar_scan(job_id: str):
    """
    Stop a running scan.

    A scan started on the wrong horizon, or by a stray click, should not have to
    run its minute out. The settled job is returned so the button that asked
    sees the outcome without another poll; the last persisted result is left
    untouched, since a cancelled scan wrote nothing.
    """
    job = await analysis_jobs.get_job(job_id)
    if job is None or job.kind != KIND_RADAR:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    settled = await analysis_jobs.cancel_job(job_id)
    return (settled or job).to_dict()
