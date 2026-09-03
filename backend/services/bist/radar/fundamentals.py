"""
Eight quarters of financial statements per company, from İş Yatırım.

`www.isyatirim.com.tr` publishes every listed company's statements as JSON
behind `Data.aspx/MaliTablo` — no key, no bot wall, and the host is already
mapped to the `bist` health category by the ownership board's card scraper.
Four periods per call, so a cold read is three calls per company.

Three facts about the payload that a parser must hold or it produces nonsense:

* **Income and cash-flow lines are year-to-date.** The 6-month figure is
  January–June, not April–June. A quarter is the difference between two
  consecutive periods of the same year; Q1 is itself. Balance-sheet lines are
  point-in-time and are used as they come.
* **The financial group selects the layout, and the wrong one returns an
  empty `value` rather than an error.** `XI_29` is the industrial chart of
  accounts; banks and insurers answer only under `UFRS`, with two different
  layouts of their own that share the codes that matter here (`3Z` net income,
  `2O` equity, `1Z` total assets). The client tries `XI_29` first and falls
  back.
* **Each period is stated in that period's own lira.** Comparing Q2-2026 with
  Q2-2025 needs the CPI between them; that is `scoring.real_growth`'s job and
  the reason nothing here computes growth.

Cached on disk per ticker. Statements change four times a year, so the cache is
judged against the calendar rather than a TTL: a file is refetched when the most
recent quarter that should have been published by now is not in it, and at
least every 45 days in case of a restatement.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass
from functools import partial
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable, Optional

import httpx

from services.asset_registry import DATA_DIR
from services.http_client import get_json

logger = logging.getLogger(__name__)

STATEMENTS_URL = (
    "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo"
)

CACHE_DIR = os.path.join(DATA_DIR, "bist_fundamentals")

PERIODS_WANTED = 12
"""Enough year-to-date points to difference into eight or nine clean quarters."""

PERIODS_PER_CALL = 4

PUBLICATION_LAG_DAYS = 40
"""SPK's shortest filing deadline. A quarter younger than this may not be out yet."""

RECHECK_DAYS = 3
"""How often to look again for a quarter that should be out but is not yet in the cache."""

HARD_REFRESH_DAYS = 45

CONCURRENCY = 3
REQUEST_SPACING_SECONDS = 0.2

LAYOUT_INDUSTRIAL = "industrial"
LAYOUT_BANK = "bank"
LAYOUT_INSURANCE = "insurance"

# Item codes per layout. Flow items are year-to-date in the payload; stock
# items are balances.
_FLOWS: dict[str, dict[str, tuple[str, ...]]] = {
    LAYOUT_INDUSTRIAL: {
        "revenue": ("3C",),
        "gross_profit": ("3D",),
        "operating_profit": ("3DF",),
        "depreciation": ("4B",),
        "net_income": ("3Z", "3L"),
        "financing_expense": ("3HC",),
        "ocf": ("4C",),
        "capex": ("4CAI",),
        "fcf": ("4CB",),
        "dividends_paid": ("4CBB",),
    },
    LAYOUT_BANK: {
        "net_interest_income": ("3C",),
        "fee_income": ("3CA",),
        "operating_profit": ("3CH",),
        "net_income": ("3Z",),
    },
    LAYOUT_INSURANCE: {
        "net_income": ("3Z",),
    },
}

_STOCKS: dict[str, dict[str, tuple[str, ...]]] = {
    LAYOUT_INDUSTRIAL: {
        "equity": ("2N",),
        "total_assets": ("1BL",),
        "short_term_debt": ("2AA",),
        "long_term_debt": ("2BA",),
        "cash": ("1AA",),
        "current_assets": ("1A",),
        "current_liabilities": ("2A",),
    },
    LAYOUT_BANK: {
        "equity": ("2O",),
        "total_assets": ("1Z",),
    },
    LAYOUT_INSURANCE: {
        "equity": ("2O",),
        "total_assets": ("1Z",),
    },
}


class FundamentalsUnavailable(RuntimeError):
    """İş Yatırım did not answer, or answered with nothing usable for this company."""


