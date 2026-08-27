"""
The home macro calendar: its horizon, its fallback, and its refusal.

The panel used to run on ForexFactory's `ff_calendar_thisweek.xml`, which is the
only file that feed publishes — the nextweek and thismonth URLs answer 404 — so
by Friday afternoon the widget was down to a row or two and looked broken. The
month-ahead source is now primary and the week feed sits behind it, which makes
three things worth pinning: the normalisation that lets the frontend treat the
two sources identically, the order the chain is tried in, and the fact that a
total outage still raises rather than returning an empty month.

Nothing here touches the network.
"""

from datetime import datetime, timedelta, UTC

import pytest

from services import home_service
from services.cache import home_cache


@pytest.fixture(autouse=True)
def _clean_cache():
    """Each test starts with no cached calendar, no stale copy and no backoff."""
    home_cache.clear()
    yield
    home_cache.clear()


def _tv_event(**overrides):
    """A TradingView calendar entry, medium impact, an hour from now."""
    scheduled = datetime.now(UTC) + timedelta(hours=1)
    event = {
        "title": "Unemployment Claims",
        "country": "US",
        "date": scheduled.strftime("%Y-%m-%dT%H:%M:00.000Z"),
        "importance": 0,
        "forecast": 231,
        "previous": 226.5,
        "unit": None,
        "scale": "K",
    }
    event.update(overrides)
    return event


def _tv_payload(*events):
    return {"status": "ok", "result": list(events)}


