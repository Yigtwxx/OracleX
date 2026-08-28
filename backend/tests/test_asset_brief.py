"""
The Home brief's composing service.

Everything this module does is orchestration, so the tests are about the seams:
which symbol reaches the downstream calls, what a partial upstream failure does
to the payload, and whether the crypto and equity legs can ever both be present.

The last one carries the most weight. A brief that filled an equity's
`funding_rate` with 0.0 would render a figure a reader could act on for a market
that does not exist, which is the failure `CLAUDE.md` singles out — so the shape
is asserted from both directions rather than only for the class under test.

Nothing here touches the network: every upstream is monkeypatched at the module
it is imported from, because the service imports them inside the functions to
keep the import graph flat.
"""

from typing import Any

import pytest

from services import asset_brief_service, symbol_detection_service
from services.asset_brief_service import SymbolNotFound, build_brief


def _candles(closes: list[float]) -> list[dict[str, Any]]:
    return [{"open": c, "high": c, "low": c, "close": c, "volume": 10.0} for c in closes]


TICKER = {
    "price": 100.0,
    "change_pct": 2.0,
    "volume": 1_000.0,
    "volume_usd": 100_000.0,
    "high_24h": 101.0,
    "low_24h": 99.0,
}

ANALYSIS = {
    "rsi_value": 61.4,
    "rsi_signal": "neutral",
    "trend": "bullish",
    "primary_timeframe": "4h",
    "zones": {
        "support": [{"mid": 95.0, "low": 94.0, "high": 96.0}],
        "resistance": [{"mid": 110.0, "low": 109.0, "high": 111.0}],
    },
}

FUNDING_ROWS = [
    {"symbol": "BTC", "rate": 0.0001, "interval_hours": 8, "is_extreme": False},
    {"symbol": "ETH", "rate": -0.0003, "interval_hours": 8, "is_extreme": False},
]

QUOTE = {
    "symbol": "NVDA",
    "name": "NVIDIA Corporation",
    "sector": "Technology",
    "price": 200.0,
    "change_24h": -1.5,
    "volume_24h": 2_000_000.0,
    "fifty_two_week_high": 250.0,
    "fifty_two_week_low": 100.0,
}


@pytest.fixture(autouse=True)
def _no_notes(monkeypatch):
    """
    The note is a local-model call and is not what any of this is testing.

    Pinned to the real `unavailable` contract rather than to None, so the payload
    under assertion is the one the frontend actually receives.
    """

    async def _unavailable(*_args, **_kwargs):
        return {"status": "unavailable", "note": None, "generated_at": None, "reason": "test"}

    monkeypatch.setattr(asset_brief_service, "get_note", _unavailable)


def _profile(levels: list[list[float]]) -> dict[str, Any]:
    """A liquidation profile on a $1-per-bin grid starting at $90."""
    return {
        "levels": levels,
        "price_min": 90.0,
        "price_max": 110.0,
        "bin_size": 1.0,
        "bins": 20,
        "total_long": 500,
        "total_short": 700,
        "exchange": "OKX",
    }


# [bin, tier, side, notional]; side 0 = longs (below spot), 1 = shorts (above).
# Bins 4 and 5 are the same wall seen at two leverage tiers.
PROFILE_LEVELS = [
    [4, 0, 0, 100.0],
    [5, 1, 0, 90.0],
    [1, 0, 0, 60.0],
    [15, 0, 1, 200.0],
    [16, 1, 1, 150.0],
    [19, 0, 1, 50.0],
]


@pytest.fixture
def crypto(monkeypatch):
    """A resolvable crypto pair with every upstream answering."""
    from services import (
        home_service,
        liquidation_map_service,
        liquidation_service,
        okx_market,
        technical_analysis_service,
    )

    seen: dict[str, Any] = {}

    async def _resolve(candidate, hint="crypto"):
        seen["resolved_candidates"] = seen.get("resolved_candidates", []) + [candidate]
        return "BINANCE:BTCUSDT"

    async def _ticker(symbol):
        seen["ticker_symbol"] = symbol
        return dict(TICKER)

    async def _candle_fetch(symbol, interval="1h", limit=168):
        seen["candles_symbol"] = symbol
        return _candles([90.0 + i * 0.1 for i in range(limit)])

    async def _funding():
        return [dict(row) for row in FUNDING_ROWS]

    async def _analysis(symbol):
        seen["analysis_symbol"] = symbol
        return dict(ANALYSIS)

    monkeypatch.setattr(symbol_detection_service, "resolve", _resolve)
    monkeypatch.setattr(okx_market, "fetch_ticker_24h", _ticker)
    monkeypatch.setattr(
        liquidation_service.liquidation_service, "fetch_candles", staticmethod(_candle_fetch)
    )

    async def _profile_fetch(symbol, **_kwargs):
        seen["profile_symbol"] = symbol
        return _profile(PROFILE_LEVELS)

    monkeypatch.setattr(home_service, "fetch_funding_rates", _funding)
    monkeypatch.setattr(technical_analysis_service, "get_technical_analysis", _analysis)
    monkeypatch.setattr(liquidation_map_service, "get_liquidation_profile", _profile_fetch)
    return seen