@dataclass(frozen=True)
class Quarter:
    """One calendar quarter. Flows are for the quarter alone; balances at its end."""

    period: str
    """`2026Q2`."""
    year: int
    quarter: int
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_profit: Optional[float] = None
    ebitda: Optional[float] = None
    net_income: Optional[float] = None
    financing_expense: Optional[float] = None
    """Negative in the payload; kept negative."""
    ocf: Optional[float] = None
    capex: Optional[float] = None
    fcf: Optional[float] = None
    dividends_paid: Optional[float] = None
    equity: Optional[float] = None
    total_assets: Optional[float] = None
    total_debt: Optional[float] = None
    short_term_debt: Optional[float] = None
    cash: Optional[float] = None
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None


@dataclass(frozen=True)
class Fundamentals:
    ticker: str
    layout: str
    quarters: tuple[Quarter, ...]
    """Newest first."""
    fetched_at: str
    source_url: str

    @property
    def latest_period(self) -> Optional[str]:
        return self.quarters[0].period if self.quarters else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "layout": self.layout,
            "fetched_at": self.fetched_at,
            "source_url": self.source_url,
            "quarters": [asdict(q) for q in self.quarters],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Fundamentals:
        quarters = tuple(Quarter(**q) for q in raw.get("quarters", []))
        return cls(
            ticker=raw["ticker"],
            layout=raw.get("layout", LAYOUT_INDUSTRIAL),
            quarters=quarters,
            fetched_at=raw.get("fetched_at", ""),
            source_url=raw.get("source_url", STATEMENTS_URL),
        )


# ── Calendar ────────────────────────────────────────────────────────────────


