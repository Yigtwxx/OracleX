"""
Where a name is ranked and where it is thrown out. Pure functions, no I/O.

Two rules carry this module. **Missing is not zero**: a ratio the statements
do not carry leaves its component out and the remaining weights are
renormalised, the way `sentiment_service._weighted` does it — a company with a
thin filing is scored on what it did file, not marked down for silence. And
**the veto is separate from the score**: a company in its third losing quarter
is not a low-scoring candidate, it is not a candidate, and no strength on the
chart buys that back.

Every threshold is a module constant with the reasoning beside it, because
these are the numbers a reader will want to argue with.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Optional

from services.bist.radar.fundamentals import Fundamentals, Quarter
from services.bist.radar.profiles import Profile
from services.bist.radar.technical import Levels
from services.bist.real_return import deflate
from services.bist.text import fold
from services.bist.tradingview_client import EquityRow

MIN_RR = 1.5
"""Below this the nearest target does not pay for the stop under the band."""

MIN_TOTAL = 60

MIN_ANALYSTS = 3
"""One analyst is an opinion; three is a consensus worth adjusting for."""

STREET_UPSIDE = 0.20

MIN_SECTOR_SAMPLE = 4
"""Fewer peers than this and the sector median is one company's multiple."""

NET_DEBT_EBITDA_VETO = 4.0
LOSS_QUARTERS_VETO = 3

SECTOR_CLASSES: tuple[str, ...] = ("industrial", "bank", "insurance", "reit", "holding")

VETO_LABELS: dict[str, str] = {
    "negative_equity": "Negatif özkaynak",
    "losses_3_of_4": "Son 4 çeyreğin 3'ü zarar",
    "net_debt_ebitda_gt_4": "Net borç / FAVÖK > 4",
    "interest_coverage_lt_1": "Faiz karşılama < 1",
    "rights_issue_recent": "Yakın tarihli bedelli sermaye artırımı",
    "trading_restriction": "Aktif işlem tedbiri",
}

FLAG_LABELS: dict[str, str] = {
    "earnings_soon": "Bilanço 5 iş günü içinde",
    "quiet_pullback": "Sessiz geri çekilme",
    "heavy_volume": "Satış hacmi yüksek",
    "bullish_divergence": "Pozitif RSI uyumsuzluğu",
    "ratios_only": "Mali tablo alınamadı — sadece oranlar",
    "no_fundamentals": "Temel veri yok",
    "kap_unchecked": "KAP kontrolü yapılamadı",
}


@dataclass(frozen=True)
class KapFlags:
    rights_issue: bool
    restriction: bool


@dataclass(frozen=True)
class Adjustment:
    key: str
    label: str
    points: int


@dataclass(frozen=True)
class Street:
    gap_pct: float
    """Average target over price, minus one."""
    mark: Optional[float]
    analysts: int


# ── Classification ──────────────────────────────────────────────────────────


def sector_class(row: EquityRow, fund: Optional[Fundamentals] = None) -> str:
    """
    Which ratio set applies.

    The name outranks the industry label because TradingView files Sabancı
    Holding under `Bölgesel bankalar` on the strength of Akbank; the industry
    outranks the statement layout because an insurer's UFRS filing looks like a
    bank's to a parser. The layout is the last word only when nothing else says.
    """
    name = fold(row.name or "")
    industry = fold(row.industry or "")
    if "holding" in name or "holding" in industry:
        return "holding"
    if "sigorta" in industry or "sigorta" in name or "emeklilik" in name:
        return "insurance"
    if "banka" in industry or "banka" in name:
        return "bank"
    if "gayr" in industry or "gyo" in name.split() or "gayrimenkul yat" in name:
        return "reit"
    if fund is not None and fund.layout == "bank":
        return "bank"
    if fund is not None and fund.layout == "insurance":
        return "insurance"
    return "industrial"


def uses_ebitda(klass: str) -> bool:
    return klass in ("industrial", "holding", "reit")


# ── Weighted average over what is measurable ────────────────────────────────


def weighted(components: list[tuple[Optional[float], float]]) -> Optional[float]:
    """Weighted mean of the components that exist, in 0..1; None when none do."""
    present = [(v, w) for v, w in components if v is not None and w > 0]
    if not present:
        return None
    total = sum(w for _, w in present)
    return sum(max(0.0, min(1.0, v)) * w for v, w in present) / total


def scale(value: Optional[float], low: float, high: float) -> Optional[float]:
    """Linear 0..1 between `low` and `high`; reversed when `high < low`."""
    if value is None:
        return None
    if high == low:
        return None
    frac = (value - low) / (high - low)
    return max(0.0, min(1.0, frac))


# ── Sector medians ──────────────────────────────────────────────────────────

ALL_SECTORS = "__all__"


