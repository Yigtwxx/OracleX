"""
A line is a claim about *when* a level existed, and every defence here guards
that axis.

The heatmap's cells only ever have to be right about a level's size at one
instant. A span additionally asserts where the level came from and where price
finally reached it, so it can be wrong in two ways the heatmap cannot: it can
start before the window it is drawn on, and it can outlive the sweep that should
have ended it. The trimming tests guard a third failure that is quieter than
either — a floor that empties the very tier the leverage filter exists to show.
"""

from statistics import median

import pytest

from services import liquidation_map_service as lm

# Field positions in an emitted span, so the assertions read as claims about the
# model rather than as tuple arithmetic.
START, END, BIN, LEVERAGE, SIDE, NOTIONAL = range(6)


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


@pytest.fixture
def patched(monkeypatch):
    """
    Serve a fixed candle series and a neutral, fully covering statistics pair.

    `state["candles"]` is mutable so a test can bend the price path without
    rebuilding the fixture; the statistics samples sit before the first candle
    so `stats_from_column` stays 0 and never confounds a geometry assertion.
    """
    state = {"candles": _candles(120)}

    async def fake_candles(inst_id, interval="1h", limit=168):
        return state["candles"]

    async def fake_rubik(endpoint, ccy, period, value_index):
        return [(state["candles"][0]["time"] * 1000 - 1, 1.0)]

    monkeypatch.setattr(lm.liquidation_service, "fetch_candles", fake_candles)
    monkeypatch.setattr(lm, "_fetch_rubik_series", fake_rubik)
    lm._map_cache.clear()
    yield state
    lm._map_cache.clear()


def _bin_of(result, price):
    """The grid row a price lands on, using the payload's own geometry."""
    return int((price - result["price_min"]) / result["bin_size"])


class TestWarmupClamping:
    """
    Columns before the window are simulated but never drawn.

    A span opened there is real and has to survive, but it cannot be dated: the
    chart maps column to time off the first *emitted* candle, so a negative
    column would stretch the time axis backwards and squeeze the candles into
    the right of the canvas.
    """

    @pytest.mark.asyncio
    async def test_a_level_opened_during_warmup_starts_at_column_zero(self, patched):
        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        starts = [line[START] for line in result["lines"]]
        assert min(starts) == 0, "a level standing before the window must start at the left edge"
        assert all(start >= 0 for start in starts), "no span may start before column 0"

    @pytest.mark.asyncio
    async def test_a_level_swept_inside_warmup_is_not_emitted(self, patched):
        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        columns = len(result["candles"])
        assert all(0 <= line[START] <= line[END] < columns for line in result["lines"]), (
            "every span must lie inside the emitted window"
        )

    @pytest.mark.asyncio
    async def test_no_span_ends_past_the_last_column(self, patched):
        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        last = len(result["candles"]) - 1
        assert max(line[END] for line in result["lines"]) == last, (
            "levels price never reached must run to the right edge"
        )


class TestSweepSemantics:
    """
    The sweep is the whole point: a span ends where price reached it.

    These pin the behaviour rather than describe it, because the two obvious
    "improvements" — staggering the ends of a wide sweep, or re-ordering the
    sweep against the deposit — would each invent data.
    """

    @pytest.mark.asyncio
    async def test_a_level_price_never_reaches_survives_to_the_last_column(self, patched):
        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        # A 10x long entered at 100 liquidates near 90.4, far under a series that
        # never trades below 99.
        far = [line for line in result["lines"] if line[LEVERAGE] == 10 and line[SIDE] == 0]
        assert far, "the 10x long band must be on the map"
        assert all(line[END] == len(result["candles"]) - 1 for line in far), (
            "an untouched level cannot have been swept"
        )

    @pytest.mark.asyncio
    async def test_a_wide_candle_closes_every_span_inside_its_range(self, patched):
        candles = _candles(120)
        candles[100]["high"] = 130.0
        candles[100]["low"] = 70.0
        patched["candles"] = candles

        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        wide_column = 100 - (120 - 60)
        low_bin = _bin_of(result, 70.0)
        high_bin = _bin_of(result, 130.0)
        survivors = [
            line
            for line in result["lines"]
            # Strictly before, because the sweep runs ahead of the deposit: a
            # level this same candle *created* was never standing when price
            # passed through, and it correctly survives.
            if low_bin <= line[BIN] <= high_bin and line[START] < wide_column < line[END]
        ]
        assert not survivors, (
            "a candle that traded through a level cannot leave that level standing"
        )

    @pytest.mark.asyncio
    async def test_a_level_inside_its_own_candle_survives_exactly_one_column(self, patched):
        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        # 125x liquidates 0.4% from entry, inside a candle that ranges 1% — so
        # the next candle's sweep, which runs before its deposit, takes it.
        stubs = [line for line in result["lines"] if line[LEVERAGE] == 125]
        assert stubs, "the 125x band must be on the map"
        assert max(line[END] - line[START] for line in stubs) <= 1, (
            "sweep-before-deposit ordering must cap a same-candle level at one column"
        )


