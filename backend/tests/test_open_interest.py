"""
The open-interest board is a sum across venues, which makes it easy to be wrong
in a way nobody notices.

Three failure modes are worth locking down. A venue that answered with nothing
must be *dropped*, because zero-filling draws a real exchange as having no open
positions and drags the aggregate down with it. Bybit reports contracts where
the others report dollars, so a missing conversion adds a number three orders of
magnitude too small and the chart still looks plausible. And a venue whose
history starts later than the rest makes the aggregate step up on the bar it
first appears — `coverage_from` exists so that step is never read as an inflow
of new positions.

Nothing here may reach the network.
"""

import pytest

from services import open_interest_service as ois


def _candles(count, *, start_s=1_700_000_000, step_s=3_600, close=100.0):
    """Minimal OHLCV series in the shape `okx_market.fetch_candles` returns."""
    return [
        {
            "time": start_s + i * step_s,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 10.0,
            "volume_usd": 1000.0,
        }
        for i in range(count)
    ]


@pytest.fixture(autouse=True)
def clean_cache():
    """Each test starts cold; the service caches per symbol and interval."""
    ois._cache.clear()
    yield
    ois._cache.clear()


@pytest.fixture
def venues(monkeypatch):
    """
    Stub the three exchange clients and the OKX candle feed.

    `state` is what a test reshapes: each venue's series is separate so an
    aggregate that quietly became one exchange is visible in the numbers.
    """
    state = {
        "candles": _candles(48),
        "binance": None,
        "okx": None,
        "bybit": None,
    }

    async def fake_candles(inst_id, interval="1h", limit=168):
        return state["candles"]

    async def fake_binance(symbol, interval, limit):
        if state["binance"] is None:
            return [(candle["time"] * 1000, 1_000.0) for candle in state["candles"]]
        return state["binance"]

    async def fake_okx(symbol, interval, limit):
        if state["okx"] is None:
            return [(candle["time"] * 1000, 2_000.0) for candle in state["candles"]]
        return state["okx"]

    async def fake_bybit(symbol, interval, limit):
        if state["bybit"] is None:
            return [(candle["time"] * 1000, 5.0) for candle in state["candles"]]
        return state["bybit"]

    async def no_supply(base, latest_close):
        return None

    monkeypatch.setattr(ois.okx_market, "fetch_candles", fake_candles)
    monkeypatch.setattr(ois.binance_market, "fetch_open_interest", fake_binance)
    monkeypatch.setattr(ois.okx_market, "fetch_open_interest", fake_okx)
    monkeypatch.setattr(ois.bybit_market, "fetch_open_interest", fake_bybit)
    monkeypatch.setattr(ois, "_circulating_supply", no_supply)
    monkeypatch.setattr(ois.coinalyze, "has_key", lambda: False)
    return state


