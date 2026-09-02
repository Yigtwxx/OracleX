"""
The BIST equity heatmap, and the futures roll underneath it.

Three things are pinned here, and each one is a place where a wrong answer
would look entirely plausible on screen:

* **Absent is not zero.** A name with contracts but an empty open-interest
  column has to stay distinguishable from a name with no contracts at all.
  Both collapsed to `0.0` before `roll_by_underlying` existed.
* **Nothing falls off the board.** A listing with no sector, or no market
  capitalisation, is still a company in the index. Dropping it makes the board
  quietly stop summing to the index it claims to draw.
* **Statistics are computed before `limit`.** Otherwise a sector's weight
  changes when the reader asks for fewer tiles, and nothing on screen says so.
"""

import pytest
from fastapi.testclient import TestClient

from main import app
from services.bist.equity_service import EquityBoard, EquityDataUnavailable
from services.bist.heatmap_service import (
    UNCLASSIFIED_SECTOR,
    build_heatmap,
    open_interest_change_pct,
)
from services.bist.positioning_service import build_positioning, futures_positioning
from services.bist.tradingview_client import EquityRow
from services.bist.viop_service import (
    ViopBoard,
    ViopContract,
    ViopUnavailable,
    roll_by_underlying,
    summarise,
)
from services.cache import bist_cache


@pytest.fixture(autouse=True)
def _clean_cache():
    bist_cache.clear()
    yield
    bist_cache.clear()


def _row(ticker, **kwargs) -> EquityRow:
    defaults: dict = {
        "ticker": ticker,
        "symbol": f"BIST:{ticker}",
        "name": f"{ticker} A.Ş.",
        "price": 100.0,
        "change_pct": 0.01,
        "change_abs": 1.0,
        "volume": 1000.0,
        "traded_value": 100_000.0,
        "market_cap": 1_000_000_000.0,
        "pe": 10.0,
        "pb": 1.5,
        "ev_ebitda": 7.0,
        "free_float_pct": 0.4,
        "sector": "Finans",
        "indices": ("XU100",),
    }
    defaults.update(kwargs)
    return EquityRow(**defaults)


def _contract(underlying, expiry="31 Eki 26", **kwargs) -> ViopContract:
    defaults: dict = {
        "contract": f"{underlying} ({expiry}) Vadeli",
        "underlying": underlying,
        "expiry": expiry,
        "physical": False,
        "last": 100.0,
        "change_pct": 0.01,
        "high": 101.0,
        "low": 99.0,
        "open_interest": 1000.0,
        "open_interest_change": 100.0,
        "settlement": 100.0,
        "previous_settlement": 99.0,
        "traded_at": "17:59",
    }
    defaults.update(kwargs)
    return ViopContract(**defaults)


class TestOpenInterestRoll:
    def test_expiries_are_summed_onto_the_underlying(self):
        rolls = roll_by_underlying(
            [
                _contract("THYAO", "31 Eki 26", open_interest=1000.0, open_interest_change=100.0),
                _contract("THYAO", "31 Ara 26", open_interest=500.0, open_interest_change=-40.0),
            ]
        )

        assert set(rolls) == {"THYAO"}
        assert rolls["THYAO"].contracts == 2
        assert rolls["THYAO"].open_interest == 1500.0
        assert rolls["THYAO"].open_interest_change == 60.0

    def test_contracts_without_a_reading_are_none_not_zero(self):
        # The distinction the whole overlay rests on: futures exist on this
        # name, but nobody published a position. Colouring that as a measured
        # zero states something the board does not know.
        rolls = roll_by_underlying(
            [_contract("SISE", open_interest=None, open_interest_change=None)]
        )

        assert rolls["SISE"].contracts == 1
        assert rolls["SISE"].open_interest is None
        assert rolls["SISE"].open_interest_change is None

    def test_the_two_columns_are_summed_independently(self):
        # A row can carry a change without a level. Pairing them would throw
        # away a reading that is genuinely there.
        rolls = roll_by_underlying(
            [_contract("EREGL", open_interest=None, open_interest_change=250.0)]
        )

        assert rolls["EREGL"].open_interest is None
        assert rolls["EREGL"].open_interest_change == 250.0

    def test_a_name_without_futures_is_absent_from_the_roll(self):
        assert "AKBNK" not in roll_by_underlying([_contract("THYAO")])

    def test_no_board_rolls_to_nothing(self):
        assert roll_by_underlying(None) == {}
        assert roll_by_underlying([]) == {}


