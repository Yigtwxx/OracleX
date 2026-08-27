"""
A profile is a claim about what is standing *right now*, and it is the only one
of the three views a reader adds up.

The heatmap and the levels view are read by eye: a cell that is 4% too dark or a
span trimmed for being faint costs nothing a viewer would notice. A profile's
bars are stacked and its totals are printed, so the same liberties become wrong
answers — a dropped tier silently shortens a bar, and a bar that disagrees with
the heatmap's last column means two views of one book are telling different
stories. Most of what follows guards those two properties.
"""

import pytest

from services import liquidation_map_service as lm

# Field positions in an emitted level, so the assertions read as claims about
# the model rather than as tuple arithmetic.
BIN, TIER, SIDE, NOTIONAL = range(4)


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

    Every venue is stubbed — not one of these tests may reach the network — and
    each one's traded notional is scaled differently so a test can tell the
    books apart by size alone. An aggregate that quietly became one exchange is
    the failure worth being able to see.
    """
    state = {"candles": _candles(120), "binance_scale": 3.0, "bybit_scale": 2.0}

    async def fake_candles(inst_id, interval="1h", limit=168):
        return state["candles"]

    async def fake_rubik(endpoint, ccy, period, value_index):
        return [(state["candles"][0]["time"] * 1000 - 1, 1.0)]

    async def fake_binance_candles(symbol, interval="1h", limit=200):
        return [
            {**candle, "volume_usd": candle["volume_usd"] * state["binance_scale"]}
            for candle in state["candles"]
        ]

    async def fake_binance_oi(symbol, interval, limit):
        return [(state["candles"][0]["time"] * 1000 - 1, 1.0)]

    async def fake_binance_ls(symbol, interval, limit):
        return [(state["candles"][0]["time"] * 1000 - 1, 0.5)]

    monkeypatch.setattr(lm.liquidation_service, "fetch_candles", fake_candles)
    monkeypatch.setattr(lm, "_fetch_rubik_series", fake_rubik)
    monkeypatch.setattr(lm.binance_market, "fetch_candles", fake_binance_candles)
    monkeypatch.setattr(lm.binance_market, "fetch_open_interest", fake_binance_oi)

    async def fake_bybit_candles(symbol, interval="1h", limit=200):
        return [
            {**candle, "volume_usd": candle["volume_usd"] * state["bybit_scale"]}
            for candle in state["candles"]
        ]

    async def fake_bybit_oi(symbol, interval, limit):
        # Base units, as the real client returns; the service converts.
        return [(state["candles"][0]["time"] * 1000 - 1, 0.01)]

    async def fake_bybit_ls(symbol, interval, limit):
        return [(state["candles"][0]["time"] * 1000 - 1, 0.5)]

    monkeypatch.setattr(lm.binance_market, "fetch_long_share", fake_binance_ls)
    monkeypatch.setattr(lm.bybit_market, "fetch_candles", fake_bybit_candles)
    monkeypatch.setattr(lm.bybit_market, "fetch_open_interest", fake_bybit_oi)
    monkeypatch.setattr(lm.bybit_market, "fetch_long_share", fake_bybit_ls)
    lm._map_cache.clear()
    yield state
    lm._map_cache.clear()


def _price_of(result, cell):
    """The centre price of a bin, using the payload's own geometry."""
    return result["price_min"] + (cell + 0.5) * result["bin_size"]


def _bin_totals(result):
    """Notional per bin, summed back over the tier and side split."""
    totals = [0.0] * result["bins"]
    for level in result["levels"]:
        totals[level[BIN]] += level[NOTIONAL]
    return totals


