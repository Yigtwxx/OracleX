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


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-TIMEFRAME READ
# ═══════════════════════════════════════════════════════════════════════════════


def _oscillating(low, high, cycles, *, bars_per_leg=3, volume=100.0):
    """
    A series that bounces between two prices, so the swing detector has real
    reversals to find at known levels.
    """
    closes = []
    for _ in range(cycles):
        closes += [low + (high - low) * i / bars_per_leg for i in range(bars_per_leg)]
        closes += [high - (high - low) * i / bars_per_leg for i in range(bars_per_leg)]
    return _candles(closes, spread=0.05, volume=volume)


class TestRsiSeries:
    def test_is_aligned_to_the_closes_it_was_given(self):
        closes = [100 + (i % 5) for i in range(40)]
        series = ta.rsi_series(closes, 14)

        assert len(series) == len(closes), "A misaligned series would read RSI at the wrong bar"
        assert series[:14] == [None] * 14, "RSI does not exist before its first full period"
        assert all(v is not None for v in series[14:])

    def test_last_value_is_the_scalar_rsi(self):
        closes = [100 + (i % 7) - 3 for i in range(60)]
        assert ta.rsi_series(closes, 14)[-1] == ta.calculate_rsi(closes, 14)

    def test_empty_below_one_period(self):
        assert ta.rsi_series([100.0] * 5, 14) == [None] * 5


class TestZones:
    def test_reversals_at_one_price_become_one_band(self):
        candles = _oscillating(100.0, 110.0, 6)
        zones = ta.build_zones(candles, 105.0, timeframe="1d", horizon="medium")

        assert zones["support"], "Repeated bounces at 100 must produce a support band"
        assert zones["resistance"], "Repeated rejections at 110 must produce a resistance band"

        support = zones["support"][0]
        assert support["low"] <= 100.5 <= support["high"] + 1, (
            f"The support band should sit around 100, got {support['low']}-{support['high']}"
        )
        assert support["touches"] >= 2, "A band is only a band because price reversed there twice"

    def test_a_band_straddling_spot_is_neither_support_nor_resistance(self):
        candles = _oscillating(100.0, 110.0, 6)
        zones = ta.build_zones(candles, 100.2, timeframe="1d", horizon="medium")

        for zone in zones["support"] + zones["resistance"]:
            assert not (zone["low"] <= 100.2 <= zone["high"]), (
                "Price inside a band is a fact about the band, not two levels"
            )

    def test_no_zones_without_enough_history(self):
        zones = ta.build_zones(_candles([100.0] * 10), 100.0, timeframe="1d", horizon="medium")
        assert zones == {"support": [], "resistance": []}

    def test_strength_rewards_a_flipped_band(self):
        flipped = [
            ta.Swing(10, 100.0, 100.0, 0, "high"),
            ta.Swing(20, 100.0, 100.0, 0, "low"),
        ]
        one_sided = [
            ta.Swing(10, 100.0, 100.0, 0, "high"),
            ta.Swing(20, 100.0, 100.0, 0, "high"),
        ]

        assert ta._zone_strength(flipped, 100, 100.0) > ta._zone_strength(one_sided, 100, 100.0), (
            "A level that has acted as both support and resistance is the one traders watch"
        )