class TestSummariseIsUnchanged:
    """
    `/api/bist/viop` has published these as numbers since it existed.

    `roll_by_underlying` keeps a None that this payload never carried, so the
    flattening back to 0.0 is deliberate and pinned — the refactor underneath
    must not reach the wire.
    """

    def test_missing_readings_still_render_as_zero(self):
        result = summarise([_contract("SISE", open_interest=None, open_interest_change=None)])

        assert result["by_underlying"] == [
            {"underlying": "SISE", "open_interest": 0.0, "change": 0.0, "contracts": 1}
        ]
        assert result["total_open_interest"] == 0.0

    def test_ranked_by_open_interest_descending(self):
        result = summarise(
            [
                _contract("SISE", open_interest=100.0),
                _contract("THYAO", open_interest=900.0),
                _contract("AKBNK", open_interest=500.0),
            ]
        )

        assert [row["underlying"] for row in result["by_underlying"]] == [
            "THYAO",
            "AKBNK",
            "SISE",
        ]
        assert result["total_open_interest"] == 1500.0


class TestOpenInterestChangePct:
    def test_change_is_measured_against_yesterday(self):
        # 1100 today after a +100 day is a 10% build on yesterday's 1000.
        assert open_interest_change_pct(1100.0, 100.0) == pytest.approx(0.1)

    def test_sign_survives(self):
        assert open_interest_change_pct(900.0, -100.0) == pytest.approx(-0.1)

    def test_a_position_built_from_nothing_has_no_percentage(self):
        assert open_interest_change_pct(100.0, 100.0) is None

    def test_missing_inputs_stay_missing(self):
        assert open_interest_change_pct(None, 100.0) is None
        assert open_interest_change_pct(1000.0, None) is None


class TestBuildHeatmap:
    def test_index_scopes_the_board(self):
        board = build_heatmap(
            [
                _row("THYAO", indices=("XU100", "XU030")),
                _row("SISE", indices=("XU100",)),
            ],
            index="XU030",
        )

        assert [tile.ticker for tile in board.tiles] == ["THYAO"]
        assert board.total == 1

    def test_tiles_are_ordered_by_market_cap(self):
        board = build_heatmap(
            [
                _row("SMALL", market_cap=1e9),
                _row("BIG", market_cap=9e9),
                _row("MID", market_cap=5e9),
            ],
            index="XU100",
        )

        assert [tile.ticker for tile in board.tiles] == ["BIG", "MID", "SMALL"]

    def test_an_unsectored_listing_is_grouped_not_dropped(self):
        board = build_heatmap([_row("THYAO", sector=""), _row("SISE")], index="XU100")

        assert {tile.ticker for tile in board.tiles} == {"THYAO", "SISE"}
        assert UNCLASSIFIED_SECTOR in {group.sector for group in board.sectors}
        assert sum(group.count for group in board.sectors) == len(board.tiles)

    def test_sector_weights_sum_to_the_scoped_index(self):
        board = build_heatmap(
            [
                _row("AKBNK", sector="Bankacılık", market_cap=6e9),
                _row("THYAO", sector="Ulaştırma", market_cap=4e9),
            ],
            index="XU100",
        )

        assert sum(group.weight for group in board.sectors) == pytest.approx(1.0)

    def test_limit_truncates_tiles_without_moving_the_statistics(self):
        equities = [
            _row("AKBNK", sector="Bankacılık", market_cap=6e9),
            _row("THYAO", sector="Ulaştırma", market_cap=4e9),
        ]
        full = build_heatmap(equities, index="XU100")
        clipped = build_heatmap(equities, index="XU100", limit=1)

        assert len(clipped.tiles) == 1
        assert clipped.total == 2
        assert {g.sector: g.weight for g in clipped.sectors} == {
            g.sector: g.weight for g in full.sectors
        }

    def test_a_listing_without_a_market_cap_still_gets_a_tile(self):
        # Its area is unknown, not zero. Dropping it here would understate how
        # broad a move was, which is the same rule `sector_performance` follows.
        board = build_heatmap([_row("THYAO", market_cap=None)], index="XU100")

        assert [tile.ticker for tile in board.tiles] == ["THYAO"]
        assert board.tiles[0].market_cap is None
        assert board.total_market_cap == 0.0