def sector_medians(rows: list[EquityRow]) -> dict[str, dict[str, Optional[float]]]:
    """Median P/E, P/B and EV/EBITDA per sector, positives only, plus the universe."""
    buckets: dict[str, dict[str, list[float]]] = {}

    def add(sector: str, field: str, value: Optional[float]) -> None:
        if value is None or value <= 0:
            return
        buckets.setdefault(sector, {}).setdefault(field, []).append(value)

    for row in rows:
        for sector in (row.sector or "", ALL_SECTORS):
            add(sector, "pe", row.pe)
            add(sector, "pb", row.pb)
            add(sector, "ev_ebitda", row.ev_ebitda)

    out: dict[str, dict[str, Optional[float]]] = {}
    for sector, fields in buckets.items():
        out[sector] = {
            field: (statistics.median(values) if len(values) >= MIN_SECTOR_SAMPLE else None)
            for field, values in fields.items()
        }
    return out


def _median_for(
    medians: dict[str, dict[str, Optional[float]]], sector: str, field: str
) -> Optional[float]:
    value = medians.get(sector, {}).get(field)
    if value is None:
        value = medians.get(ALL_SECTORS, {}).get(field)
    return value


# ── Vetoes ──────────────────────────────────────────────────────────────────


def vetoes(row: EquityRow, fund: Optional[Fundamentals], kap: Optional[KapFlags]) -> list[str]:
    out: list[str] = []
    klass = sector_class(row, fund)

    if fund is not None and fund.quarters:
        latest = fund.quarters[0]
        if latest.equity is not None and latest.equity < 0:
            out.append("negative_equity")

        recent = [q.net_income for q in fund.quarters[:4] if q.net_income is not None]
        if (
            len(recent) >= LOSS_QUARTERS_VETO
            and sum(1 for v in recent if v < 0) >= LOSS_QUARTERS_VETO
        ):
            out.append("losses_3_of_4")

        if uses_ebitda(klass):
            ratio = net_debt_to_ebitda(fund)
            if ratio is not None and ratio > NET_DEBT_EBITDA_VETO:
                out.append("net_debt_ebitda_gt_4")
            coverage = interest_coverage(fund)
            if coverage is not None and coverage < 1:
                out.append("interest_coverage_lt_1")

    if kap is not None:
        if kap.rights_issue:
            out.append("rights_issue_recent")
        if kap.restriction:
            out.append("trading_restriction")
    return out


# ── Statement arithmetic ────────────────────────────────────────────────────


def ttm(quarters: tuple[Quarter, ...], field: str, offset: int = 0) -> Optional[float]:
    """Sum of four quarters starting `offset` quarters back; None if any is missing."""
    window = quarters[offset : offset + 4]
    if len(window) < 4:
        return None
    values = [getattr(q, field) for q in window]
    if any(v is None for v in values):
        return None
    return float(sum(values))


def net_debt(quarter: Quarter) -> Optional[float]:
    if quarter.total_debt is None:
        return None
    return quarter.total_debt - (quarter.cash or 0.0)


def net_debt_to_ebitda(fund: Fundamentals) -> Optional[float]:
    """
    Net debt over trailing EBITDA. Positive net debt against zero or negative
    EBITDA is reported as an arbitrarily large ratio rather than None: the
    company owes money it is not earning, which is the case the veto exists for.
    """
    if not fund.quarters:
        return None
    debt = net_debt(fund.quarters[0])
    ebitda = ttm(fund.quarters, "ebitda")
    if debt is None or ebitda is None:
        return None
    if debt <= 0:
        return 0.0
    if ebitda <= 0:
        return float("inf")
    return debt / ebitda


def interest_coverage(fund: Fundamentals) -> Optional[float]:
    ebit = ttm(fund.quarters, "operating_profit")
    expense = ttm(fund.quarters, "financing_expense")
    if ebit is None or expense is None or expense >= 0:
        return None
    return ebit / abs(expense)


def real_growth(fund: Fundamentals, field: str, inflation: Optional[float]) -> Optional[float]:
    """Trailing year over the year before, with CPI stripped out. None if either is missing."""
    now = ttm(fund.quarters, field)
    before = ttm(fund.quarters, field, offset=4)
    if now is None or before is None or before <= 0:
        return None
    nominal = now / before - 1
    if inflation is None:
        return None
    return deflate(nominal, inflation)


def level_growth(fund: Fundamentals, field: str, inflation: Optional[float]) -> Optional[float]:
    """A balance a year ago to now — equity, assets — with CPI stripped out."""
    if len(fund.quarters) < 5:
        return None
    now = getattr(fund.quarters[0], field)
    before = getattr(fund.quarters[4], field)
    if now is None or before is None or before <= 0 or inflation is None:
        return None
    return deflate(now / before - 1, inflation)


