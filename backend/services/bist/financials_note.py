"""
A grounded read of one company's trailing year, from its own statements.

The board around this note draws twelve quarters in two price frames. The gap it
closes is the one a chart cannot: whether a company that looks like it tripled
actually sold more, and whether the profit it reported turned into cash.

Three properties shape the facts block:

* **Only trailing aggregates go in, never a quarter.** The charts carry every
  quarter; the note carries the trailing year and the year before it. That is
  not a size economy — a facts block holding twelve quarters would invite a
  quarter-by-quarter narration, and every sentence of it would be a figure the
  reader can already see plotted, quoted back at them less precisely.
* **Everything is quantized, and the steps are wide.** Statements move four
  times a year but the market header beside them moves every two minutes, and
  CPI is revised. Snapping to five points of growth and one point of margin is
  what keeps a note about an unchanged quarter from being rewritten because the
  index moved a decimal.
* **Absence is typed, not blank.** A missing EBITDA means one of two things —
  the bank's chart of accounts has no such line, or the company did not report
  it — and a reader looking at an empty panel wants to know which. The two
  travel separately into the prompt.

Nothing here raises. The board is complete without the paragraph.
"""

from __future__ import annotations

from typing import Any, Optional

from services.ai_notes import NoteSpec, get_note
from services.bist import deflator
from services.bist.financials_service import (
    LAYOUT_FIELDS,
    LAYOUT_LABELS,
    MIN_QUARTERS_FOR_NOTE,
)

NOTE_SPEC = NoteSpec(
    kind="bist_financials",
    prompt="notes/bist_financials",
    # Longer than the tape's notes. This one has to name the nominal-versus-real
    # gap, the margin direction, the balance sheet and the cash conversion, and
    # at 280 the cash clause was what got dropped.
    max_tokens=340,
    temperature=0.2,
    # Statements change quarterly and the fingerprint retires the note the
    # moment they do. The ceiling only covers what the facts leave out.
    max_age_seconds=7 * 24 * 3600,
    max_chars=1200,
)

UNKNOWN = "not available"

# Turkish statements run to trillions of lira. Stating the unit once, in the
# facts, is what stops the model rescaling a figure into "billion" prose and
# getting the exponent wrong.
UNIT = "billion TRY"
_BILLION = 1_000_000_000.0

# Why a line is missing. The two are not interchangeable to a reader.
ABSENT_LAYOUT = "layout"
ABSENT_UNREPORTED = "unreported"

FIELD_LABELS: dict[str, str] = {
    "revenue": "revenue",
    "gross_profit": "gross profit",
    "operating_profit": "operating profit",
    "ebitda": "EBITDA",
    "net_income": "net income",
    "financing_expense": "financing expense",
    "ocf": "operating cash flow",
    "capex": "capital expenditure",
    "fcf": "free cash flow",
    "dividends_paid": "dividends paid",
    "equity": "equity",
    "total_assets": "total assets",
    "total_debt": "total debt",
    "short_term_debt": "short-term debt",
    "cash": "cash",
    "current_assets": "current assets",
    "current_liabilities": "current liabilities",
}

REASON_SENTENCES: dict[str, str] = {
    deflator.REASON_KEY_MISSING: (
        "No inflation series is configured on this deployment, so nothing on the "
        "board is deflated and every figure below is nominal lira"
    ),
    deflator.REASON_UNAVAILABLE: (
        "The central bank's price index could not be reached, so nothing on the "
        "board is deflated and every figure below is nominal lira"
    ),
    deflator.REASON_TOO_SHORT: (
        "The price index does not reach this company's newest quarter, so nothing "
        "on the board is deflated and every figure below is nominal lira"
    ),
}


def _zeroed(value: float) -> float:
    """`-0.0` renders as "-0%" and the model quotes it verbatim."""
    return 0.0 if value == 0 else value


