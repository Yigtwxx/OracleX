"""
Characterization tests for the Live tab's event calendar.

The three things pinned here are the ones whose failure is silent: a timezone
that drifts an hour across a DST boundary, a status window that leaves an event
stuck on LIVE, and a source-format quirk that drops rows without erroring.
"""

from datetime import UTC, datetime, timedelta

import pytest

from services import live_events_service as les


# ==========================================
# FED CALENDAR PARSING
# ==========================================


@pytest.mark.parametrize(
    "month,days,time_str,expected_utc",
    [
        # November — Eastern is UTC-5, so a 2:00 p.m. statement lands at 19:00Z.
        ("2026-11", "18", "2:00 p.m.", "2026-11-18T19:00:00+00:00"),
        # July — Eastern is UTC-4, so the same wall-clock time lands at 18:00Z.
        # These two together are the whole point: a fixed offset passes one and
        # fails the other, and the failure is a silent one-hour drift.
        ("2026-07", "29", "2:00 p.m.", "2026-07-29T18:00:00+00:00"),
        ("2026-08", "5", "4:05 p.m.", "2026-08-05T20:05:00+00:00"),
        ("2026-08", "8", "12:45 p.m.", "2026-08-08T16:45:00+00:00"),
    ],
)
def test_fed_start_converts_eastern_to_utc_across_dst(month, days, time_str, expected_utc):
    result = les._fed_start({"month": month, "days": days, "time": time_str})

    assert result is not None, f"Expected a parsed instant for {month}-{days} {time_str}"
    starts_at, confirmed = result
    assert confirmed is True, "A published clock time must count as confirmed"
    assert starts_at.astimezone(UTC).isoformat() == expected_utc, (
        f"Expected {expected_utc}, got {starts_at.astimezone(UTC).isoformat()}"
    )


def test_fed_start_untimed_entry_falls_to_end_of_day_unconfirmed():
    """A quarter of the Fed feed carries no time; those must never read as live."""
    result = les._fed_start({"month": "2026-09", "days": "7", "time": ""})

    assert result is not None, "An untimed entry should still be placed on its day"
    starts_at, confirmed = result
    assert confirmed is False, "No published time means the clock is not confirmed"
    assert (starts_at.hour, starts_at.minute) == (23, 59), (
        f"Expected end of day, got {starts_at.hour}:{starts_at.minute}"
    )


@pytest.mark.parametrize("days", ["3, 10, 17, 24", "14-15"])
def test_fed_start_takes_the_first_day_of_a_multi_day_field(days):
    """Recurring releases write a list into `days`; `int()` on it would raise."""
    result = les._fed_start({"month": "2026-09", "days": days, "time": "2:00 p.m."})

    assert result is not None, f"Expected {days!r} to parse rather than be dropped"
    assert result[0].day == int(days.split(",")[0].split("-")[0])


@pytest.mark.parametrize("entry", [{}, {"month": "2026-09"}, {"month": "nonsense", "days": "3"}])
def test_fed_start_returns_none_rather_than_raising_on_junk(entry):
    assert les._fed_start(entry) is None, f"Expected None for {entry!r}"


def test_clean_unwraps_the_feeds_escaped_markup():
    raw = "&lt;p&gt;Two-day meeting, September 15 - 16&lt;br /&gt;&#10;Press Conference&lt;/p&gt;"

    assert les._clean(raw) == "Two-day meeting, September 15 - 16 Press Conference"


# ==========================================
# CLASSIFICATION AND DURATION
# ==========================================


@pytest.mark.parametrize(
    "title,expected_shape",
    [
        # Ordering matters here: "FOMC Press Conference" contains both the FOMC
        # marker and the presser marker, and must not be given the 120-minute
        # meeting window.
        ("FOMC Press Conference", "presser"),
        ("FOMC Statement", "fomc"),
        ("FOMC Member Hammack Speaks", "speech"),
        ("RBA Press Conference", "presser"),
        ("Main Refinancing Rate", "data"),
        ("Official Bank Rate", "decision"),
        ("Core CPI m/m", "data"),
        ("Testimony - Chairman Kevin Warsh", "presser"),
    ],
)
def test_shape_places_a_title_in_its_duration_bucket(title, expected_shape):
    assert les._shape(title) == expected_shape, f"{title!r} misclassified"


@pytest.mark.parametrize(
    "title,source,expected_kind",
    [
        ("FOMC Member Barkin Speaks", "forexfactory", "central_bank"),
        ("ECB President Lagarde Speaks", "forexfactory", "central_bank"),
        ("Core CPI m/m", "forexfactory", "macro_data"),
        ("Trump Speaks on Tariffs", "forexfactory", "political"),
        ("CSCO earnings", "nasdaq", "corporate"),
        # A Fed entry is a central banker whatever the title reads like —
        # testimony to Congress would otherwise trip the political keywords.
        ("Testimony - Chairman Kevin Warsh", "federalreserve", "central_bank"),
    ],
)
def test_classify_routes_a_title_to_its_filter_chip(title, source, expected_kind):
    assert les._classify(title, source) == expected_kind, f"{title!r} misrouted"


