"""
The liquidation map must not present modelled-from-nothing columns as equal.

OKX serves a fixed window per statistics resolution and ignores the `limit` we
ask for, so a fine resolution on a long chart runs out partway back. Every candle
older than that gets no open-interest and no long/short sample, and the model
quietly degrades to volume alone with a neutral 50/50 split. These lock in the
two defences: pick a resolution that actually spans the window, and report the
columns that are still left uncovered.
"""

import pytest

from services import liquidation_map_service as lm
from services import okx_market


def _candles(count, *, start_ms=1_700_000_000_000, step_ms=3_600_000, close=100.0):
    """Minimal OHLCV series in the shape `okx_market.fetch_candles` returns."""
    return [
        {
            "time": (start_ms + i * step_ms) // 1000,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 10.0,
            "volume_usd": 1000.0,
        }
        for i in range(count)
    ]


class TestRubikPeriodSelection:
    def test_short_window_keeps_the_finest_resolution(self):
        # 220 one-minute candles is under four hours — well inside 5m's 2 days.
        assert lm._rubik_period("1m", 220) == "5m"

    def test_hourly_window_uses_the_hourly_series(self):
        # 220 hours exceeds 5m's 2-day window but fits 1H's 30 days.
        assert lm._rubik_period("1h", 220) == "1H"

    @pytest.mark.parametrize("interval", ["15m", "4h", "6h", "12h"])
    def test_intervals_that_outran_their_old_period_step_up(self, interval):
        """
        These are the regressions the static table used to hide.

        A 15m chart was pinned to 5m (2 days) while spanning 55 hours, and 4h/6h/
        12h were pinned to 1H (30 days) while spanning 37 to 110 days. Each must
        now land on a resolution whose window actually covers it.
        """
        candles = 220
        period = lm._rubik_period(interval, candles)
        window_ms = dict(okx_market.RUBIK_WINDOW_MS)[period]
        assert window_ms >= candles * okx_market.INTERVAL_MS[interval]

    def test_weekly_window_falls_back_to_the_coarsest(self):
        # 220 weeks is over four years; nothing OKX publishes reaches that far,
        # so take the widest window available and let the caller flag the gap.
        assert lm._rubik_period("1w", 220) == "1D"

    def test_unknown_interval_does_not_raise(self):
        assert lm._rubik_period("nonsense", 220) in dict(okx_market.RUBIK_WINDOW_MS)

    def test_every_supported_interval_has_a_length(self):
        # A missing entry would silently fall back to the 1h default and pick a
        # period too fine for the window.
        from services.okx_market import OKX_BAR_BY_INTERVAL

        assert set(OKX_BAR_BY_INTERVAL) <= set(okx_market.INTERVAL_MS)


class TestStatsCoverageReporting:
    """`stats_from_column` is the map's own account of where its inputs begin."""

    @pytest.fixture
    def patched(self, monkeypatch):
        """Serve fixed candles and let each test choose the statistics series."""
        state = {"oi": [], "ratio": []}

        async def fake_candles(inst_id, interval="1h", limit=168):
            return _candles(120)

        async def fake_rubik(endpoint, ccy, period, value_index):
            return state["oi"] if endpoint == "open-interest-volume" else state["ratio"]

        monkeypatch.setattr(lm.liquidation_service, "fetch_candles", fake_candles)
        monkeypatch.setattr(lm, "_fetch_rubik_series", fake_rubik)
        lm._map_cache.clear()
        return state

    @pytest.mark.asyncio
    async def test_no_statistics_marks_the_whole_window(self, patched):
        # Both endpoints failing returns []; every column is volume-only.
        result = await lm.get_liquidation_map("BTC", interval="1h", columns=60)

        assert result["stats_from_column"] == len(result["candles"])

    @pytest.mark.asyncio
    async def test_full_statistics_marks_nothing(self, patched):
        candles = _candles(120)
        # One sample at or before the very first candle covers all of them.
        series = [(candles[0]["time"] * 1000 - 1, 1.0)]
        patched["oi"] = series
        patched["ratio"] = series

        result = await lm.get_liquidation_map("BTC", interval="1h", columns=60)

        assert result["stats_from_column"] == 0

    @pytest.mark.asyncio
    async def test_partial_statistics_marks_only_the_uncovered_head(self, patched):
        candles = _candles(120)
        emit_from = 120 - 60
        # Series starts 10 emitted columns in, so those 10 are uncovered.
        series = [(candles[emit_from + 10]["time"] * 1000, 1.0)]
        patched["oi"] = series
        patched["ratio"] = series

        result = await lm.get_liquidation_map("BTC", interval="1h", columns=60)

        assert result["stats_from_column"] == 10

    @pytest.mark.asyncio
    async def test_one_missing_series_still_counts_as_uncovered(self, patched):
        candles = _candles(120)
        # Open interest covers everything but the long/short ratio never arrives —
        # the split is still neutral, so the column is not fully modelled.
        patched["oi"] = [(candles[0]["time"] * 1000 - 1, 1.0)]
        patched["ratio"] = []

        result = await lm.get_liquidation_map("BTC", interval="1h", columns=60)

        assert result["stats_from_column"] == len(result["candles"])

    @pytest.mark.asyncio
    async def test_empty_map_still_reports_the_field(self, monkeypatch):
        async def no_candles(inst_id, interval="1h", limit=168):
            return []

        async def no_rubik(endpoint, ccy, period, value_index):
            return []

        monkeypatch.setattr(lm.liquidation_service, "fetch_candles", no_candles)
        monkeypatch.setattr(lm, "_fetch_rubik_series", no_rubik)
        lm._map_cache.clear()

        result = await lm.get_liquidation_map("BTC", interval="1h", columns=60)

        # The frontend reads this on every payload; both branches must define it.
        assert result["stats_from_column"] == 0