class TestAgreementWithTheHeatmap:
    """
    The profile is the heatmap's newest column, and has to add up to it.

    Two simulations over one book is a duplication the payload shapes force, and
    the failure it invites is silent: nothing raises when they drift, the two
    tabs just disagree about how much is sitting at a price. This is the test
    that would catch it.
    """

    @pytest.mark.asyncio
    async def test_each_bin_matches_the_maps_last_column(self, patched):
        profile = await lm.get_liquidation_profile("BTC", interval="1h", columns=60, bins=120)
        heatmap = await lm.get_liquidation_map("BTC", interval="1h", columns=60, bins=120)

        last = len(heatmap["candles"]) - 1
        totals = _bin_totals(profile)

        compared = 0
        for column, cell, long_usd, short_usd in heatmap["cells"]:
            if column != last:
                continue
            compared += 1
            # Each view rounds its own components, so they can differ by the
            # number of parts one of them rounds — not by more.
            assert abs(totals[cell] - (long_usd + short_usd)) <= 2 * len(lm.LEVERAGE_TIERS), (
                f"bin {cell} disagrees between the profile and the map's last column"
            )

        assert compared > 0, "the map's last column was empty, so nothing was actually compared"

    @pytest.mark.asyncio
    async def test_it_shares_the_price_grid(self, patched):
        profile = await lm.get_liquidation_profile("BTC", interval="1h", columns=60, bins=90)
        heatmap = await lm.get_liquidation_map("BTC", interval="1h", columns=60, bins=120)

        # Different bin counts on purpose: the grid is a property of the candle
        # window, not of the resolution asked for.
        assert profile["price_min"] == heatmap["price_min"]
        assert profile["price_max"] == heatmap["price_max"]


class TestSnapshotSemantics:
    """A standing level is one price has not reached yet — nothing else."""

    @pytest.mark.asyncio
    async def test_a_level_price_never_reached_is_still_there(self, patched):
        result = await lm.get_liquidation_profile("BTC", interval="1h", columns=60)

        assert result["levels"], "a flat market accumulates a book; it must not come back empty"

    @pytest.mark.asyncio
    async def test_a_sweep_across_the_whole_grid_empties_the_book(self, patched):
        candles = _candles(120)
        # A final candle spanning the entire padded grid reaches every level
        # there is. Sweep runs before deposit, so what survives is exactly this
        # candle's own deposits and nothing older.
        candles[-1]["low"] = 1.0
        candles[-1]["high"] = 10_000.0
        patched["candles"] = candles

        result = await lm.get_liquidation_profile("BTC", interval="1h", columns=60)
        deposits = len(lm.LEVERAGE_TIERS) * 2

        assert len(result["levels"]) <= deposits, (
            "after a full sweep only the sweeping candle's own deposits may stand"
        )

    @pytest.mark.asyncio
    async def test_longs_sit_below_the_price_and_shorts_above(self, patched):
        result = await lm.get_liquidation_profile("BTC", interval="1h", columns=60)
        price = result["price"]

        for level in result["levels"]:
            side_price = _price_of(result, level[BIN])
            if level[SIDE] == 0:
                assert side_price < price, "a long liquidates below the price that opened it"
            else:
                assert side_price > price, "a short liquidates above the price that opened it"

    @pytest.mark.asyncio
    async def test_higher_leverage_sits_closer_to_the_price(self, patched):
        result = await lm.get_liquidation_profile("BTC", interval="1h", columns=60)
        tiers = result["leverage_tiers"]

        # Distance from spot has to fall as leverage rises, on both sides. If it
        # ever rises, the liquidation-distance arithmetic has been inverted.
        for side in (0, 1):
            distances = {}
            for level in result["levels"]:
                if level[SIDE] != side:
                    continue
                gap = abs(_price_of(result, level[BIN]) - result["price"])
                distances.setdefault(tiers[level[TIER]], []).append(gap)

            ordered = [min(distances[tier]) for tier in sorted(distances)]
            assert ordered == sorted(ordered, reverse=True), (
                f"side {side}: distance from spot must fall as leverage rises"
            )