@pytest.fixture
def equity(monkeypatch):
    """A resolvable US ticker with every upstream answering."""
    from services import stock_market_service, technical_analysis_service

    async def _resolve(candidate, hint="crypto"):
        return "NASDAQ:NVDA"

    async def _quote(_client, symbol):
        return dict(QUOTE, symbol=symbol)

    async def _candles_for(symbol, interval="1d", range_="6mo"):
        rows = _candles([180.0 + i for i in range(40)])
        # A quiet baseline with one busy session on top, so `relative_volume`
        # has something to actually measure.
        for row in rows[:-1]:
            row["volume"] = 1_000_000.0
        rows[-1]["volume"] = 3_000_000.0
        return rows

    async def _analysis(symbol):
        return dict(ANALYSIS, zones={"support": [{"mid": 190.0}], "resistance": [{"mid": 210.0}]})

    monkeypatch.setattr(symbol_detection_service, "resolve", _resolve)
    monkeypatch.setattr(stock_market_service, "fetch_single_stock", _quote)
    monkeypatch.setattr(stock_market_service, "fetch_stock_candles", _candles_for)
    monkeypatch.setattr(technical_analysis_service, "get_technical_analysis", _analysis)


# ── Resolution ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unresolvable_symbol_is_not_found(monkeypatch):
    async def _nothing(candidate, hint="crypto"):
        return None

    monkeypatch.setattr(symbol_detection_service, "resolve", _nothing)

    with pytest.raises(SymbolNotFound):
        await build_brief("ZZZZNOPE")


@pytest.mark.asyncio
async def test_symbol_is_resolved_once_and_passed_down_venue_qualified(crypto):
    """
    The whole reason this service exists rather than three browser calls.

    `/api/price` and `/api/technical` each carry their own inline heuristic for
    what is crypto; resolving twice is how a tokenised equity perp ends up with
    NASDAQ levels drawn under it.
    """
    brief = await build_brief("btc")

    assert crypto["resolved_candidates"] == ["btc"]
    assert brief["symbol"] == "BINANCE:BTCUSDT"
    assert brief["display_symbol"] == "BTCUSDT"
    # The venue goes to the technical read, which needs it to choose a provider;
    # the bare pair goes to OKX, which does not understand the prefix.
    assert crypto["analysis_symbol"] == "BINANCE:BTCUSDT"
    assert crypto["ticker_symbol"] == "BTCUSDT"


# ── The two legs are mutually exclusive ──────────────────────────────────────


@pytest.mark.asyncio
async def test_crypto_brief_carries_only_the_crypto_leg(crypto):
    brief = await build_brief("BTCUSDT")

    assert brief["asset_type"] == "crypto"
    assert brief["equity"] is None
    assert brief["crypto"]["funding_rate"] == pytest.approx(0.0001)
    assert brief["crypto"]["funding_interval_hours"] == 8


@pytest.mark.asyncio
async def test_equity_brief_carries_only_the_equity_leg(equity):
    brief = await build_brief("NVDA")

    assert brief["asset_type"] == "stock"
    # The assertion that matters: no funding field exists to be read as zero.
    assert brief["crypto"] is None
    assert brief["equity"]["name"] == "NVIDIA Corporation"
    assert brief["equity"]["relative_volume"] == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_pair_without_a_listed_perp_reports_null_funding(crypto, monkeypatch):
    """No perpetual is not a funding rate of zero, and must not render as one."""
    from services import home_service

    async def _no_rows():
        return []

    monkeypatch.setattr(home_service, "fetch_funding_rates", _no_rows)

    brief = await build_brief("BTCUSDT")
    assert brief["crypto"]["funding_rate"] is None
    assert brief["crypto"]["funding_interval_hours"] is None