class TestVenueProvider:
    @pytest.mark.asyncio
    async def test_aggregate_sums_every_venue(self, venues):
        result = await ois.get_open_interest("BTCUSDT", "1h", 48)

        assert result["source"] == ois.SOURCE_VENUES
        assert result["venues"] == ["Binance", "OKX", "Bybit"]
        # Bybit's 5 contracts at a close of 100 is 500 USD, not 5.
        assert result["aggregate"][-1] == pytest.approx(1_000.0 + 2_000.0 + 500.0)

    @pytest.mark.asyncio
    async def test_bybit_converts_contracts_at_each_candles_close(self, venues, monkeypatch):
        """
        The conversion has to use the candle a sample was aligned to.

        One price for the whole window would leave a month-long chart drifting
        against the two venues that already report dollars.
        """
        candles = _candles(4)
        for index, candle in enumerate(candles):
            candle["close"] = 100.0 * (index + 1)
        venues["candles"] = candles

        result = await ois.get_open_interest("BTCUSDT", "1h", 4)

        assert result["series"]["Bybit"] == [500.0, 1_000.0, 1_500.0, 2_000.0]

    @pytest.mark.asyncio
    async def test_contract_venues_are_asked_for_a_pair_not_a_bare_asset(self, venues, monkeypatch):
        """
        Binance and Bybit index by contract, OKX by currency.

        Handing the first two a bare "BTC" is not an error — they answer with an
        empty list, the venue is dropped as if it had gone quiet, and the board
        silently narrows to one exchange. That is how this shipped broken once.
        """
        seen: dict[str, str] = {}

        async def record(name, fallback):
            async def fetch(symbol, interval, limit):
                seen[name] = symbol
                return fallback

            return fetch

        candles = venues["candles"]
        series = [(candle["time"] * 1000, 1.0) for candle in candles]
        monkeypatch.setattr(
            ois.binance_market, "fetch_open_interest", await record("binance", series)
        )
        monkeypatch.setattr(ois.bybit_market, "fetch_open_interest", await record("bybit", series))
        monkeypatch.setattr(ois.okx_market, "fetch_open_interest", await record("okx", series))

        await ois.get_open_interest("BTCUSDT", "4h", 48)

        assert seen["binance"] == "BTCUSDT"
        assert seen["bybit"] == "BTCUSDT"
        # OKX publishes per currency, so it takes the base and nothing else.
        assert seen["okx"] == "BTC"

    @pytest.mark.asyncio
    async def test_a_silent_venue_is_dropped_not_zero_filled(self, venues):
        venues["okx"] = []

        result = await ois.get_open_interest("BTCUSDT", "1h", 48)

        assert result["venues"] == ["Binance", "Bybit"]
        assert "OKX" not in result["series"]
        assert result["aggregate"][-1] == pytest.approx(1_500.0)

    @pytest.mark.asyncio
    async def test_coarse_series_step_aligns_onto_finer_candles(self, venues):
        """
        A venue sampling every four hours must hold its value across the hours
        between, not leave them blank and not interpolate a number nobody
        published.
        """
        candles = venues["candles"]
        venues["binance"] = [
            (candles[index]["time"] * 1000, float(index)) for index in range(0, len(candles), 4)
        ]

        result = await ois.get_open_interest("BTCUSDT", "1h", 48)
        binance = result["series"]["Binance"]

        assert binance[0] == 0.0
        assert binance[1] == 0.0
        assert binance[3] == 0.0
        assert binance[4] == 4.0

    @pytest.mark.asyncio
    async def test_coverage_starts_where_every_venue_has_a_sample(self, venues):
        candles = venues["candles"]
        # Bybit's history begins ten bars in, as a newer listing's would.
        venues["bybit"] = [(candle["time"] * 1000, 5.0) for candle in candles[10:]]

        result = await ois.get_open_interest("BTCUSDT", "1h", 48)

        assert result["coverage_from"] == 10
        assert result["series"]["Bybit"][9] is None
        # And the aggregate does not exist before that bar. A sum over two books
        # followed by a sum over three is not one series, and drawing it as one
        # puts a step in the chart that reads as positions being opened.
        assert result["aggregate"][9] is None
        assert result["aggregate"][10] == pytest.approx(3_500.0)
        # The venue's own history is untouched — nothing is hidden, only the
        # number that would have been wrong.
        assert result["series"]["Binance"][0] == pytest.approx(1_000.0)

    @pytest.mark.asyncio
    async def test_no_candles_returns_a_complete_empty_payload(self, venues):
        venues["candles"] = []

        result = await ois.get_open_interest("BTCUSDT", "1h", 48)

        assert result["candles"] == []
        assert result["venues"] == []
        # Every key present: the client renders an empty state rather than
        # crashing on a field that vanished.
        for key in ("series", "aggregate", "market_cap", "coverage_from", "source"):
            assert key in result

    @pytest.mark.asyncio
    async def test_an_interval_no_provider_serves_degrades_to_daily(self, venues):
        """
        Weekly is the live case: nothing publishes it. The payload reports what
        was served rather than echoing what was asked for, so a chart cannot
        label a daily series as weekly.
        """
        result = await ois.get_open_interest("BTCUSDT", "1w", 48)

        assert result["interval"] == "1d"

    @pytest.mark.asyncio
    async def test_second_call_is_served_from_cache(self, venues, monkeypatch):
        calls = {"n": 0}
        original = ois.okx_market.fetch_candles

        async def counted(inst_id, interval="1h", limit=168):
            calls["n"] += 1
            return await original(inst_id, interval=interval, limit=limit)

        monkeypatch.setattr(ois.okx_market, "fetch_candles", counted)

        await ois.get_open_interest("BTCUSDT", "1h", 48)
        await ois.get_open_interest("BTCUSDT", "1h", 48)

        assert calls["n"] == 1