class TestCompleteness:
    """
    Nothing is trimmed, because a stacked bar is a sum and a sum with a piece
    missing is simply wrong. This is the one place the profile deliberately
    departs from what the other two views do.
    """

    @pytest.mark.asyncio
    async def test_no_floor_drops_a_tier(self, patched):
        result = await lm.get_liquidation_profile("BTC", interval="1h", columns=60)

        present = {level[TIER] for level in result["levels"]}
        assert present == set(range(len(lm.LEVERAGE_TIERS))), (
            "every leverage tier the model deposits into must reach the payload"
        )

    @pytest.mark.asyncio
    async def test_the_totals_are_the_levels_added_up(self, patched):
        result = await lm.get_liquidation_profile("BTC", interval="1h", columns=60)

        for side, key in ((0, "total_long"), (1, "total_short")):
            summed = sum(level[NOTIONAL] for level in result["levels"] if level[SIDE] == side)
            assert abs(result[key] - summed) <= 1, f"{key} must equal the levels it summarises"

    @pytest.mark.asyncio
    async def test_max_value_is_the_tallest_bar(self, patched):
        result = await lm.get_liquidation_profile("BTC", interval="1h", columns=60)

        assert abs(result["max_value"] - max(_bin_totals(result))) <= len(lm.LEVERAGE_TIERS) * 2


class TestPayloadShape:
    """The fields a client indexes into, and what an empty answer looks like."""

    @pytest.mark.asyncio
    async def test_every_level_is_four_numbers_in_range(self, patched):
        result = await lm.get_liquidation_profile("BTC", interval="1h", columns=60, bins=80)

        for level in result["levels"]:
            assert len(level) == 4
            assert 0 <= level[BIN] < result["bins"]
            assert 0 <= level[TIER] < len(result["leverage_tiers"])
            assert level[SIDE] in (0, 1)
            assert level[NOTIONAL] > 0

    @pytest.mark.asyncio
    async def test_it_names_its_venue(self, patched):
        result = await lm.get_liquidation_profile("BTC", interval="1h", columns=60)

        assert result["exchange"] == lm.EXCHANGE

    @pytest.mark.asyncio
    async def test_it_carries_no_time_axis(self, patched):
        result = await lm.get_liquidation_profile("BTC", interval="1h", columns=60)

        # A profile is one moment. Shipping candles would invite a client to
        # draw a series that the numbers do not describe.
        assert "candles" not in result
        assert "interval_ms" not in result

    @pytest.mark.asyncio
    async def test_no_candles_gives_an_empty_but_complete_payload(self, monkeypatch):
        async def no_candles(inst_id, interval="1h", limit=168):
            return []

        async def fake_rubik(endpoint, ccy, period, value_index):
            return []

        monkeypatch.setattr(lm.liquidation_service, "fetch_candles", no_candles)
        monkeypatch.setattr(lm, "_fetch_rubik_series", fake_rubik)
        lm._map_cache.clear()

        result = await lm.get_liquidation_profile("NOPE", interval="1h", columns=60)

        assert result["levels"] == []
        for key in ("price", "price_min", "price_max", "bin_size", "bins", "max_value"):
            assert key in result, f"an empty answer still has to carry {key}"

        lm._map_cache.clear()


class TestSharedInputs:
    """Three views, one fetch, three cache keys that do not collide."""

    @pytest.mark.asyncio
    async def test_the_three_views_fetch_candles_once(self, monkeypatch, patched):
        calls = {"count": 0}
        original = lm.liquidation_service.fetch_candles

        async def counting(inst_id, interval="1h", limit=168):
            calls["count"] += 1
            return await original(inst_id, interval=interval, limit=limit)

        monkeypatch.setattr(lm.liquidation_service, "fetch_candles", counting)

        await lm.get_liquidation_profile("BTC", interval="1h", columns=60)
        await lm.get_liquidation_map("BTC", interval="1h", columns=60)
        await lm.get_liquidation_lines("BTC", interval="1h", columns=60)

        assert calls["count"] == 1, "the shared inputs cache must serve all three views"

    @pytest.mark.asyncio
    async def test_the_cache_keys_stay_apart(self, patched):
        profile = await lm.get_liquidation_profile("BTC", interval="1h", columns=60, bins=120)
        heatmap = await lm.get_liquidation_map("BTC", interval="1h", columns=60, bins=120)

        assert "cells" not in profile
        assert "levels" not in heatmap


