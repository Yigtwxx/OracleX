"""
The macro board: what it does when an upstream is missing, and where it may go.

Two properties carry this module and are asserted directly. A reading it could
not take stays `None` — the board is rendered as prices, and a `0` there is not
an absence, it is the claim that gold is worthless. And the scraped rung reaches
only the constant `INVESTING_URLS` map, never an address derived from a symbol,
for the same reason `scrape_service` allowlists its browser rung.

Nothing here touches the network: Yahoo, Scrapling and the sparkline fetch are
all stubbed.
"""

import sys
from types import ModuleType

import pytest

from services import macro_board_service as board
from services.asset_registry import GLOBAL_INDICES, MACRO_COMMODITIES
from services.cache import market_cache

ALL_SYMBOLS = list(MACRO_COMMODITIES) + list(GLOBAL_INDICES)


def _chart(price, *, previous=None, high=None, low=None, currency="USD"):
    """A minimal Yahoo v8 chart payload."""
    meta = {"regularMarketPrice": price, "currency": currency}
    if previous is not None:
        meta["chartPreviousClose"] = previous
    if high is not None:
        meta["fiftyTwoWeekHigh"] = high
    if low is not None:
        meta["fiftyTwoWeekLow"] = low
    return {"chart": {"result": [{"meta": meta}]}}


@pytest.fixture(autouse=True)
def _clean_cache():
    """The board is one cache entry; a leftover one would answer every test."""
    market_cache.clear()
    yield
    market_cache.clear()


@pytest.fixture
def upstreams(monkeypatch):
    """
    Stub Yahoo and the sparkline batch, and record every symbol asked for.

    `quotes` maps symbol → payload; anything absent is treated as a symbol Yahoo
    refused, which is what drives the fallback path.
    """

    state = {
        "quotes": {symbol: _chart(100.0, previous=100.0) for symbol in ALL_SYMBOLS},
        "series": {},
        "asked": [],
    }

    async def fake_yahoo(url, *, params=None, timeout=None):
        symbol = url.rsplit("/", 1)[-1]
        state["asked"].append(symbol)
        payload = state["quotes"].get(symbol)
        if payload is None:
            raise RuntimeError("Too Many Requests")
        return payload

    async def fake_sparklines(symbols):
        return {s: state["series"][s] for s in symbols if s in state["series"]}

    monkeypatch.setattr(board, "get_json_impersonated", fake_yahoo)
    monkeypatch.setattr(board, "fetch_stock_sparklines", fake_sparklines)
    return state


@pytest.fixture
def scrapling(monkeypatch):
    """
    Install a stub `scrapling.fetchers` and record every URL it was pointed at.

    The rung imports it lazily inside the function, so replacing the module in
    `sys.modules` is enough — there is no import-time binding to patch.
    """
    visited: list[str] = []
    pages: dict[str, tuple[str, str]] = {}

    class _Element:
        def __init__(self, text):
            self._text = text

        def get_all_text(self):
            return self._text

    class _Response:
        def __init__(self, status, price, change):
            self.status = status
            self._price = price
            self._change = change

        def css(self, selector):
            if selector == board.PRICE_SELECTOR and self._price:
                return [_Element(self._price)]
            if selector == board.CHANGE_PCT_SELECTOR and self._change:
                return [_Element(self._change)]
            return []

    class _AsyncFetcher:
        @staticmethod
        async def get(url, **kwargs):
            visited.append(url)
            if url not in pages:
                return _Response(404, "", "")
            price, change = pages[url]
            return _Response(200, price, change)

    module = ModuleType("scrapling.fetchers")
    module.AsyncFetcher = _AsyncFetcher
    package = ModuleType("scrapling")
    package.fetchers = module
    monkeypatch.setitem(sys.modules, "scrapling", package)
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", module)

    return {"visited": visited, "pages": pages}


def _row(board_payload, symbol):
    for row in board_payload["commodities"] + board_payload["indices"]:
        if row["symbol"] == symbol:
            return row
    raise AssertionError(f"{symbol} is missing from the board")


# ── absence is not zero ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_symbol_no_upstream_answers_keeps_its_row_with_a_null_price(upstreams, scrapling):
    del upstreams["quotes"]["PA=F"]

    result = await board.fetch_macro_board()

    row = _row(result, "PA=F")
    assert row["price"] is None
    assert row["change_24h"] is None
    assert row["source"] is None
    # The row survives so the board does not silently shrink to the symbols that
    # happened to answer.
    assert len(result["commodities"]) == len(MACRO_COMMODITIES)


@pytest.mark.asyncio
async def test_a_chart_payload_without_a_price_is_not_read_as_a_price_of_zero(upstreams, scrapling):
    upstreams["quotes"]["GC=F"] = {"chart": {"result": [{"meta": {"currency": "USD"}}]}}

    result = await board.fetch_macro_board()

    assert _row(result, "GC=F")["price"] is None


@pytest.mark.asyncio
async def test_a_ratio_with_a_missing_leg_is_null_rather_than_zero(upstreams, scrapling):
    del upstreams["quotes"]["SI=F"]

    result = await board.fetch_macro_board()

    gold_silver = next(r for r in result["ratios"] if r["key"] == "gold_silver")
    assert gold_silver["value"] is None
    assert gold_silver["caption"] == "Unavailable"
    # The strip keeps its shape, so a gap reads as a gap rather than a shorter row.
    assert len(result["ratios"]) == 3


@pytest.mark.asyncio
async def test_copper_gold_keeps_enough_precision_to_be_a_reading(upstreams, scrapling):
    """Two decimals would round this live quotient to a flat 0.00."""
    upstreams["quotes"]["HG=F"] = _chart(6.68, previous=6.68)
    upstreams["quotes"]["GC=F"] = _chart(4376.20, previous=4376.20)

    result = await board.fetch_macro_board()

    copper_gold = next(r for r in result["ratios"] if r["key"] == "copper_gold")
    assert copper_gold["value"] == pytest.approx(0.00153, abs=1e-5)


