"""Gece Mesaisi Endeksi — scoring, parsing, and what it refuses to answer."""

from datetime import date

from services.bist.night_shift_service import (
    BASELINE_DAYS,
    DUYURU_WINDOW,
    MIN_SOURCES,
    RATIO_CAP,
    parse_gazette_day,
    parse_last_mukerrer,
    parse_presidency,
    score,
)

TODAY = date(2026, 8, 28)


def gazette(counts: dict[int, int], karar_on: set[int] | None = None) -> dict:
    """`{days_ago: item_count}` as the service's parsed shape."""
    karar_on = karar_on or set()
    out = {}
    for ago, n in counts.items():
        day = date.fromordinal(TODAY.toordinal() - ago).isoformat()
        out[day] = {"items": n, "karar": ago in karar_on}
    return out


def flat(items: int, days: int = BASELINE_DAYS, karar_on=None) -> dict:
    return gazette(dict.fromkeys(range(days), items), karar_on)


def feed(per_day: int = 2, days: int = BASELINE_DAYS) -> dict:
    """A presidency feed steady enough to be a second scorable source."""
    return {date.fromordinal(TODAY.toordinal() - i).isoformat(): per_day for i in range(days)}


# ── Parsing ──────────────────────────────────────────────────────────────────


def test_items_are_counted_once_though_the_index_lists_them_twice():
    # Every item appears as a PDF and again as HTML; counting links would double
    # the day's volume and halve every ratio drawn against it.
    html = """
      <a href="/eskiler/2026/08/20260828-1.pdf">x</a>
      <a href="/eskiler/2026/08/20260828-1.htm">x</a>
      <a href="/eskiler/2026/08/20260828-2.pdf">y</a>
    """
    assert parse_gazette_day(html)["items"] == 2


def test_an_extra_editions_files_are_not_counted_as_the_normal_day():
    # `20260703M1-1.pdf` belongs to the mükerrer, not to that day's edition.
    html = '<a href="/eskiler/2026/07/20260703M1-1.pdf">x</a>'
    assert parse_gazette_day(html)["items"] == 0


def test_the_executive_decision_section_is_detected_through_markup():
    html = "<div><b>CUMHURBAŞKANI&nbsp;KARARLARI</b></div>"
    assert parse_gazette_day(html.replace("&nbsp;", " "))["karar"] is True
    assert parse_gazette_day("<div>YÖNETMELİKLER</div>")["karar"] is False


def test_last_mukerrer_is_the_most_recent_one_linked():
    html = (
        '<a href="/fihrist?tarih=2026-05-21&amp;mukerrer=1">a</a>'
        '<a href="/fihrist?tarih=2026-07-03&amp;mukerrer=1">b</a>'
    )
    assert parse_last_mukerrer(html) == date(2026, 7, 3)


def test_no_linked_extra_edition_is_none_not_today():
    assert parse_last_mukerrer("<html>nothing here</html>") is None


def test_presidency_feed_is_counted_per_day():
    html = "28.08.2026 x 28.08.2026 y 27.08.2026 z 31.02.2026 impossible"
    counts = parse_presidency(html)
    assert counts["2026-08-28"] == 2
    assert counts["2026-08-27"] == 1
    # An impossible date is dropped rather than crashing the parse.
    assert all(k.startswith("2026-08") for k in counts)


# ── Scoring ──────────────────────────────────────────────────────────────────


def test_an_ordinary_day_reads_as_normal():
    result = score(flat(8), feed(), None, today=TODAY)
    assert result["status"] == "normal"
    assert result["index"] is not None


def test_a_heavy_day_against_a_quiet_fortnight_reads_as_a_spike():
    counts = dict.fromkeys(range(BASELINE_DAYS), 4)
    counts[0] = 40
    result = score(gazette(counts), feed(), None, today=TODAY)
    assert result["status"] in {"spike", "elevated"}
    assert result["index"] is not None and result["index"] > 2


