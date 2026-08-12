"""
The funding widget's contract: the core reference pairs are always there, in
market-cap order, and anything else has to earn its row by clearing the extreme
threshold from inside the liquid universe. OKX's board also carries tokenised
equities and commodities, so "liquid universe" is doing real filtering work.
"""

import pytest

from services import home_service
from services.cache import home_cache
from services.home_service import (
    FUNDING_CORE_SYMBOLS,
    FUNDING_EXTREME_LIMIT,
    FUNDING_EXTREME_THRESHOLD,
    fetch_funding_rates,
)

# 8h apart, which is what `interval_hours` should read off the payload.
FUNDING_TIME = 1786118400000
NEXT_FUNDING_TIME = FUNDING_TIME + 8 * 3_600_000


def board_entry(inst_id: str, rate: float, interval_hours: int = 8) -> dict:
    return {
        "instId": inst_id,
        "fundingRate": str(rate),
        "fundingTime": str(FUNDING_TIME),
        "nextFundingTime": str(FUNDING_TIME + interval_hours * 3_600_000),
    }


def build_board(extra: dict[str, float] | None = None, interval_hours: int = 8) -> dict:
    """Every core symbol at a calm rate, plus whatever the test wants on top."""
    board = {
        f"{symbol}-USDT-SWAP": board_entry(f"{symbol}-USDT-SWAP", 0.0001)
        for symbol in FUNDING_CORE_SYMBOLS
    }
    for symbol, rate in (extra or {}).items():
        inst_id = f"{symbol}-USDT-SWAP"
        board[inst_id] = board_entry(inst_id, rate, interval_hours)
    return board


@pytest.fixture(autouse=True)
def stub_upstreams(monkeypatch):
    """Cut every network call and hand the service a controllable board."""
    home_cache.clear()

    state: dict = {
        "board": build_board(),
        # Ordered the way the registry would return it, i.e. by market cap.
        "by_cap": ["BTC", "ETH", "XRP", "BNB", "SOL", "DOGE", "ADA", "LINK", "AVAX", "LTC"],
        "liquid": list(FUNDING_CORE_SYMBOLS),
        "board_error": None,
    }

    async def fake_top_perp_symbols(limit=8):
        return state["liquid"][:limit]

    async def fake_crypto_symbols(limit=50):
        return state["by_cap"][:limit]

    async def fake_price_index(client, path, params, price_field):
        return {}

    async def fake_funding_rates(client):
        if state["board_error"]:
            raise state["board_error"]
        return state["board"]

    monkeypatch.setattr(home_service.asset_registry, "get_top_perp_symbols", fake_top_perp_symbols)
    monkeypatch.setattr(home_service.asset_registry, "get_crypto_symbols", fake_crypto_symbols)
    monkeypatch.setattr(home_service, "_okx_price_index", fake_price_index)
    monkeypatch.setattr(home_service, "_okx_funding_rates", fake_funding_rates)

    yield state

    home_cache.clear()


async def test_core_symbols_always_present_even_when_calm(stub_upstreams):
    rows = await fetch_funding_rates()

    assert [row["symbol"] for row in rows] == list(stub_upstreams["by_cap"])
    assert all(row["is_extreme"] is False for row in rows)


async def test_core_block_is_ordered_by_market_cap_not_by_rate(stub_upstreams):
    # LTC is last by market cap but carries the loudest rate in the set.
    stub_upstreams["board"]["LTC-USDT-SWAP"] = board_entry("LTC-USDT-SWAP", 0.004)

    rows = await fetch_funding_rates()

    assert [row["symbol"] for row in rows] == list(stub_upstreams["by_cap"])
    assert rows[-1]["symbol"] == "LTC"
    assert rows[-1]["is_extreme"] is True