def _stub_month(monkeypatch, payload):
    """Answer the TradingView fetch with `payload`, or raise it if it is an error."""
    captured = {}

    async def get_json(url, *, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(home_service, "get_json", get_json)
    return captured


def _stub_week(monkeypatch, events):
    """Answer the ForexFactory fallback with `events`, or raise it."""
    calls = []

    async def load_week():
        calls.append(True)
        if isinstance(events, Exception):
            raise events
        return events

    monkeypatch.setattr(home_service, "_load_macro_week", load_week)
    return calls


# ==========================================
# HORIZON
# ==========================================


@pytest.mark.asyncio
async def test_asks_for_a_month_not_a_week(monkeypatch):
    """The whole point of the source change: the window is a month wide."""
    captured = _stub_month(monkeypatch, _tv_payload(_tv_event()))
    _stub_week(monkeypatch, [])

    await home_service.fetch_macro_calendar()

    start = datetime.strptime(captured["params"]["from"], "%Y-%m-%dT%H:%M:%S.000Z")
    end = datetime.strptime(captured["params"]["to"], "%Y-%m-%dT%H:%M:%S.000Z")
    assert (end - start).days == home_service.MACRO_HORIZON_DAYS
    assert captured["params"]["countries"] == "US"


@pytest.mark.asyncio
async def test_sends_the_origin_the_endpoint_checks(monkeypatch):
    """A browser User-Agent alone earns a 403 here; the widget's Origin does not."""
    captured = _stub_month(monkeypatch, _tv_payload(_tv_event()))

    await home_service.fetch_macro_calendar()

    assert captured["headers"]["Origin"] == "https://www.tradingview.com"


# ==========================================
# NORMALISATION
# ==========================================


@pytest.mark.asyncio
async def test_month_entries_take_the_week_feed_shape(monkeypatch):
    """
    The frontend prints whatever it is handed, so both sources must hand it the
    same fields in the same formats.
    """
    scheduled = datetime.now(UTC).replace(microsecond=0) + timedelta(days=2, hours=1)
    scheduled = scheduled.replace(hour=13, minute=30)
    _stub_month(
        monkeypatch,
        _tv_payload(_tv_event(date=scheduled.strftime("%Y-%m-%dT%H:%M:00.000Z"))),
    )

    (event,) = await home_service.fetch_macro_calendar()

    assert event["date"] == scheduled.strftime("%m-%d-%Y")
    assert event["time"] == "1:30pm"
    assert event["country"] == "USD"
    assert event["impact"] == "Medium"
    assert event["forecast"] == "231K"
    assert event["previous"] == "226.5K"


@pytest.mark.asyncio
async def test_high_importance_maps_to_high_impact(monkeypatch):
    _stub_month(monkeypatch, _tv_payload(_tv_event(importance=1)))

    (event,) = await home_service.fetch_macro_calendar()

    assert event["impact"] == "High"


@pytest.mark.asyncio
async def test_low_importance_is_dropped(monkeypatch):
    """
    A month of low-impact entries is API crude stocks and regional Fed speeches;
    keeping them would bury the releases that move a book.
    """
    _stub_month(
        monkeypatch,
        _tv_payload(_tv_event(importance=-1), _tv_event(importance=1, title="CPI")),
    )

    events = await home_service.fetch_macro_calendar()

    assert [e["title"] for e in events] == ["CPI"]


@pytest.mark.asyncio
async def test_midnight_entries_read_as_all_day(monkeypatch):
    """
    Midnight UTC marks a fixture with no release time. Rendering it as "12:00am"
    would put Jackson Hole at 8pm ET the evening before.
    """
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00.000Z")
    _stub_month(monkeypatch, _tv_payload(_tv_event(date=tomorrow, title="Jackson Hole")))

    (event,) = await home_service.fetch_macro_calendar()

    assert event["time"] == "All Day"


def test_dollar_readings_keep_the_sign_outside_the_symbol():
    assert home_service._format_release_value(-99, "$", "B") == "-$99B"
    assert home_service._format_release_value(6.746, "$", "T") == "$6.746T"
    assert home_service._format_release_value(0.1, "%", "") == "0.1%"
    assert home_service._format_release_value(54.0, "", "") == "54"
    assert home_service._format_release_value(None, "%", "") == ""


# ==========================================
# FILTERING
# ==========================================


@pytest.mark.asyncio
async def test_events_already_printed_are_dropped(monkeypatch):
    """The window starts at "today", so its first day is always partly spent."""
    past = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT13:30:00.000Z")
    _stub_month(monkeypatch, _tv_payload(_tv_event(date=past), _tv_event(title="Ahead")))

    events = await home_service.fetch_macro_calendar()

    assert [e["title"] for e in events] == ["Ahead"]


@pytest.mark.asyncio
async def test_the_list_is_chronological(monkeypatch):
    """The panel groups by day, which only reads if the days arrive in order."""
    later = (datetime.now(UTC) + timedelta(days=5)).strftime("%Y-%m-%dT13:30:00.000Z")
    sooner = (datetime.now(UTC) + timedelta(days=2)).strftime("%Y-%m-%dT13:30:00.000Z")
    _stub_month(
        monkeypatch,
        _tv_payload(_tv_event(date=later, title="Later"), _tv_event(date=sooner, title="Sooner")),
    )

    events = await home_service.fetch_macro_calendar()

    assert [e["title"] for e in events] == ["Sooner", "Later"]


# ==========================================
# THE CHAIN
# ==========================================


@pytest.mark.asyncio
async def test_week_feed_is_not_consulted_while_the_month_answers(monkeypatch):
    _stub_month(monkeypatch, _tv_payload(_tv_event()))
    week_calls = _stub_week(monkeypatch, [])

    await home_service.fetch_macro_calendar()

    assert week_calls == []


@pytest.mark.asyncio
async def test_falls_back_to_the_week_feed(monkeypatch):
    _stub_month(monkeypatch, RuntimeError("403"))
    # Date *and* time from the same future instant. Pinning the clock to a
    # literal made the test pass only when it happened to run before that hour,
    # since `_upcoming` drops anything already scheduled.
    ahead = datetime.now(UTC) + timedelta(hours=2)
    _stub_week(
        monkeypatch,
        [
            {
                "title": "Unemployment Claims",
                "country": "USD",
                "date": ahead.strftime("%m-%d-%Y"),
                "time": ahead.strftime("%I:%M%p").lower(),
                "impact": "Medium",
                "forecast": "231K",
                "previous": "226K",
            }
        ],
    )

    events = await home_service.fetch_macro_calendar()

    assert [e["title"] for e in events] == ["Unemployment Claims"]


@pytest.mark.asyncio
async def test_a_failed_month_backs_off_instead_of_retrying(monkeypatch):
    """A rate-limited feed must not be re-asked once per request."""
    attempts = []

    async def get_json(url, *, params=None, headers=None, timeout=None):
        attempts.append(url)
        raise RuntimeError("429")

    monkeypatch.setattr(home_service, "get_json", get_json)
    _stub_week(monkeypatch, [])

    await home_service.fetch_macro_calendar()
    home_cache.invalidate("macro")
    await home_service.fetch_macro_calendar()

    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_an_empty_result_is_treated_as_a_broken_shape(monkeypatch):
    """
    The window always contains jobless claims. Zero usable rows means the payload
    changed under us, so the week feed gets its turn rather than the panel
    claiming a quiet month.
    """
    _stub_month(monkeypatch, _tv_payload())
    week_calls = _stub_week(monkeypatch, [])

    await home_service.fetch_macro_calendar()

    assert week_calls == [True]


@pytest.mark.asyncio
async def test_total_outage_raises_rather_than_emptying_the_panel(monkeypatch):
    _stub_month(monkeypatch, RuntimeError("403"))
    _stub_week(monkeypatch, RuntimeError("429"))

    with pytest.raises(home_service.UpstreamUnavailable):
        await home_service.fetch_macro_calendar()


@pytest.mark.asyncio
async def test_stale_data_stands_in_before_the_outage_is_reported(monkeypatch):
    """A calendar is scheduled well in advance, so yesterday's copy is today's."""
    _stub_month(monkeypatch, _tv_payload(_tv_event(title="CPI")))
    await home_service.fetch_macro_calendar()
    home_cache.invalidate("macro")

    _stub_month(monkeypatch, RuntimeError("403"))
    _stub_week(monkeypatch, RuntimeError("429"))

    events = await home_service.fetch_macro_calendar()

    assert [e["title"] for e in events] == ["CPI"]