def _bucket(value: Optional[float], step: float) -> Optional[float]:
    if value is None:
        return None
    try:
        return _zeroed(round(round(float(value) / step) * step, 4))
    except (TypeError, ValueError):
        return None


def _pct(value: Optional[float], step: float) -> Optional[float]:
    """A fraction as percentage points, snapped to `step`."""
    if value is None:
        return None
    try:
        return _bucket(float(value) * 100, step)
    except (TypeError, ValueError):
        return None


def _billions(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value) / _BILLION, 1)
    except (TypeError, ValueError):
        return None


MIN_SPREAD = 0.01
"""
How far apart the widest and narrowest margin must be before either is named.

A company whose margin barely moves has no best quarter, and handing the model
one invites a sentence built on noise. The floor is one percentage point, which
is also the step the margins themselves are quantized to.
"""


def _extremes(ratios: list[dict[str, Any]], key: str) -> tuple[Optional[str], Optional[str]]:
    """
    The widest and narrowest period on one ratio, or two Nones.

    Ties are broken by period rather than by iteration order. `min` and `max`
    return the first match, so on a flat series the answer would depend on
    float noise several decimal places below anything the board displays — and
    a label that flips for that reason retires a cached note for nothing.
    """
    measured = [r for r in ratios if r.get(key) is not None]
    if len(measured) < 4:
        return None, None
    ordered = sorted(measured, key=lambda r: (r[key], r.get("period") or ""))
    low, high = ordered[0], ordered[-1]
    if high[key] - low[key] < MIN_SPREAD:
        return None, None
    return high.get("period"), low.get("period")


# ── Facts ────────────────────────────────────────────────────────────────────