def quarter_ends(today: date, count: int = PERIODS_WANTED) -> list[tuple[int, int]]:
    """
    The last `count` quarter-ends as (year, month) pairs, newest first, starting
    from the most recent one at least `PUBLICATION_LAG_DAYS` old.
    """
    cutoff = today - timedelta(days=PUBLICATION_LAG_DAYS)
    # The last quarter-end on or before the cutoff: June counts once the
    # cutoff has passed 30 June, not once it is in June.
    year, month = cutoff.year, ((cutoff.month - 1) // 3) * 3
    if month == 0:
        year, month = year - 1, 12
    out: list[tuple[int, int]] = []
    for _ in range(count):
        out.append((year, month))
        month -= 3
        if month == 0:
            year, month = year - 1, 12
    return out


def expected_latest(today: date) -> str:
    year, month = quarter_ends(today, 1)[0]
    return f"{year}Q{month // 3}"


# ── Parsing ─────────────────────────────────────────────────────────────────


def _number(raw: Any) -> Optional[float]:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(str(raw).replace(",", "."))
    except ValueError:
        return None
    return value if value == value else None


def detect_layout(rows: list[dict[str, Any]], group: str) -> str:
    if group == "XI_29":
        return LAYOUT_INDUSTRIAL
    for row in rows:
        if row.get("itemCode") == "3A" and "FAİZ" in str(row.get("itemDescTr", "")).upper():
            return LAYOUT_BANK
    return LAYOUT_INSURANCE


def parse_periods(
    rows: list[dict[str, Any]], periods: list[tuple[int, int]]
) -> dict[tuple[int, int], dict[str, Optional[float]]]:
    """Item code → value per requested period. `value1` is the first period asked for."""
    out: dict[tuple[int, int], dict[str, Optional[float]]] = {p: {} for p in periods}
    for row in rows:
        code = str(row.get("itemCode") or "")
        if not code:
            continue
        for index, period in enumerate(periods, start=1):
            out[period][code] = _number(row.get(f"value{index}"))
    return out


def _pick(items: dict[str, Optional[float]], codes: tuple[str, ...]) -> Optional[float]:
    for code in codes:
        value = items.get(code)
        if value is not None:
            return value
    return None


def _quarter_flow(
    items: dict[str, Optional[float]],
    previous: Optional[dict[str, Optional[float]]],
    month: int,
    codes: tuple[str, ...],
) -> Optional[float]:
    """This period's year-to-date figure less the previous period's; Q1 is itself."""
    ytd = _pick(items, codes)
    if ytd is None:
        return None
    if month == 3:
        return ytd
    before = _pick(previous or {}, codes)
    if before is None:
        return None
    return ytd - before


def _flow_for(
    items: dict[str, Optional[float]],
    previous: Optional[dict[str, Optional[float]]],
    month: int,
    flows: dict[str, tuple[str, ...]],
    field: str,
) -> Optional[float]:
    return _quarter_flow(items, previous, month, flows[field])


def _stock_for(
    items: dict[str, Optional[float]], stocks: dict[str, tuple[str, ...]], field: str
) -> Optional[float]:
    return _pick(items, stocks[field]) if field in stocks else None


def build_quarters(
    by_period: dict[tuple[int, int], dict[str, Optional[float]]], layout: str
) -> tuple[Quarter, ...]:
    """
    Year-to-date points into quarters, newest first.

    A quarter whose previous year-to-date point is missing is dropped rather
    than reported with a year-to-date flow in a quarterly slot — that is the
    single most common way a Turkish statements parser produces a company that
    apparently tripled its revenue in one quarter.
    """
    flows = _FLOWS[layout]
    stocks = _STOCKS[layout]
    quarters: list[Quarter] = []

    for year, month in sorted(by_period, reverse=True):
        items = by_period[(year, month)]
        if not any(v is not None and v != 0 for v in items.values()):
            continue
        previous = by_period.get((year, month - 3)) if month > 3 else None
        if month > 3 and previous is None:
            continue

        flow = partial(_flow_for, items, previous, month, flows)
        stock = partial(_stock_for, items, stocks)

        if layout == LAYOUT_INDUSTRIAL:
            operating = flow("operating_profit")
            depreciation = flow("depreciation")
            ebitda = (
                operating + depreciation
                if operating is not None and depreciation is not None
                else None
            )
            short_debt, long_debt = stock("short_term_debt"), stock("long_term_debt")
            total_debt = (
                (short_debt or 0.0) + (long_debt or 0.0)
                if short_debt is not None or long_debt is not None
                else None
            )
            quarters.append(
                Quarter(
                    period=f"{year}Q{month // 3}",
                    year=year,
                    quarter=month // 3,
                    revenue=flow("revenue"),
                    gross_profit=flow("gross_profit"),
                    operating_profit=operating,
                    ebitda=ebitda,
                    net_income=flow("net_income"),
                    financing_expense=flow("financing_expense"),
                    ocf=flow("ocf"),
                    capex=flow("capex"),
                    fcf=flow("fcf"),
                    dividends_paid=flow("dividends_paid"),
                    equity=stock("equity"),
                    total_assets=stock("total_assets"),
                    total_debt=total_debt,
                    short_term_debt=short_debt,
                    cash=stock("cash"),
                    current_assets=stock("current_assets"),
                    current_liabilities=stock("current_liabilities"),
                )
            )
        elif layout == LAYOUT_BANK:
            interest, fees = flow("net_interest_income"), flow("fee_income")
            revenue = interest + fees if interest is not None and fees is not None else interest
            quarters.append(
                Quarter(
                    period=f"{year}Q{month // 3}",
                    year=year,
                    quarter=month // 3,
                    revenue=revenue,
                    operating_profit=flow("operating_profit"),
                    net_income=flow("net_income"),
                    equity=stock("equity"),
                    total_assets=stock("total_assets"),
                )
            )
        else:
            quarters.append(
                Quarter(
                    period=f"{year}Q{month // 3}",
                    year=year,
                    quarter=month // 3,
                    net_income=flow("net_income"),
                    equity=stock("equity"),
                    total_assets=stock("total_assets"),
                )
            )
    return tuple(quarters)


# ── Fetching ────────────────────────────────────────────────────────────────


def _params(ticker: str, group: str, periods: list[tuple[int, int]]) -> dict[str, Any]:
    params: dict[str, Any] = {"companyCode": ticker, "exchange": "TRY", "financialGroup": group}
    for index, (year, month) in enumerate(periods, start=1):
        params[f"year{index}"] = year
        params[f"period{index}"] = month
    return params


async def _call(ticker: str, group: str, periods: list[tuple[int, int]]) -> list[dict[str, Any]]:
    try:
        body = await get_json(STATEMENTS_URL, params=_params(ticker, group, periods), timeout=30.0)
    except (httpx.HTTPError, OSError, ValueError) as e:
        raise FundamentalsUnavailable(f"İş Yatırım statements for {ticker} unavailable: {e}") from e
    rows = body.get("value") if isinstance(body, dict) else None
    return rows if isinstance(rows, list) else []


async def fetch_statements(ticker: str, today: Optional[date] = None) -> Fundamentals:
    """
    Every wanted period for one company, trying the industrial chart of accounts
    first and the financial one when that comes back empty.
    """
    code = ticker.strip().upper().rsplit(":", 1)[-1]
    periods = quarter_ends(today or date.today())
    chunks = [periods[i : i + PERIODS_PER_CALL] for i in range(0, len(periods), PERIODS_PER_CALL)]

    layout: Optional[str] = None
    by_period: dict[tuple[int, int], dict[str, Optional[float]]] = {}
    for group in ("XI_29", "UFRS"):
        first = await _call(code, group, chunks[0])
        if not first:
            continue
        layout = detect_layout(first, group)
        by_period.update(parse_periods(first, chunks[0]))
        for chunk in chunks[1:]:
            await asyncio.sleep(REQUEST_SPACING_SECONDS)
            by_period.update(parse_periods(await _call(code, group, chunk), chunk))
        break

    if layout is None:
        raise FundamentalsUnavailable(f"İş Yatırım has no statements for {code}")

    quarters = build_quarters(by_period, layout)
    if not quarters:
        raise FundamentalsUnavailable(f"İş Yatırım statements for {code} carried no usable period")

    return Fundamentals(
        ticker=code,
        layout=layout,
        quarters=quarters,
        fetched_at=datetime.now(UTC).isoformat(),
        source_url=STATEMENTS_URL,
    )


# ── Disk cache ──────────────────────────────────────────────────────────────


def _path(ticker: str) -> str:
    return os.path.join(CACHE_DIR, f"{ticker.upper()}.json")


def read_cached(ticker: str) -> Optional[Fundamentals]:
    path = _path(ticker)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return Fundamentals.from_dict(json.load(handle))
    except (OSError, ValueError, TypeError, KeyError):
        return None


def write_cached(fund: Fundamentals) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _path(fund.ticker)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(fund.to_dict(), handle, ensure_ascii=False)
    os.replace(tmp, path)


def is_fresh(fund: Fundamentals, today: Optional[date] = None) -> bool:
    """
    Whether the cached statements can be used without asking again.

    Stale when older than the hard limit, or when the newest quarter that should
    be public is missing and the last look was more than a few days ago.
    """
    now = datetime.now(UTC)
    try:
        fetched = datetime.fromisoformat(fund.fetched_at)
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=UTC)
    except ValueError:
        return False
    age_days = (now - fetched).total_seconds() / 86400
    if age_days > HARD_REFRESH_DAYS:
        return False
    if fund.latest_period != expected_latest(today or now.date()) and age_days > RECHECK_DAYS:
        return False
    return True


