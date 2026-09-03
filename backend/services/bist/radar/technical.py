"""
The chart half of the Radar: is this a pullback inside an uptrend, and where
are the entry, the stop and the targets?

Two passes. `gate` runs on the scanner snapshot alone — price against its
moving averages — and costs nothing, which is what lets the whole index be
screened before a single candle is fetched. `analyse` runs on the daily series
for the survivors and produces `Levels`, or a `Rejection` naming the one rule
that failed. Every threshold comes from the horizon `Profile`; nothing here
knows which horizon it is serving.

Levels are bands and prices computed from swing clusters and ATR, the same
machinery `/api/technical` draws its ladder from — the Radar adds the decision
rules on top, it does not invent a second notion of support.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional, Sequence

from services.bist.radar.profiles import Profile
from services.bist.tradingview_client import EquityRow
from services.technical_analysis_service import (
    _rsi_divergence,
    build_zones,
    calculate_atr,
    rsi_series,
)

MIN_BARS = 60
"""Fewer than three months of daily bars cannot carry a 50-bar average, let alone a 100."""

REACH_ATR = 1.0
"""How far above the entry band price may sit and still count as 'at' it."""

BELOW_ATR = 0.25
"""How far below the band's low price may dip before the band is considered lost."""

MIN_TARGET_DISTANCE = 0.02
"""A target closer than 2% is noise, not a target."""

EARNINGS_SOON_DAYS = 5

REASON_LABELS: dict[str, str] = {
    "no_price": "Fiyat yok",
    "no_trend_data": "Ortalama verisi yok",
    "below_sma50": "SMA50 altında",
    "below_sma200": "SMA200 altında",
    "sma50_below_sma200": "SMA50, SMA200 altında",
    "insufficient_history": "Yeterli geçmiş yok",
    "lower_lows": "Dipler alçalıyor",
    "weekly_lower_lows": "Haftalık dipler alçalıyor",
    "not_pulled_back": "Geri çekilme yok",
    "pullback_too_deep": "Geri çekilme çok derin",
    "rsi_out_of_band": "RSI bandın dışında",
    "below_support": "Destek kaybedilmiş",
    "far_from_support": "Destekten uzak",
    "no_target": "Üstte hedef yok",
    "reward_insufficient": "Ödül/risk yetersiz",
}


@dataclass(frozen=True)
class Rejection:
    reason: str

    @property
    def label(self) -> str:
        return REASON_LABELS.get(self.reason, self.reason)


@dataclass(frozen=True)
class Levels:
    entry_low: float
    entry_high: float
    stop: float
    target1: float
    target2: Optional[float]
    rr: float
    atr: float
    price: float
    pullback_pct: float
    """Distance below the 20-bar high, as a fraction."""
    rsi: float
    rsi_divergence: Optional[str]
    volume_ratio: Optional[float]
    """Mean volume of the last five bars over the twenty before them. <1 is a quiet pullback."""
    structure: Optional[str]
    """`higher`, `lower` or `mixed` from the last two swing highs and lows."""
    zone_touches: int
    """How many swings built the entry band; 0 when the band is the moving average."""
    zone_source: str
    """`support_zone` or `moving_average`."""
    range_position: Optional[float]
    ema_fast: float
    ema_slow: float
    high20: float
    sma50_gap: Optional[float]
    """SMA50 over SMA200 minus one; how far apart the averages are."""

    @property
    def entry_mid(self) -> float:
        return (self.entry_low + self.entry_high) / 2


# ── Snapshot gate ───────────────────────────────────────────────────────────


def gate(row: EquityRow, profile: Profile) -> Optional[str]:
    """The rejection reason, or None when the name is worth fetching candles for."""
    if not row.price:
        return "no_price"
    if profile.trend_gate == "sma50":
        if row.sma50 is None:
            return "no_trend_data"
        return None if row.price > row.sma50 else "below_sma50"
    if row.sma50 is None or row.sma200 is None:
        return "no_trend_data"
    if row.price <= row.sma200:
        return "below_sma200"
    if row.sma50 <= row.sma200:
        return "sma50_below_sma200"
    return None