class TestZoneMerging:
    def _zone(self, low, high, timeframe, horizon, strength=60):
        return {
            "low": low,
            "high": high,
            "mid": (low + high) / 2,
            "touches": 2,
            "flip": False,
            "strength": strength,
            "age_bars": 5,
            "last_touch_at": 1,
            "timeframe": timeframe,
            "horizon": horizon,
            "distance_percent": 0.0,
            "confluence": [],
        }

    def test_overlapping_bands_from_different_timeframes_become_one(self):
        merged = ta._merge_zones(
            [
                self._zone(100.0, 101.0, "4h", "short"),
                self._zone(100.5, 101.5, "1d", "medium"),
                self._zone(100.8, 102.0, "1w", "long"),
            ],
            110.0,
        )

        assert len(merged) == 1, f"One level was found three times, not three levels: {merged}"
        assert merged[0]["timeframes"] == ["1d", "1w", "4h"]
        assert merged[0]["horizon"] == "long", (
            "A band the weekly chart also respects is a long-term band"
        )
        assert merged[0]["touches"] == 6, "Touches from every timeframe count toward the band"
        assert merged[0]["strength"] > 60, "Agreement across timeframes must raise the score"

    def test_separate_levels_stay_separate(self):
        merged = ta._merge_zones(
            [self._zone(100.0, 101.0, "4h", "short"), self._zone(140.0, 141.0, "1w", "long")],
            110.0,
        )
        assert len(merged) == 2, "Bands that do not overlap describe different levels"

    def test_a_chain_of_overlaps_cannot_swallow_the_chart(self):
        # Each band overlaps the next by a hair. Merged blindly they would form
        # one band from 100 to 140, which is not a level, it is the whole range.
        chain = [self._zone(100.0 + i, 101.0 + i, "1d", "medium") for i in range(0, 40, 1)]
        merged = ta._merge_zones(chain, 200.0)

        widest = max(z["high"] - z["low"] for z in merged)
        assert widest <= 3.0, f"Merging ran away: a {widest:.1f}-wide band says nothing"

    def test_each_horizon_keeps_its_best_band(self):
        zones = [
            self._zone(109.0, 109.5, "4h", "short", strength=95),
            self._zone(108.0, 108.5, "4h", "short", strength=94),
            self._zone(107.0, 107.5, "4h", "short", strength=93),
            self._zone(106.0, 106.5, "4h", "short", strength=92),
            self._zone(90.0, 91.0, "1d", "medium", strength=50),
            self._zone(70.0, 72.0, "1w", "long", strength=40),
        ]
        for zone in zones:
            zone["distance_percent"] = (zone["mid"] - 110.0) / 110.0 * 100

        picked = ta._strongest(zones)
        horizons = {z["horizon"] for z in picked}

        assert horizons == {"short", "medium", "long"}, (
            "Strength alone returns five versions of 'just below here' and nothing "
            f"about the longer chart: {horizons}"
        )


class TestStructure:
    def test_reads_rising_swings_as_higher_highs_and_higher_lows(self):
        closes = []
        for step in range(4):
            base = 100 + step * 10
            closes += [base, base + 5, base + 8, base + 3, base + 1]
        assert ta._swing_structure(_candles(closes)) == "higher highs & higher lows"

    def test_no_structure_without_two_swings_each_side(self):
        assert ta._swing_structure(_candles([100 + i for i in range(30)])) is None

    def test_alignment_names_the_conflict(self):
        assert ta._alignment({"4h": "bullish", "1d": "bullish", "1w": "bullish"}).startswith(
            "aligned bullish"
        )
        conflicted = ta._alignment({"4h": "bullish", "1d": "neutral", "1w": "bearish"})
        assert conflicted.startswith("conflicting"), conflicted
        assert "1w bearish" in conflicted, "The reader must be told which horizon disagrees"

    def test_alignment_is_none_without_a_single_trend(self):
        assert ta._alignment({"4h": None, "1d": None}) is None


class TestDivergence:
    def test_finds_a_bearish_divergence(self):
        # A sharp rally to 130, a deep pullback, then a slow grind to a marginally
        # higher high. The second peak is higher in price and lower in RSI, which
        # is the whole definition.
        closes = [100.0] * 15
        closes += [100 + i * 2 for i in range(1, 16)]
        closes += [130 - i * 1.5 for i in range(1, 15)]
        closes += [109 + i * 0.6 for i in range(1, 40)]
        closes += [132 - i * 0.8 for i in range(1, 8)]

        candles = _candles(closes)
        divergence = ta._rsi_divergence(candles, ta.rsi_series([c["close"] for c in candles], 14))

        assert divergence is not None and divergence.startswith("bearish"), divergence

    def test_a_clean_uptrend_is_not_a_divergence(self):
        # Price and momentum rising together. Anything looser than the swing-to-
        # swing comparison finds a divergence here too.
        closes = [100 + i * 1.5 for i in range(80)]
        candles = _candles(closes)

        assert ta._rsi_divergence(candles, ta.rsi_series([c["close"] for c in candles], 14)) is None

    def test_none_on_a_series_with_no_rsi_yet(self):
        candles = _candles([100 + i for i in range(10)])
        assert ta._rsi_divergence(candles, ta.rsi_series([c["close"] for c in candles], 14)) is None


