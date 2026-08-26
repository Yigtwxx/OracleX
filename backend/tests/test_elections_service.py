"""
The elections board: what a partial outage costs, and what a total one does.

The calendar and the odds are separate upstreams with separate caches, and the
asymmetry between them is the thing worth pinning. Losing the dates means the
board would assert that no election is scheduled anywhere on Earth, so it 503s.
Losing the odds costs a column and is reported in the payload, because a board
with no prices and a world with no markets must not look the same.

Nothing here touches the network.
"""

from datetime import date, datetime, timedelta, UTC

import pytest

from services.elections import odds as odds_module
from services.elections import service, wikipedia
from services.elections.service import elections_cache
from services.home_service import UpstreamUnavailable


@pytest.fixture(autouse=True)
def _clean_cache():
    """Each test starts with no calendar, no odds, no stale copy and no backoff."""
    elections_cache.clear()
    yield
    elections_cache.clear()


def _soon(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _bullet(country: str, day: date, office: str = "Parliament") -> str:
    return f"* {day.day} {day.strftime('%B')}: [[{country}]], [[…|{office}]]"


def _page(*countries_and_offsets) -> str:
    """A wikitext page holding one bullet per (country, days-from-today)."""
    by_month: dict[str, list[str]] = {}
    for country, offset in countries_and_offsets:
        day = date.today() + timedelta(days=offset)
        by_month.setdefault(day.strftime("%B"), []).append(_bullet(country, day))
    return "\n".join(f"== {month} ==\n" + "\n".join(bullets) for month, bullets in by_month.items())


def _stub_calendar(monkeypatch, pages: dict[int, object]):
    """Answer each year's fetch with wikitext, or raise what it is handed."""
    asked: list[int] = []

    async def fetch_year(year: int) -> str:
        asked.append(year)
        answer = pages.get(year, ValueError(f"no page for {year}"))
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(wikipedia, "fetch_year", fetch_year)
    return asked


def _stub_odds(monkeypatch, payload):
    """Answer the Gamma fetch with raw events, or raise what it is handed."""

    async def fetch_election_events(limit=None):
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(odds_module, "fetch_election_events", fetch_election_events)


def _raw_event(title: str, *, end: str, tags=("elections", "sweden")) -> dict:
    return {
        "slug": "an-event",
        "title": title,
        "endDate": f"{end}T00:00:00Z",
        "volume24hr": 55_000,
        "liquidity": 90_000,
        "tags": [{"slug": slug} for slug in tags],
        "markets": [
            {
                "groupItemTitle": "Someone",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.62", "0.38"]',
                "oneWeekPriceChange": 0.04,
            }
        ],
    }


# ==========================================
# THE BOARD
# ==========================================


async def test_the_board_is_chronological(monkeypatch):
    _stub_calendar(monkeypatch, {date.today().year: _page(("Sweden", 40), ("Brazil", 10))})
    _stub_odds(monkeypatch, ValueError("no markets"))

    board = await service.fetch_elections()

    assert [row["country"] for row in board["elections"]] == ["Brazil", "Sweden"]


async def test_elections_already_held_are_dropped(monkeypatch):
    """
    Filtered per request rather than at cache time: the calendar is cached for a
    day, and an election held this morning must leave the board this morning.
    """
    _stub_calendar(monkeypatch, {date.today().year: _page(("Sweden", 40), ("Benin", -30))})
    _stub_odds(monkeypatch, ValueError("no markets"))

    board = await service.fetch_elections()

    assert [row["country"] for row in board["elections"]] == ["Sweden"]


async def test_a_tracked_country_carries_its_tickers(monkeypatch):
    _stub_calendar(monkeypatch, {date.today().year: _page(("Brazil", 30))})
    _stub_odds(monkeypatch, ValueError("no markets"))

    board = await service.fetch_elections()

    assert board["elections"][0]["tickers"]
    assert board["elections"][0]["flag"] == "🇧🇷"


async def test_an_untracked_country_still_appears_with_no_tickers(monkeypatch):
    """An empty Watch cell is correct; a guessed ticker is not."""
    _stub_calendar(monkeypatch, {date.today().year: _page(("Wakanda", 30))})
    _stub_odds(monkeypatch, ValueError("no markets"))

    board = await service.fetch_elections()

    assert board["elections"][0]["tickers"] == []
    assert board["elections"][0]["flag"] == "🏳️"


async def test_the_board_reports_the_coverage_cap_it_asked_for(monkeypatch):
    """The listing is ordered by volume, so most rows having no market means we
    asked for the loudest few — not that Polymarket covers nothing."""
    _stub_calendar(monkeypatch, {date.today().year: _page(("Sweden", 30))})
    _stub_odds(monkeypatch, ValueError("no markets"))

    board = await service.fetch_elections()

    assert board["odds_cap"] > 0


# ==========================================
# THE ODDS LAYER FAILING
# ==========================================


async def test_polymarket_failing_serves_the_calendar_and_names_the_outage(monkeypatch):
    _stub_calendar(monkeypatch, {date.today().year: _page(("Sweden", 30))})
    _stub_odds(monkeypatch, RuntimeError("gamma down"))

    board = await service.fetch_elections()

    assert board["odds_available"] is False
    assert board["elections"][0]["odds"] is None


async def test_an_empty_market_list_is_a_source_failure_not_an_empty_world(monkeypatch):
    """Gamma's tag taxonomy churns; a renamed slug answers 200 with nothing."""
    _stub_calendar(monkeypatch, {date.today().year: _page(("Sweden", 30))})
    _stub_odds(monkeypatch, [])

    board = await service.fetch_elections()

    assert board["odds_available"] is False


async def test_a_matched_market_reaches_the_row(monkeypatch):
    day = date.today() + timedelta(days=20)
    _stub_calendar(monkeypatch, {date.today().year: _page(("Sweden", 20))})
    _stub_odds(
        monkeypatch,
        [_raw_event("Next Prime Minister of Sweden", end=day.isoformat())],
    )

    board = await service.fetch_elections()

    assert board["odds_available"] is True
    assert board["elections"][0]["odds"]["outcomes"][0]["price"] == pytest.approx(0.62)


async def test_a_failed_odds_fetch_backs_off_instead_of_retrying(monkeypatch):
    calls = []

    async def fetch_election_events(limit=None):
        calls.append(1)
        raise RuntimeError("gamma down")

    _stub_calendar(monkeypatch, {date.today().year: _page(("Sweden", 30))})
    monkeypatch.setattr(odds_module, "fetch_election_events", fetch_election_events)

    await service.fetch_elections()
    await service.fetch_elections()

    assert len(calls) == 1


# ==========================================
# THE CALENDAR FAILING
# ==========================================


async def test_a_later_year_page_failing_thins_the_board_rather_than_breaking_it(monkeypatch):
    """A page for a year nobody has written up yet is normal, not an outage."""
    this_year = date.today().year
    _stub_calendar(monkeypatch, {this_year: _page(("Sweden", 30))})
    _stub_odds(monkeypatch, ValueError("no markets"))

    board = await service.fetch_elections()

    assert board["years"] == [this_year]
    assert board["elections"]


async def test_the_current_year_failing_with_no_recent_copy_raises(monkeypatch):
    """An empty board would claim no election is scheduled anywhere on Earth."""
    _stub_calendar(monkeypatch, {})
    _stub_odds(monkeypatch, ValueError("no markets"))

    with pytest.raises(UpstreamUnavailable):
        await service.fetch_elections()


async def test_the_current_year_failing_replays_the_last_calendar_first(monkeypatch):
    this_year = date.today().year
    _stub_calendar(monkeypatch, {this_year: _page(("Sweden", 30))})
    _stub_odds(monkeypatch, ValueError("no markets"))
    await service.fetch_elections()

    elections_cache.invalidate(service.CACHE_KEY_CALENDAR)
    _stub_calendar(monkeypatch, {})

    board = await service.fetch_elections()

    assert [row["country"] for row in board["elections"]] == ["Sweden"]
    assert board["stale"] is True


async def test_a_stale_calendar_past_its_window_is_not_served(monkeypatch):
    """
    A week, not a month. An election date is fixed months ahead so a week-old
    copy is very nearly today's — but dates do move, and replaying a superseded
    one is worse than the panel being down.
    """
    this_year = date.today().year
    _stub_calendar(monkeypatch, {this_year: _page(("Sweden", 30))})
    _stub_odds(monkeypatch, ValueError("no markets"))
    await service.fetch_elections()

    elections_cache.invalidate(service.CACHE_KEY_CALENDAR)
    monkeypatch.setattr(service, "MAX_STALE_CALENDAR", 0)
    _stub_calendar(monkeypatch, {})

    with pytest.raises(UpstreamUnavailable):
        await service.fetch_elections()


async def test_a_failed_calendar_fetch_backs_off_instead_of_retrying(monkeypatch):
    asked = _stub_calendar(monkeypatch, {})
    _stub_odds(monkeypatch, ValueError("no markets"))

    for _ in range(2):
        with pytest.raises(UpstreamUnavailable):
            await service.fetch_elections()

    assert len(asked) == service.settings.ELECTIONS_CALENDAR_YEARS


async def test_an_empty_board_is_never_parked_in_the_cache(monkeypatch):
    """Which is what would make a later outage indistinguishable from a quiet year."""
    _stub_calendar(monkeypatch, {})
    _stub_odds(monkeypatch, ValueError("no markets"))

    with pytest.raises(UpstreamUnavailable):
        await service.fetch_elections()

    assert elections_cache.get_with_fallback(service.CACHE_KEY_CALENDAR) is None


# ==========================================
# THE STAMP
# ==========================================


async def test_a_fresh_board_is_not_marked_stale(monkeypatch):
    _stub_calendar(monkeypatch, {date.today().year: _page(("Sweden", 30))})
    _stub_odds(monkeypatch, ValueError("no markets"))

    board = await service.fetch_elections()

    assert board["stale"] is False
    assert datetime.fromisoformat(board["as_of"]).tzinfo is not None
    assert datetime.fromisoformat(board["as_of"]) <= datetime.now(UTC)


async def test_an_unnamed_placeholder_leg_is_not_listed_as_a_candidate(monkeypatch):
    """
    Polymarket seeds an event with lettered legs before the field is known, and
    they sit at exactly 0.50 because nobody can price a letter. Listed beside a
    real name they read as joint favourites in a race that does not exist.
    """
    day = date.today() + timedelta(days=20)
    _stub_calendar(monkeypatch, {date.today().year: _page(("Sweden", 20))})
    event = _raw_event("Next Prime Minister of Sweden", end=day.isoformat())
    event["markets"].extend(
        [
            {
                "groupItemTitle": "Candidate A",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.50", "0.50"]',
            },
            {
                "groupItemTitle": "Candidate B",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.50", "0.50"]',
            },
        ]
    )
    _stub_odds(monkeypatch, [event])

    board = await service.fetch_elections()

    labels = [o["label"] for o in board["elections"][0]["odds"]["outcomes"]]
    assert labels == ["Someone"]


async def test_prices_are_served_as_they_are_quoted(monkeypatch):
    """
    Never normalised to sum to one. An event's markets may be mutually
    exclusive, independent, or margin buckets, so a set of them can legitimately
    sum to well over 100% — and rescaling would be inventing the difference.
    """
    day = date.today() + timedelta(days=20)
    _stub_calendar(monkeypatch, {date.today().year: _page(("Sweden", 20))})
    event = _raw_event("Next Prime Minister of Sweden", end=day.isoformat())
    event["markets"].append(
        {
            "groupItemTitle": "Someone Else",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.71", "0.29"]',
        }
    )
    _stub_odds(monkeypatch, [event])

    board = await service.fetch_elections()

    prices = [o["price"] for o in board["elections"][0]["odds"]["outcomes"]]
    assert prices == [pytest.approx(0.71), pytest.approx(0.62)]


async def test_the_yes_leg_is_read_by_label_not_by_position(monkeypatch):
    """Gamma is consistent about ordering today. A silently reversed pair would
    render the least likely candidate as the favourite with nothing to show it."""
    day = date.today() + timedelta(days=20)
    _stub_calendar(monkeypatch, {date.today().year: _page(("Sweden", 20))})
    event = _raw_event("Next Prime Minister of Sweden", end=day.isoformat())
    event["markets"] = [
        {
            "groupItemTitle": "Someone",
            "outcomes": '["No", "Yes"]',
            "outcomePrices": '["0.38", "0.62"]',
        }
    ]
    _stub_odds(monkeypatch, [event])

    board = await service.fetch_elections()

    assert board["elections"][0]["odds"]["outcomes"][0]["price"] == pytest.approx(0.62)
