"""
Matching a market to an election, and the many ways that goes wrong.

Every rejection here is drawn from a live `tag_slug=elections` listing rather
than imagined. The tag carries US House-district markets, a Rio de Janeiro
governor race, a question about Trump leaving office, and 2028 presidential
markets — all of which have a plausible-looking country and would otherwise land
on a 2026 row.

The gate this pins is asymmetric on purpose: a structured country signal plus a
credible resolution date earns a *price*; prose, a missing date or a thin book
earns a *link*; everything else earns nothing. The date is a cited fact and the
match is a heuristic, and they share a row — so the number is the thing that
must never be wrong.

`now` is injected everywhere. Nothing here touches the network or the clock.
"""

from datetime import date, datetime, timedelta, UTC

import pytest

from services.elections.join import attach_odds
from services.elections.odds import EventSummary, Outcome
from services.elections.registry import CountryEntry, Registry
from services.elections.wikipedia import ElectionDate

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def _election(country: str, day: str, office: str = "Parliament") -> ElectionDate:
    return ElectionDate(
        date=date.fromisoformat(day),
        through=None,
        precision="day",
        country=country,
        office=office,
        minor=False,
        source_url="https://en.wikipedia.org/wiki/2026_national_electoral_calendar",
    )


def _event(
    title: str,
    *,
    slug: str = "an-event",
    end: str | None = "2026-09-13",
    country_name: str | None = None,
    tags: tuple[str, ...] = ("elections",),
    volume: float = 50_000.0,
    liquidity: float = 90_000.0,
    election_type: str | None = None,
    outcomes: tuple[Outcome, ...] = (Outcome("Someone", 0.6, 0.02),),
) -> EventSummary:
    return EventSummary(
        slug=slug,
        title=title,
        url=f"https://polymarket.com/event/{slug}",
        country_name=country_name,
        election_type=election_type,
        tag_slugs=tags,
        end_date=datetime.fromisoformat(f"{end}T00:00:00+00:00") if end else None,
        volume_24h=volume,
        liquidity=liquidity,
        outcomes=outcomes,
        others=0,
        exclusive=False,
    )


@pytest.fixture
def registry():
    """Only the countries a test needs, so a seed edit cannot break these."""
    return Registry(
        {
            "Sweden": CountryEntry(iso2="SE", flag="🇸🇪", tier="watch"),
            "Brazil": CountryEntry(iso2="BR", flag="🇧🇷", tier="major"),
            "France": CountryEntry(iso2="FR", flag="🇫🇷", tier="major"),
            "United States": CountryEntry(iso2="US", flag="🇺🇸", tier="major"),
            "Georgia": CountryEntry(iso2="GE", flag="🇬🇪", aliases=("georgian dream",)),
        }
    )


def _match(elections, events, registry, now=NOW):
    return attach_odds(elections, events, registry, now=now)


# ==========================================
# WHAT EARNS A PRICE
# ==========================================


def test_a_tagged_country_and_a_nearby_resolution_date_earns_a_price(registry):
    elections = [_election("Sweden", "2026-09-13")]
    events = [_event("Next Prime Minister of Sweden", tags=("elections", "sweden"))]

    matched = _match(elections, events, registry)

    assert matched[0].confidence == "high"
    assert "tag" in matched[0].matched_on


def test_a_dirty_country_field_still_resolves(registry):
    """`countryName` arrives as "U.S.", "FL-19" and "Ann Arbor" as well as clean
    names; running it through the same matcher is what filters the dirt."""
    elections = [_election("Sweden", "2026-09-13")]
    events = [
        _event("Who will lead the next government?", country_name="Sweden", tags=("elections",))
    ]

    matched = _match(elections, events, registry)

    assert matched[0].matched_on[0] == "country_field"


def test_a_registry_alias_reaches_a_country_geography_cannot_name(registry):
    """Georgia is in `geography.AMBIGUOUS` with no aliases, so `countries_in`
    compiles no pattern for it at all. The seed is the only route."""
    elections = [_election("Georgia", "2026-10-26")]
    events = [_event("Will Georgian Dream win the parliamentary election?", end="2026-11-01")]

    matched = _match(elections, events, registry)

    assert matched[0].matched_on[0] == "registry_alias"


def test_the_resolution_date_may_lag_the_polling_day(registry):
    """France 2027 resolves on 30 April for an election held on the 18th."""
    elections = [_election("France", "2027-04-18", "President")]
    events = [_event("Next French Presidential Election", end="2027-04-30", country_name="France")]

    matched = _match(elections, events, registry)

    assert matched[0].confidence == "high"


def test_a_balance_of_power_market_does_attach_to_the_midterms(registry):
    elections = [_election("United States", "2026-11-03", "House and Senate")]
    events = [
        _event("Balance of Power: 2026 Midterms", end="2026-11-03", country_name="United States")
    ]

    matched = _match(elections, events, registry)

    assert matched[0].confidence == "high"


