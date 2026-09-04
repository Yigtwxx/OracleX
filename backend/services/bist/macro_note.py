"""
What the Turkish macro backdrop says as a whole, above the tiles that draw it.

The macro page prints six figures and two charts and leaves the reader to put
them together, which is the one thing the page cannot do for them: a policy
rate is a number, an inflation print is a number, and the read is what the
first is worth after the second. Three crossings in particular:

* the real policy rate — computed with the Fisher relation rather than by
  subtraction, because at these levels the two differ by a point and the
  subtraction is the one every reader does in their head;
* the lira's depreciation against the policy rate — a currency that lost less
  over the year than the rate paid is a different regime from one that lost
  more, and neither chart says which;
* producer prices against consumer prices — a producer print running ahead of
  the consumer one is pressure that has not arrived yet, and the tile shows
  two percentages side by side without saying so.

Alongside them, the tedbir radar: the exchange's own measures are filed as
disclosures rather than published as a series, so how many landed this week is
a count the page lists but never states.

Every reading is classified in Python and handed to `services/ai_notes` as a
finished set of facts, the contract `market_note` and `viop_note` hold to: a
local model asked to do arithmetic does it confidently and wrongly, and the
Fisher relation is exactly the arithmetic it would get wrong.

**Bucketing is load-bearing.** The snapshot is cached for half an hour and the
lira quote inside it moves every time it is refreshed, so fingerprinting a raw
rate would retire the note on every refresh. Every reading is snapped, and the
prompt is rendered from the same snapped values, so a cached note can never
quote a figure that has since moved.

Nothing here raises. A note is a paragraph above a page that is already
complete, so every failure comes back as `unavailable` and the tiles stay up.
"""

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from services.ai_notes import (
    REASON_INSUFFICIENT_DATA,
    NoteSpec,
    get_note,
    unavailable,
)
from services.bist.kap_service import Disclosure, KapUnavailable, fetch_tape, filter_restrictions
from services.bist.macro_service import (
    MacroSnapshot,
    MacroUnavailable,
    fetch_cpi_series,
    fetch_macro_snapshot,
    fetch_usdtry_series,
)
from services.bist.text import fold

logger = logging.getLogger(__name__)

UNKNOWN = "not available"

MACRO_SPEC = NoteSpec(
    kind="bist_macro",
    prompt="notes/bist_macro",
    # The room the other board-wide reads get: this crosses rates, the
    # currency, prices and the exchange's measures rather than describing one.
    max_tokens=480,
    max_chars=1200,
    temperature=0.25,
    max_age_seconds=6 * 3600,
)

# What this read does not cover, named rather than left implicit. Every one of
# these is a figure a Turkish macro reader will reach for first and none of
# them is on this page.
NOT_MEASURED: tuple[str, ...] = (
    "CDS primi",
    "TCMB rezervleri",
    "swap ve mevduat faizleri",
    "yabancı payı",
    "cari denge",
)

# A year of daily lira closes, for the twelve-month depreciation the carry read
# needs. Kept to one range so the note's series and the page's do not diverge.
FX_RANGE = "1y"

# The tedbir radar's window. A week, because measures are filed in bursts
# around a volatile session and a count over a longer window is a count of
# how volatile the quarter was rather than of what the exchange did lately.
MEASURE_WINDOW_DAYS = 7
# Read well past the count: measures are a thin slice of an already filtered
# tape. Same ratio the restrictions route uses, for the same reason.
MEASURE_TAPE_ROWS = 240

# How far the real policy rate has to sit from zero, in points, before it is
# a positive or a negative rate rather than a flat one. Two points: the
# inflation print alone moves by more than one between months.
REAL_RATE_DEADBAND_PCT = 2.0

STANCE_REAL_POSITIVE = "real_positive"
STANCE_REAL_NEAR_ZERO = "real_near_zero"
STANCE_REAL_NEGATIVE = "real_negative"

# The exchange's measures by the fixed phrasing Borsa İstanbul files them
# under, in the order a reader ranks them by severity. Substrings, because
# these do not vary — see `kap_service.RESTRICTION_PHRASES`.
MEASURE_KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("circuit_breaker", ("Devre Kesici",)),
    ("short_selling", ("Açığa Satış",)),
    ("gross_settlement", ("Brüt Takas",)),
    ("margin_trading", ("Kredili İşlem",)),
    ("session_closure", ("Sıra Kapatma", "İşlem Sırası")),
    ("price_limit", ("Fiyat Limiti",)),
)
MEASURE_OTHER = "other"
NAMED_TICKERS = 4