async def test_core_symbol_missing_from_the_registry_ranking_sinks_to_the_back(stub_upstreams):
    # A core symbol the registry doesn't rank must not sort ahead of BTC.
    stub_upstreams["by_cap"] = [s for s in stub_upstreams["by_cap"] if s != "LINK"]

    rows = await fetch_funding_rates()

    assert rows[0]["symbol"] == "BTC"
    assert rows[-1]["symbol"] == "LINK"


async def test_liquid_outlier_joins_but_a_calm_one_does_not(stub_upstreams):
    stub_upstreams["liquid"] = [*FUNDING_CORE_SYMBOLS, "PEPE", "WIF"]
    stub_upstreams["board"].update(
        build_board({"PEPE": FUNDING_EXTREME_THRESHOLD * 2, "WIF": 0.0002})
    )

    symbols = [row["symbol"] for row in await fetch_funding_rates()]

    assert symbols[-1] == "PEPE"
    assert "WIF" not in symbols


async def test_a_rate_exactly_on_the_threshold_counts_as_extreme(stub_upstreams):
    stub_upstreams["liquid"] = [*FUNDING_CORE_SYMBOLS, "PEPE"]
    stub_upstreams["board"].update(build_board({"PEPE": FUNDING_EXTREME_THRESHOLD}))

    symbols = [row["symbol"] for row in await fetch_funding_rates()]

    assert "PEPE" in symbols


async def test_only_the_loudest_outliers_survive_the_limit(stub_upstreams):
    # Eight candidates, ascending in intensity, for a limit of five.
    candidates = {f"ALT{i}": 0.001 * i for i in range(1, 9)}
    stub_upstreams["liquid"] = [*FUNDING_CORE_SYMBOLS, *candidates]
    stub_upstreams["board"].update(build_board(candidates))

    rows = await fetch_funding_rates()
    outliers = [row["symbol"] for row in rows if row["symbol"].startswith("ALT")]

    assert outliers == ["ALT8", "ALT7", "ALT6", "ALT5", "ALT4"]
    assert len(outliers) == FUNDING_EXTREME_LIMIT


async def test_extreme_pair_outside_the_liquid_universe_is_ignored(stub_upstreams):
    # SKHYNIX is a tokenised equity OKX quotes as a `-USDT-SWAP`. It sits on the
    # funding board but never in the registry's crypto ranking, so it must not
    # reach the widget however loud its rate is.
    stub_upstreams["board"].update(build_board({"SKHYNIX": 0.005}))

    symbols = [row["symbol"] for row in await fetch_funding_rates()]

    assert "SKHYNIX" not in symbols


async def test_interval_hours_is_read_off_the_payload(stub_upstreams):
    stub_upstreams["liquid"] = [*FUNDING_CORE_SYMBOLS, "PEPE"]
    stub_upstreams["board"].update(build_board({"PEPE": 0.002}, interval_hours=4))

    rows = {row["symbol"]: row for row in await fetch_funding_rates()}

    assert rows["BTC"]["interval_hours"] == 8
    assert rows["PEPE"]["interval_hours"] == 4


async def test_interval_falls_back_to_eight_hours_when_okx_omits_the_next_time(stub_upstreams):
    del stub_upstreams["board"]["BTC-USDT-SWAP"]["nextFundingTime"]

    rows = {row["symbol"]: row for row in await fetch_funding_rates()}

    assert rows["BTC"]["interval_hours"] == 8


async def test_a_core_symbol_okx_stops_quoting_is_skipped_not_fatal(stub_upstreams):
    del stub_upstreams["board"]["ADA-USDT-SWAP"]

    symbols = [row["symbol"] for row in await fetch_funding_rates()]

    assert "ADA" not in symbols
    assert "BTC" in symbols
    assert len(symbols) == len(FUNDING_CORE_SYMBOLS) - 1


async def test_a_failed_funding_board_raises_rather_than_returning_a_short_list(stub_upstreams):
    stub_upstreams["board_error"] = RuntimeError("OKX down")

    with pytest.raises(home_service.UpstreamUnavailable):
        await fetch_funding_rates()
