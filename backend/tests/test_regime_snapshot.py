"""
The regime block is what lets a news verdict account for the tape it lands in.
Its contract is the same as the report snapshot's: degrade feed by feed, never
raise, and name every gap so a thin backdrop reads as thin.
"""

import asyncio

import pytest

from services import analysis_data
from services.analysis_data import (
    build_regime_snapshot,
    cached_regime_markdown,
    render_regime_markdown,
)

COINS = [
    {
        "symbol": "BTC",
        "price": 64000.0,
        "change_24h": -2.4,
        "market_cap": 1.2e12,
        "volume_24h": 3e10,
    },
    {"symbol": "ETH", "price": 3100.0, "change_24h": -3.1, "market_cap": 4e11, "volume_24h": 1e10},
    {"symbol": "SOL", "price": 140.0, "change_24h": 1.8, "market_cap": 6e10, "volume_24h": 4e9},
]

MARKET = {
    "total_market_cap": 2.3e12,
    "total_volume_24h": 9e10,
    "btc_dominance": 58.4,
    "eth_dominance": 13.1,
    "coins": COINS,
}

FEAR_GREED = {
    "value": 31,
    "classification": "Fear",
    "history": [{"value": 31}, {"value": 45}],
}


@pytest.fixture(autouse=True)
def clear_cache():
    analysis_data._regime_cache.clear()
    yield
    analysis_data._regime_cache.clear()


def _patch_feeds(
    monkeypatch, *, market=MARKET, fear_greed=FEAR_GREED, liquidations=None, sectors=None, fail=()
):
    """Install fake feed modules; names in `fail` raise instead of returning."""
    import sys
    import types

    async def maybe(name, value):
        if name in fail:
            raise RuntimeError(f"{name} is down")
        return value

    def module(name, **attrs):
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        monkeypatch.setitem(sys.modules, name, mod)

    module(
        "services.market_overview_service",
        fetch_market_overview=lambda: maybe("crypto_market", market),
    )
    module(
        "services.fear_greed_service",
        fetch_fear_greed_index=lambda: maybe("crypto_fear_greed", fear_greed),
    )
    module("services.heatmap_service", fetch_heatmap_data=lambda: maybe("sectors", sectors))

    class _Liq:
        @staticmethod
        def get_heatmap_data(_window):
            return maybe("liquidations", liquidations)

    module("services.liquidation_service", liquidation_service=_Liq())
    module(
        "services.stock_market_service",
        fetch_nasdaq_overview=lambda: maybe("stock_market", {"fear_greed": {"value": 40}}),
        fetch_global_indices=lambda: maybe("global_indices", []),
    )


# ── snapshot ─────────────────────────────────────────────────────────────────


async def test_crypto_items_do_not_fetch_equity_feeds(monkeypatch):
    called = []
    _patch_feeds(monkeypatch)

    import sys
    import types

    async def tracked(*_a, **_k):
        called.append("equities")
        return {}

    mod = types.ModuleType("services.stock_market_service")
    mod.fetch_nasdaq_overview = tracked
    mod.fetch_global_indices = tracked
    monkeypatch.setitem(sys.modules, "services.stock_market_service", mod)

    snapshot = await build_regime_snapshot("crypto")

    assert called == [], "a crypto headline does not need the NASDAQ session"
    assert snapshot["stock_market"] is None


async def test_equity_items_do_fetch_equity_feeds(monkeypatch):
    _patch_feeds(monkeypatch)

    snapshot = await build_regime_snapshot("stock")

    assert snapshot["stock_market"] == {"fear_greed": {"value": 40}}


async def test_derived_metrics_are_computed_in_python(monkeypatch):
    _patch_feeds(monkeypatch)

    snapshot = await build_regime_snapshot("crypto")

    breadth = snapshot["derived"]["breadth"]
    assert breadth["universe_size"] == 3
    assert breadth["advancing"] == 1
    assert snapshot["derived"]["fear_greed_trend"]["delta_7d"] == 31 - 45
    assert snapshot["derived"]["fear_greed_trend"]["direction"] == "falling"