# ── Degradation ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_price_failure_is_not_found_rather_than_a_placeholder(crypto, monkeypatch):
    from services import okx_market

    async def _no_ticker(symbol):
        return None

    monkeypatch.setattr(okx_market, "fetch_ticker_24h", _no_ticker)

    with pytest.raises(SymbolNotFound):
        await build_brief("BTCUSDT")


@pytest.mark.asyncio
async def test_technical_failure_nulls_the_badges_and_keeps_the_price(crypto, monkeypatch):
    """A missing RSI costs a badge. It must not cost the card."""
    from services import technical_analysis_service

    async def _boom(symbol):
        raise RuntimeError("upstream refused")

    monkeypatch.setattr(technical_analysis_service, "get_technical_analysis", _boom)

    brief = await build_brief("BTCUSDT")

    assert brief["price"] == pytest.approx(100.0)
    assert brief["rsi_14"] is None
    assert brief["trend"] is None
    assert brief["support"] is None
    assert brief["resistance"] is None
    assert brief["support_distance_pct"] is None


@pytest.mark.asyncio
async def test_candle_failure_leaves_an_empty_series_not_a_flat_line(crypto, monkeypatch):
    from services import liquidation_service

    async def _boom(symbol, interval="1h", limit=168):
        raise RuntimeError("no candles")

    monkeypatch.setattr(
        liquidation_service.liquidation_service, "fetch_candles", staticmethod(_boom)
    )

    brief = await build_brief("BTCUSDT")
    assert brief["spark"] == []
    assert brief["change_7d_pct"] is None
    assert brief["price"] == pytest.approx(100.0)


# ── Derived figures ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sparkline_is_downsampled_and_keeps_the_latest_close(crypto):
    brief = await build_brief("BTCUSDT")

    assert len(brief["spark"]) == asset_brief_service.SPARK_POINTS
    # The card's price label sits beside the end of this line, so the last point
    # must survive the thinning.
    assert brief["spark"][-1] == pytest.approx(90.0 + 167 * 0.1)


@pytest.mark.asyncio
async def test_level_distances_are_signed_from_spot(crypto):
    brief = await build_brief("BTCUSDT")

    assert brief["support"] == pytest.approx(95.0)
    assert brief["resistance"] == pytest.approx(110.0)
    assert brief["support_distance_pct"] == pytest.approx(-5.0)
    assert brief["resistance_distance_pct"] == pytest.approx(10.0)


# ── The note's fingerprint ───────────────────────────────────────────────────


def _brief(**over: Any) -> dict[str, Any]:
    base = {
        "display_symbol": "BTCUSDT",
        "asset_type": "crypto",
        "change_24h_pct": 2.03,
        "change_7d_pct": 5.4,
        "rsi_14": 61.4,
        "rsi_signal": "neutral",
        "trend": "bullish",
        "support_distance_pct": -5.02,
        "resistance_distance_pct": 10.1,
        "crypto": {"funding_rate": 0.0001, "funding_is_extreme": False},
        "equity": None,
    }
    base.update(over)
    return base


def test_note_facts_quantize_so_an_unremarkable_tick_reuses_the_note():
    """
    The card refreshes every minute. Fingerprinting raw figures would mean a
    local-model run per minute per symbol, and the cache would never hit.
    """
    first = asset_brief_service.note_facts(_brief())
    second = asset_brief_service.note_facts(_brief(change_24h_pct=2.11, rsi_14=62.0))

    assert first == second


def test_note_facts_change_when_a_reading_crosses_a_bucket():
    moved = asset_brief_service.note_facts(_brief(rsi_14=71.0))
    assert moved != asset_brief_service.note_facts(_brief())


def test_note_facts_carry_the_leg_the_asset_actually_has():
    crypto_facts = asset_brief_service.note_facts(_brief())
    assert "funding_bps" in crypto_facts
    assert "relative_volume" not in crypto_facts

    equity_facts = asset_brief_service.note_facts(
        _brief(
            asset_type="stock",
            crypto=None,
            equity={"relative_volume": 1.63},
        )
    )
    assert "relative_volume" in equity_facts
    assert "funding_bps" not in equity_facts