def margin_trend(fund: Fundamentals, numerator: str) -> Optional[float]:
    """Trailing margin minus the year-before margin, in fraction points."""
    now_num, now_rev = ttm(fund.quarters, numerator), ttm(fund.quarters, "revenue")
    old_num, old_rev = (
        ttm(fund.quarters, numerator, offset=4),
        ttm(fund.quarters, "revenue", offset=4),
    )
    if None in (now_num, now_rev, old_num, old_rev) or not now_rev or not old_rev:
        return None
    return now_num / now_rev - old_num / old_rev


# ── Scores ──────────────────────────────────────────────────────────────────


def technical_score(levels: Levels, profile: Profile) -> int:
    """
    0–100. Trend 30, pullback quality 30, volume 15, reward/risk 25.

    Reward/risk is scored on a line from the floor to 3:1 rather than open-ended,
    because a 6:1 target that sits at a two-year high is a wish, not twice as
    good a trade.
    """
    trend = 0.6
    if levels.structure == "higher":
        trend += 0.2
    if levels.sma50_gap is not None and levels.sma50_gap > 0.02:
        trend += 0.2

    at_band = levels.price <= levels.entry_high
    near_band = levels.price <= levels.entry_high + 0.5 * levels.atr
    pullback = 0.4 if at_band else 0.27 if near_band else 0.13
    mid = (profile.rsi_low + profile.rsi_high) / 2
    span = (profile.rsi_high - profile.rsi_low) / 2
    pullback += 0.33 if abs(levels.rsi - mid) <= span / 3 else 0.2
    if levels.zone_touches >= 3:
        pullback += 0.14
    if levels.rsi_divergence == "bullish":
        pullback += 0.13

    volume: Optional[float]
    if levels.volume_ratio is None:
        volume = None
    elif levels.volume_ratio < 0.8:
        volume = 1.0
    elif levels.volume_ratio < 1.0:
        volume = 0.67
    elif levels.volume_ratio < 1.5:
        volume = 0.33
    else:
        volume = 0.0

    rr = scale(levels.rr, MIN_RR, 3.0)
    rr = None if rr is None else 0.4 + 0.6 * rr

    score = weighted([(trend, 30), (pullback, 30), (volume, 15), (rr, 25)])
    return round((score or 0.0) * 100)


