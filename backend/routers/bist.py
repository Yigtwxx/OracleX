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

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

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
from services.bist.kap_service import (
    SIGNAL_CATEGORIES,
    Disclosure,
    KapUnavailable,
    fetch_tape,
    filter_restrictions,
)
from services.bist.positioning_service import (
    PositioningRow,
    build_positioning,
    futures_positioning,
)
from services.bist.real_return import enrich_returns, summarise_real_losses
from services.bist.viop_service import ViopContract, ViopUnavailable, fetch_viop_board, summarise
from services.bist.tefas_client import FUND_TYPES, FundRow

router = APIRouter(prefix="/api/bist", tags=["bist"])


def _unavailable(error: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=str(error))


def _fund_row(row: FundRow, enriched: Optional[dict] = None) -> dict:
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
            )
            for row in rows
        ],
    }


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
    return {"facts": facts, "note": await funds_market_note(facts)}


@router.get("/funds/{code}")
async def get_fund(code: str, months: int = Query(12, ge=1, le=60)):
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
    payload["ai_note"] = await note_for_fund(payload)
    return payload


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
    payload["ai_note"] = await note_for_stock(payload)
    return payload


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
async def get_market_note():
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
    return {"facts": facts, "note": await market_note(facts)}


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


# ══════════════════════════════════════════════════════════════════════════
# KAP — the disclosure tape
# ══════════════════════════════════════════════════════════════════════════


def _disclosure(item: Disclosure) -> dict:
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
        "disclosures": [_disclosure(item) for item in rows],
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


@router.get("/positioning")
async def get_positioning(limit: int = Query(50, ge=1, le=500)):
    """
    Where the crowd is: free float, unusual volume, range position, futures OI.

    Not the fund-to-stock cross index this board was originally meant to be —
    TEFAS withdrew portfolio breakdowns from its public API and KAP publishes
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
