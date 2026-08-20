"""
Tests for the Pentagon Pizza Index.

Two kinds of test here, and the split is deliberate. The parsing and timezone
tests run against `fixtures/pizzint_page.html`, a saved capture of the real page,
because the thing most likely to break is the shape of someone else's HTML.
The scoring tests use hand-built venues, because the properties that matter —
that a small baseline is refused, that one quantized venue cannot move the
median, that a thin sample yields no number — are precisely the cases a real
capture happens not to contain on any given day.
"""

import pathlib
from datetime import UTC, datetime

import pytest

from services import pentagon_pizza_service as pizza
from services.pentagon_pizza_service import (
    MIN_BASELINE,
    MIN_VENUES,
    RATIO_CAP,
    baseline_at,
    build_history,
    build_venue_history,
    fetch_pizza_index,
    parse_venues,
    score,
)

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "pizzint_page.html"

# The hour the fixture was captured in.
CAPTURED_AT = datetime(2026, 8, 18, 11, 30, tzinfo=UTC)


@pytest.fixture
def page_html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _venue(
    name: str,
    *,
    current,
    baseline: int,
    hour: int = 19,
    dow: str = "1",
    closed: bool = False,
) -> dict:
    """
    A venue whose baseline curve is flat at `baseline` for the given hour.

    Only the weekday under test is populated; a lookup landing on any other day
    returning nothing is itself useful, since that is what a timezone slip does.
    """
    return {
        "place_id": f"place-{name}",
        "name": name,
        "address": "1 Test Way, Arlington, VA",
        "current_popularity": current,
        "is_closed_now": closed,
        "baseline_popular_times": {dow: [{"hour": hour, "popularity": baseline}]},
        "sparkline_24h": [],
    }


class TestParsing:
    def test_extracts_every_venue_from_the_flight_payload(self, page_html):
        venues = parse_venues(page_html)
        assert len(venues) == 6
        assert "Extreme Pizza" in {v["name"] for v in venues}

    def test_venues_carry_the_fields_scoring_depends_on(self, page_html):
        for venue in parse_venues(page_html):
            assert venue["baseline_popular_times"].keys() == {"0", "1", "2", "3", "4", "5", "6"}
            assert len(venue["sparkline_24h"]) == 24

    def test_a_page_without_venue_records_parses_to_nothing(self):
        # Not an exception: an unrecognisable page is the service's problem to
        # report as an outage, not the parser's to raise from.
        assert parse_venues("<html><body>maintenance</body></html>") == []

    def test_a_brace_inside_a_string_does_not_truncate_the_record(self):
        html = (
            '<script>self.__next_f.push([1,"'
            '{\\"place_id\\":\\"x\\",\\"name\\":\\"Pizza {The Best}\\",'
            '\\"current_popularity\\":50,'
            '\\"baseline_popular_times\\":{\\"1\\":[{\\"hour\\":19,\\"popularity\\":40}]}}'
            '"])</script>'
        )
        venues = parse_venues(html)
        assert len(venues) == 1
        # The field after the brace-bearing string survived, which is the point.
        assert venues[0]["current_popularity"] == 50


class TestTimezone:
    """
    Snapshots are UTC, the baseline curve is local. Reading one against the other
    without converting produces a number for every hour — just the wrong hour's —
    so these pin the conversion rather than trusting it.
    """

    def test_baseline_is_looked_up_in_venue_local_time(self):
        # 23:00 UTC on a Monday is 19:00 ET the same day. Google keys weekdays
        # from Sunday, so ET Monday is "1".
        venue = _venue("Local", current=None, baseline=70, hour=19, dow="1")
        assert baseline_at(venue, datetime(2026, 8, 17, 23, 0, tzinfo=UTC)) == 70

    def test_utc_hour_is_not_used_directly(self):
        # Same instant, but the baseline only exists at the UTC hour (23). A
        # lookup that skipped the conversion would find it; the correct one
        # must not.
        venue = _venue("Naive", current=None, baseline=70, hour=23, dow="1")
        assert baseline_at(venue, datetime(2026, 8, 17, 23, 0, tzinfo=UTC)) is None

    def test_the_date_rolls_back_a_day_across_midnight_utc(self):
        # 02:00 UTC Tuesday is 22:00 ET Monday — both the hour and the weekday
        # differ, which is the case a fixed offset applied to the hour alone
        # would still get wrong.
        venue = _venue("Rollover", current=None, baseline=55, hour=22, dow="1")
        assert baseline_at(venue, datetime(2026, 8, 18, 2, 0, tzinfo=UTC)) == 55

    def test_winter_and_summer_offsets_both_resolve(self):
        # EST is UTC-5, EDT is UTC-4. A hardcoded offset gets one of these wrong.
        summer = _venue("Summer", current=None, baseline=60, hour=13, dow="1")
        assert baseline_at(summer, datetime(2026, 8, 17, 17, 0, tzinfo=UTC)) == 60

        winter = _venue("Winter", current=None, baseline=60, hour=12, dow="1")
        assert baseline_at(winter, datetime(2026, 1, 12, 17, 0, tzinfo=UTC)) == 60