def test_note_values_render_only_from_the_facts_they_were_given():
    """
    A cached note must never be able to quote a figure that has since moved, so
    the prompt is filled from the rounded facts and never from the live payload.
    """
    facts = asset_brief_service.note_facts(_brief())
    values = asset_brief_service.note_values(facts)

    assert values["symbol"] == "BTCUSDT"
    assert values["asset_class"] == "crypto pair"
    assert f"{facts['change_24h_pct']:+.1f}%" in values["facts"]
    # The raw 2.03 never reaches the prompt — only the bucketed 2.0 does.
    assert "2.03" not in values["facts"]


def test_note_values_state_a_missing_reading_rather_than_omitting_it():
    values = asset_brief_service.note_values(
        asset_brief_service.note_facts(_brief(rsi_14=None, trend=None))
    )
    assert "RSI: not available" in values["facts"]


def test_note_values_say_no_perp_exists_rather_than_printing_zero():
    values = asset_brief_service.note_values(
        asset_brief_service.note_facts(_brief(crypto={"funding_rate": None}))
    )
    assert "no listed perpetual" in values["facts"]
    assert "0.0 bps" not in values["facts"]


# ── The liquidation book ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_liquidity_clusters_are_summarised_per_side(crypto):
    liquidity = (await build_brief("BTCUSDT"))["crypto"]["liquidity"]

    assert liquidity["venue"] == "OKX"
    assert liquidity["total_long_usd"] == 500
    assert liquidity["total_short_usd"] == 700
    assert liquidity["modelled"] is True

    longs = [c for c in liquidity["clusters"] if c["side"] == "long"]
    shorts = [c for c in liquidity["clusters"] if c["side"] == "short"]
    assert longs and shorts
    # Every long wall is below spot and every short wall above it — the sign of
    # `distance_pct` is what the card reads to place them.
    assert all(c["distance_pct"] < 0 for c in longs)
    assert all(c["distance_pct"] > 0 for c in shorts)


@pytest.mark.asyncio
async def test_adjacent_bins_are_one_wall_not_several(crypto):
    """
    The model deposits the same wall once per leverage tier, so bins 4 and 5 are
    one level seen twice. Reporting both would tell the reader there are two
    walls a dollar apart, which is a claim the simulation never made.
    """
    liquidity = (await build_brief("BTCUSDT"))["crypto"]["liquidity"]
    longs = sorted(c["price"] for c in liquidity["clusters"] if c["side"] == "long")

    assert longs == pytest.approx([91.5, 94.5])


@pytest.mark.asyncio
async def test_clusters_are_capped_per_side(crypto, monkeypatch):
    from services import liquidation_map_service

    crowded = [[index, 0, 0, 100.0 - index] for index in range(0, 20, 3)]

    async def _crowded(symbol, **_kwargs):
        return _profile(crowded)

    monkeypatch.setattr(liquidation_map_service, "get_liquidation_profile", _crowded)

    liquidity = (await build_brief("BTCUSDT"))["crypto"]["liquidity"]
    assert len(liquidity["clusters"]) <= asset_brief_service.LIQUIDITY_CLUSTERS_PER_SIDE * 2


@pytest.mark.asyncio
async def test_unmodellable_book_is_null_rather_than_empty(crypto, monkeypatch):
    """
    An empty ladder and a book nobody could model look identical once drawn, and
    they are opposite claims. The card renders nothing for null.
    """
    from services import liquidation_map_service

    async def _empty(symbol, **_kwargs):
        return _profile([])

    monkeypatch.setattr(liquidation_map_service, "get_liquidation_profile", _empty)
    assert (await build_brief("BTCUSDT"))["crypto"]["liquidity"] is None


@pytest.mark.asyncio
async def test_profile_failure_does_not_cost_the_card(crypto, monkeypatch):
    from services import liquidation_map_service

    async def _boom(symbol, **_kwargs):
        raise RuntimeError("venue unreachable")

    monkeypatch.setattr(liquidation_map_service, "get_liquidation_profile", _boom)

    brief = await build_brief("BTCUSDT")
    assert brief["crypto"]["liquidity"] is None
    assert brief["price"] == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_equities_have_no_liquidation_book_to_report(equity):
    """
    The book is modelled from perpetual open interest and US equities have no
    equivalent public feed, so the field does not exist on that leg at all —
    rather than existing and reading as an empty book.
    """
    brief = await build_brief("NVDA")
    assert "liquidity" not in brief["equity"]
