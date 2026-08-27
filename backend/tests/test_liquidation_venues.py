"""
The heatmap and the levels view model whichever venue was asked for.

Both used to be pinned to OKX while the profile already took a `venue`, so the
same page answered "whose book is this?" two different ways. The failure this
guards is silent in the worst way: a payload labelled Bybit built from OKX's
statistics looks completely normal, and nothing about the chart would say so.

The venue clients are stubbed with deliberately different traded notional, so a
test can tell the books apart by size alone rather than by trusting the label.
"""

import pytest

from services import binance_market, bybit_market
from services import liquidation_map_service as lm


# What the page actually sends. A bare base asset is not a symbol Binance or
# Bybit recognises — `to_binance_symbol("BTC")` is "BTC", which they answer with
# an empty list rather than an error — so testing with one would be testing a
# request the UI never makes.
SYMBOL = "BTCUSDT"


def _candles(count, *, start_ms=1_700_000_000_000, step_ms=3_600_000, close=100.0):
    """Minimal OHLCV series in the shape every venue client returns."""
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


@pytest.fixture
def patched(monkeypatch):
    """Every venue served locally, each with its own traded notional."""
    candles = _candles(120)
    first_ms = candles[0]["time"] * 1000 - 1

    async def fake_okx_candles(inst_id, interval="1h", limit=168):
        return candles

    async def fake_rubik(endpoint, ccy, period, value_index):
        return [(first_ms, 1.0)]

    def scaled(factor):
        async def fetch(symbol, interval="1h", limit=200):
            return [{**candle, "volume_usd": candle["volume_usd"] * factor} for candle in candles]

        return fetch

    async def fake_oi(symbol, interval, limit):
        return [(first_ms, 1.0)]

    async def fake_bybit_oi(symbol, interval, limit):
        # Base units, as the real client returns; the service converts.
        return [(first_ms, 0.01)]

    async def fake_ls(symbol, interval, limit):
        return [(first_ms, 0.5)]

    monkeypatch.setattr(lm.liquidation_service, "fetch_candles", fake_okx_candles)
    monkeypatch.setattr(lm, "_fetch_rubik_series", fake_rubik)
    monkeypatch.setattr(lm.binance_market, "fetch_candles", scaled(3.0))
    monkeypatch.setattr(lm.binance_market, "fetch_open_interest", fake_oi)
    monkeypatch.setattr(lm.binance_market, "fetch_long_share", fake_ls)
    monkeypatch.setattr(lm.bybit_market, "fetch_candles", scaled(2.0))
    monkeypatch.setattr(lm.bybit_market, "fetch_open_interest", fake_bybit_oi)
    monkeypatch.setattr(lm.bybit_market, "fetch_long_share", fake_ls)
    lm._map_cache.clear()
    yield
    lm._map_cache.clear()


def _map_total(result):
    """Every dollar the heatmap's last column places, however it is split."""
    last = len(result["candles"]) - 1
    return sum(
        long_usd + short_usd for column, _, long_usd, short_usd in result["cells"] if column == last
    )


class TestTheHeatmapFollowsItsVenue:
    @pytest.mark.asyncio
    async def test_each_venue_names_itself_and_its_own_instrument(self, patched):
        for venue, exchange, inst_id in (
            (lm.OKX_VENUE, "OKX", "BTC-USDT-SWAP"),
            (lm.BINANCE_VENUE, "Binance", "BTCUSDT"),
            (lm.BYBIT_VENUE, "Bybit", "BTCUSDT"),
        ):
            result = await lm.get_liquidation_map(SYMBOL, columns=60, venue=venue)
            assert result["exchange"] == exchange
            assert result["symbol"] == inst_id, "the payload must carry the id that was asked"

    @pytest.mark.asyncio
    async def test_a_venue_is_modelled_from_its_own_book(self, patched):
        okx = await lm.get_liquidation_map(SYMBOL, columns=60, venue=lm.OKX_VENUE)
        binance = await lm.get_liquidation_map(SYMBOL, columns=60, venue=lm.BINANCE_VENUE)

        # Binance's stub trades three times the notional. A label alone would
        # pass this file's first test while serving OKX's numbers underneath.
        assert _map_total(binance) > _map_total(okx) * 2

    @pytest.mark.asyncio
    async def test_venue_caches_stay_apart(self, patched):
        first = await lm.get_liquidation_map(SYMBOL, columns=60, venue=lm.OKX_VENUE)
        second = await lm.get_liquidation_map(SYMBOL, columns=60, venue=lm.BINANCE_VENUE)
        again = await lm.get_liquidation_map(SYMBOL, columns=60, venue=lm.OKX_VENUE)

        assert second["exchange"] != first["exchange"]
        assert again["exchange"] == first["exchange"], "a second venue evicted the first"


class TestTheLevelsViewFollowsItsVenue:
    @pytest.mark.asyncio
    async def test_each_venue_names_itself(self, patched):
        for venue, exchange in (
            (lm.OKX_VENUE, "OKX"),
            (lm.BINANCE_VENUE, "Binance"),
            (lm.BYBIT_VENUE, "Bybit"),
        ):
            result = await lm.get_liquidation_lines(SYMBOL, columns=60, venue=venue)
            assert result["exchange"] == exchange

    @pytest.mark.asyncio
    async def test_a_venue_is_modelled_from_its_own_book(self, patched):
        okx = await lm.get_liquidation_lines(SYMBOL, columns=60, venue=lm.OKX_VENUE)
        binance = await lm.get_liquidation_lines(SYMBOL, columns=60, venue=lm.BINANCE_VENUE)

        assert max(binance["tier_max"]) > max(okx["tier_max"]) * 2

    @pytest.mark.asyncio
    async def test_venue_caches_stay_apart(self, patched):
        first = await lm.get_liquidation_lines(SYMBOL, columns=60, venue=lm.OKX_VENUE)
        await lm.get_liquidation_lines(SYMBOL, columns=60, venue=lm.BYBIT_VENUE)
        again = await lm.get_liquidation_lines(SYMBOL, columns=60, venue=lm.OKX_VENUE)

        assert again["exchange"] == first["exchange"]


class TestAVenueThatCannotServeTheIntervalStillAnswers:
    """
    The two coarse windows this page offers are the ones the venues disagree on.

    Bybit's candle endpoint had no daily or weekly spelling at all, so selecting
    it at those intervals produced an empty chart rather than a shallow one; and
    both venues publish statistics only down to a span far finer than a weekly
    candle. Neither is a reason to serve nothing: the samples are aligned onto
    candles by "last value at or before", so a finer series is correct on a
    coarser candle, it simply reaches less far back — which is exactly what
    `stats_from_column` already reports.
    """

    @pytest.mark.parametrize("interval", ["4h", "1d", "1w"])
    def test_bybit_spells_every_interval_the_page_offers(self, interval):
        assert bybit_market.KLINE_INTERVALS.get(interval) is not None

    @pytest.mark.parametrize("interval", ["1d", "1w"])
    def test_a_coarse_candle_falls_back_to_the_coarsest_published_span(self, interval):
        assert bybit_market._stat_span(interval) == "4h"

    def test_a_candle_finer_than_the_finest_sample_still_gets_one(self):
        assert bybit_market._stat_span("1m") == "5min"
        assert binance_market._stat_period("1m") == "5m"

    def test_a_weekly_candle_takes_the_daily_series_not_the_hourly_one(self):
        # Five hundred hourly rows cover three weeks of a chart spanning years.
        assert binance_market._stat_period("1w") == "1d"