def test_ratios_clamp_so_one_extraordinary_day_cannot_run_away():
    counts = dict.fromkeys(range(BASELINE_DAYS), 3)
    counts[0] = 3000
    result = score(gazette(counts), {}, None, today=TODAY)
    assert result["sources"][0]["ratio"] == RATIO_CAP


def test_a_baseline_too_small_to_divide_by_yields_no_ratio():
    # Two items a day is the noise floor; as a denominator it would turn an
    # ordinary four-item day into a 2x reading.
    counts = dict.fromkeys(range(BASELINE_DAYS), 1)
    counts[0] = 4
    result = score(gazette(counts), {}, None, today=TODAY)
    assert result["sources"][0]["ratio"] is None


def test_an_extra_edition_today_floors_the_reading_at_elevated():
    # The volume components can sit at normal on a day the state published
    # something it could not hold until tomorrow.
    quiet = score(flat(8), feed(), None, today=TODAY)
    assert quiet["status"] == "normal"

    loud = score(flat(8), feed(), TODAY, today=TODAY)
    assert loud["status"] == "elevated"
    assert loud["mukerrer_today"] is True
    assert loud["days_since_mukerrer"] == 0


def test_an_old_extra_edition_is_reported_but_does_not_lift_the_reading():
    result = score(flat(8), feed(), date(2026, 7, 3), today=TODAY)
    assert result["status"] == "normal"
    assert result["mukerrer_today"] is False
    assert result["days_since_mukerrer"] == 56


def test_the_index_refuses_when_only_one_source_could_be_scored():
    result = score(flat(8), {}, None, today=TODAY)
    assert result["sources_used"] < MIN_SOURCES
    assert result["status"] == "insufficient_data"
    assert result["index"] is None


def test_two_sources_are_enough_to_score():
    presidency = {date.fromordinal(TODAY.toordinal() - i).isoformat(): 2 for i in range(10)}
    result = score(flat(8), presidency, None, today=TODAY)
    assert result["sources_used"] >= MIN_SOURCES
    assert result["status"] != "insufficient_data"


def test_executive_decisions_become_a_rate_rather_than_a_coin_flip():
    # A single day carries the section or it does not; counted over a week it is
    # a rate with a baseline the other week can supply.
    result = score(flat(8, karar_on={0, 1, 2, 3}), {}, None, today=TODAY)
    karar = next((s for s in result["sources"] if s["key"] == "karar"), None)
    assert karar is not None
    assert karar["ratio"] is None or karar["ratio"] > 0


def test_every_source_explains_itself_in_the_units_it_was_measured_in():
    presidency = {date.fromordinal(TODAY.toordinal() - i).isoformat(): 2 for i in range(10)}
    result = score(flat(8), presidency, None, today=TODAY)
    assert all(s["detail"] for s in result["sources"])
    assert all("baseline" in s for s in result["sources"])


def test_history_days_line_up_across_sources():
    presidency = {
        date.fromordinal(TODAY.toordinal() - i).isoformat(): 2 for i in range(BASELINE_DAYS)
    }
    result = score(flat(8), presidency, None, today=TODAY)
    days = [row["day"] for row in result["history"]]
    assert days == sorted(days)
    assert len(days) == BASELINE_DAYS
    # The grid is the union the panel stacks on; every source's own row must be
    # drawn on one of these days or the bars would not align.
    for source in result["sources"]:
        for row in source["history"]:
            assert row["day"] in days or row["day"] < days[0]


def test_an_empty_board_answers_insufficient_rather_than_zero():
    result = score({}, {}, None, today=TODAY)
    assert result["status"] == "insufficient_data"
    assert result["index"] is None
    assert result["sources_used"] == 0