class TestLeverageIdentity:
    """The identity the heatmap's cells collapse, and the filter's whole basis."""

    @pytest.mark.asyncio
    async def test_every_span_carries_a_leverage_from_the_tier_table(self, patched):
        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        assert {line[LEVERAGE] for line in result["lines"]} <= {
            tier for tier, _ in lm.LEVERAGE_TIERS
        }, "a span's leverage must be one the model actually placed"

    @pytest.mark.asyncio
    async def test_both_sides_appear_in_a_symmetric_window(self, patched):
        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        assert {0, 1} <= {line[SIDE] for line in result["lines"]}, (
            "a neutral long/short split must place levels above and below price"
        )

    @pytest.mark.asyncio
    async def test_high_leverage_spans_are_shorter_than_low_leverage_ones(self, patched):
        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        def spans(leverage):
            return [
                line[END] - line[START] for line in result["lines"] if line[LEVERAGE] == leverage
            ]

        # If this ever inverts, the liquidation-distance arithmetic is reversed:
        # a tighter stop cannot outlive a wider one.
        assert median(spans(125)) < median(spans(10)), (
            "the 125x band must be swept sooner than the 10x band"
        )


class TestTrimming:
    """
    The floor has to be measured per tier.

    The tiers' peaks differ by roughly 2.6x, so one global fraction cuts the
    100x band several times harder than the 10x band — and empties it first.
    That failure is silent: the map still renders, the high-leverage filter just
    turns on nothing.
    """

    @pytest.mark.asyncio
    async def test_the_floor_is_relative_to_each_tier_not_the_global_peak(
        self, patched, monkeypatch
    ):
        monkeypatch.setattr(lm, "LINE_FLOOR", 0.5)
        lm._map_cache.clear()

        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        present = {line[LEVERAGE] for line in result["lines"]}
        assert present == set(result["leverage_tiers"]), (
            "a floor this aggressive must thin every tier, not delete one"
        )

    @pytest.mark.asyncio
    async def test_the_cap_leaves_every_tier_on_the_chart(self, patched, monkeypatch):
        monkeypatch.setattr(lm, "MAX_LINES", 40)
        lm._map_cache.clear()

        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        assert len(result["lines"]) <= 40, "the cap must actually bind"
        assert {line[LEVERAGE] for line in result["lines"]} == set(result["leverage_tiers"]), (
            "interleaving across tiers is what stops the cap emptying one"
        )

    @pytest.mark.asyncio
    async def test_span_count_stays_under_the_structural_ceiling(self, patched):
        columns = 60
        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=columns)

        # Each candle can open at most one record per (tier, side), so the bound
        # holds whatever `bins` is — a finer grid only makes merges rarer.
        ceiling = (columns + lm.WARMUP_COLUMNS) * len(lm.LEVERAGE_TIERS) * 2
        assert len(result["lines"]) <= ceiling