# ── units ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_cent_quoted_crop_is_carried_in_its_own_unit_not_converted(upstreams, scrapling):
    upstreams["quotes"]["ZW=F"] = _chart(634.25, previous=631.25, currency="USX")

    result = await board.fetch_macro_board()

    row = _row(result, "ZW=F")
    assert row["price"] == 634.25  # not 6.3425
    assert row["unit"] == "USc/bu"
    assert row["currency"] == "USX"


# ── the drawn line and the printed number ────────────────────────────────────


@pytest.mark.asyncio
async def test_the_seven_day_change_comes_from_the_series_the_page_draws(upstreams, scrapling):
    upstreams["series"]["GC=F"] = [100.0, 105.0, 110.0]

    result = await board.fetch_macro_board()

    row = _row(result, "GC=F")
    assert row["sparkline"] == [100.0, 105.0, 110.0]
    assert row["change_7d"] == 10.0


@pytest.mark.asyncio
async def test_a_symbol_with_no_series_reports_no_seven_day_change(upstreams, scrapling):
    result = await board.fetch_macro_board()

    row = _row(result, "GC=F")
    assert row["sparkline"] == []
    assert row["change_7d"] is None


# ── the scraped rung ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_scraped_rung_runs_only_for_the_symbols_yahoo_dropped(upstreams, scrapling):
    del upstreams["quotes"]["GC=F"]
    scrapling["pages"][board.INVESTING_URLS["GC=F"]] = ("4,377.15", "(+1.80%)")

    result = await board.fetch_macro_board()

    assert scrapling["visited"] == [board.INVESTING_URLS["GC=F"]]
    row = _row(result, "GC=F")
    assert row["price"] == 4377.15
    assert row["change_24h"] == 1.80
    assert row["source"] == "investing"
    # The scraped page carries no 52-week range, and borrowing one from another
    # source would compare two different instants.
    assert row["high_52w"] is None
    assert row["low_52w"] is None


@pytest.mark.asyncio
async def test_the_scraped_rung_visits_only_addresses_in_the_constant_map(upstreams, scrapling):
    for symbol in ("GC=F", "SI=F", "^GSPC"):
        del upstreams["quotes"][symbol]

    await board.fetch_macro_board()

    assert set(scrapling["visited"]) <= set(board.INVESTING_URLS.values())


@pytest.mark.asyncio
async def test_a_parenthesised_fall_is_read_as_a_negative_change(upstreams, scrapling):
    del upstreams["quotes"]["SI=F"]
    scrapling["pages"][board.INVESTING_URLS["SI=F"]] = ("64.62", "(-1.10%)")

    result = await board.fetch_macro_board()

    assert _row(result, "SI=F")["change_24h"] == -1.10


@pytest.mark.asyncio
async def test_a_page_whose_price_element_vanished_reports_no_price(upstreams, scrapling):
    """A layout change upstream must surface as a gap, not as a flat quote."""
    del upstreams["quotes"]["GC=F"]
    scrapling["pages"][board.INVESTING_URLS["GC=F"]] = ("", "(+1.80%)")

    result = await board.fetch_macro_board()

    assert _row(result, "GC=F")["price"] is None


@pytest.mark.asyncio
async def test_the_board_still_builds_when_scrapling_is_not_installed(upstreams, monkeypatch):
    del upstreams["quotes"]["GC=F"]
    monkeypatch.setitem(sys.modules, "scrapling", None)
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", None)

    result = await board.fetch_macro_board()

    assert _row(result, "GC=F")["price"] is None
    assert _row(result, "SI=F")["price"] == 100.0


# ── outage handling ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_total_outage_replays_the_last_good_board_flagged_stale(upstreams, scrapling):
    first = await board.fetch_macro_board()
    assert first["stale"] is False

    market_cache.invalidate(board.CACHE_KEY)
    upstreams["quotes"].clear()

    replayed = await board.fetch_macro_board()

    assert replayed["stale"] is True
    assert _row(replayed, "GC=F")["price"] == 100.0


@pytest.mark.asyncio
async def test_a_total_outage_with_nothing_to_replay_is_reported_not_emptied(upstreams, scrapling):
    upstreams["quotes"].clear()

    with pytest.raises(board.UpstreamUnavailable):
        await board.fetch_macro_board()


@pytest.mark.asyncio
async def test_a_replayed_board_recomputes_the_session_badges(upstreams, scrapling, monkeypatch):
    """Sessions open and close while a board sits in the fallback slot."""
    await board.fetch_macro_board()
    market_cache.invalidate(board.CACHE_KEY)
    upstreams["quotes"].clear()
    monkeypatch.setattr(board, "_region_status", lambda region: {"status": "open", "label": "Open"})

    replayed = await board.fetch_macro_board()

    assert all(row["market_status"]["status"] == "open" for row in replayed["indices"])


# ── the ticker's view ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_ticker_slice_drops_rows_it_cannot_render(upstreams, scrapling):
    """The strip is fixed-width and has nowhere to put an em dash."""
    del upstreams["quotes"]["^GSPC"]

    rows = await board.fetch_macro_indices()

    assert all(row["price"] is not None for row in rows)
    assert "^GSPC" not in {row["symbol"] for row in rows}
    assert {"symbol", "name", "price", "change_24h", "region"} == set(rows[0])


@pytest.mark.asyncio
async def test_the_ticker_slice_carries_the_dollar_index(upstreams, scrapling):
    rows = await board.fetch_macro_indices()

    assert "DX-Y.NYB" in {row["symbol"] for row in rows}