# ── Series helpers ──────────────────────────────────────────────────────────


def ema(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period or period <= 0:
        return None
    k = 2 / (period + 1)
    current = sum(values[:period]) / period
    for value in values[period:]:
        current = value * k + current * (1 - k)
    return current


def sma(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def weekly_closes(candles: Sequence[dict[str, Any]]) -> list[float]:
    """The last close of each ISO week, oldest first."""
    weeks: dict[tuple[int, int], float] = {}
    for candle in candles:
        raw = candle.get("date")
        try:
            day = date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
        iso = day.isocalendar()
        weeks[(iso[0], iso[1])] = float(candle["close"])
    return [weeks[key] for key in sorted(weeks)]


def _swings(values: Sequence[float], span: int) -> tuple[list[float], list[float]]:
    highs: list[float] = []
    lows: list[float] = []
    for i in range(span, len(values) - span):
        window = values[i - span : i + span + 1]
        if values[i] == max(window):
            highs.append(values[i])
        if values[i] == min(window):
            lows.append(values[i])
    return highs, lows


def swing_structure(values: Sequence[float], span: int = 3) -> Optional[str]:
    """`higher`, `lower` or `mixed` from the last two swing highs and lows; None if too few."""
    highs, lows = _swings(values, span)
    if len(highs) < 2 or len(lows) < 2:
        return None
    rising_highs = highs[-1] > highs[-2]
    rising_lows = lows[-1] > lows[-2]
    if rising_highs and rising_lows:
        return "higher"
    if not rising_highs and not rising_lows:
        return "lower"
    return "mixed"


def range_position(price: float, low: Optional[float], high: Optional[float]) -> Optional[float]:
    if low is None or high is None or high <= low:
        return None
    return max(0.0, min(1.0, (price - low) / (high - low)))


def earnings_soon(next_earnings: Optional[str], today: Optional[date] = None) -> bool:
    if not next_earnings:
        return False
    try:
        when = date.fromisoformat(next_earnings[:10])
    except ValueError:
        return False
    days = (when - (today or date.today())).days
    return 0 <= days <= EARNINGS_SOON_DAYS


# ── The read ────────────────────────────────────────────────────────────────


def analyse(candles: list[dict[str, Any]], row: EquityRow, profile: Profile) -> Levels | Rejection:
    """
    Levels for one name, or the first rule it fails.

    Rules run in the order a trader would check them: is the structure intact,
    has price actually pulled back, is momentum cold but not broken, is price at
    a reference the market has respected, and does the nearest target pay for
    the stop. The first failure is the answer; there is no partial credit.
    """
    if len(candles) < MIN_BARS:
        return Rejection("insufficient_history")

    closes = [float(c["close"]) for c in candles]
    price = float(row.price or closes[-1])

    structure = swing_structure(closes)
    if structure == "lower":
        return Rejection("lower_lows")
    if profile.weekly_structure:
        weekly = weekly_closes(candles)
        if swing_structure(weekly, span=2) == "lower":
            return Rejection("weekly_lower_lows")

    high20 = max(float(c["high"]) for c in candles[-20:])
    pullback = 1 - price / high20 if high20 > 0 else 0.0
    if pullback < profile.pullback_min:
        return Rejection("not_pulled_back")
    if pullback > profile.pullback_max:
        return Rejection("pullback_too_deep")

    rsis = rsi_series(closes, 14)
    rsi = rsis[-1]
    if rsi is None or not (profile.rsi_low <= rsi <= profile.rsi_high):
        return Rejection("rsi_out_of_band")

    atr = calculate_atr(candles, 14)
    if not atr or atr <= 0:
        return Rejection("insufficient_history")

    fast = ema(closes, profile.ema_fast)
    slow = ema(closes, profile.ema_slow)
    if fast is None or slow is None:
        return Rejection("insufficient_history")

    zones = build_zones(candles, price, timeframe="1d", horizon="single", atr=atr, per_side=3)
    band = _entry_band(price, atr, slow, zones["support"])
    if band is None:
        return Rejection("far_from_support" if price > slow else "below_support")
    entry_low, entry_high, touches, source = band
    if price < entry_low - BELOW_ATR * atr:
        return Rejection("below_support")
    if price > entry_high + REACH_ATR * atr:
        return Rejection("far_from_support")

    stop = entry_low - profile.stop_atr * atr
    targets = _targets(price, zones["resistance"], high20, row.week52_high)
    if not targets:
        return Rejection("no_target")
    target1 = targets[0]
    target2 = targets[1] if len(targets) > 1 else None

    entry_mid = (entry_low + entry_high) / 2
    risk = entry_mid - stop
    if risk <= 0:
        return Rejection("reward_insufficient")
    rr = (target1 - entry_mid) / risk

    volumes = [float(c.get("volume") or 0.0) for c in candles]
    recent = volumes[-5:]
    prior = volumes[-25:-5]
    volume_ratio = None
    if prior and sum(prior) > 0 and recent:
        volume_ratio = (sum(recent) / len(recent)) / (sum(prior) / len(prior))

    sma50 = row.sma50 if row.sma50 is not None else sma(closes, 50)
    sma200 = row.sma200 if row.sma200 is not None else sma(closes, 200)
    sma_gap = (sma50 / sma200 - 1) if sma50 and sma200 else None

    return Levels(
        entry_low=round(entry_low, 4),
        entry_high=round(entry_high, 4),
        stop=round(stop, 4),
        target1=round(target1, 4),
        target2=round(target2, 4) if target2 is not None else None,
        rr=round(rr, 2),
        atr=round(atr, 4),
        price=price,
        pullback_pct=round(pullback, 4),
        rsi=round(rsi, 1),
        rsi_divergence=_rsi_divergence(candles, rsis),
        volume_ratio=round(volume_ratio, 2) if volume_ratio is not None else None,
        structure=structure,
        zone_touches=touches,
        zone_source=source,
        range_position=range_position(price, row.week52_low, row.week52_high),
        ema_fast=round(fast, 4),
        ema_slow=round(slow, 4),
        high20=round(high20, 4),
        sma50_gap=round(sma_gap, 4) if sma_gap is not None else None,
    )


def _entry_band(
    price: float,
    atr: float,
    slow_ema: float,
    supports: Sequence[dict[str, Any]],
) -> Optional[tuple[float, float, int, str]]:
    """
    The band price is being bought at: the nearest support cluster within reach,
    otherwise the slow moving average widened by half an ATR — a level the
    market has *respected*, and the average is only a stand-in when no swing
    cluster sits close enough.
    """
    within_reach = [z for z in supports if price - z["high"] <= REACH_ATR * atr]
    if within_reach:
        zone = max(within_reach, key=lambda z: z["high"])
        return float(zone["low"]), float(zone["high"]), int(zone["touches"]), "support_zone"
    if abs(price - slow_ema) <= REACH_ATR * atr:
        return slow_ema - 0.5 * atr, slow_ema + 0.5 * atr, 0, "moving_average"
    return None


def _targets(
    price: float,
    resistances: Sequence[dict[str, Any]],
    high20: float,
    week52_high: Optional[float],
) -> list[float]:
    """Nearest resistance first. Falls back to the 20-bar high and the 52-week high."""
    floor = price * (1 + MIN_TARGET_DISTANCE)
    mids = sorted(float(z["mid"]) for z in resistances if float(z["mid"]) >= floor)
    out: list[float] = list(mids[:2])
    for fallback in (high20, week52_high):
        if len(out) >= 2:
            break
        if fallback and fallback >= floor and all(abs(fallback - t) / t > 0.01 for t in out):
            out.append(float(fallback))
    return sorted(out)[:2]
