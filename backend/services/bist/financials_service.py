"""
A company's quarterly statements, shaped for the Bilanço board.

`fundamentals.py` already answers what a company reported. This module answers
the two questions a reader has in front of those numbers, neither of which the
raw statements settle:

**What did it earn in money that buys the same thing?** Every period is stated
in its own lira, so over the twelve quarters this serves, the nominal series is
mostly a picture of inflation. `deflator` restates each quarter into the newest
one's lira and the board draws that by default. The nominal figures are served
beside it, untouched — the point is the gap between the two, and a board that
showed only one of them would be making the reader's argument for them.

**Which of these lines does this company actually have?** İş Yatırım answers
under three charts of accounts, and a bank has no gross profit the way a factory
does — not "reported zero", *no such line*. Two separate coverage signals come
out of here for that reason: `layout_fields` is what the chart of accounts can
carry at all, `available_fields` is what this company filled in. A blank panel
means one of two different things to a reader, and the board has to be able to
say which.

The arithmetic is deliberately not reimplemented. `radar/scoring.py` already
owns trailing sums, real growth, margin trend and net debt over EBITDA, and it
is tested; a second copy here with its own edge rules is how the Radar and this
board start disagreeing about the same company. Where a ratio is wanted for an
earlier quarter, the Fundamentals is sliced and the same function is called
again rather than the rule being restated.
"""

from __future__ import annotations

import logging
import math
from dataclasses import replace
from typing import Any, Optional

from services.bist import deflator
from services.bist.fundamentals import (
    LAYOUT_BANK,
    LAYOUT_INDUSTRIAL,
    LAYOUT_INSURANCE,
    Fundamentals,
    Quarter,
    fetch_fundamentals,
)
from services.bist.radar import scoring

logger = logging.getLogger(__name__)

MAX_QUARTERS = 12
MIN_QUARTERS_FOR_NOTE = 5
"""Every growth figure on this board compares a trailing year against the one
before it, so four quarters can be drawn but cannot be narrated."""

FIELD_KEYS: tuple[str, ...] = (
    "revenue",
    "gross_profit",
    "operating_profit",
    "ebitda",
    "net_income",
    "financing_expense",
    "ocf",
    "capex",
    "fcf",
    "dividends_paid",
    "equity",
    "total_assets",
    "total_debt",
    "short_term_debt",
    "cash",
    "current_assets",
    "current_liabilities",
)

# What each chart of accounts can carry. Mirrors the item-code maps in
# `fundamentals.py`; the coverage-drift test asserts the two have not parted.
LAYOUT_FIELDS: dict[str, tuple[str, ...]] = {
    LAYOUT_INDUSTRIAL: FIELD_KEYS,
    LAYOUT_BANK: ("revenue", "operating_profit", "net_income", "equity", "total_assets"),
    LAYOUT_INSURANCE: ("net_income", "equity", "total_assets"),
}

LAYOUT_LABELS: dict[str, str] = {
    LAYOUT_INDUSTRIAL: "Sanayi/ticaret şablonu",
    LAYOUT_BANK: "Banka şablonu",
    LAYOUT_INSURANCE: "Sigorta şablonu",
}

RATIO_KEYS: tuple[str, ...] = (
    "gross_margin",
    "operating_margin",
    "ebitda_margin",
    "net_margin",
    "current_ratio",
    "short_debt_share",
    "cash_conversion",
    "net_debt_ebitda",
    "roe_ttm",
)


class FinancialsUnavailable(RuntimeError):
    """No statements for this code. The router turns this into a 404."""


def _finite(value: Optional[float]) -> Optional[float]:
    """
    A ratio as JSON can carry it.

    `scoring.net_debt_to_ebitda` answers `inf` for positive net debt against
    non-positive EBITDA, which is the right answer for a veto: the company owes
    money it is not earning. It is not a number a chart can plot or JSON can
    encode, so the sentinel is translated once, here, at the boundary — rather
    than the Radar's rule being forked so this board gets a different one.
    """
    if value is None:
        return None
    if not math.isfinite(value):
        return None
    return value


def _ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def available_fields(quarters: tuple[Quarter, ...], layout: str) -> tuple[str, ...]:
    """
    The lines this company actually reported, of the ones its layout can carry.

    Present if *any* quarter in the window carries it, not only the newest. A
    company that stopped reporting a line last quarter should show a chart with
    a gap at the end, which is a fact about the company; the stricter rule would
    retire the whole panel and hide it.
    """
    allowed = LAYOUT_FIELDS.get(layout, FIELD_KEYS)
    return tuple(
        field
        for field in allowed
        if any(getattr(quarter, field, None) is not None for quarter in quarters)
    )