class TestScoring:
    """`now` is a Monday 19:00 ET, which is where `_venue` puts its baseline."""

    NOW = datetime(2026, 8, 17, 23, 0, tzinfo=UTC)

    def _score(self, venues):
        return score(venues, now=self.NOW)

    def test_index_is_the_median_ratio(self):
        result = self._score(
            [
                _venue("A", current=40, baseline=40),  # 1.0
                _venue("B", current=60, baseline=40),  # 1.5
                _venue("C", current=80, baseline=40),  # 2.0
            ]
        )
        assert result["index"] == 1.5
        assert result["venues_used"] == 3

    def test_one_quantized_venue_cannot_move_the_index(self):
        """
        The failure this replaces: Google pins busyness to 100, and under a mean
        that single venue drags the whole reading up. The median holds.
        """
        venues = [
            _venue("A", current=40, baseline=40),  # 1.0
            _venue("B", current=40, baseline=40),  # 1.0
            _venue("Quantized", current=100, baseline=25),  # 4.0
        ]
        assert self._score(venues)["index"] == 1.0

    def test_a_small_baseline_is_refused_rather_than_divided_by(self):
        low = MIN_BASELINE - 1
        result = self._score(
            [
                _venue("A", current=40, baseline=40),
                _venue("B", current=40, baseline=40),
                _venue("Tiny", current=41, baseline=low),  # would be 4.5x
            ]
        )
        tiny = next(v for v in result["venues"] if v["name"] == "Tiny")
        assert tiny["ratio"] is None
        assert tiny["excluded_reason"] == "baseline too low to compare"
        assert result["venues_used"] == 2

    def test_ratios_clamp_at_the_cap(self):
        result = self._score(
            [
                _venue("A", current=100, baseline=20),
                _venue("B", current=100, baseline=20),
                _venue("C", current=100, baseline=20),
            ]
        )
        assert result["index"] == RATIO_CAP

    def test_a_thin_sample_yields_no_number_at_all(self):
        venues = [_venue(str(i), current=40, baseline=40) for i in range(MIN_VENUES - 1)]
        result = self._score(venues)
        assert result["index"] is None
        assert result["status"] == "insufficient_data"

    def test_closed_venues_are_excluded_not_counted_as_zero(self):
        """
        A closed venue folded in as 0.0 would report every night as "quiet" —
        a claim about hours in which nothing was measured.
        """
        result = self._score(
            [
                _venue("Open A", current=40, baseline=40),
                _venue("Open B", current=40, baseline=40),
                _venue("Open C", current=40, baseline=40),
                _venue("Shut", current=None, baseline=40, closed=True),
            ]
        )
        assert result["index"] == 1.0
        assert result["venues_used"] == 3
        assert result["venues_total"] == 4
        shut = next(v for v in result["venues"] if v["name"] == "Shut")
        assert shut["excluded_reason"] == "closed"

    @pytest.mark.parametrize(
        ("current", "expected"),
        [(20, "quiet"), (40, "normal"), (60, "elevated"), (90, "spike")],
    )
    def test_status_thresholds(self, current, expected):
        venues = [_venue(str(i), current=current, baseline=40) for i in range(3)]
        assert self._score(venues)["status"] == expected

    def test_source_readings_are_passed_through_for_cross_checking(self):
        venue = _venue("Cross", current=40, baseline=40)
        venue |= {
            "percentage_of_usual": 118,
            "is_spike": True,
            "spike_magnitude": 1.18,
            "data_freshness": "fresh",
        }
        row = self._score([venue])["venues"][0]
        assert row["source_pct_of_usual"] == 118
        assert row["source_is_spike"] is True
        assert row["source_spike_magnitude"] == 1.18
        assert row["freshness"] == "fresh"


class TestHistory:
    def test_hours_are_bucketed_in_local_time_and_stamped_on_the_hour(self):
        venue = _venue("H", current=None, baseline=40, hour=19, dow="1")
        venue["sparkline_24h"] = [
            {"current_popularity": 40, "recorded_at": "2026-08-17T23:07:12.5+00:00"},
            {"current_popularity": 80, "recorded_at": "2026-08-17T23:52:00.123456+00:00"},
        ]
        history = build_history([venue, venue | {"place_id": "H2"}, venue | {"place_id": "H3"}])
        assert len(history) == 1
        assert history[0]["hour_et"].startswith("2026-08-17T19:00")

    def test_fractional_seconds_of_any_width_parse(self):
        """The source emits `.14`, `.733` and `.733123` interchangeably."""
        venue = _venue("F", current=None, baseline=40, hour=19, dow="1")
        venue["sparkline_24h"] = [
            {"current_popularity": 40, "recorded_at": f"2026-08-17T23:0{i}:00.{frac}+00:00"}
            for i, frac in enumerate(["1", "14", "733", "733123"])
        ]
        assert build_history([venue])[0]["venues_used"] == 4

    def test_a_thin_hour_keeps_its_slot_with_a_null_index(self):
        """
        Dropping the hour would close the gap and draw a continuous line across
        time nothing was measured in.
        """
        venue = _venue("Lonely", current=None, baseline=40, hour=19, dow="1")
        venue["sparkline_24h"] = [
            {"current_popularity": 100, "recorded_at": "2026-08-17T23:07:00.0+00:00"}
        ]
        history = build_history([venue])
        assert len(history) == 1
        assert history[0]["index"] is None
        assert history[0]["venues_used"] == 1

    def test_real_capture_produces_a_scored_trend(self, page_html):
        history = build_history(parse_venues(page_html))
        assert history, "the saved capture carries 24h of snapshots"
        # Every hour is either scored or explicitly null; none is a bare zero
        # standing in for "we could not tell".
        for hour in history:
            assert hour["index"] is None or hour["index"] > 0
            if hour["venues_used"] < MIN_VENUES:
                assert hour["index"] is None