class TestFuturesOverlay:
    def test_open_interest_lands_on_its_underlying(self):
        board = build_heatmap(
            [_row("THYAO"), _row("SISE")],
            [
                _contract("THYAO", "31 Eki 26", open_interest=1000.0, open_interest_change=100.0),
                _contract("THYAO", "31 Ara 26", open_interest=500.0, open_interest_change=0.0),
            ],
            index="XU100",
        )
        tiles = {tile.ticker: tile for tile in board.tiles}

        assert tiles["THYAO"].has_futures is True
        assert tiles["THYAO"].contracts == 2
        assert tiles["THYAO"].open_interest == 1500.0
        assert tiles["THYAO"].open_interest_change_pct == pytest.approx(100.0 / 1400.0)
        assert board.futures_covered == 1

    def test_a_name_without_futures_reads_as_absent(self):
        board = build_heatmap([_row("SISE")], [_contract("THYAO")], index="XU100")
        tile = board.tiles[0]

        assert tile.has_futures is False
        assert tile.contracts == 0
        assert tile.open_interest is None
        assert tile.open_interest_change is None
        assert tile.open_interest_change_pct is None

    def test_an_unreadable_futures_board_costs_a_column_not_the_board(self):
        board = build_heatmap([_row("THYAO"), _row("SISE")], None, index="XU100")

        assert len(board.tiles) == 2
        assert board.has_futures_data is False
        assert board.futures_covered == 0
        assert all(tile.has_futures is False for tile in board.tiles)

    def test_an_empty_futures_board_is_not_an_unreadable_one(self):
        board = build_heatmap([_row("THYAO")], [], index="XU100")

        assert board.has_futures_data is True
        assert board.futures_covered == 0


class TestPositioningStillWorks:
    """The roll extraction changed `build_positioning`'s internals, not its answers."""

    def test_open_interest_column_is_unchanged(self):
        rows = build_positioning(
            [_row("THYAO"), _row("SISE")],
            [
                _contract("THYAO", "31 Eki 26", open_interest=1000.0, open_interest_change=100.0),
                _contract("THYAO", "31 Ara 26", open_interest=500.0, open_interest_change=-40.0),
            ],
        )
        by_ticker = {row.ticker: row for row in rows}

        assert by_ticker["THYAO"].open_interest == 1500.0
        assert by_ticker["THYAO"].open_interest_change == 60.0
        assert by_ticker["SISE"].open_interest is None

    def test_futures_positioning_still_filters_and_ranks(self):
        rows = build_positioning(
            [_row("THYAO"), _row("AKBNK"), _row("SISE")],
            [
                _contract("THYAO", open_interest=1000.0, open_interest_change=10.0),
                _contract("AKBNK", open_interest=1000.0, open_interest_change=-500.0),
            ],
        )

        assert [row.ticker for row in futures_positioning(rows)] == ["AKBNK", "THYAO"]


class TestEndpoint:
    """
    The one behaviour that lives in the router rather than the service: a broken
    VİOP scrape must not take the board down with it.
    """

    def _board(self) -> EquityBoard:
        return EquityBoard(
            equities=[_row("THYAO"), _row("SISE")],
            indices=[],
            stale=False,
            as_of="2026-09-01T12:00:00+00:00",
        )

    def test_a_broken_viop_scrape_still_answers_200(self, monkeypatch):
        async def _equities():
            return self._board()

        async def _viop():
            raise ViopUnavailable("board unreadable")

        monkeypatch.setattr("routers.bist.fetch_equity_board", _equities)
        monkeypatch.setattr("routers.bist.fetch_viop_board", _viop)

        response = TestClient(app).get("/api/bist/heatmap?index=XU100")

        assert response.status_code == 200
        payload = response.json()
        assert payload["has_futures_data"] is False
        assert payload["viop_as_of"] is None
        assert len(payload["tiles"]) == 2
        assert all(tile["open_interest"] is None for tile in payload["tiles"])

    def test_futures_readings_reach_the_wire(self, monkeypatch):
        async def _equities():
            return self._board()

        async def _viop():
            return ViopBoard(
                contracts=[_contract("THYAO", open_interest=1100.0, open_interest_change=100.0)],
                as_of="2026-09-01T12:05:00+00:00",
                stale=False,
            )

        monkeypatch.setattr("routers.bist.fetch_equity_board", _equities)
        monkeypatch.setattr("routers.bist.fetch_viop_board", _viop)

        payload = TestClient(app).get("/api/bist/heatmap?index=XU100").json()
        tiles = {tile["ticker"]: tile for tile in payload["tiles"]}

        assert payload["has_futures_data"] is True
        assert payload["futures_covered"] == 1
        assert tiles["THYAO"]["open_interest"] == 1100.0
        assert tiles["THYAO"]["open_interest_change_pct"] == pytest.approx(0.1)
        assert tiles["SISE"]["has_futures"] is False

    def test_an_unreadable_equity_board_is_a_503(self, monkeypatch):
        async def _equities():
            raise EquityDataUnavailable("scanner down")

        monkeypatch.setattr("routers.bist.fetch_equity_board", _equities)

        assert TestClient(app).get("/api/bist/heatmap").status_code == 503

    def test_an_unknown_index_is_a_400(self):
        assert TestClient(app).get("/api/bist/heatmap?index=ZZZ").status_code == 400
