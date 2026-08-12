"""
Tests for the market snapshot builder.

The point of `analysis_data` is that a broken feed degrades the report instead
of killing it, so these tests mostly poke at failure paths.
"""

import asyncio

import pytest

from services import analysis_data


class _FakeNews:
    def __init__(self, title, asset_type, published_at, source="Test"):
        self.title = title
        self.asset_type = asset_type
        self.published_at = published_at
        self.source = source


def _coins():
    return [
        {"symbol": "BTC", "price": 100.0, "change_24h": 2.0, "market_cap": 1000, "volume_24h": 10},
        {"symbol": "ETH", "price": 50.0, "change_24h": -1.0, "market_cap": 500, "volume_24h": 5},
        {"symbol": "SOL", "price": 10.0, "change_24h": 5.0, "market_cap": 100, "volume_24h": 1},
    ]


@pytest.fixture
def patch_feeds(monkeypatch):
    """
    Replace every external feed with a controllable double.

    Returns a dict of feed name -> callable so a test can swap one for a
    failing version.
    """

    async def market():
        return {
            "coins": _coins(),
            "total_market_cap": 1600,
            "total_volume_24h": 16,
            "btc_dominance": 62.5,
            "eth_dominance": 31.25,
        }

    async def fear_greed():
        return {
            "value": 40,
            "classification": "Fear",
            "history": [{"value": 40}, {"value": 55}],
        }

    async def nasdaq():
        return {"coins": [], "market_status": {"status": "Open"}, "fear_greed": None}

    async def indices():
        return [
            {
                "symbol": "^GSPC",
                "name": "S&P 500",
                "region": "US",
                "price": 5000.0,
                "change_24h": 0.4,
            }
        ]

    async def liquidations(window):
        return [
            {"symbol": "BTCUSDT", "value": 300.0, "long_liq": 200.0, "short_liq": 100.0, "count": 4}
        ]

    async def whales():
        return {
            "trades": [],
            "stats": {
                "net_flow": 5.0,
                "observed_volume": 50.0,
                "buy_pressure_percent": 55.0,
                "window_seconds": 3600,
                "whale_count": 3,
            },
        }

    async def sectors():
        return {"sectors": {"L1": [{"price_change_24h": 3.0}, {"price_change_24h": 1.0}]}}

    async def technicals(movers):
        return {
            "BTCUSDT": {
                "current_price": 100.0,
                "support_levels": ["95", "92"],
                "resistance_levels": ["105", "108"],
                "rsi_value": 55.0,
                "rsi_signal": "Neutral",
                "pivot_point": "100",
                "target_price": "104",
                "atr": 3.0,
                "trend": "Uptrend",
            }
        }

    async def news(timeframe):
        from datetime import datetime

        return [_FakeNews("BTC headline", "crypto", datetime(2026, 1, 1, 12, 0))]

    import services.fear_greed_service as fg_module
    import services.heatmap_service as heatmap_module
    import services.liquidation_service as liq_module
    import services.market_overview_service as market_module
    import services.onchain_service as onchain_module
    import services.stock_market_service as stock_module

    monkeypatch.setattr(market_module, "fetch_market_overview", market)
    monkeypatch.setattr(fg_module, "fetch_fear_greed_index", fear_greed)
    monkeypatch.setattr(stock_module, "fetch_nasdaq_overview", nasdaq)
    monkeypatch.setattr(stock_module, "fetch_global_indices", indices)
    monkeypatch.setattr(liq_module.liquidation_service, "get_heatmap_data", liquidations)
    monkeypatch.setattr(onchain_module, "fetch_whale_trades", whales)
    monkeypatch.setattr(heatmap_module, "fetch_heatmap_data", sectors)
    monkeypatch.setattr(analysis_data, "_fetch_technicals", technicals)
    monkeypatch.setattr(analysis_data, "_fetch_news", news)

    return {"market": market_module, "onchain": onchain_module}


async def test_build_market_snapshot_all_feeds_healthy_reports_no_gaps(patch_feeds):
    snapshot = await analysis_data.build_market_snapshot("daily")

    assert snapshot["unavailable"] == [], f"Expected no gaps, got {snapshot['unavailable']}"
    assert snapshot["timeframe"] == "daily", "Timeframe should be echoed back on the snapshot"
    assert snapshot["derived"]["breadth"]["advancing"] == 2, "Two of three coins are up on the day"


async def test_build_market_snapshot_failing_feed_is_recorded_not_raised(patch_feeds, monkeypatch):
    async def broken():
        raise RuntimeError("upstream 503")

    monkeypatch.setattr(patch_feeds["onchain"], "fetch_whale_trades", broken)

    snapshot = await analysis_data.build_market_snapshot("daily")

    assert snapshot["whales"] is None, "A failed feed must leave its slot empty"
    assert analysis_data.FEED_NAMES["whales"] in snapshot["unavailable"], (
        f"Failed feed missing from gap list: {snapshot['unavailable']}"
    )
    assert snapshot["crypto_market"] is not None, "Healthy feeds must survive a sibling failure"