async def test_a_failing_feed_is_named_not_raised(monkeypatch):
    _patch_feeds(monkeypatch, fail=("crypto_fear_greed",))

    snapshot = await build_regime_snapshot("crypto")

    assert snapshot["crypto_fear_greed"] is None
    assert "Crypto Fear & Greed index" in snapshot["unavailable"]
    assert snapshot["crypto_market"] is not None, "one bad feed must not take the rest down"


async def test_an_empty_feed_counts_as_a_gap(monkeypatch):
    _patch_feeds(monkeypatch, sectors=None)

    snapshot = await build_regime_snapshot("crypto")

    assert "Sector breadth" in snapshot["unavailable"]


async def test_a_slow_feed_is_bounded_by_the_timeout(monkeypatch):
    import sys
    import types

    _patch_feeds(monkeypatch)

    async def hang():
        await asyncio.sleep(10)

    mod = types.ModuleType("services.market_overview_service")
    mod.fetch_market_overview = hang
    monkeypatch.setitem(sys.modules, "services.market_overview_service", mod)

    snapshot = await build_regime_snapshot("crypto", feed_timeout=0.05)

    assert snapshot["crypto_market"] is None
    assert "Crypto market overview" in snapshot["unavailable"]


# ── rendering ────────────────────────────────────────────────────────────────


async def test_rendered_block_carries_the_figures_a_verdict_turns_on(monkeypatch):
    _patch_feeds(monkeypatch)

    block = render_regime_markdown(await build_regime_snapshot("crypto"))

    assert "MARKET REGIME" in block
    assert "58.4" in block, "BTC dominance"
    assert "31" in block, "Fear & Greed level"
    assert "advancing" in block


async def test_rendered_block_omits_sections_the_regime_never_collects(monkeypatch):
    _patch_feeds(monkeypatch)

    block = render_regime_markdown(await build_regime_snapshot("crypto"))

    assert "Technical levels" not in block, "levels come from the per-symbol technicals block"
    assert "News headlines" not in block, "the item under analysis is the news"


async def test_rendered_block_lists_unavailable_feeds(monkeypatch):
    _patch_feeds(monkeypatch, fail=("sectors",))

    block = render_regime_markdown(await build_regime_snapshot("crypto"))

    assert "UNAVAILABLE" in block
    assert "Sector breadth" in block


def test_a_wholly_empty_regime_forbids_characterising_the_backdrop():
    block = render_regime_markdown(
        {
            "asset_type": "crypto",
            "crypto_market": None,
            "crypto_fear_greed": None,
            "stock_market": None,
            "global_indices": None,
            "liquidations": None,
            "sectors": None,
            "derived": {},
            "unavailable": ["everything"],
        }
    )

    assert "not available" in block
    assert "do not characterise" in block.lower()


# ── cache ────────────────────────────────────────────────────────────────────


async def test_the_rendered_regime_is_cached_per_asset_type(monkeypatch):
    calls = []

    _patch_feeds(monkeypatch)
    original = analysis_data.build_regime_snapshot

    async def counted(asset_type, **kwargs):
        calls.append(asset_type)
        return await original(asset_type, **kwargs)

    monkeypatch.setattr(analysis_data, "build_regime_snapshot", counted)

    first = await cached_regime_markdown("crypto")
    second = await cached_regime_markdown("crypto")

    assert first == second
    assert calls == ["crypto"], "the backdrop does not turn over between two clicks"


async def test_crypto_and_stock_regimes_are_cached_separately(monkeypatch):
    calls = []

    _patch_feeds(monkeypatch)
    original = analysis_data.build_regime_snapshot

    async def counted(asset_type, **kwargs):
        calls.append(asset_type)
        return await original(asset_type, **kwargs)

    monkeypatch.setattr(analysis_data, "build_regime_snapshot", counted)

    await cached_regime_markdown("crypto")
    await cached_regime_markdown("stock")

    assert calls == ["crypto", "stock"]
