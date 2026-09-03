"""
One parameter set per trading horizon.

The setup is the same at every horizon — an uptrend, a pullback towards a
reference the market has respected, a defined stop under it and a target above
— and only the yardsticks change: how far the pullback may run, how cold the
RSI should be, how wide the stop sits, and how much the balance sheet counts
against the chart. Holding these in one frozen record per horizon keeps the
scan itself free of `if horizon == …` branches.
"""

from dataclasses import dataclass
from typing import Literal

Horizon = Literal["short", "swing", "position"]

HORIZONS: tuple[str, ...] = ("short", "swing", "position")


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    """Turkish, for the toggle and the result header."""
    trend_gate: str
    """`sma50` — price above SMA50; `sma200` — price above SMA200 and SMA50 above it."""
    weekly_structure: bool
    """Also require higher lows on weekly closes (the position horizon)."""
    ema_fast: int
    ema_slow: int
    pullback_min: float
    """Minimum distance below the 20-bar high, as a fraction, for this to count as a pullback."""
    pullback_max: float
    """Beyond this the move is a breakdown, not a pullback."""
    rsi_low: float
    rsi_high: float
    stop_atr: float
    """ATR multiples below the entry band's low."""
    candle_range: str
    """Yahoo range string for the daily series."""
    weight_technical: float
    weight_fundamental: float


PROFILES: dict[str, Profile] = {
    "short": Profile(
        key="short",
        label="Kısa (1-5 gün)",
        trend_gate="sma50",
        weekly_structure=False,
        ema_fast=10,
        ema_slow=20,
        pullback_min=0.02,
        pullback_max=0.08,
        rsi_low=35,
        rsi_high=60,
        stop_atr=1.0,
        candle_range="1y",
        weight_technical=0.8,
        weight_fundamental=0.2,
    ),
    "swing": Profile(
        key="swing",
        label="Swing (1-4 hafta)",
        trend_gate="sma200",
        weekly_structure=False,
        ema_fast=20,
        ema_slow=50,
        pullback_min=0.04,
        pullback_max=0.15,
        rsi_low=35,
        rsi_high=55,
        stop_atr=1.0,
        candle_range="1y",
        weight_technical=0.6,
        weight_fundamental=0.4,
    ),
    "position": Profile(
        key="position",
        label="Pozisyon (1-6 ay)",
        trend_gate="sma200",
        weekly_structure=True,
        ema_fast=50,
        ema_slow=100,
        pullback_min=0.05,
        pullback_max=0.20,
        rsi_low=35,
        rsi_high=55,
        stop_atr=1.5,
        candle_range="2y",
        weight_technical=0.4,
        weight_fundamental=0.6,
    ),
}


def get_profile(horizon: str) -> Profile:
    """Raises `KeyError` for an unknown horizon; the router turns that into a 422."""
    return PROFILES[horizon]
