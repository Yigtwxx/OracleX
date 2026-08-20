"""
The exchange-flow strip, and the daily history now kept behind it.

`flows.py` had no tests before the anomaly detector started depending on it, and
the risk this file guards is specific: the strip's payload feeds a rendered UI
panel, and widening the lookback to build a baseline must not change one byte of
what that panel receives.

Nothing here touches the network — `get_json` is replaced with a function that
returns literal rows, which is the only upstream this module has.
"""

import pytest

from services.chains import flows


@pytest.fixture(autouse=True)
def _clean_series(monkeypatch):
    monkeypatch.setattr(flows, "_series", {})


def _rows(asset: str, days: int, *, addresses: int = 900_000) -> list[dict]:
    return [
        {
            "asset": asset,
            "time": f"2026-07-{day + 1:02d}T00:00:00.000000000Z",
            "AdrActCnt": str(addresses + day),
            "TxCnt": "400000",
            "FlowInExUSD": "1000000",
            "FlowOutExUSD": "400000",
        }
        for day in range(days)
    ]


@pytest.fixture
def upstream(monkeypatch):
    """Serve a canned Coin Metrics response and record the request."""
    captured = {}

    async def fake_get_json(_url, **kwargs):
        captured["params"] = kwargs.get("params")
        return captured["payload"]

    captured["payload"] = {"data": _rows("btc", 30) + _rows("eth", 30)}
    monkeypatch.setattr(flows, "get_json", fake_get_json)
    return captured


async def test_the_strip_payload_is_unchanged_by_the_longer_lookback(upstream):
    """
    `FlowStrip` renders these three fields and nothing else. Widening the window
    to build a baseline must be invisible to it.
    """
    result = await flows.fetch_flows()

    assert sorted(result) == ["as_of", "assets"], "The board payload must not grow"
    btc = next(row for row in result["assets"] if row["symbol"] == "BTC")
    assert sorted(btc) == ["active_addresses", "net_flow_usd", "symbol", "transactions"]
    assert btc["net_flow_usd"] == pytest.approx(600000.0)


async def test_the_daily_history_is_kept_beside_the_strip(upstream):
    """
    Thirty days of dailies is what makes a deviation measurable, and it is held
    here rather than returned on the board — which is a ten-second payload polled
    by every open tab and has no business carrying a month of history with it.
    """
    await flows.fetch_flows()

    series = flows.recent_series()
    assert set(series) == {"BTC", "ETH"}
    assert len(series["BTC"]) == 30
    assert series["BTC"][0]["date"] == "2026-07-01"
    assert series["BTC"][-1]["active_addresses"] == 900_029


async def test_an_outage_leaves_the_previous_history_alone(upstream, monkeypatch):
    """
    A stale baseline is worth more than none — the caller can see the dates and
    judge for itself. And the strip's own contract is that an outage is an empty
    asset list, never a raised exception.
    """
    await flows.fetch_flows()

    async def boom(_url, **_kwargs):
        raise RuntimeError("coin metrics is down")

    monkeypatch.setattr(flows, "get_json", boom)
    result = await flows.fetch_flows()

    assert result == {"assets": [], "as_of": None}
    assert len(flows.recent_series()["BTC"]) == 30


async def test_a_late_publishing_metric_still_resolves(upstream):
    """
    The reason a lookback existed at all: metrics land at different times, so the
    newest row overall is not necessarily the newest row carrying a given metric.
    """
    rows = _rows("btc", 30)
    for row in rows[-3:]:
        del row["AdrActCnt"]
    upstream["payload"] = {"data": rows}

    result = await flows.fetch_flows()
    btc = next(row for row in result["assets"] if row["symbol"] == "BTC")

    assert btc["active_addresses"] == 900_026, "The last published day, not None"
    assert flows.recent_series()["BTC"][-1]["active_addresses"] is None


async def test_the_window_still_fits_in_one_page(upstream):
    """
    One request, one page. Coin Metrics returns a row per asset per day, so the
    lookback and the covered assets together have to stay under `page_size` —
    past roughly 49 days this would silently truncate instead of paginating.
    """
    await flows.fetch_flows()

    page_size = upstream["params"]["page_size"]
    assert flows.LOOKBACK_DAYS * len(flows.COVERED) <= page_size