class TestVenues:
    """
    Three panes, three books — and the one that must not go wrong quietly is the
    aggregate. A venue that returns nothing has to leave the sum *and* the label,
    because an aggregate silently reduced to one exchange reads as the market
    having thinned out rather than as a feed being down.
    """

    @pytest.mark.asyncio
    async def test_each_venue_names_itself(self, patched):
        for venue, name in (
            (lm.OKX_VENUE, "OKX"),
            (lm.BINANCE_VENUE, "Binance"),
            (lm.BYBIT_VENUE, "Bybit"),
        ):
            result = await lm.get_liquidation_profile("BTC", columns=60, venue=venue)
            assert result["exchange"] == name

    @pytest.mark.asyncio
    async def test_a_venue_is_fetched_from_itself(self, patched):
        okx = await lm.get_liquidation_profile("BTC", columns=60, venue=lm.OKX_VENUE)
        binance = await lm.get_liquidation_profile("BTC", columns=60, venue=lm.BINANCE_VENUE)

        # The fixture gives Binance three times the traded notional. If the two
        # panes came back equal, one of them is showing the other's book.
        assert binance["total_long"] > okx["total_long"]

    @pytest.mark.asyncio
    async def test_the_aggregate_is_the_sum_of_its_parts(self, patched):
        parts = [
            await lm.get_liquidation_profile("BTC", columns=60, venue=venue)
            for venue in lm.AGGREGATED_VENUES
        ]
        combined = await lm.get_liquidation_profile("BTC", columns=60, venue=lm.COMBINED_VENUE)

        for key in ("total_long", "total_short"):
            # Re-binning rounds once per merged cell, so the sum is exact to
            # within the number of cells, not to the cent.
            expected = sum(part[key] for part in parts)
            assert abs(combined[key] - expected) <= len(combined["levels"])

    @pytest.mark.asyncio
    async def test_the_aggregate_names_every_venue_in_it(self, patched):
        combined = await lm.get_liquidation_profile("BTC", columns=60, venue=lm.COMBINED_VENUE)

        assert combined["exchange"] == "Binance + OKX + Bybit"

    @pytest.mark.asyncio
    async def test_a_dead_venue_leaves_the_label_too(self, monkeypatch, patched):
        async def no_candles(symbol, interval="1h", limit=200):
            return []

        monkeypatch.setattr(lm.binance_market, "fetch_candles", no_candles)
        lm._map_cache.clear()

        combined = await lm.get_liquidation_profile("BTC", columns=60, venue=lm.COMBINED_VENUE)

        assert combined["exchange"] == "OKX + Bybit", "a venue with no book must not be claimed"
        assert combined["levels"], "the surviving venues still have to be shown"

    @pytest.mark.asyncio
    async def test_bybit_open_interest_is_converted_to_notional(self, patched):
        # The client hands over contracts, not dollars. Skip the conversion and
        # open interest reads as a rounding error against traded notional, so
        # the model falls back to the volume-only path without saying so.
        result = await lm.get_liquidation_profile("BTC", columns=60, venue=lm.BYBIT_VENUE)

        assert result["total_long"] > 0
        assert result["stats_from_column"] == 0

    @pytest.mark.asyncio
    async def test_the_aggregate_spans_both_grids(self, patched):
        okx = await lm.get_liquidation_profile("BTC", columns=60, venue=lm.OKX_VENUE)
        combined = await lm.get_liquidation_profile("BTC", columns=60, venue=lm.COMBINED_VENUE)

        # Never narrower than a part: a wall outside the shared range would be
        # dropped rather than drawn at the edge.
        assert combined["price_min"] <= okx["price_min"]
        assert combined["price_max"] >= okx["price_max"]

    @pytest.mark.asyncio
    async def test_venue_caches_stay_apart(self, patched):
        first = await lm.get_liquidation_profile("BTC", columns=60, venue=lm.OKX_VENUE)
        second = await lm.get_liquidation_profile("BTC", columns=60, venue=lm.BINANCE_VENUE)
        again = await lm.get_liquidation_profile("BTC", columns=60, venue=lm.OKX_VENUE)

        assert first["exchange"] == again["exchange"] == "OKX"
        assert second["exchange"] == "Binance"
