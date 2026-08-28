"""
Where the previous close comes from, and why it is not the field named after it.

Yahoo's `meta.chartPreviousClose` is the close preceding the requested *range
window*, so it drifts further from the previous session the wider the range: at
`range=2d` the global ticker reported the DAX down 0.16% on a session it closed
up 0.26%, and at `range=5d` the stock detail card reported AAPL up 1.98% on a
day it fell 1.75%. Both were the wrong sign, not merely the wrong magnitude.

These pin the replacement: the reference close is read from the daily bars, and
a payload that cannot supply one reports no change rather than a flat zero.
"""

from services.yahoo_chart import previous_close

SESSION_OPEN = 1_787_260_000
DAY = 86_400


def _payload(closes, *, market_time=None, meta=None, first_open=None):
    """A v8 chart payload carrying `closes` as consecutive daily bars."""
    start = first_open if first_open is not None else SESSION_OPEN - (len(closes) - 1) * DAY
    timestamps = [start + i * DAY for i in range(len(closes))]
    result = {
        "meta": {"regularMarketPrice": closes[-1], **(meta or {})},
        "timestamp": timestamps,
        "indicators": {"quote": [{"close": list(closes)}]},
    }
    if market_time is not None:
        result["meta"]["regularMarketTime"] = market_time
    return {"chart": {"result": [result]}}


def test_the_reference_close_is_the_bar_before_the_live_one():
    payload = _payload([100.0, 110.0, 120.0], market_time=SESSION_OPEN + 3600)

    assert previous_close(payload) == 110.0


def test_the_range_windows_own_previous_close_is_ignored():
    """
    The whole point of the module: `chartPreviousClose` disagrees with the bars
    by however many sessions the range spans, and the bars win.
    """
    payload = _payload(
        [100.0, 110.0, 120.0],
        market_time=SESSION_OPEN + 3600,
        meta={"chartPreviousClose": 100.0},
    )

    assert previous_close(payload) == 110.0


def test_a_quote_from_a_session_with_no_bar_yet_uses_the_last_bar():
    """
    Pre-market on a venue whose daily bar appears late: the newest bar is
    already the previous session, so stepping back one more would skip a day.
    """
    payload = _payload([100.0, 110.0], market_time=SESSION_OPEN + 2 * DAY)

    assert previous_close(payload) == 110.0


def test_bars_without_a_close_are_skipped_rather_than_read_as_zero():
    payload = _payload([100.0, 110.0, 120.0], market_time=SESSION_OPEN + 3600)
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][1] = None

    assert previous_close(payload) == 100.0


def test_a_single_bar_reports_no_reference_close():
    payload = _payload([120.0], market_time=SESSION_OPEN + 3600)

    assert previous_close(payload) is None


def test_a_payload_with_no_bars_falls_back_to_the_range_independent_field():
    payload = {
        "chart": {"result": [{"meta": {"regularMarketPrice": 120.0, "previousClose": 110.0}}]}
    }

    assert previous_close(payload) == 110.0


def test_a_malformed_payload_reports_no_reference_close():
    assert previous_close({}) is None
    assert previous_close({"chart": {"result": []}}) is None
    assert previous_close(None) is None