def build_ratios(fund: Fundamentals) -> list[dict[str, Any]]:
    """
    Per-quarter ratios, oldest first, `None` wherever a ratio is unmeasurable.

    Trailing figures for an earlier quarter come from re-running the same
    `scoring` function against a slice of the same Fundamentals, so the trailing
    window, the EBITDA edge rule and the net-debt definition are the ones the
    Radar uses by construction rather than by agreement.
    """
    quarters = fund.quarters  # newest first
    rows: list[dict[str, Any]] = []

    for index, quarter in enumerate(quarters):
        window = replace(fund, quarters=quarters[index:])
        revenue = scoring.ttm(quarters, "revenue", offset=index)
        net_income = scoring.ttm(quarters, "net_income", offset=index)

        # Average of opening and closing equity, not closing alone. A company
        # that raised capital during the year carries the new equity in the
        # denominator for the whole trailing period on the closing formula, and
        # its ROE reads high for four quarters. In Turkey that is most of the
        # listing, so the flattering version would be the common case.
        opening_equity = quarters[index + 4].equity if len(quarters) > index + 4 else None
        closing_equity = quarter.equity
        if opening_equity is not None and closing_equity is not None:
            average_equity: Optional[float] = (opening_equity + closing_equity) / 2
        else:
            average_equity = None

        rows.append(
            {
                "period": quarter.period,
                "gross_margin": _ratio(scoring.ttm(quarters, "gross_profit", index), revenue),
                "operating_margin": _ratio(
                    scoring.ttm(quarters, "operating_profit", index), revenue
                ),
                "ebitda_margin": _ratio(scoring.ttm(quarters, "ebitda", index), revenue),
                "net_margin": _ratio(net_income, revenue),
                "current_ratio": _ratio(quarter.current_assets, quarter.current_liabilities),
                "short_debt_share": _ratio(quarter.short_term_debt, quarter.total_debt),
                "cash_conversion": _ratio(scoring.ttm(quarters, "ocf", index), net_income),
                "net_debt_ebitda": _finite(scoring.net_debt_to_ebitda(window)),
                "roe_ttm": _ratio(net_income, average_equity),
            }
        )

    rows.reverse()
    return rows


def build_ttm(fund: Fundamentals, inflation_yoy: Optional[float]) -> dict[str, Any]:
    """
    The trailing-year block above the charts.

    `scoring.real_growth` is the right tool here and `deflator` is not: a
    trailing year over the year before is a *return*, so the Fisher relation
    applies. The levels the charts draw are a different operation entirely.
    """
    quarters = fund.quarters
    recent = quarters[:4]
    losses = [q for q in recent if q.net_income is not None and q.net_income < 0]

    nominal_now = scoring.ttm(quarters, "revenue")
    nominal_before = scoring.ttm(quarters, "revenue", offset=4)
    nominal_growth = (
        nominal_now / nominal_before - 1
        if nominal_now is not None and nominal_before not in (None, 0) and nominal_before > 0
        else None
    )

    return {
        "revenue": scoring.ttm(quarters, "revenue"),
        "ebitda": scoring.ttm(quarters, "ebitda"),
        "net_income": scoring.ttm(quarters, "net_income"),
        "real_revenue_growth": scoring.real_growth(fund, "revenue", inflation_yoy),
        "real_ebitda_growth": scoring.real_growth(fund, "ebitda", inflation_yoy),
        "real_net_income_growth": scoring.real_growth(fund, "net_income", inflation_yoy),
        "real_equity_growth": scoring.level_growth(fund, "equity", inflation_yoy),
        "nominal_revenue_growth": nominal_growth,
        "margin_trend": scoring.margin_trend(fund, "net_income"),
        "inflation_yoy": inflation_yoy,
        # None rather than 0 when the window is short: "no loss-making quarter"
        # and "we cannot see four quarters" are different statements.
        "loss_quarters": len(losses) if len(recent) == 4 else None,
    }


def inflation_yoy(cpi_series: list[dict[str, Any]]) -> Optional[float]:
    """Consumer prices over the trailing twelve months, as a fraction."""
    index = deflator.index_by_month(cpi_series)
    if len(index) < 13:
        return None
    months = sorted(index)
    latest, year_ago = months[-1], months[-13]
    if index[year_ago] <= 0:
        return None
    return index[latest] / index[year_ago] - 1


