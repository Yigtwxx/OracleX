"""
The elections board: two independent sources, assembled per request.

The calendar and the odds fail separately and are treated separately, which is
the reason they are cached separately rather than as one board.

A board with no rows would assert that no national election is scheduled
anywhere on Earth, which is never true. That is `home_service._load_macro_events`'
case exactly — "an empty calendar is a claim about the month, not an absence of
information" — so losing the calendar past its fallback is a 503.

A board with dates and no odds asserts nothing false, *provided the outage is
named*. `odds_available` is that naming, and without it a Polymarket failure
would be byte-identical to "no market covers any of these elections". This is
the same call `/api/macro/pizza-index` makes for the same reason.

The assembled board itself is never cached. `fetch_live_events` recomputes its
partition on every call so a cache cannot leave a badge stuck on something that
has finished; here it is so an election held this morning leaves the board this
morning rather than up to a day later.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, UTC
from typing import Any

from config import settings
from services.cache import ServiceCache
from services.elections import odds as odds_module
from services.elections import wikipedia
from services.elections.join import attach_odds
from services.elections.odds import EventSummary
from services.elections.registry import load_registry
from services.elections.wikipedia import ElectionDate
from services.home_service import UpstreamUnavailable

logger = logging.getLogger(__name__)

elections_cache = ServiceCache(maxsize=16)

CACHE_KEY_CALENDAR = "elections_calendar"
CACHE_KEY_ODDS = "elections_odds"
BACKOFF_CALENDAR = "elections_calendar_backoff"
BACKOFF_ODDS = "elections_odds_backoff"

# The calendar is warmed once a day by the scheduler; this TTL only bounds how
# long an unwarmed process trusts its own first fetch.
TTL_CALENDAR = 24 * 3600
TTL_ODDS = 900
TTL_BACKOFF = 300

# The longest stale window in the codebase, and the justification is specific:
# an election date is fixed months in advance, so a week-old copy is very nearly
# today's. It stops at a week rather than a month because dates do move —
# postponement, coup, a court — and replaying a superseded date is the one
# failure worse than the panel being down.
MAX_STALE_CALENDAR = 7 * 24 * 3600
MAX_STALE_ODDS = 3600


async def fetch_elections() -> dict[str, Any]:
    """The board: every upcoming national election, priced where it can be."""
    calendar_result, odds_result = await asyncio.gather(
        _load_calendar(), _load_odds(), return_exceptions=True
    )

    if isinstance(calendar_result, BaseException):
        raise calendar_result
    rows, years = calendar_result

    if isinstance(odds_result, BaseException):
        logger.warning("Election odds unavailable: %s", odds_result)
        events: list[EventSummary] = []
        odds_available = False
    else:
        events = odds_result
        odds_available = True

    now = datetime.now(UTC)
    today = now.date()
    # Filtered per request rather than at cache time, so the board stays honest
    # as elections pass during a cached day.
    upcoming = [row for row in rows if (row.through or row.date) >= today]
    upcoming.sort(key=lambda row: (row.date, row.country))

    registry = load_registry()
    matches = attach_odds(upcoming, events, registry, now=now)

    age = elections_cache.get_fallback_age(CACHE_KEY_CALENDAR)
    return {
        "elections": [
            _row(election, registry, matches.get(index)) for index, election in enumerate(upcoming)
        ],
        "odds_available": odds_available,
        # A coverage cap, not a filter: the listing is ordered by volume, so
        # most rows having no market means we asked for the loudest forty, not
        # that Polymarket covers nothing. The panel says so in its footnote.
        "odds_cap": settings.ELECTIONS_ODDS_LIMIT,
        "years": years,
        "as_of": now.isoformat(),
        "stale": not elections_cache.is_valid(CACHE_KEY_CALENDAR) and age is not None,
    }


def _row(election: ElectionDate, registry, match) -> dict[str, Any]:
    entry = registry.get(election.country)
    row: dict[str, Any] = {
        "id": f"{election.date.isoformat()}-{_slug(election.country)}",
        "date": election.date.isoformat(),
        "through": election.through.isoformat() if election.through else None,
        "precision": election.precision,
        "country": election.country,
        "iso2": entry.iso2,
        "flag": entry.flag,
        "office": election.office,
        "minor": election.minor,
        "tier": entry.tier,
        "tickers": list(entry.tickers),
        "note": entry.note,
        "odds": None,
        "market_link": None,
        "source_url": election.source_url,
    }
    if match is None:
        return row

    link = {
        "event_slug": match.event.slug,
        "event_title": match.event.title,
        "url": match.event.url,
        "confidence": match.confidence,
        "matched_on": list(match.matched_on),
    }
    if match.confidence != "high":
        # A link is a claim we can defend from prose; a number is not. The
        # distinction is the whole reason the gate exists.
        row["market_link"] = link
        return row

    row["odds"] = {
        **link,
        "volume_24h": match.event.volume_24h,
        "liquidity": match.event.liquidity,
        "exclusive": match.event.exclusive,
        "outcomes": [
            {"label": o.label, "price": o.price, "change_1w": o.change_1w}
            for o in match.event.outcomes
        ],
        "others": match.event.others,
    }
    return row


def _slug(text: str) -> str:
    return "".join(char if char.isalnum() else "-" for char in text.lower()).strip("-")


async def _load_calendar() -> tuple[list[ElectionDate], list[int]]:
    """
    The calendar window, cached, and which year pages contributed to it.

    The current year is load-bearing and a later one is not: a page for a year
    nobody has written up yet is normal, while a current-year page with no dated
    rows means the article's shape changed. Both arrive here as the same
    `ValueError`, so the distinction is made by which year raised it.
    """
    cached = elections_cache.get(CACHE_KEY_CALENDAR)
    if cached is not None:
        return cached

    if elections_cache.is_valid(BACKOFF_CALENDAR):
        stale = elections_cache.get_with_fallback(CACHE_KEY_CALENDAR, max_age=MAX_STALE_CALENDAR)
        if stale is not None:
            return stale
        raise UpstreamUnavailable("electoral calendar unavailable (backing off)")

    first_year = date.today().year
    years = [first_year + offset for offset in range(settings.ELECTIONS_CALENDAR_YEARS)]
    results = await asyncio.gather(*(_load_year(year) for year in years), return_exceptions=True)

    rows: list[ElectionDate] = []
    contributed: list[int] = []
    for year, result in zip(years, results):
        if isinstance(result, BaseException):
            if year == first_year:
                logger.error("Electoral calendar for %d unavailable: %s", year, result)
            else:
                logger.warning("Electoral calendar for %d unavailable: %s", year, result)
            continue
        rows.extend(result)
        contributed.append(year)

    if first_year not in contributed:
        stale = elections_cache.get_with_fallback(CACHE_KEY_CALENDAR, max_age=MAX_STALE_CALENDAR)
        if stale is not None:
            return stale
        elections_cache.set(BACKOFF_CALENDAR, True, TTL_BACKOFF)
        raise UpstreamUnavailable("electoral calendar unavailable")

    payload = (rows, contributed)
    elections_cache.set(CACHE_KEY_CALENDAR, payload, TTL_CALENDAR)
    return payload


async def _load_year(year: int) -> list[ElectionDate]:
    return wikipedia.parse_calendar(await wikipedia.fetch_year(year), year)


async def _load_odds() -> list[EventSummary]:
    """
    The election markets, cached, summarised. Raises; the board degrades around it.

    An empty summary list is treated as a failure rather than cached. Gamma
    answering 200 with nothing usable is what a renamed tag looks like, and
    parking [] here would be indistinguishable from a world with no election
    markets in it.
    """
    cached = elections_cache.get(CACHE_KEY_ODDS)
    if cached is not None:
        return cached

    if elections_cache.is_valid(BACKOFF_ODDS):
        stale = elections_cache.get_with_fallback(CACHE_KEY_ODDS, max_age=MAX_STALE_ODDS)
        if stale is not None:
            return stale
        raise UpstreamUnavailable("election markets unavailable (backing off)")

    try:
        raw = await odds_module.fetch_election_events()
        summaries = [s for s in (odds_module.summarise_event(event) for event in raw) if s]
        if not summaries:
            raise ValueError("no election events carried a priceable outcome")
    except Exception as error:
        stale = elections_cache.get_with_fallback(CACHE_KEY_ODDS, max_age=MAX_STALE_ODDS)
        if stale is not None:
            return stale
        elections_cache.set(BACKOFF_ODDS, True, TTL_BACKOFF)
        raise UpstreamUnavailable(f"election markets unavailable: {error}") from error

    elections_cache.set(CACHE_KEY_ODDS, summaries, TTL_ODDS)
    return summaries