class TestAnalyseTimeframes:
    def _series(self):
        return {
            "4h": _oscillating(100.0, 110.0, 10),
            "1d": _oscillating(95.0, 115.0, 10),
            "1w": _oscillating(80.0, 130.0, 10),
        }

    def test_none_when_no_timeframe_has_enough_history(self):
        short = {label: _candles([100.0] * 5) for label in ("4h", "1d", "1w")}
        assert ta.analyse_timeframes(short, 100.0, ta.CRYPTO_TIMEFRAMES) is None

    def test_a_thin_timeframe_is_dropped_and_named(self):
        series = self._series()
        series["1w"] = _candles([100.0] * 5)

        result = ta.analyse_timeframes(series, 105.0, ta.CRYPTO_TIMEFRAMES)

        assert result is not None
        assert "1w" not in result["timeframes"], "A timeframe without history must not be analysed"
        assert result["coverage"]["1w"]["available"] is False, (
            "The gap must be reported, not silently dropped"
        )
        assert result["coverage"]["1d"]["available"] is True

    def test_flat_fields_come_from_the_daily_read(self):
        series = self._series()
        result = ta.analyse_timeframes(series, 105.0, ta.CRYPTO_TIMEFRAMES)

        assert result["timeframe"] == "1d"
        assert result["rsi_value"] == result["timeframes"]["1d"]["rsi"]["value"]
        assert result["atr"] == result["timeframes"]["1d"]["atr"]
        assert result["trend"] == result["timeframes"]["1d"]["trend"]

    def test_every_zone_carries_a_horizon_and_the_timeframes_that_found_it(self):
        result = ta.analyse_timeframes(self._series(), 105.0, ta.CRYPTO_TIMEFRAMES)

        zones = result["zones"]["support"] + result["zones"]["resistance"]
        assert zones, "A series that bounces between two prices has levels"
        for zone in zones:
            assert zone["horizon"] in ("short", "medium", "long")
            assert zone["timeframes"], "A band with no timeframe behind it cannot be quoted"
            assert zone["low"] <= zone["high"]

    def test_legacy_fields_survive_for_existing_callers(self):
        result = ta.analyse_timeframes(self._series(), 105.0, ta.CRYPTO_TIMEFRAMES)

        for key in (
            "current_price",
            "support_levels",
            "resistance_levels",
            "rsi_value",
            "rsi_signal",
            "pivot_point",
            "atr",
            "trend",
            "timeframe",
        ):
            assert key in result, f"{key} is read by the news panel and the chat prompt"
        assert all(isinstance(level, str) for level in result["support_levels"])


class TestFetchingIsBoundedToTwoYears:
    @pytest.mark.asyncio
    async def test_crypto_asks_for_three_timeframes_and_caps_the_weekly(self, monkeypatch):
        asked = []

        async def _fetch(symbol, interval, limit, **kwargs):
            asked.append((interval, limit))
            return _oscillating(100.0, 110.0, 10)

        async def _ticker(*args, **kwargs):
            return {"price": 105.0}

        monkeypatch.setattr(ta, "fetch_candles", _fetch)
        monkeypatch.setattr(ta, "fetch_ticker_24h", _ticker)

        result = await ta.get_crypto_analysis("BTCUSDT")

        assert result is not None
        assert [interval for interval, _ in asked] == ["4h", "1d", "1w"]
        assert dict(asked)["1w"] == ta.WEEKLY_LOOKBACK == 104, (
            "The weekly read is capped at two years on purpose — older levels "
            "describe a market with different participants"
        )

    @pytest.mark.asyncio
    async def test_equities_request_two_years_of_daily_and_weekly_bars(self, monkeypatch):
        asked = {}

        async def _fetch(symbol, interval="1d", range_="6mo"):
            asked[interval] = range_
            return _oscillating(100.0, 110.0, 10)

        import services.stock_market_service as stock

        monkeypatch.setattr(stock, "fetch_stock_candles", _fetch)

        result = await ta.get_stock_analysis("AAPL")

        assert result is not None
        assert asked == {"1h": "3mo", "1d": "2y", "1wk": "2y"}, asked

    @pytest.mark.asyncio
    async def test_one_dead_timeframe_does_not_kill_the_analysis(self, monkeypatch):
        async def _fetch(symbol, interval, limit, **kwargs):
            if interval == "1w":
                raise RuntimeError("okx said no")
            return _oscillating(100.0, 110.0, 10)

        async def _ticker(*args, **kwargs):
            return {"price": 105.0}

        monkeypatch.setattr(ta, "fetch_candles", _fetch)
        monkeypatch.setattr(ta, "fetch_ticker_24h", _ticker)

        result = await ta.get_crypto_analysis("BTCUSDT")

        assert result is not None, "Two good timeframes are still an analysis"
        assert result["coverage"]["1w"]["available"] is False