# ── Quantization ─────────────────────────────────────────────────────────────


def _zeroed(value: float) -> float:
    """Rounding turns a small negative into `-0.0`, which renders as "-0.0%"."""
    return 0.0 if value == 0 else value


def _bucket(value: float | None, step: float) -> float | None:
    """Snap to a multiple of `step`. The whole cache design rests on this."""
    if value is None:
        return None
    return _zeroed(round(round(value / step) * step, 4))


def _pct(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    try:
        return _zeroed(round(float(value) * 100, digits))
    except (TypeError, ValueError):
        return None


def _pct_bucket(value: float | None, step: float) -> float | None:
    """A fraction as percentage points, snapped to `step`."""
    return _bucket(_pct(value, 4), step)


def _day(stamp: str | None) -> str | None:
    return (stamp or "")[:10] or None


# ── Rendering helpers ────────────────────────────────────────────────────────


def _show_pct(value: float | None, sign: bool = True) -> str:
    if value is None:
        return UNKNOWN
    return f"{value:+.1f}%" if sign else f"{value:.1f}%"


def _show_num(value: float | None, digits: int = 2) -> str:
    return UNKNOWN if value is None else f"{value:,.{digits}f}"


# ── Classification ───────────────────────────────────────────────────────────


def real_policy_rate(policy: float | None, inflation: float | None) -> float | None:
    """
    Fisher, not subtraction. Same expression the macro route serves.

    At 37% against 32%, subtracting gives 5 points and the true answer is under
    4 — and the model would subtract, which is why this is computed here.
    """
    if policy is None or inflation is None or inflation <= -1:
        return None
    return (1 + policy) / (1 + inflation) - 1


def classify_macro_stance(real_pct: float | None) -> str:
    """The sign of the real policy rate, from the bucketed figure, with a deadband."""
    if real_pct is None:
        return STANCE_REAL_NEAR_ZERO
    if real_pct >= REAL_RATE_DEADBAND_PCT:
        return STANCE_REAL_POSITIVE
    if real_pct <= -REAL_RATE_DEADBAND_PCT:
        return STANCE_REAL_NEGATIVE
    return STANCE_REAL_NEAR_ZERO


def measure_kind(disclosure: Disclosure) -> str:
    haystack = fold(f"{disclosure.title} {disclosure.summary}")
    for kind, phrases in MEASURE_KINDS:
        if any(fold(phrase) in haystack for phrase in phrases):
            return kind
    return MEASURE_OTHER


# ── Aggregation ──────────────────────────────────────────────────────────────


def fx_change(series: list[dict], days: int) -> float | None:
    """
    The lira's move over `days` calendar days, as a fraction of the earlier rate.

    Anchored on the newest point and the last point at or before the target
    date, so a weekend or a holiday does not shift the window onto a different
    week. None when the series does not reach back far enough — a one-month
    change measured over three weeks is a different number wearing its name.
    """
    if len(series) < 2:
        return None
    try:
        last = series[-1]
        last_day = date.fromisoformat(last["date"])
        target = last_day - timedelta(days=days)
        earlier = None
        for point in series:
            if date.fromisoformat(point["date"]) <= target:
                earlier = point
            else:
                break
        if earlier is None or not earlier["rate"]:
            return None
        return float(last["rate"]) / float(earlier["rate"]) - 1
    except (KeyError, TypeError, ValueError):
        return None


def cpi_momentum(series: list[dict]) -> dict[str, Any] | None:
    """
    The consumer index's own pace, where the series is present.

    The year-on-year rate compares this month with a month a year ago, so it
    moves on what dropped out as much as on what came in. The month-on-month
    change and its three-month annualisation say what prices did lately.
    """
    if len(series) < 4:
        return None
    try:
        latest = float(series[-1]["index"])
        prior = float(series[-2]["index"])
        quarter = float(series[-4]["index"])
    except (KeyError, TypeError, ValueError):
        return None
    if prior <= 0 or quarter <= 0:
        return None
    return {
        "month": series[-1].get("month"),
        "mom_pct": _pct_bucket(latest / prior - 1, 0.1),
        "three_month_annualized_pct": _pct_bucket((latest / quarter) ** 4 - 1, 0.5),
    }


def measures_in_window(disclosures: list[Disclosure], now: datetime) -> dict[str, Any]:
    """The exchange's measures filed inside the window, by kind and by name."""
    cutoff = now - timedelta(days=MEASURE_WINDOW_DAYS)
    by_kind: dict[str, int] = {}
    tickers: list[str] = []
    latest: str | None = None
    for item in disclosures:
        stamp = item.published_at
        if not stamp:
            continue
        try:
            published = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        if published < cutoff:
            continue
        kind = measure_kind(item)
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if item.ticker and item.ticker not in tickers:
            tickers.append(item.ticker)
        day = _day(stamp)
        if day and (latest is None or day > latest):
            latest = day
    return {
        "window_days": MEASURE_WINDOW_DAYS,
        "total": sum(by_kind.values()),
        "by_kind": by_kind,
        "tickers": tickers[:NAMED_TICKERS],
        "latest_day": latest,
    }


def facts_from_snapshot(
    snapshot: MacroSnapshot,
    fx_series: list[dict],
    cpi_series: list[dict],
    measures: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """
    The backdrop as a quantized set of readings, or None.

    Split from `build_macro_facts` so the aggregation can be tested without
    four upstreams in the way. None when the two figures every other reading
    hangs off — the policy rate and the inflation print — are missing.
    """
    if snapshot.policy_rate is None or snapshot.inflation_yoy is None:
        return None

    policy_pct = _pct_bucket(snapshot.policy_rate, 0.25)
    inflation_pct = _pct_bucket(snapshot.inflation_yoy, 0.1)
    ppi_pct = _pct_bucket(snapshot.ppi_yoy, 0.1)
    real_pct = _pct_bucket(real_policy_rate(snapshot.policy_rate, snapshot.inflation_yoy), 0.5)

    change_12m = _pct_bucket(fx_change(fx_series, 365), 0.5)
    carry = (
        _bucket(policy_pct - change_12m, 0.5)
        if policy_pct is not None and change_12m is not None
        else None
    )

    return {
        "stance": classify_macro_stance(real_pct),
        "as_of": _day(snapshot.as_of),
        "stale": snapshot.stale,
        "rates": {
            "policy_pct": policy_pct,
            "inflation_pct": inflation_pct,
            "ppi_pct": ppi_pct,
            "real_policy_pct": real_pct,
            "ppi_cpi_gap_pct": (
                _bucket(ppi_pct - inflation_pct, 0.5)
                if ppi_pct is not None and inflation_pct is not None
                else None
            ),
            "unemployment_pct": _pct_bucket(snapshot.unemployment, 0.1),
            "gdp_pct": _pct_bucket(snapshot.gdp_yoy, 0.1),
        },
        "fx": {
            # A tenth of a lira is two tenths of a percent at these levels,
            # which is roughly a session's crawl; finer than this and the
            # fingerprint would move between one refresh and the next.
            "usdtry": _bucket(snapshot.usdtry, 0.1),
            "eurtry": _bucket(snapshot.eurtry, 0.1),
            "change_1m_pct": _pct_bucket(fx_change(fx_series, 30), 0.5),
            "change_3m_pct": _pct_bucket(fx_change(fx_series, 91), 0.5),
            "change_12m_pct": change_12m,
            "carry_12m_pct": carry,
            "series_points": len(fx_series),
        },
        "prices": cpi_momentum(cpi_series),
        "measures": measures,
        "not_measured": list(NOT_MEASURED),
    }


async def build_macro_facts() -> dict[str, Any] | None:
    """
    The whole backdrop as facts, or None.

    The snapshot is the one upstream that has to answer; the lira series, the
    consumer index and the tape each degrade to "not read" and are said to be.
    """
    try:
        snapshot = await fetch_macro_snapshot()
    except MacroUnavailable as e:
        logger.info("Macro snapshot unavailable for its note: %s", e)
        return None

    fx_series = await fetch_usdtry_series(FX_RANGE)
    cpi_series = await fetch_cpi_series()

    measures: dict[str, Any] | None = None
    try:
        rows = await fetch_tape(MEASURE_TAPE_ROWS, categories=frozenset({"ODA", "DUY"}))
        measures = measures_in_window(filter_restrictions(rows), datetime.now(UTC))
    except KapUnavailable as e:
        logger.info("KAP tape unavailable for the macro note's measures: %s", e)

    return facts_from_snapshot(snapshot, fx_series, cpi_series, measures)


# ── Prompt rendering ─────────────────────────────────────────────────────────

_STANCE_GLOSS: dict[str, str] = {
    STANCE_REAL_POSITIVE: "the policy rate exceeds inflation by more than the deadband",
    STANCE_REAL_NEAR_ZERO: "the policy rate and inflation are within two points of each other",
    STANCE_REAL_NEGATIVE: "inflation exceeds the policy rate by more than the deadband",
}

_KIND_GLOSS: dict[str, str] = {
    "circuit_breaker": "circuit breaker",
    "short_selling": "short-selling ban",
    "gross_settlement": "gross settlement",
    "margin_trading": "margin-trading restriction",
    "session_closure": "trading halt or session closure",
    "price_limit": "price limit",
    MEASURE_OTHER: "other measure",
}


def macro_values(facts: dict[str, Any]) -> dict[str, str]:
    """Render the prompt's placeholders from the facts, and from nothing else."""
    rates = facts["rates"]
    fx = facts["fx"]
    prices = facts["prices"]
    measures = facts["measures"]

    rate_lines = [
        f"- Policy rate (TCMB one-week repo): {_show_pct(rates['policy_pct'], sign=False)}",
        f"- Consumer inflation, year on year: {_show_pct(rates['inflation_pct'], sign=False)}",
        f"- Producer inflation, year on year: {_show_pct(rates['ppi_pct'], sign=False)}",
        f"- Real policy rate, by the Fisher relation (1+rate)/(1+inflation)-1, "
        f"NOT by subtraction: {_show_pct(rates['real_policy_pct'])}",
        f"- Producer minus consumer inflation: {_show_pct(rates['ppi_cpi_gap_pct'])} "
        "(positive means producer prices are running ahead of consumer prices)",
        f"- Unemployment: {_show_pct(rates['unemployment_pct'], sign=False)}",
        f"- GDP growth, year on year: {_show_pct(rates['gdp_pct'])}",
    ]

    fx_lines = [
        f"- USD/TRY: {_show_num(fx['usdtry'])}; EUR/TRY: {_show_num(fx['eurtry'])}",
        f"- Lira against the dollar over one month: {_show_pct(fx['change_1m_pct'])}; "
        f"three months: {_show_pct(fx['change_3m_pct'])}; "
        f"twelve months: {_show_pct(fx['change_12m_pct'])} "
        "(positive means the lira weakened)",
        f"- Policy rate minus the twelve-month depreciation: {_show_pct(fx['carry_12m_pct'])} "
        "— an indication of whether the rate paid has outrun the currency's loss, "
        "not a realised return",
    ]
    if fx["series_points"] == 0:
        fx_lines.append("- The daily lira series could not be read, so no change is measured")

    if prices is None:
        price_lines = [
            "- The monthly consumer price index is not available (no central-bank data "
            "key configured or the series could not be read), so the pace of prices "
            "inside the year is unmeasured; only the year-on-year rate above is known"
        ]
    else:
        price_lines = [
            f"- Consumer index, latest month {prices['month']}: {_show_pct(prices['mom_pct'])} "
            "on the month",
            f"- Three-month change, annualised: {_show_pct(prices['three_month_annualized_pct'])}",
        ]

    if measures is None:
        measure_lines = ["- The KAP tape could not be read, so the exchange's measures are unknown"]
    elif measures["total"] == 0:
        measure_lines = [
            f"- No exchange measure (circuit breaker, short-selling ban, gross settlement, "
            f"margin restriction) was filed in the last {measures['window_days']} days"
        ]
    else:
        measure_lines = [
            f"- Exchange measures filed in the last {measures['window_days']} days: "
            f"{measures['total']}, the latest on {measures['latest_day']}"
        ]
        for kind, _ in MEASURE_KINDS + ((MEASURE_OTHER, ()),):
            count = measures["by_kind"].get(kind)
            if count:
                measure_lines.append(f"- {_KIND_GLOSS[kind]}: {count}")
        if measures["tickers"]:
            measure_lines.append("- Names involved: " + ", ".join(measures["tickers"]))

    staleness = (
        "The snapshot is served from cache because the source did not answer; "
        "say so in the same breath as the read."
        if facts["stale"]
        else "The snapshot is current."
    )

    return {
        "stance": f"{facts['stance'].replace('_', ' ')} — {_STANCE_GLOSS[facts['stance']]}",
        "rates": "\n".join(rate_lines),
        "fx": "\n".join(fx_lines),
        "prices": "\n".join(price_lines),
        "measures": "\n".join(measure_lines),
        "staleness": staleness,
        "not_measured": ", ".join(facts["not_measured"]),
    }


async def macro_note(facts: dict[str, Any] | None, user_id: str | None = None) -> dict[str, Any]:
    """The note for this backdrop, or `unavailable` when there is nothing to read."""
    if not facts:
        return unavailable(REASON_INSUFFICIENT_DATA)
    return await get_note(MACRO_SPEC, facts, macro_values(facts), user_id)