# ==========================================
# WHAT EARNS A LINK AND NO NUMBER
# ==========================================


def test_a_country_named_only_in_prose_earns_a_link(registry):
    elections = [_election("Sweden", "2026-09-13")]
    events = [_event("Sweden Parliamentary Election Winner", tags=("elections",))]

    matched = _match(elections, events, registry)

    assert matched[0].confidence == "medium"
    assert matched[0].matched_on[0] == "title"


def test_a_market_with_no_resolution_date_earns_a_link(registry):
    elections = [_election("Sweden", "2026-09-13")]
    events = [_event("Next Swedish government", end=None, tags=("elections", "sweden"))]

    matched = _match(elections, events, registry)

    assert matched[0].confidence == "medium"


def test_a_market_below_the_liquidity_floor_earns_a_link(registry):
    """Below the floor the quoted mid is one resting order rather than a crowd."""
    elections = [_election("Sweden", "2026-09-13")]
    events = [
        _event("Next Prime Minister of Sweden", tags=("elections", "sweden"), liquidity=200.0)
    ]

    matched = _match(elections, events, registry)

    assert matched[0].confidence == "medium"


def test_two_elections_in_one_country_that_cannot_be_told_apart_earn_a_link(registry):
    """A March presidential and an October legislative in the same country. The
    office vocabulary is not reliable enough to choose, so neither gets a price."""
    elections = [
        _election("Brazil", "2026-10-04", "President"),
        _election("Brazil", "2027-02-01", "Governors"),
    ]
    events = [_event("Brazil Election Winner", end="2026-10-10", country_name="Brazil")]

    matched = _match(elections, events, registry)

    assert all(match.confidence == "medium" for match in matched.values())


# ==========================================
# WHAT EARNS NOTHING
# ==========================================


def test_a_market_resolving_two_years_out_does_not_attach(registry):
    elections = [_election("United States", "2026-11-03", "House and Senate")]
    events = [
        _event(
            "Presidential Election Winner 2028",
            end="2028-11-07",
            country_name="United States",
            tags=("elections", "midterms"),
        )
    ]

    assert _match(elections, events, registry) == {}


def test_a_us_house_district_does_not_attach_to_the_midterms(registry):
    """`countryName` arrives as "FL-19"; the district wording is the backstop."""
    elections = [_election("United States", "2026-11-03", "House and Senate")]
    events = [_event("FL-19 congressional district winner", country_name="FL-19", end="2026-11-03")]

    assert _match(elections, events, registry) == {}


def test_a_state_senate_race_does_not_attach_to_the_midterms(registry):
    """
    The US is the one country the reject list cannot carry alone: Polymarket
    runs a market per competitive seat and all of them normalise to one country.
    """
    elections = [_election("United States", "2026-11-03", "House and Senate")]
    events = [
        _event("Michigan Senate Election Winner", country_name="United States", end="2026-11-03")
    ]

    assert _match(elections, events, registry) == {}


def test_a_state_governor_race_does_not_attach_to_the_national_election(registry):
    """Brazil's general election does elect governors. One state's race is still
    not the national catalyst."""
    elections = [_election("Brazil", "2026-10-04", "President")]
    events = [
        _event("Rio de Janeiro Governor Election Winner", country_name="Brazil", end="2026-10-05")
    ]

    assert _match(elections, events, registry) == {}


def test_a_primary_does_not_attach_to_the_general_election(registry):
    elections = [_election("United States", "2026-11-03", "House and Senate")]
    events = [
        _event(
            "South Carolina Republican Senate Special Primary Winner",
            country_name="United States",
            end="2026-08-11",
            tags=("elections", "primaries"),
        )
    ]

    assert _match(elections, events, registry) == {}


def test_a_president_leaving_office_is_not_an_election(registry):
    """Tagged `elections`, contains "President", and is a question about a term
    ending. Which is why bare "president" is not election vocabulary."""
    elections = [_election("United States", "2026-11-03", "House and Senate")]
    events = [
        _event(
            "Trump out as President before 2027?",
            country_name="United States",
            end="2026-12-31",
            tags=("elections", "midterms"),
        )
    ]

    assert _match(elections, events, registry) == {}


def test_a_snap_election_market_does_not_attach_to_the_scheduled_one(registry):
    """A real election question about a different election."""
    elections = [_election("France", "2027-04-18", "President")]
    events = [
        _event("Snap election in France before 2027?", country_name="France", end="2027-01-01")
    ]

    assert _match(elections, events, registry) == {}


def test_a_market_whose_resolution_has_long_passed_does_not_attach(registry):
    """`closed=false` lags; a resolution a month gone is not an open question."""
    elections = [_election("Sweden", "2026-09-13")]
    events = [
        _event("Next Prime Minister of Sweden", tags=("elections", "sweden"), end="2026-07-01")
    ]

    assert _match(elections, events, registry) == {}


