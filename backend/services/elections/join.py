"""
Matching a Polymarket event to a scheduled election, or declining to.

The board puts a market price in the same row as a `<ref>`-cited polling date.
That asymmetry is the whole design problem: the date is a fact, the match is a
heuristic, and one bad join teaches a reader to distrust both. So the rule here
is narrow on purpose — **a structured country signal plus a plausible resolution
date earns a number; anything weaker earns a link and no number; anything else
earns nothing.**

What that has to survive, taken from a live listing rather than imagined:

    countryName: "FL-19"                      a US House district
    countryName: "Ann Arbor"                  a city
    "Rio de Janeiro Governor Election Winner" a state race under a clean "Brazil"
    "Trump out as President before 2027?"     tagged elections, not an election
    "Presidential Election Winner 2028"       real, two years past the row it would land on
    "Next French Presidential Election"       endDate 30 April, election the 18th
    "Next Prime Minister of Sweden"           and "Sweden Parliamentary Election
                                              Winner" — two events, one election

`attach_odds` takes `now` as a parameter and never reads the clock. Every rule
below is date-relative, so a module that told the time would make its own tests
expire.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, UTC

from services.elections.odds import EventSummary
from services.elections.registry import Registry
from services.elections.wikipedia import ElectionDate
from services.polymarket.geography import countries_in

# `endDate` is when the market *resolves*, which trails the vote by days and
# occasionally by weeks — France 2027 resolves on 30 April for an 18 April
# election. The window is therefore asymmetric: generous after the vote, tight
# before it, because a market resolving well ahead of a poll is about something
# else.
WINDOW_BEFORE = timedelta(days=30)
WINDOW_AFTER = timedelta(days=90)

# An event whose resolution date has passed by more than a week while still
# flagged open. `closed=false` lags.
STALE_AFTER = timedelta(days=7)

# Two calendar rows this close together are the rounds of one election. The
# market prices the outcome, not the round.
SAME_ELECTION_WINDOW = timedelta(days=60)

# Below these the quoted mid is one resting order rather than a crowd, and a
# price with no depth behind it is exactly the plausible wrong number this
# terminal declines. Such an event still surfaces — as a link.
MIN_VOLUME_24H = 1_000.0
MIN_LIQUIDITY = 5_000.0

_ELECTION_WORDS = re.compile(
    r"\b(elections?|electoral|elected|presidential|parliamentary|legislative"
    r"|referendum|ballot|midterms?|general election|next president"
    r"|prime minister|chancellor)\b",
    re.IGNORECASE,
)

# A bare "president" is deliberately absent from the vocabulary above and
# handled here instead: "Trump out as President before 2027?" is a question
# about a term ending, not about a vote.
_NOT_AN_ELECTION = re.compile(
    r"\b(out as|resign\w*|impeach\w*|step down|removed from|coup|assassinat\w*"
    r"|before (?:19|20)\d\d)\b",
    re.IGNORECASE,
)

# Sub-national races. Brazil's general election does elect state governors, so
# this deliberately under-matches: one state's race is not the national
# catalyst, and pricing the board off it would be worse than leaving the cell
# empty.
_SUB_NATIONAL = re.compile(
    r"\b(governor|mayor(?:al)?|senate seat|congressional district|district"
    r"|city council|county|state of)\b",
    re.IGNORECASE,
)

# A nomination contest is a real election and the wrong one.
_NOMINATION = re.compile(
    r"\b(primar(?:y|ies)|caucus(?:es)?|nominee|nomination|leadership|party leader)\b",
    re.IGNORECASE,
)

# A market on where a candidate *places*, not on who wins. Brazil's listing
# carries "Presidential Election First Round: 2nd Place", whose leading outcome
# at 86% is 86% likely to come second — rendered on a board beside a winner
# probability it reads as a landslide. Rejected rather than linked so a genuine
# winner market further down the volume ranking can still claim the row.
_RANKING = re.compile(
    r"\b(\d+(?:st|nd|rd|th) place|second place|third place|runner[- ]?up"
    r"|margin of victory|vote share|turnout)\b",
    re.IGNORECASE,
)

# Markets about whether a *different* election happens at all.
_HYPOTHETICAL = re.compile(
    r"\b(snap election|early election|election called|postponed|delayed|cancell?ed)\b",
    re.IGNORECASE,
)

# The United States is the one country the reject list cannot carry on its own:
# Polymarket runs dozens of House, Senate and statewide markets that all
# normalise to the same country and would pile onto a single midterm row. Only a
# market about national control is allowed through.
_US_COUNTRIES = frozenset({"United States of America", "United States"})
_US_NATIONAL = re.compile(
    r"\b(midterms?|balance of power|house control|senate control"
    r"|win the house|win the senate|control of congress)\b",
    re.IGNORECASE,
)

_NOMINATION_TAGS = frozenset({"primaries", "primary"})


@dataclass(frozen=True)
class Match:
    event: EventSummary
    confidence: str  # "high" — a price — or "medium" — a link only
    matched_on: tuple[str, ...]


def attach_odds(
    elections: list[ElectionDate],
    events: list[EventSummary],
    registry: Registry,
    *,
    now: datetime,
) -> dict[int, Match]:
    """
    The best market for each election, keyed by the election's index.

    Scores every plausible pairing, then resolves the two ways a naive matcher
    goes wrong: one event may claim only one row (otherwise "Next French
    President" appears on both April rows), and only the earlier of two rounds
    is eligible (otherwise the same odds are printed twice as if they were two
    readings).
    """
    aliases = registry.alias_index()
    eligible = _first_rounds(elections)

    scored: dict[str, tuple[int, float, Match]] = {}
    for event in events:
        if not _is_a_national_election(event):
            continue
        if event.end_date is not None and event.end_date < now - STALE_AFTER:
            continue

        claimed = _country_claim(event, aliases)
        if claimed is None:
            continue
        country, source = claimed
        if country in _US_COUNTRIES and not _is_us_national(event):
            continue

        best: tuple[int, float, Match] | None = None
        for index in eligible:
            election = elections[index]
            if not _same_country(election.country, country, aliases):
                continue
            distance = _date_distance(election.date, event.end_date)
            if distance is None:
                continue
            match = Match(
                event=event,
                confidence=_confidence(source, event, event.end_date is not None),
                matched_on=_provenance(source, event),
            )
            if best is None or distance < best[1]:
                best = (index, distance, match)

        if best is not None:
            scored[event.slug] = best

    # An election named by two rows that cannot be told apart gets a link, not a
    # price: the office vocabulary is not reliable enough to pick between a
    # March presidential and an October legislative in the same country.
    ambiguous = _ambiguous_rows(elections, eligible)

    attached: dict[int, Match] = {}
    for index, distance, match in scored.values():
        if index in ambiguous:
            match = Match(match.event, "medium", match.matched_on + ("ambiguous_row",))
        current = attached.get(index)
        if current is None or match.event.volume_24h > current.event.volume_24h:
            attached[index] = match
    return attached


def _is_a_national_election(event: EventSummary) -> bool:
    """Whether the event is about a scheduled national vote at all."""
    haystack = " ".join((event.title, event.election_type or "", " ".join(event.tag_slugs)))
    if _NOT_AN_ELECTION.search(haystack):
        return False
    if _SUB_NATIONAL.search(haystack) or _NOMINATION.search(haystack):
        return False
    if _HYPOTHETICAL.search(haystack) or _RANKING.search(haystack):
        return False
    if _NOMINATION_TAGS & set(event.tag_slugs):
        return False
    return bool(_ELECTION_WORDS.search(haystack) or event.election_type)


def _is_us_national(event: EventSummary) -> bool:
    """
    Whether a US market is about national control rather than one of the races.

    The reject list above is enough everywhere else. It is not enough here:
    Polymarket carries a market per competitive House and Senate seat, each of
    which normalises to the same country and lands on the same single midterm
    row. Only a market whose subject is which party holds Congress says anything
    about that row.
    """
    haystack = " ".join((event.title, " ".join(event.tag_slugs)))
    return bool(_US_NATIONAL.search(haystack))


def _country_claim(
    event: EventSummary, aliases: dict[str, tuple[str, ...]]
) -> tuple[str, str] | None:
    """
    The one country an event is about, and how we know.

    Ordered by how much the signal is worth. A registry alias and a tag slug are
    structured claims; a name read out of the title is prose, and prose earns a
    link rather than a price.
    """
    for country, phrases in aliases.items():
        if any(
            re.search(rf"\b{re.escape(phrase)}\b", event.title, re.IGNORECASE) for phrase in phrases
        ):
            return country, "registry_alias"

    for slug in event.tag_slugs:
        found = _single(countries_in(slug.replace("-", " ")))
        if found:
            return found, "tag"

    if event.country_name:
        found = _single(countries_in(event.country_name))
        if found:
            return found, "country_field"

    found = _single(countries_in(event.title))
    if found:
        return found, "title"
    return None


def _single(found: list[str]) -> str | None:
    """
    One country, after dropping names contained inside a longer match.

    `countries_in` matches on word boundaries, so "Papua New Guinea" also
    reports "Guinea" and "Equatorial Guinea" reports only "Guinea". Collapsing
    substrings turns the first case into one right answer; the second is why the
    registry, not this function, decides what a calendar row's country is.
    """
    if not found:
        return None
    longest = [
        name for name in found if not any(other != name and name in other for other in found)
    ]
    return longest[0] if len(longest) == 1 else None


def _same_country(
    calendar_name: str, market_name: str, aliases: dict[str, tuple[str, ...]]
) -> bool:
    """
    Whether a calendar row and a market claim are about the same country.

    The two vocabularies do not agree — the calendar says "United States", the
    map says "United States of America" — so equality is checked both ways and
    the registry's own key wins when it matched.
    """
    if calendar_name == market_name:
        return True
    if calendar_name in aliases and market_name == calendar_name:
        return True
    return _single(countries_in(calendar_name)) == market_name


def _date_distance(polling_day: date, end_date: datetime | None) -> float | None:
    """Days between the vote and the market's resolution, or None if out of window."""
    if end_date is None:
        # No date evidence. Still matchable — the confidence gate caps it at a
        # link — so it sorts last rather than not at all.
        return 10_000.0
    vote = datetime.combine(polling_day, time.min, tzinfo=UTC)
    delta = end_date - vote
    if -WINDOW_BEFORE <= delta <= WINDOW_AFTER:
        return abs(delta.total_seconds())
    return None


def _confidence(source: str, event: EventSummary, has_date: bool) -> str:
    if source == "title" or not has_date:
        return "medium"
    if event.volume_24h < MIN_VOLUME_24H or event.liquidity < MIN_LIQUIDITY:
        return "medium"
    return "high"


def _provenance(source: str, event: EventSummary) -> tuple[str, ...]:
    parts = [source]
    if event.end_date is not None:
        parts.append("end_date")
    if event.election_type:
        parts.append("election_type")
    if event.exclusive:
        parts.append("neg_risk")
    return tuple(parts)


def _first_rounds(elections: list[ElectionDate]) -> list[int]:
    """
    Indices eligible for odds: the earliest row per country within a round window.

    A second round is a separate catalyst and keeps its own row on the board.
    It does not keep its own price, because there is only one market and
    printing it twice would read as two independent readings that agree.
    """
    eligible: list[int] = []
    earliest: dict[str, tuple[int, date]] = {}
    for index, election in enumerate(elections):
        held = earliest.get(election.country)
        if held is not None and election.date - held[1] <= SAME_ELECTION_WINDOW:
            continue
        earliest[election.country] = (index, election.date)
        eligible.append(index)
    return eligible


def _ambiguous_rows(elections: list[ElectionDate], eligible: list[int]) -> set[int]:
    """Rows whose country holds another, separate election inside the odds window."""
    by_country: dict[str, list[int]] = {}
    for index in eligible:
        by_country.setdefault(elections[index].country, []).append(index)
    return {index for rows in by_country.values() if len(rows) > 1 for index in rows}