async def test_build_market_snapshot_stalled_feed_times_out_and_is_flagged(
    patch_feeds, monkeypatch
):
    async def hangs():
        await asyncio.sleep(3600)

    monkeypatch.setattr(analysis_data, "FEED_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(patch_feeds["onchain"], "fetch_whale_trades", hangs)

    snapshot = await analysis_data.build_market_snapshot("daily")

    assert snapshot["whales"] is None, "A stalled feed must not block the snapshot"
    assert analysis_data.FEED_NAMES["whales"] in snapshot["unavailable"], (
        f"Timed-out feed missing from gap list: {snapshot['unavailable']}"
    )


async def test_build_market_snapshot_every_feed_failing_still_returns(patch_feeds, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("everything is down")

    for module, name in (
        ("services.market_overview_service", "fetch_market_overview"),
        ("services.fear_greed_service", "fetch_fear_greed_index"),
        ("services.stock_market_service", "fetch_nasdaq_overview"),
        ("services.stock_market_service", "fetch_global_indices"),
        ("services.onchain_service", "fetch_whale_trades"),
        ("services.heatmap_service", "fetch_heatmap_data"),
    ):
        monkeypatch.setattr(f"{module}.{name}", broken)
    monkeypatch.setattr("services.liquidation_service.liquidation_service.get_heatmap_data", broken)
    monkeypatch.setattr(analysis_data, "_fetch_technicals", broken)
    monkeypatch.setattr(analysis_data, "_fetch_news", broken)

    snapshot = await analysis_data.build_market_snapshot("weekly")

    assert len(snapshot["unavailable"]) == len(analysis_data.FEED_NAMES), (
        f"All feeds should be flagged, got {snapshot['unavailable']}"
    )
    rendered = analysis_data.render_snapshot_markdown(snapshot)
    assert "UNAVAILABLE" in rendered, "The prompt block must tell the model what is missing"


async def test_render_snapshot_markdown_includes_derived_metrics(patch_feeds):
    snapshot = await analysis_data.build_market_snapshot("daily")
    rendered = analysis_data.render_snapshot_markdown(snapshot)

    assert "Breadth:" in rendered, "Breadth is a core derived metric and must reach the prompt"
    assert "Liquidations over the last" in rendered, "Liquidation stats must reach the prompt"
    assert "BTC headline" in rendered, "Headlines must reach the prompt"


def test_render_derivatives_empty_whale_window_reports_no_reading():
    """An empty window yields `buy_pressure_percent = None`; that must not crash."""
    snapshot = {
        "derived": {"liquidations": None, "liquidation_window_hours": 24},
        "whales": {
            "stats": {
                "net_flow": 0,
                "observed_volume": 0,
                "buy_pressure_percent": None,
                "window_seconds": 0,
                "whale_count": 0,
            }
        },
    }
    rendered = analysis_data._render_derivatives(snapshot)
    assert rendered is None, f"An empty whale window is not a reading, got {rendered!r}"


def test_render_derivatives_reports_observed_volume_not_a_missing_key():
    """The renderer must read the key the feed actually emits (`observed_volume`)."""
    snapshot = {
        "derived": {"liquidations": None, "liquidation_window_hours": 24},
        "whales": {
            "stats": {
                "net_flow": 5.0,
                "observed_volume": 50.0,
                "buy_pressure_percent": 55.0,
                "window_seconds": 3600,
                "whale_count": 3,
            }
        },
    }
    rendered = analysis_data._render_derivatives(snapshot)
    assert "$50" in rendered, f"Observed volume must reach the prompt, got {rendered!r}"
    assert "55.0%" in rendered, f"Buy pressure must reach the prompt, got {rendered!r}"
    assert "n/a" not in rendered, f"No field should render as unavailable, got {rendered!r}"


def test_breadth_empty_universe_returns_none():
    assert analysis_data._breadth([]) is None, "No coins means no breadth reading"


def test_liquidation_stats_zero_notional_returns_none():
    rows = [{"symbol": "X", "value": 0, "long_liq": 0, "short_liq": 0, "count": 0}]
    assert analysis_data._liquidation_stats(rows) is None, "Zero notional is not a reading"


def test_fear_greed_trend_falling_when_index_dropped():
    trend = analysis_data._fear_greed_trend(
        {"value": 30, "classification": "Fear", "history": [{"value": 30}, {"value": 60}]}
    )
    assert trend["delta_7d"] == -30, f"Expected -30, got {trend['delta_7d']}"
    assert trend["direction"] == "falling", f"Expected falling, got {trend['direction']}"