def quarter_payload(quarter: Quarter, deflation: deflator.Deflation) -> dict[str, Any]:
    """One quarter, in both price frames."""
    nominal = {field: getattr(quarter, field, None) for field in FIELD_KEYS}
    factor = deflation.factors.get(quarter.period)

    # `real` is null for the whole quarter rather than a dict of nulls: the
    # frontend keys "this bar has no deflated form" off the object's absence,
    # and a populated shape full of nulls is the kind of thing that gets plotted
    # at zero by accident.
    real = (
        {field: deflator.restate(nominal[field], factor) for field in FIELD_KEYS}
        if factor is not None
        else None
    )

    return {
        "period": quarter.period,
        "year": quarter.year,
        "quarter": quarter.quarter,
        "nominal": nominal,
        "real": real,
        "deflator": factor,
        "provisional": quarter.period in deflation.provisional,
    }


def build_payload(
    fund: Fundamentals,
    *,
    cpi_series: list[dict[str, Any]],
    key_configured: bool,
    equity: Any | None = None,
    quarters: int = MAX_QUARTERS,
) -> dict[str, Any]:
    """The board's whole response, assembled from statements already in hand."""
    window = fund.quarters[: max(1, min(quarters, MAX_QUARTERS))]
    sliced = replace(fund, quarters=window)

    periods = [q.period for q in window]
    deflation = deflator.build_deflation(periods, cpi_series, key_configured=key_configured)
    layout = fund.layout

    # Oldest first from here down. Fundamentals is newest-first because every
    # trailing calculation counts backwards from now; a chart reads left to
    # right, and a silently reversed series is a plausible-looking picture of
    # the opposite trend.
    ordered = tuple(reversed(window))

    payload: dict[str, Any] = {
        "ticker": fund.ticker,
        "name": getattr(equity, "name", None),
        "sector": getattr(equity, "sector", None) or None,
        "layout": layout,
        "layout_label": LAYOUT_LABELS.get(layout, layout),
        "layout_fields": list(LAYOUT_FIELDS.get(layout, FIELD_KEYS)),
        "available_fields": list(available_fields(window, layout)),
        "latest_period": fund.latest_period,
        "fetched_at": fund.fetched_at,
        "source_url": fund.source_url,
        "quarters": [quarter_payload(q, deflation) for q in ordered],
        "ratios": build_ratios(sliced),
        "ttm": build_ttm(sliced, inflation_yoy(cpi_series)),
        "deflation": {
            "available": deflation.available,
            "reason": deflation.reason,
            "base_period": deflation.base_period,
            "base_month": deflation.base_month,
            "cpi_latest_month": deflation.cpi_latest_month,
            "cpi_series": "TP.FG.J0",
            "provisional_periods": list(deflation.provisional),
            "uncovered_periods": list(deflation.uncovered),
        },
        "market": None,
        "stale": False,
    }

    if equity is not None:
        payload["market"] = {
            "price": getattr(equity, "price", None),
            "market_cap": getattr(equity, "market_cap", None),
            "pe": getattr(equity, "pe", None),
            "pb": getattr(equity, "pb", None),
            "delay_minutes": 15,
        }

    return payload


async def build_financials(ticker: str, *, quarters: int = MAX_QUARTERS) -> dict[str, Any]:
    """
    Statements, deflated, with the market header when the scanner can be reached.

    Raises `FinancialsUnavailable` when İş Yatırım has nothing for this code and
    no cache does either. That is a 404 rather than an empty board on purpose:
    a company page full of dashes reads as a company that reported nothing,
    which is a different and much worse claim than "we could not resolve this".
    """
    from config import settings
    from services.bist import equity_service, macro_service

    code = ticker.strip().upper().rsplit(":", 1)[-1]
    if not code:
        raise FinancialsUnavailable("no ticker given")

    fund = await fetch_fundamentals(code)
    if fund is None or not fund.quarters:
        raise FinancialsUnavailable(f"İş Yatırım has no statements for {code}")

    cpi_series = await macro_service.fetch_cpi_series(years=6)

    equity: Any | None = None
    try:
        equity = await equity_service.fetch_equity(code)
    except Exception as e:  # noqa: BLE001
        # The scanner is a separate upstream and its outage costs the price
        # header, not the statements. Every figure on the board below comes
        # from İş Yatırım.
        logger.info("no scanner row for %s: %s", code, e)

    return build_payload(
        fund,
        cpi_series=cpi_series,
        key_configured=bool(settings.TCMB_EVDS_API_KEY),
        equity=equity,
        quarters=quarters,
    )