def test_speaker_is_lifted_out_of_the_fed_title():
    assert les._speaker("Speech - Governor Lisa D. Cook") == "Governor Lisa D. Cook"
    assert les._speaker("Beige Book") is None


@pytest.mark.parametrize(
    "raw,expected",
    [("$478,608,411,371", 478608411371.0), ("N/A", None), ("", None), (None, None)],
)
def test_market_cap_parses_nasdaqs_formatted_string(raw, expected):
    assert les._market_cap(raw) == expected, f"Expected {expected} from {raw!r}"


# ==========================================
# STATUS DERIVATION
# ==========================================


def _event(starts_at: datetime, *, shape: str = "presser", **overrides):
    return les._build(
        source="federalreserve",
        title="FOMC Press Conference",
        starts_at=starts_at,
        impact="high",
        shape=shape,
        **overrides,
    )


NOW = datetime(2026, 9, 16, 18, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "offset_minutes,expected_status",
    [
        (-1, "live"),  # one minute in
        (-89, "live"),  # a presser runs 90 minutes
        (-91, "ended"),  # one minute past the window
        (1, "scheduled"),  # not yet
    ],
)
def test_derive_status_walks_the_event_window(offset_minutes, expected_status):
    event = _event(NOW + timedelta(minutes=offset_minutes))

    placed = les._with_status(event, NOW, [])

    assert placed["status"] == expected_status, (
        f"At {offset_minutes:+d} min expected {expected_status}, got {placed['status']}"
    )


def test_a_data_print_closes_its_window_long_before_a_press_conference():
    """The duration ladder is the whole reason `shape` exists on an event."""
    printed = _event(NOW - timedelta(minutes=20), shape="data")
    speaking = _event(NOW - timedelta(minutes=20), shape="presser")

    assert les._with_status(printed, NOW, [])["status"] == "ended"
    assert les._with_status(speaking, NOW, [])["status"] == "live"


def test_an_unconfirmed_time_never_reports_live():
    """An earnings row anchored at a session edge is not a claim about a minute."""
    event = _event(NOW - timedelta(minutes=5), shape="earnings", time_confirmed=False)

    assert les._with_status(event, NOW, [])["status"] == "scheduled"


def test_a_live_broadcast_promotes_a_matching_event_starting_soon():
    """How a press conference that begins early still shows up as live."""
    event = _event(NOW + timedelta(minutes=10))
    channel = {
        "implies": "central_bank",
        "embed_url": "https://www.youtube-nocookie.com/embed/abc123",
        "is_live": True,
    }

    placed = les._with_status(event, NOW, [channel])

    assert placed["status"] == "live"
    assert placed["embed_url"] == channel["embed_url"], "The event should inherit the stream"


def test_a_live_market_channel_does_not_promote_anything():
    """CNBC is on air at 3am; that must not light up an unrelated calendar row."""
    event = _event(NOW + timedelta(minutes=10))
    channel = {"implies": "market", "embed_url": "https://example.invalid", "is_live": True}

    assert les._with_status(event, NOW, [channel])["status"] == "scheduled"


def test_a_broadcast_far_from_any_event_does_not_promote_it():
    event = _event(NOW + timedelta(minutes=90))
    channel = {"implies": "central_bank", "embed_url": "https://example.invalid", "is_live": True}

    assert les._with_status(event, NOW, [channel])["status"] == "scheduled"


# ==========================================
# DEDUPLICATION
# ==========================================


def test_dedupe_drops_the_fed_meeting_row_forexfactory_already_describes():
    """
    Both feeds cover an FOMC day. ForexFactory splits it into a statement and a
    press conference with forecasts attached, which is the more useful pair, so
    the Fed's single "FOMC Meeting" row is the one that goes.
    """
    events = [
        les._build(
            source="forexfactory",
            title="FOMC Statement",
            starts_at=NOW,
            impact="high",
            country="USD",
        ),
        les._build(source="federalreserve", title="FOMC Meeting", starts_at=NOW, impact="high"),
    ]

    kept = les._dedupe(events)

    assert [event["source"] for event in kept] == ["forexfactory"]


def test_dedupe_keeps_a_fed_row_on_a_day_forexfactory_says_nothing_about():
    """The Fed calendar runs months ahead; ForexFactory only covers this week."""
    events = [
        les._build(
            source="federalreserve",
            title="FOMC Meeting",
            starts_at=NOW + timedelta(days=60),
            impact="high",
        )
    ]

    assert len(les._dedupe(events)) == 1


def test_dedupe_collapses_an_exact_duplicate():
    event = les._build(source="forexfactory", title="Core CPI m/m", starts_at=NOW, impact="high")

    assert len(les._dedupe([event, dict(event)])) == 1


def test_stable_id_survives_a_refetch_but_separates_two_events():
    first = les._build(source="forexfactory", title="CPI m/m", starts_at=NOW, impact="high")
    again = les._build(source="forexfactory", title="CPI m/m", starts_at=NOW, impact="high")
    other = les._build(source="forexfactory", title="CPI y/y", starts_at=NOW, impact="high")

    assert first["id"] == again["id"], "The same event must key the same across refetches"
    assert first["id"] != other["id"]