class TestCoinalyzeProvider:
    @pytest.fixture
    def coinalyze(self, venues, monkeypatch):
        candles = _candles(24)
        state = {"candles": candles, "oi": {}}

        async def fake_resolve(base, exchanges=None):
            return [
                ois.coinalyze.PerpMarket("BTCUSDT_PERP.A", "Binance", "USDT"),
                ois.coinalyze.PerpMarket("BTCUSDC_PERP.A", "Binance", "USDC"),
                ois.coinalyze.PerpMarket("BTCUSDT_PERP.6", "Bybit", "USDT"),
            ]

        async def fake_oi(symbols, interval, start, end):
            return state["oi"]

        async def fake_price(symbol, interval, start, end):
            return state["candles"]

        monkeypatch.setattr(ois.coinalyze, "has_key", lambda: True)
        monkeypatch.setattr(ois.coinalyze, "resolve_perp_symbols", fake_resolve)
        monkeypatch.setattr(ois.coinalyze, "fetch_open_interest_history", fake_oi)
        monkeypatch.setattr(ois.coinalyze, "fetch_price_history", fake_price)
        return state

    @pytest.mark.asyncio
    async def test_a_venues_contracts_are_summed_into_one_series(self, coinalyze):
        """
        A venue's open interest is the sum of its books.

        Binance lists BTC against USDT, USDC, USD1 and U; reporting one of them
        as "Binance" understates the venue by whatever the others hold.
        """
        candles = coinalyze["candles"]
        coinalyze["oi"] = {
            "BTCUSDT_PERP.A": [(candle["time"], 10.0) for candle in candles],
            "BTCUSDC_PERP.A": [(candle["time"], 2.0) for candle in candles],
            "BTCUSDT_PERP.6": [(candle["time"], 4.0) for candle in candles],
        }

        result = await ois.get_open_interest("BTCUSDT", "1d", 24)

        assert result["source"] == ois.SOURCE_COINALYZE
        assert result["venues"] == ["Binance", "Bybit"]
        assert result["series"]["Binance"][-1] == pytest.approx(12.0)
        # Already USD via convert_to_usd — no contract conversion on this path.
        assert result["aggregate"][-1] == pytest.approx(16.0)

    @pytest.mark.asyncio
    async def test_a_thin_contract_with_no_history_does_not_drop_its_venue(self, coinalyze):
        """
        The regression that shipped: Binance's USDC book has no open-interest
        history, and treating one contract as the venue lost Binance entirely.
        """
        candles = coinalyze["candles"]
        coinalyze["oi"] = {
            "BTCUSDT_PERP.A": [(candle["time"], 10.0) for candle in candles],
        }

        result = await ois.get_open_interest("BTCUSDT", "1d", 24)

        assert result["venues"] == ["Binance"]
        assert result["series"]["Binance"][-1] == pytest.approx(10.0)

    @pytest.mark.asyncio
    async def test_bars_before_any_venue_reported_are_cut(self, coinalyze):
        """
        Coinalyze caps a history request while OHLCV keeps coming, so a long
        window arrives with a price line and no open interest under its left
        edge. That dead space reads as a collapse to zero, so it is cut.
        """
        candles = coinalyze["candles"]
        coinalyze["oi"] = {
            "BTCUSDT_PERP.A": [(candle["time"], 10.0) for candle in candles[6:]],
            "BTCUSDT_PERP.6": [(candle["time"], 4.0) for candle in candles[9:]],
        }

        result = await ois.get_open_interest("BTCUSDT", "1d", 24)

        # Trimmed to the earliest venue, not the latest — Bybit's later start is
        # what `coverage_from` is for, and cutting to it would throw away three
        # bars of Binance the per-venue pane can legitimately show.
        assert len(result["candles"]) == len(candles) - 6
        assert result["candles"][0]["time"] == candles[6]["time"]
        assert result["series"]["Binance"][0] == pytest.approx(10.0)
        assert result["series"]["Bybit"][0] is None
        assert result["coverage_from"] == 3

    @pytest.mark.asyncio
    async def test_empty_response_falls_through_to_the_exchanges(self, coinalyze):
        """
        A configured key that answers with nothing must not cost the board its
        chart — the exchange path is shallower, not absent.
        """
        coinalyze["oi"] = {}

        result = await ois.get_open_interest("BTCUSDT", "1h", 48)

        assert result["source"] == ois.SOURCE_VENUES
        assert result["venues"] == ["Binance", "OKX", "Bybit"]
