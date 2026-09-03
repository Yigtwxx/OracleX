"""
The chart rules of the Radar on synthetic series.

Built series rather than recorded ones, because each test needs exactly one
property — a pullback of a known depth, a structure of lower lows — and a real
chart carries all of them at once.
"""

import math

from services.bist.radar import technical
from services.bist.radar.profiles import PROFILES
from services.bist.tradingview_client import EquityRow

SWING = PROFILES["swing"]


def _row(price: float, **kwargs) -> EquityRow:
    defaults = {
        "ticker": "TEST",
        "symbol": "BIST:TEST",
        "name": "Test",
        "price": price,
        "change_pct": 0.0,
        "change_abs": 0.0,
        "volume": 1e6,
        "traded_value": 1e8,
        "market_cap": 1e10,
        "pe": 8.0,
        "pb": 1.0,
        "ev_ebitda": 5.0,
        "free_float_pct": 0.4,
        "sector": "Sanayi",
        "indices": ("XU100",),
        "sma50": price * 0.97,
        "sma200": price * 0.85,
        "week52_high": price * 1.2,
        "week52_low": price * 0.6,
    }
    defaults.update(kwargs)
    return EquityRow(**defaults)


def _candles(closes: list[float], volumes: list[float] | None = None) -> list[dict]:
    out = []
    for i, close in enumerate(closes):
        day = 1 + i
        year, rest = 2025 + day // 365, day % 365
        month, dom = 1 + rest // 28, 1 + rest % 28
        out.append(
            {
                "date": f"{year}-{month:02d}-{dom:02d}",
                "time": i,
                "open": close,
                "high": close * 1.015,
                "low": close * 0.985,
                "close": close,
                "volume": volumes[i] if volumes else 1e6,
            }
        )
    return out


def _uptrend_with_pullback(
    bars: int = 160, pullback: float = 0.077, down_bars: int = 8
) -> list[float]:
    """
    A rising channel with visible swings, then a pullback towards its last swing low.

    The pullback wiggles rather than falling in a straight line: eight straight
    down closes push a 14-bar RSI under 30, which is a breakdown by the scan's
    own rule, not the cooling-off it is looking for.
    """
    closes = [100 + i * 0.5 + 4 * math.sin(i / 6) for i in range(bars - down_bars)]
    high = max(closes[-20:])
    target = high * (1 - pullback)
    start = closes[-1]
    for i in range(1, down_bars + 1):
        closes.append(start + (target - start) * i / down_bars + 2.5 * math.sin(i * 1.7))
    return closes


class TestGate:
    def test_swing_gate_needs_price_and_sma50_above_sma200(self):
        assert technical.gate(_row(100, sma50=95, sma200=90), SWING) is None
        assert technical.gate(_row(100, sma50=95, sma200=105), SWING) == "below_sma200"
        assert technical.gate(_row(100, sma50=88, sma200=90), SWING) == "sma50_below_sma200"

    def test_missing_averages_are_a_named_reason_not_a_pass(self):
        assert technical.gate(_row(100, sma200=None), SWING) == "no_trend_data"

    def test_short_gate_only_looks_at_sma50(self):
        assert technical.gate(_row(100, sma50=95, sma200=110), PROFILES["short"]) is None


class TestHelpers:
    def test_swing_structure_reads_higher_and_lower(self):
        rising = [10, 12, 9, 14, 11, 16, 13, 18, 15, 20, 17]
        falling = list(reversed(rising))
        assert technical.swing_structure(rising, span=1) == "higher"
        assert technical.swing_structure(falling, span=1) == "lower"
        assert technical.swing_structure([1, 2, 3], span=1) is None

    def test_weekly_closes_take_the_last_close_of_each_iso_week(self):
        candles = [
            {"date": "2026-08-24", "close": 1.0},
            {"date": "2026-08-26", "close": 2.0},
            {"date": "2026-08-31", "close": 3.0},
        ]
        assert technical.weekly_closes(candles) == [2.0, 3.0]

    def test_range_position_is_clamped_and_needs_a_range(self):
        assert technical.range_position(150, 100, 200) == 0.5
        assert technical.range_position(250, 100, 200) == 1.0
        assert technical.range_position(150, 200, 100) is None

    def test_ema_needs_enough_bars(self):
        assert technical.ema([1.0, 2.0], 5) is None
        assert technical.ema([1.0] * 10, 5) == 1.0


class TestAnalyse:
    def test_too_short_a_series_is_named_not_guessed(self):
        result = technical.analyse(_candles([100.0] * 30), _row(100), SWING)
        assert isinstance(result, technical.Rejection)
        assert result.reason == "insufficient_history"

    def test_a_pullback_in_an_uptrend_yields_levels_with_stop_under_the_band(self):
        closes = _uptrend_with_pullback()
        price = closes[-1]
        result = technical.analyse(_candles(closes), _row(price), SWING)
        assert isinstance(result, technical.Levels), getattr(result, "reason", None)
        assert result.stop < result.entry_low <= result.entry_high
        assert result.target1 > price
        assert result.rr > 0
        assert SWING.pullback_min <= result.pullback_pct <= SWING.pullback_max

    def test_no_pullback_is_rejected_as_such(self):
        closes = [100 + i * 0.5 + 4 * math.sin(i / 6) for i in range(160)]
        closes[-1] = max(closes)
        result = technical.analyse(_candles(closes), _row(closes[-1]), SWING)
        assert isinstance(result, technical.Rejection)
        assert result.reason == "not_pulled_back"

    def test_lower_lows_fail_before_anything_else_is_measured(self):
        closes = [200 - i * 0.6 + 4 * math.sin(i / 6) for i in range(160)]
        result = technical.analyse(_candles(closes), _row(closes[-1]), SWING)
        assert isinstance(result, technical.Rejection)
        assert result.reason == "lower_lows"

    def test_every_reason_has_a_turkish_label(self):
        for reason in (
            "no_price",
            "no_trend_data",
            "below_sma50",
            "below_sma200",
            "sma50_below_sma200",
            "insufficient_history",
            "lower_lows",
            "weekly_lower_lows",
            "not_pulled_back",
            "pullback_too_deep",
            "rsi_out_of_band",
            "below_support",
            "far_from_support",
            "no_target",
            "reward_insufficient",
        ):
            assert technical.REASON_LABELS[reason]