def test_a_market_naming_no_country_at_all_does_not_attach(registry):
    elections = [_election("Sweden", "2026-09-13")]
    events = [_event("Who will win the next election?", tags=("elections",))]

    assert _match(elections, events, registry) == {}


# ==========================================
# ONE MARKET, ONE ROW
# ==========================================


def test_one_event_attaches_to_at_most_one_election(registry):
    """Otherwise "Next French President" prints on both April rounds."""
    elections = [
        _election("France", "2027-04-18", "President (1st round)"),
        _election("France", "2027-05-02", "President (2nd round)"),
    ]
    events = [_event("Next French Presidential Election", end="2027-04-30", country_name="France")]

    matched = _match(elections, events, registry)

    assert len(matched) == 1


def test_only_the_first_round_carries_the_price(registry):
    """The market prices the outcome, not the round. Printing it twice would
    read as two independent readings that happen to agree."""
    elections = [
        _election("France", "2027-04-18", "President (1st round)"),
        _election("France", "2027-05-02", "President (2nd round)"),
    ]
    events = [_event("Next French Presidential Election", end="2027-04-30", country_name="France")]

    matched = _match(elections, events, registry)

    assert set(matched) == {0}


def test_the_deepest_market_wins_when_several_match(registry):
    """Sweden carries both "Next Prime Minister" and "Parliamentary Election
    Winner". Liquidity is the tiebreaker a trader would use."""
    elections = [_election("Sweden", "2026-09-13")]
    events = [
        _event("Sweden A", slug="a", tags=("elections", "sweden"), volume=10_000.0),
        _event("Sweden B", slug="b", tags=("elections", "sweden"), volume=90_000.0),
    ]

    matched = _match(elections, events, registry)

    assert matched[0].event.slug == "b"


# ==========================================
# COUNTRY NAMES THAT CONTAIN OTHER COUNTRY NAMES
# ==========================================


def test_papua_new_guinea_is_not_read_as_guinea(registry):
    """`countries_in` matches on word boundaries, so the longer name reports
    both. Collapsing substrings is what leaves one answer."""
    registry.entries["Papua New Guinea"] = CountryEntry(iso2="PG", flag="🇵🇬")
    elections = [_election("Papua New Guinea", "2027-06-01")]
    events = [
        _event(
            "Papua New Guinea general election winner",
            country_name="Papua New Guinea",
            end="2027-06-15",
        )
    ]

    matched = _match(elections, events, registry)

    assert matched and matched[0].event.slug == "an-event"


def test_a_market_naming_two_unrelated_countries_does_not_attach(registry):
    elections = [_election("France", "2027-04-18", "President")]
    events = [_event("Will France and Brazil hold elections in the same week?", end="2027-04-20")]

    assert _match(elections, events, registry) == {}


# ==========================================
# TIME
# ==========================================


def test_the_matcher_never_reads_the_clock(registry):
    """Every rule is date-relative; a module that told the time would make these
    tests expire."""
    elections = [_election("Sweden", "2026-09-13")]
    events = [_event("Next Prime Minister of Sweden", tags=("elections", "sweden"))]

    ten_years_on = NOW + timedelta(days=3650)
    assert _match(elections, events, registry, now=NOW)
    assert _match(elections, events, registry, now=ten_years_on) == {}


# ==========================================
# MARKETS THAT PRICE THE WRONG QUESTION
# ==========================================


def test_a_second_place_market_does_not_attach(registry):
    """
    Brazil's listing carries "Presidential Election First Round: 2nd Place",
    whose leading outcome at 86% is 86% likely to come *second*. Beside a winner
    probability on the same board it reads as a landslide. Rejected rather than
    linked, so a genuine winner market can still claim the row.
    """
    elections = [_election("Brazil", "2026-10-04", "President")]
    events = [
        _event(
            "Brazil Presidential Election First Round: 2nd Place",
            country_name="Brazil",
            end="2026-10-05",
        )
    ]

    assert _match(elections, events, registry) == {}


def test_a_turnout_or_vote_share_market_does_not_attach(registry):
    elections = [_election("France", "2027-04-18", "President")]
    events = [_event("French election turnout above 70%?", country_name="France", end="2027-04-25")]

    assert _match(elections, events, registry) == {}


def test_a_winner_market_still_wins_the_row_beside_a_ranking_one(registry):
    elections = [_election("Brazil", "2026-10-04", "President")]
    events = [
        _event(
            "Brazil Presidential Election First Round: 2nd Place",
            slug="ranking",
            country_name="Brazil",
            end="2026-10-05",
            volume=900_000.0,
        ),
        _event(
            "Brazil Presidential Election Winner",
            slug="winner",
            country_name="Brazil",
            end="2026-10-05",
            volume=1_000.0,
        ),
    ]

    matched = _match(elections, events, registry)

    assert matched[0].event.slug == "winner"
