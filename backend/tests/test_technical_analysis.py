"""
Technical analysis must never invent a level.

These lock in the behaviour that replaced `get_fallback_analysis_for_symbol`,
which used to answer every failed fetch with "Calculating..." levels and a
neutral RSI of 50 — values that reached the news panel and the LLM prompt
looking exactly like measurements.
"""

import pytest

from services import technical_analysis_service as ta


def _candles(closes, *, spread=1.0, volume=100.0):
    """Minimal OHLCV series in the shape `okx_market.fetch_candles` returns."""
    return [
        {
            "time": 1_700_000_000 + i * 3600,
            "open": close,
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": volume,
            "volume_usd": volume * close,
        }
        for i, close in enumerate(closes)
    ]


class TestIndicatorsReturnNoneWithoutData:
    def test_rsi_is_none_below_one_period(self):
        assert ta.calculate_rsi([100.0] * 10, period=14) is None

    def test_rsi_is_computed_with_enough_closes(self):
        rsi = ta.calculate_rsi([100 + i for i in range(30)], period=14)
        assert rsi is not None
        assert 0 <= rsi <= 100

    def test_atr_is_none_below_one_period(self):
        assert ta.calculate_atr(_candles([100.0] * 5), period=14) is None

    def test_trend_is_none_below_long_period(self):
        assert ta.calculate_trend([100.0] * 10, 10, 30) is None

    def test_rsi_signal_passes_none_through(self):
        assert ta.get_rsi_signal(None) is None


class TestTargetPriceRequiresRealInputs:
    def test_none_without_atr(self):
        # The removed fallback substituted 2% of spot for a missing ATR, which
        # turned "volatility unknown" into a concrete-looking range.
        assert ta.calculate_target_price(100.0, None, "bullish", 55.0, [], []) is None

    def test_none_without_trend_or_rsi(self):
        assert ta.calculate_target_price(100.0, 2.0, None, 55.0, [], []) is None
        assert ta.calculate_target_price(100.0, 2.0, "bullish", None, [], []) is None

    def test_range_when_every_input_is_present(self):
        target = ta.calculate_target_price(100.0, 2.0, "bullish", 55.0, [95.0], [110.0])
        assert target is not None and " - " in target


class TestAnalyseCandles:
    def test_none_below_minimum_history(self):
        series = _candles([100 + i for i in range(ta.MIN_CANDLES - 1)])
        assert ta.analyse_candles(series, 100.0, "4h") is None

    def test_levels_are_not_padded_to_a_fixed_count(self):
        # A monotonically rising series has nothing above spot to act as
        # resistance. The old code appended `last + atr` until it had two.
        series = _candles([100 + i for i in range(60)])
        result = ta.analyse_candles(series, 200.0, "4h")

        assert result is not None
        assert result["resistance_levels"] == []
        assert all("Calculating" not in level for level in result["support_levels"])

    def test_reports_real_values_on_a_normal_series(self):
        closes = [100 + (i % 7) - 3 for i in range(60)]
        series = _candles(closes)
        result = ta.analyse_candles(series, closes[-1], "4h")

        assert result is not None
        assert result["current_price"] == closes[-1]
        assert result["rsi_value"] is not None
        assert result["timeframe"] == "4h"


class TestNoDataMeansNoAnalysis:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_candles(self, monkeypatch):
        async def _no_candles(*args, **kwargs):
            return []

        monkeypatch.setattr(ta, "fetch_candles", _no_candles)
        assert await ta.get_crypto_analysis("NOTACOIN") is None

    @pytest.mark.asyncio
    async def test_falls_back_to_last_close_without_a_ticker(self, monkeypatch):
        series = _candles([100 + (i % 5) for i in range(60)])

        async def _candles_only(*args, **kwargs):
            return series

        async def _no_ticker(*args, **kwargs):
            return None

        monkeypatch.setattr(ta, "fetch_candles", _candles_only)
        monkeypatch.setattr(ta, "fetch_ticker_24h", _no_ticker)

        result = await ta.get_crypto_analysis("BTCUSDT")
        assert result is not None
        # The last close is a real observation from the same series, unlike a
        # zero or a placeholder.
        assert result["current_price"] == series[-1]["close"]