class TestPayloadShape:
    @pytest.mark.asyncio
    async def test_every_span_is_six_numeric_fields(self, patched):
        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        assert all(
            len(line) == 6 and all(isinstance(field, (int, float)) for field in line)
            for line in result["lines"]
        )

    @pytest.mark.asyncio
    async def test_bins_stay_inside_the_grid(self, patched):
        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        assert all(0 <= line[BIN] < result["bins"] for line in result["lines"])

    @pytest.mark.asyncio
    async def test_tier_max_aligns_with_leverage_tiers(self, patched):
        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        assert len(result["tier_max"]) == len(result["leverage_tiers"])
        for index, tier in enumerate(result["leverage_tiers"]):
            emitted = [line[NOTIONAL] for line in result["lines"] if line[LEVERAGE] == tier]
            # The frontend scales opacity by this, so a stale peak would render
            # a whole tier at a fraction of its real intensity.
            assert result["tier_max"][index] == pytest.approx(max(emitted), rel=1e-6)

    @pytest.mark.asyncio
    async def test_the_payload_names_its_venue(self, patched):
        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        # The chart says "modelled", and which book it modelled is the other
        # half of that claim — a reader comparing it against a different
        # exchange's is reading it wrong.
        assert result["exchange"] == lm.EXCHANGE

    @pytest.mark.asyncio
    async def test_empty_map_still_reports_every_field(self, monkeypatch):
        async def no_candles(inst_id, interval="1h", limit=168):
            return []

        async def no_rubik(endpoint, ccy, period, value_index):
            return []

        monkeypatch.setattr(lm.liquidation_service, "fetch_candles", no_candles)
        monkeypatch.setattr(lm, "_fetch_rubik_series", no_rubik)
        lm._map_cache.clear()

        result = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        assert result["lines"] == []
        assert result["exchange"] == lm.EXCHANGE
        assert result["tier_max"] == [0 for _ in lm.LEVERAGE_TIERS]
        assert result["stats_from_column"] == 0
        assert result["bins"] == 120


class TestSharedInputs:
    """
    Both views run off one fetch and one grid.

    The grid is the load-bearing half: the tabs sit on the same page, and a
    y-axis that shifts when the user switches between them reads as the data
    having changed.
    """

    @pytest.fixture
    def counted(self, monkeypatch):
        calls = {"candles": 0}

        async def fake_candles(inst_id, interval="1h", limit=168):
            calls["candles"] += 1
            return _candles(120)

        async def fake_rubik(endpoint, ccy, period, value_index):
            return []

        monkeypatch.setattr(lm.liquidation_service, "fetch_candles", fake_candles)
        monkeypatch.setattr(lm, "_fetch_rubik_series", fake_rubik)
        lm._map_cache.clear()
        yield calls
        lm._map_cache.clear()

    @pytest.mark.asyncio
    async def test_map_and_lines_share_one_candle_fetch(self, counted):
        await lm.get_liquidation_map("BTC", interval="1h", columns=60)
        await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        assert counted["candles"] == 1, "the second view must reuse the first view's inputs"

    @pytest.mark.asyncio
    async def test_map_and_lines_agree_on_the_price_grid(self, counted):
        heat = await lm.get_liquidation_map("BTC", interval="1h", columns=60, bins=120)
        # A different bin count on purpose: the views really do run at different
        # vertical resolutions, and the axis they share is the price extent, not
        # the row height. Pinning bin_size instead would pass while proving less.
        lines = await lm.get_liquidation_lines("BTC", interval="1h", columns=60, bins=200)

        assert (heat["price_min"], heat["price_max"]) == (
            lines["price_min"],
            lines["price_max"],
        ), "the two tabs sit on one page; a shifting y-axis reads as changed data"

    @pytest.mark.asyncio
    async def test_the_two_views_do_not_collide_in_the_cache(self, counted):
        await lm.get_liquidation_map("BTC", interval="1h", columns=60)
        lines = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        assert "lines" in lines and "cells" not in lines, (
            "a shared cache needs the key prefixes to keep the shapes apart"
        )

    @pytest.mark.asyncio
    async def test_stats_coverage_matches_between_the_views(self, counted):
        heat = await lm.get_liquidation_map("BTC", interval="1h", columns=60)
        lines = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        assert heat["stats_from_column"] == lines["stats_from_column"]

    @pytest.mark.asyncio
    async def test_both_views_name_the_same_venue(self, counted):
        heat = await lm.get_liquidation_map("BTC", interval="1h", columns=60)
        lines = await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        # They run off one fetch, so disagreeing here would mean the label had
        # drifted from the data rather than that the data had changed.
        assert heat["exchange"] == lines["exchange"] == lm.EXCHANGE