def test_announcements_are_counted_over_a_window_not_on_the_day():
    # The presidency publishes through the day and carries nothing at all on
    # about half the days in a fortnight. Scoring "today" alone reported 0.0x
    # every morning and on every quiet day, which described the calendar rather
    # than the state.
    feed_with_gap = {
        date.fromordinal(TODAY.toordinal() - i).isoformat(): n
        for i, n in enumerate([0, 0, 1, 0, 6, 0, 0, 2, 0, 0, 3, 0, 0, 1])
    }
    result = score(flat(8), feed_with_gap, None, today=TODAY)
    duyuru = next(s for s in result["sources"] if s["key"] == "duyuru")
    assert duyuru["ratio"] is not None
    assert duyuru["ratio"] > 0
    assert "son 3 günde" in duyuru["detail"]


def test_the_announcement_baseline_counts_silent_days_too():
    # Dividing by the number of dated keys rather than by the window would treat
    # a feed that spoke twice in a fortnight as averaging one a day.
    sparse = {
        TODAY.isoformat(): 1,
        date.fromordinal(TODAY.toordinal() - 13).isoformat(): 1,
    }
    result = score(flat(8), sparse, None, today=TODAY)
    duyuru = next(s for s in result["sources"] if s["key"] == "duyuru")
    # Two items across fourteen days is ~0.14 a day, so three days expects ~0.4.
    assert 0.3 < duyuru["baseline"] < 0.6


def test_a_stray_date_in_the_page_furniture_cannot_stretch_the_baseline():
    # The live feed carries a 2014 line beneath forty items from the last three
    # weeks. Measuring the span between the oldest and newest date it mentions
    # put the denominator across twelve years and drove every ratio to zero.
    feed = {date.fromordinal(TODAY.toordinal() - i).isoformat(): 3 for i in range(BASELINE_DAYS)}
    feed["2014-08-28"] = 1

    result = score(flat(8), feed, None, today=TODAY)
    duyuru = next(s for s in result["sources"] if s["key"] == "duyuru")
    # Three a day over the window, so three days expects nine — not a fraction.
    assert duyuru["baseline"] == 9.0
    assert duyuru["ratio"] == 1.0
    # And the stray day is not drawn on a fortnight's grid.
    assert all(row["day"] >= result["history"][0]["day"] for row in duyuru["history"])


def _duyuru(result: dict) -> dict:
    return next(s for s in result["sources"] if s["key"] == "duyuru")


def test_announcement_sparkline_is_scored_on_the_window_its_reading_uses():
    # The bug this pins: the reading divided by a three-day baseline and the
    # sparkline beside it by the daily rate. For this feed that rate is around
    # one, below `MIN_BASELINE`, so every bar came back unmeasured and the row
    # drew an empty grid next to a live 2.0x.
    result = score(flat(8), feed(per_day=2), None, today=TODAY)
    source = _duyuru(result)
    assert source["ratio"] is not None
    measured = [day for day in source["history"] if day["ratio"] is not None]
    assert measured, "the sparkline scored nothing the reading could score"
    # The newest bar and the headline are the same window, so they must agree.
    assert measured[-1]["ratio"] == source["ratio"]


def test_a_silent_day_is_a_nought_in_the_window_not_a_gap():
    # Restricting the series to days the feed carried something both shortened
    # the row and overstated every window spanning a silent day.
    days = [date.fromordinal(TODAY.toordinal() - i).isoformat() for i in range(BASELINE_DAYS)]
    sparse = {day: 3 for i, day in enumerate(days) if i % 2 == 0}
    result = score(flat(8), sparse, None, today=TODAY)
    source = _duyuru(result)
    assert len(source["history"]) == BASELINE_DAYS


def test_the_oldest_days_refuse_rather_than_score_a_partial_window():
    # Their window runs off the end of the fortnight, and a short window reads
    # as a quiet stretch that never happened.
    result = score(flat(8), feed(per_day=2), None, today=TODAY)
    history = _duyuru(result)["history"]
    assert all(day["ratio"] is None for day in history[: DUYURU_WINDOW - 1])
    assert history[DUYURU_WINDOW - 1]["ratio"] is not None