def fundamental_score(
    row: EquityRow,
    fund: Optional[Fundamentals],
    medians: dict[str, dict[str, Optional[float]]],
    inflation: Optional[float],
) -> tuple[Optional[int], float]:
    """
    (score 0–100 or None, coverage 0..1).

    Coverage is the share of the weight that had data behind it. A 78 built on
    the valuation multiples alone is not the same reading as a 78 built on eight
    quarters of statements, and the card says which.
    """
    klass = sector_class(row, fund)
    ebitda_based = uses_ebitda(klass)
    q = fund.quarters if fund is not None else ()

    # Valuation, against the sector's median multiple: half the median scores
    # full, 1.6x the median scores nothing.
    def versus_median(value: Optional[float], field: str) -> Optional[float]:
        median = _median_for(medians, row.sector or "", field)
        if value is None or value <= 0 or not median:
            return None
        return scale(value / median, 1.6, 0.5)

    valuation_parts = [(versus_median(row.pe, "pe"), 1.0), (versus_median(row.pb, "pb"), 1.0)]
    if ebitda_based:
        valuation_parts.append((versus_median(row.ev_ebitda, "ev_ebitda"), 1.0))
    valuation = weighted(valuation_parts)

    # Profitability. ROE is judged against the lira: at 30-odd percent inflation
    # a 12% return on equity is a real loss, so the scale runs to 45%.
    roe = scale(row.roe, 0.05, 0.45)
    if fund is not None and ebitda_based:
        trend = margin_trend(fund, "ebitda")
    elif fund is not None and klass == "bank":
        trend = margin_trend(fund, "net_income")
    else:
        trend = None
    trend_score = None if trend is None else scale(trend, -0.03, 0.03)
    profitability = weighted([(roe, 1.0), (trend_score, 1.0)])

    # Growth, real. Nominal growth below inflation is zero here — the revenue
    # line grew and the company shrank.
    if fund is not None:
        if ebitda_based:
            growth_parts = [
                (scale(real_growth(fund, "revenue", inflation), -0.10, 0.25), 1.0),
                (scale(real_growth(fund, "ebitda", inflation), -0.10, 0.30), 1.0),
            ]
        else:
            growth_parts = [(scale(real_growth(fund, "net_income", inflation), -0.10, 0.30), 1.0)]
        growth = weighted(growth_parts)
    else:
        nominal = row.revenue_growth if ebitda_based else row.net_income_growth
        real = (
            deflate(nominal, inflation) if nominal is not None and inflation is not None else None
        )
        growth = scale(real, -0.10, 0.25)

    # Balance sheet.
    if q and ebitda_based:
        latest = q[0]
        leverage = net_debt_to_ebitda(fund) if fund else None
        leverage_score = (
            None
            if leverage is None
            else 0.0
            if leverage == float("inf")
            else scale(leverage, 4.0, 0.0)
        )
        current = (
            latest.current_assets / latest.current_liabilities
            if latest.current_assets is not None and latest.current_liabilities
            else row.current_ratio
        )
        short_share = (
            latest.short_term_debt / latest.total_debt
            if latest.short_term_debt is not None and latest.total_debt
            else None
        )
        balance = weighted(
            [
                (leverage_score, 2.0),
                (scale(current, 0.8, 2.0), 1.0),
                (scale(short_share, 0.8, 0.3), 1.0),
            ]
        )
    elif q and klass in ("bank", "insurance"):
        latest = q[0]
        equity_ratio = (
            latest.equity / latest.total_assets
            if latest.equity is not None and latest.total_assets
            else None
        )
        equity_growth = level_growth(fund, "equity", inflation) if fund else None
        balance = weighted(
            [(scale(equity_ratio, 0.06, 0.14), 1.0), (scale(equity_growth, -0.10, 0.20), 1.0)]
        )
    else:
        balance = weighted(
            [
                (scale(row.debt_to_equity, 2.0, 0.0), 1.0),
                (scale(row.current_ratio, 0.8, 2.0), 1.0),
            ]
        )

    # Cash conversion and the dividend record.
    if q and ebitda_based:
        ocf, income = ttm(q, "ocf"), ttm(q, "net_income")
        conversion = scale(ocf / income, 0.5, 1.2) if ocf is not None and income else None
        fcf_quarters = [x.fcf for x in q[:4] if x.fcf is not None]
        fcf_positive = (
            sum(1 for v in fcf_quarters if v > 0) / len(fcf_quarters) if fcf_quarters else None
        )
        paid = [x.dividends_paid for x in q[:4] if x.dividends_paid is not None]
        dividend = None if not paid else (1.0 if any(v < 0 for v in paid) else 0.3)
        cash = weighted([(conversion, 1.0), (fcf_positive, 1.0), (dividend, 0.5)])
    else:
        dividend = None if row.dividend_yield is None else (1.0 if row.dividend_yield > 0 else 0.3)
        cash = weighted([(dividend, 1.0)])

    components = [
        (valuation, 25.0),
        (profitability, 20.0),
        (growth, 20.0),
        (balance, 20.0),
        (cash, 15.0),
    ]
    score = weighted(components)
    covered = sum(w for v, w in components if v is not None) / sum(w for _, w in components)
    return (None if score is None else round(score * 100)), round(covered, 2)


def street(row: EquityRow) -> Optional[Street]:
    if not row.price or row.target_avg is None or not row.analyst_count:
        return None
    return Street(
        gap_pct=round(row.target_avg / row.price - 1, 4),
        mark=row.analyst_mark,
        analysts=row.analyst_count,
    )


def analyst_adjustment(row: EquityRow) -> Optional[Adjustment]:
    """
    ±5 from the consensus target, applied only with a real sample behind it.

    An adjuster rather than a component: the street's target is a claim about
    the future, and this scan scores what the company and the chart have
    already done.
    """
    view = street(row)
    if view is None or view.analysts < MIN_ANALYSTS:
        return None
    if view.gap_pct > STREET_UPSIDE:
        return Adjustment("street_upside", "Sokak hedefi %20+ üstte", 5)
    if view.gap_pct < 0:
        return Adjustment("above_street_target", "Fiyat sokak hedefinin üstünde", -5)
    return None


def total_score(
    technical: Optional[int],
    fundamental: Optional[int],
    adjustments: list[Adjustment],
    profile: Profile,
) -> Optional[int]:
    """Weighted by horizon over what exists, then the adjusters. None with no technical read."""
    if technical is None:
        return None
    base = weighted(
        [
            (technical / 100, profile.weight_technical),
            (None if fundamental is None else fundamental / 100, profile.weight_fundamental),
        ]
    )
    if base is None:
        return None
    total = round(base * 100) + sum(a.points for a in adjustments)
    return max(0, min(100, total))


def flags_for(levels: Levels, row: EquityRow) -> list[str]:
    out: list[str] = []
    if levels.volume_ratio is not None and levels.volume_ratio < 1.0:
        out.append("quiet_pullback")
    if levels.volume_ratio is not None and levels.volume_ratio >= 1.5:
        out.append("heavy_volume")
    if levels.rsi_divergence == "bullish":
        out.append("bullish_divergence")
    return out