async def fetch_fundamentals(ticker: str, *, force: bool = False) -> Optional[Fundamentals]:
    """
    Cached statements if fresh, otherwise a live read that is then cached.

    Returns the stale cache rather than None when İş Yatırım is down — a
    company's balance sheet from six weeks ago is a far better read than no
    balance sheet at all, and the scan marks the coverage anyway.
    """
    code = ticker.strip().upper().rsplit(":", 1)[-1]
    cached = None if force else read_cached(code)
    if cached is not None and is_fresh(cached):
        return cached
    try:
        fund = await fetch_statements(code)
    except FundamentalsUnavailable as e:
        logger.warning("%s", e)
        return cached
    write_cached(fund)
    return fund


async def fetch_many(
    tickers: list[str],
    *,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> dict[str, Fundamentals]:
    """
    Statements for a list of companies, a few at a time.

    Cached names return without a request, so after the first scan this is a
    directory read. The semaphore is what keeps a cold scan from arriving at
    İş Yatırım as a hundred simultaneous requests.
    """
    semaphore = asyncio.Semaphore(CONCURRENCY)
    out: dict[str, Fundamentals] = {}
    done = 0
    total = len(tickers)

    async def one(ticker: str) -> None:
        nonlocal done
        async with semaphore:
            fund = await fetch_fundamentals(ticker)
            if fund is not None:
                out[ticker] = fund
            done += 1
            if on_progress:
                on_progress(done, total)

    await asyncio.gather(*(one(t) for t in tickers), return_exceptions=True)
    return out