class TestFetch:
    """The endpoint behind this must never fail; these pin that."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        pizza.home_cache.invalidate(pizza.CACHE_KEY)
        yield
        pizza.home_cache.clear()

    async def test_reads_scores_and_caches_the_page(self, monkeypatch, page_html):
        calls = []

        async def fake_get_text(url, **kwargs):
            calls.append(url)
            return page_html

        monkeypatch.setattr(pizza, "get_text", fake_get_text)

        first = await fetch_pizza_index()
        assert first["venues_total"] == 6
        assert first["stale"] is False

        # Second call is served from cache rather than re-fetching a megabyte.
        await fetch_pizza_index()
        assert len(calls) == 1

    async def test_a_failed_fetch_replays_the_last_good_reading(self, monkeypatch, page_html):
        async def ok(url, **kwargs):
            return page_html

        monkeypatch.setattr(pizza, "get_text", ok)
        good = await fetch_pizza_index()
        pizza.home_cache.invalidate(pizza.CACHE_KEY)

        async def boom(url, **kwargs):
            raise RuntimeError("upstream down")

        monkeypatch.setattr(pizza, "get_text", boom)
        replayed = await fetch_pizza_index()

        assert replayed["stale"] is True
        assert replayed["venues_total"] == good["venues_total"]

    async def test_a_failure_with_no_cache_reports_unavailable_rather_than_raising(
        self, monkeypatch
    ):
        async def boom(url, **kwargs):
            raise RuntimeError("upstream down")

        monkeypatch.setattr(pizza, "get_text", boom)
        result = await fetch_pizza_index()

        assert result["status"] == "unavailable"
        assert result["index"] is None
        assert result["venues"] == []

    async def test_an_unrecognisable_page_is_an_outage_not_an_empty_reading(self, monkeypatch):
        async def restructured(url, **kwargs):
            return "<html><body>we redesigned</body></html>"

        monkeypatch.setattr(pizza, "get_text", restructured)
        result = await fetch_pizza_index()

        # Not `insufficient_data` with zero venues, which would read as "the
        # pizzerias are quiet" rather than "we could not see them".
        assert result["status"] == "unavailable"


class TestVenueHistory:
    """
    The per-venue 24h the expanded panel stacks under the aggregate.

    The property under test is alignment, not arithmetic: the panel draws these
    bars directly beneath the aggregate's, so a venue series that skipped the
    hours it was shut would silently shift every later bar left of the hour it
    belongs to.
    """

    def test_pads_to_the_shared_hour_grid(self):
        venue = _venue("Solo", current=None, baseline=40, hour=19)
        venue["sparkline_24h"] = [
            {"recorded_at": "2026-08-17T23:10:00Z", "current_popularity": 60},
        ]
        hours = ["2026-08-17T18:00:00-04:00", "2026-08-17T19:00:00-04:00"]

        history = build_venue_history(venue, hours)

        assert [row["hour_et"] for row in history] == hours
        # 23:10 UTC is 19:10 local, the one hour this venue's baseline covers.
        assert history[0]["ratio"] is None
        assert history[1]["ratio"] == 1.5

    def test_medians_repeated_snapshots_in_one_hour(self):
        venue = _venue("Repeat", current=None, baseline=40, hour=19)
        venue["sparkline_24h"] = [
            {"recorded_at": "2026-08-17T23:05:00Z", "current_popularity": 20},
            {"recorded_at": "2026-08-17T23:25:00Z", "current_popularity": 40},
            {"recorded_at": "2026-08-17T23:45:00Z", "current_popularity": 100},
        ]

        history = build_venue_history(venue, ["2026-08-17T19:00:00-04:00"])

        # The median of 0.5/1.0/2.5, not the mean — one quantized 100 must not
        # own the bar, for the same reason the index itself is a median.
        assert history[0]["ratio"] == 1.0

    def test_every_venue_shares_the_payload_grid(self, page_html):
        payload = score(parse_venues(page_html), now=CAPTURED_AT)
        grid = [hour["hour_et"] for hour in payload["history"]]

        assert grid, "the saved capture carries 24h of snapshots"
        for venue in payload["venues"]:
            assert [row["hour_et"] for row in venue["history"]] == grid
