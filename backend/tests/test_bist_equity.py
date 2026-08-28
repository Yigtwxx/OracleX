"""
The Borsa İstanbul equity board.

The scanner hands back a positional array, so the first thing worth pinning is
that the columns land in the fields they are named after — an off-by-one there
would put a price-to-book ratio in the price column and nothing would raise.

After that: the ranking rules, which decide what a reader sees first, and the
sector roll-up, which is capitalisation-weighted for a reason.
"""

import pytest

from services.bist import equity_service
from services.bist.equity_service import (
    EquityDataUnavailable,
    distinct_sectors,
    fetch_equity,
    fetch_equity_board,
    screen_equities,
    sector_performance,
)
from services.bist.tradingview_client import (
    _STOCK_COLUMNS,
    EquityRow,
    TradingViewUnavailable,
    _index_codes,
    _number,
    _pct,
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


class TestScannerParsing:
    def test_percentages_become_fractions(self):
        # The scanner reports 2.19 for a 2.19% move. Everything downstream —
        # the real-return arithmetic especially — works in fractions.
        assert _pct(2.19) == pytest.approx(0.0219)
        assert _pct(None) is None

    def test_nan_is_treated_as_missing(self):
        # NaN survives float() and then makes every comparison it touches
        # false, which silently randomises the order of a sorted column.
        assert _number(float("nan")) is None
        assert _number("not a number") is None
        assert _number(True) is None

    def test_index_codes_keep_bist_and_drop_foreign_listings(self):
        cell = [
            {"name": "BIST 100", "proname": "BIST:XU100"},
            {"name": "BIST 30", "proname": "BIST:XU030"},
            {"name": "STOXX Emerging", "proname": "STOXX:EDE15BP"},
        ]
        assert _index_codes(cell) == ("XU100", "XU030")

    def test_index_codes_survive_a_missing_cell(self):
        assert _index_codes(None) == ()
        assert _index_codes([{"name": "no proname"}]) == ()

    def test_column_list_has_no_duplicates(self):
        # The response is positional: a repeated column shifts every field
        # after it into the wrong slot, and nothing raises.
        assert len(_STOCK_COLUMNS) == len(set(_STOCK_COLUMNS))


class TestScreening:
    def test_index_filter_matches_membership(self):
        rows = [_row("A", indices=("XU100",)), _row("B", indices=("XU030",))]
        assert [r.ticker for r in screen_equities(rows, index="XU100")] == ["A"]

    def test_missing_values_sort_last_in_both_directions(self):
        # Ascending by P/E should surface the cheapest company, not the eighty
        # with no earnings and therefore no ratio.
        rows = [_row("CHEAP", pe=4.0), _row("NOPE", pe=None), _row("RICH", pe=40.0)]
        ascending = [r.ticker for r in screen_equities(rows, sort_by="pe", descending=False)]
        descending = [r.ticker for r in screen_equities(rows, sort_by="pe", descending=True)]
        assert ascending == ["CHEAP", "RICH", "NOPE"]
        assert descending == ["RICH", "CHEAP", "NOPE"]

    def test_search_matches_ticker_or_name(self):
        rows = [_row("THYAO", name="TÜRK HAVA YOLLARI"), _row("GARAN", name="GARANTİ BANKASI")]
        assert [r.ticker for r in screen_equities(rows, search="hava")] == ["THYAO"]
        assert [r.ticker for r in screen_equities(rows, search="gara")] == ["GARAN"]

    def test_rejects_an_unsortable_field(self):
        with pytest.raises(ValueError):
            screen_equities([_row("A")], sort_by="nonsense")


class TestSectorPerformance:
    def test_weights_by_capitalisation_not_by_count(self):
        # One large company down a little outweighs three small ones up a lot.
        # An equal-weighted roll-up would report this sector as rising.
        rows = [
            _row("BIG", sector="Finans", market_cap=900.0, change_pct=-0.02),
            _row("S1", sector="Finans", market_cap=30.0, change_pct=0.10),
            _row("S2", sector="Finans", market_cap=30.0, change_pct=0.10),
            _row("S3", sector="Finans", market_cap=40.0, change_pct=0.10),
        ]
        stat = sector_performance(rows)[0]
        assert stat.change_pct < 0
        assert stat.advancers == 3
        assert stat.decliners == 1

    def test_a_company_with_no_capitalisation_still_counts_toward_breadth(self):
        # It is a real listing whose size is unknown; dropping it would
        # understate how broad a move was.
        rows = [
            _row("KNOWN", sector="Finans", market_cap=100.0, change_pct=0.01),
            _row("UNSIZED", sector="Finans", market_cap=None, change_pct=0.05),
        ]
        stat = sector_performance(rows)[0]
        assert stat.count == 2
        assert stat.advancers == 2
        assert stat.change_pct == pytest.approx(0.01)

    def test_sectors_are_ordered_by_size(self):
        rows = [
            _row("A", sector="Küçük", market_cap=10.0),
            _row("B", sector="Büyük", market_cap=900.0),
        ]
        assert [s.sector for s in sector_performance(rows)] == ["Büyük", "Küçük"]

    def test_weights_sum_to_one_across_sectors(self):
        rows = [_row("A", sector="X", market_cap=300.0), _row("B", sector="Y", market_cap=700.0)]
        assert sum(s.weight for s in sector_performance(rows)) == pytest.approx(1.0)

    def test_unsectored_rows_are_excluded(self):
        rows = [_row("A", sector=""), _row("B", sector="Finans")]
        assert [s.sector for s in sector_performance(rows)] == ["Finans"]


class TestBoard:
    @pytest.mark.asyncio
    async def test_serves_the_listing(self, monkeypatch):
        async def rows():
            return [_row("THYAO"), _row("GARAN")]

        async def indices():
            return []

        monkeypatch.setattr(equity_service, "fetch_equities", rows)
        monkeypatch.setattr(equity_service, "fetch_indices", indices)
        board = await fetch_equity_board()
        assert len(board.equities) == 2
        assert board.stale is False

    @pytest.mark.asyncio
    async def test_an_index_outage_does_not_take_the_board_down(self, monkeypatch):
        # The board is still a board without the XU100 strip across the top.
        async def rows():
            return [_row("THYAO")]

        async def broken():
            raise TradingViewUnavailable("indices down")

        monkeypatch.setattr(equity_service, "fetch_equities", rows)
        monkeypatch.setattr(equity_service, "fetch_indices", broken)
        board = await fetch_equity_board()
        assert board.equities and board.indices == []

    @pytest.mark.asyncio
    async def test_raises_rather_than_returning_an_empty_listing(self, monkeypatch):
        async def nothing():
            return []

        async def indices():
            return []

        monkeypatch.setattr(equity_service, "fetch_equities", nothing)
        monkeypatch.setattr(equity_service, "fetch_indices", indices)
        with pytest.raises(EquityDataUnavailable):
            await fetch_equity_board()

    @pytest.mark.asyncio
    async def test_falls_back_to_the_last_listing_when_the_scanner_is_down(self, monkeypatch):
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                return [_row("THYAO")]
            raise TradingViewUnavailable("boom")

        async def indices():
            return []

        monkeypatch.setattr(equity_service, "fetch_equities", flaky)
        monkeypatch.setattr(equity_service, "fetch_indices", indices)
        await fetch_equity_board()
        bist_cache.invalidate("equity_board")
        board = await fetch_equity_board()
        assert board.stale is True
        assert [r.ticker for r in board.equities] == ["THYAO"]


class TestFetchEquity:
    @pytest.mark.asyncio
    async def test_accepts_a_venue_prefixed_symbol(self, monkeypatch):
        async def rows():
            return [_row("THYAO")]

        async def indices():
            return []

        monkeypatch.setattr(equity_service, "fetch_equities", rows)
        monkeypatch.setattr(equity_service, "fetch_indices", indices)
        assert (await fetch_equity("BIST:THYAO")).ticker == "THYAO"
        assert (await fetch_equity("thyao")).ticker == "THYAO"

    @pytest.mark.asyncio
    async def test_an_unlisted_ticker_is_an_error(self, monkeypatch):
        # Not an empty page: an unlisted code in a trading terminal must never
        # render as a company worth nothing.
        async def rows():
            return [_row("THYAO")]

        async def indices():
            return []

        monkeypatch.setattr(equity_service, "fetch_equities", rows)
        monkeypatch.setattr(equity_service, "fetch_indices", indices)
        with pytest.raises(EquityDataUnavailable):
            await fetch_equity("NOTREAL")


def test_distinct_sectors_is_sorted_and_deduplicated():
    rows = [_row("A", sector="Finans"), _row("B", sector="Enerji"), _row("C", sector="Finans")]
    assert distinct_sectors(rows) == ["Enerji", "Finans"]