def financials_facts(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Everything the note may speak about, quantized.

    Returns None when the window is too short to compare a trailing year against
    the one before it — four quarters can be drawn but cannot be narrated, and a
    note that says only "revenue was 12 billion lira" is worse than no note.
    """
    quarters = payload.get("quarters") or []
    if len(quarters) < MIN_QUARTERS_FOR_NOTE:
        return None

    ttm = payload.get("ttm") or {}
    ratios = payload.get("ratios") or []
    latest = ratios[-1] if ratios else {}
    deflation = payload.get("deflation") or {}
    layout = payload.get("layout", "")

    layout_can_carry = set(LAYOUT_FIELDS.get(layout, ()))
    reported = set(payload.get("available_fields") or ())

    absent: dict[str, str] = {}
    for field in FIELD_LABELS:
        if field not in layout_can_carry:
            absent[field] = ABSENT_LAYOUT
        elif field not in reported:
            absent[field] = ABSENT_UNREPORTED

    return {
        "ticker": payload.get("ticker"),
        "name": payload.get("name"),
        "sector": payload.get("sector"),
        "layout": layout,
        "layout_label": LAYOUT_LABELS.get(layout, layout),
        "latest_period": payload.get("latest_period"),
        "quarters_covered": len(quarters),
        # The note always narrates the board's default view. Stated rather than
        # inferred so the prompt can say which frame its figures are in.
        "basis": "real" if deflation.get("available") else "nominal",
        "deflation_available": bool(deflation.get("available")),
        "deflation_reason": deflation.get("reason"),
        "newest_quarter_provisional": bool(quarters[-1].get("provisional")),
        "unit": UNIT,
        "ttm_revenue": _billions(ttm.get("revenue")),
        "ttm_ebitda": _billions(ttm.get("ebitda")),
        "ttm_net_income": _billions(ttm.get("net_income")),
        "real_revenue_yoy_pct": _pct(ttm.get("real_revenue_growth"), 5.0),
        "real_ebitda_yoy_pct": _pct(ttm.get("real_ebitda_growth"), 5.0),
        "real_net_income_yoy_pct": _pct(ttm.get("real_net_income_growth"), 5.0),
        "real_equity_yoy_pct": _pct(ttm.get("real_equity_growth"), 5.0),
        "nominal_revenue_yoy_pct": _pct(ttm.get("nominal_revenue_growth"), 5.0),
        "inflation_yoy_pct": _pct(ttm.get("inflation_yoy"), 1.0),
        "gross_margin_pct": _pct(latest.get("gross_margin"), 1.0),
        "operating_margin_pct": _pct(latest.get("operating_margin"), 1.0),
        "ebitda_margin_pct": _pct(latest.get("ebitda_margin"), 1.0),
        "net_margin_pct": _pct(latest.get("net_margin"), 1.0),
        "margin_trend_pp": _pct(ttm.get("margin_trend"), 1.0),
        "roe_pct": _pct(latest.get("roe_ttm"), 5.0),
        "short_debt_share_pct": _pct(latest.get("short_debt_share"), 5.0),
        "net_debt_ebitda": _bucket(latest.get("net_debt_ebitda"), 0.1),
        "current_ratio": _bucket(latest.get("current_ratio"), 0.1),
        "cash_conversion": _bucket(latest.get("cash_conversion"), 0.1),
        "loss_quarters": ttm.get("loss_quarters"),
        "strongest_quarter": _extremes(ratios, "net_margin")[0],
        "weakest_quarter": _extremes(ratios, "net_margin")[1],
        "fields_absent": sorted(absent),
        "absent_because": absent,
    }


# ── Rendering ────────────────────────────────────────────────────────────────


def _show_pct(value: Optional[float], *, signed: bool = True) -> str:
    if value is None:
        return UNKNOWN
    return f"{value:+.0f}%" if signed else f"{value:.0f}%"


def _show(value: Optional[float], suffix: str = "") -> str:
    return UNKNOWN if value is None else f"{value:g}{suffix}"


def financials_values(facts: dict[str, Any]) -> dict[str, str]:
    """The prompt's blocks, rendered from `facts` and from nothing else."""
    name = facts.get("name") or facts.get("ticker") or UNKNOWN
    instrument = [
        f"- Company: {name} ({facts.get('ticker') or UNKNOWN})",
        f"- Sector: {facts.get('sector') or UNKNOWN}",
        f"- Chart of accounts: {facts.get('layout_label')}",
        f"- Newest reported quarter: {facts.get('latest_period') or UNKNOWN}",
        f"- Quarters on the board: {facts.get('quarters_covered')}",
        f"- All money figures below are in {facts.get('unit')}.",
    ]

    if facts.get("deflation_available"):
        basis = [
            "Figures below are REAL: every quarter has been restated into the "
            f"newest quarter's lira using consumer prices. Inflation over the "
            f"trailing year was {_show_pct(facts.get('inflation_yoy_pct'), signed=False)}.",
            f"- Real trailing revenue growth: {_show_pct(facts.get('real_revenue_yoy_pct'))}",
            "- The same figure before inflation was stripped out: "
            f"{_show_pct(facts.get('nominal_revenue_yoy_pct'))}. This second number is "
            "given ONLY so you can name the gap between the two. It is not growth.",
        ]
        if facts.get("newest_quarter_provisional"):
            basis.append(
                "- The newest quarter is deflated with the most recent published "
                "price index rather than its own month, which has not been "
                "published yet. Treat that quarter's real figures as provisional "
                "and say so."
            )
    else:
        reason = REASON_SENTENCES.get(
            facts.get("deflation_reason") or "",
            "The board could not deflate these figures",
        )
        basis = [
            f"{reason}. Say plainly that the figures are nominal and that a "
            "Turkish nominal figure over a year is mostly inflation. Do not "
            "describe any figure below as real, and do not estimate what the "
            "real number would have been.",
            f"- Nominal trailing revenue growth: {_show_pct(facts.get('nominal_revenue_yoy_pct'))}",
        ]

    growth = [
        f"- Trailing revenue: {_show(facts.get('ttm_revenue'))}",
        f"- Trailing EBITDA: {_show(facts.get('ttm_ebitda'))}",
        f"- Trailing net income: {_show(facts.get('ttm_net_income'))}",
        f"- Real EBITDA growth: {_show_pct(facts.get('real_ebitda_yoy_pct'))}",
        f"- Real net income growth: {_show_pct(facts.get('real_net_income_yoy_pct'))}",
        f"- Real equity growth: {_show_pct(facts.get('real_equity_yoy_pct'))}",
    ]
    losses = facts.get("loss_quarters")
    growth.append(
        f"- Loss-making quarters in the last four: {losses}"
        if losses is not None
        else "- Loss-making quarters in the last four: not measurable, the window is short"
    )

    margins = [
        f"- Gross margin: {_show_pct(facts.get('gross_margin_pct'), signed=False)}",
        f"- Operating margin: {_show_pct(facts.get('operating_margin_pct'), signed=False)}",
        f"- EBITDA margin: {_show_pct(facts.get('ebitda_margin_pct'), signed=False)}",
        f"- Net margin: {_show_pct(facts.get('net_margin_pct'), signed=False)}",
        "- Change in net margin against a year ago, in percentage points: "
        f"{_show_pct(facts.get('margin_trend_pp'))}",
        "A margin is a ratio of two figures in the same period's lira, so "
        "inflation cancels out of it. These are the same numbers in either frame.",
    ]
    if facts.get("strongest_quarter"):
        margins.append(
            f"- Widest net margin on the board: {facts['strongest_quarter']}; "
            f"narrowest: {facts.get('weakest_quarter')}"
        )

    balance = [
        f"- Return on equity, trailing, against average equity: "
        f"{_show_pct(facts.get('roe_pct'), signed=False)}",
        f"- Net debt to trailing EBITDA: {_show(facts.get('net_debt_ebitda'), 'x')}",
        "- Share of debt due within a year: "
        f"{_show_pct(facts.get('short_debt_share_pct'), signed=False)}",
        f"- Current ratio: {_show(facts.get('current_ratio'))}",
    ]

    conversion = facts.get("cash_conversion")
    cash = [
        f"- Operating cash flow over net income, trailing: {_show(conversion, 'x')}",
        "Below 1.0 means the reported profit has not arrived as cash — in "
        "Turkey usually receivables or inventory. Above 1.0 means it has.",
    ]

    absent = facts.get("absent_because") or {}
    if not absent:
        coverage = "Every line this board draws is present for this company."
    else:
        by_layout = [FIELD_LABELS[f] for f, why in sorted(absent.items()) if why == ABSENT_LAYOUT]
        unreported = [
            FIELD_LABELS[f] for f, why in sorted(absent.items()) if why == ABSENT_UNREPORTED
        ]
        lines = []
        if by_layout:
            lines.append(
                f"- Not in this chart of accounts at all: {', '.join(by_layout)}. "
                "These lines do not exist for this kind of company. Do not say "
                "the company failed to report them."
            )
        if unreported:
            lines.append(
                f"- In the chart of accounts, but not reported by this company: "
                f"{', '.join(unreported)}."
            )
        lines.append(
            "If you would have leaned on one of these, say which and that it is "
            "missing, rather than working around it silently."
        )
        coverage = "\n".join(lines)

    return {
        "instrument": "\n".join(instrument),
        "basis": "\n".join(basis),
        "growth": "\n".join(growth),
        "margins": "\n".join(margins),
        "balance": "\n".join(balance),
        "cash": "\n".join(cash),
        "coverage": coverage,
    }


# ── Entry point ──────────────────────────────────────────────────────────────


async def note_for_financials(payload: dict[str, Any]) -> dict[str, Any]:
    facts = financials_facts(payload)
    if facts is None:
        from services.ai_notes import unavailable

        return unavailable("insufficient_history")
    return await get_note(NOTE_SPEC, facts, financials_values(facts))
