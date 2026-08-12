"""
Live event calendar.

Aggregates the scheduled, market-moving events the Live tab is built around:
macro data prints, central-bank decisions and speeches, Fed testimony and FOMC
days, and the week's big-cap earnings. Three upstreams feed it, all keyless.

* **ForexFactory's weekly JSON feed** covers the data prints and every major
  central bank's scheduled events, across currencies. The JSON variant is used
  rather than the XML one `home_service` reads: it publishes ISO-8601 instants
  with an offset instead of a bare "1:30pm" whose timezone has to be inferred,
  and the XML endpoint rate-limits noticeably harder.
* **The Federal Reserve's own `calendar.json`** is the only place Governor
  speeches, congressional testimony and FOMC days are scheduled ahead of time,
  and it carries a broadcast URL per entry.
* **Nasdaq's earnings calendar** answers a whole day of reporters per request,
  with a market cap on each, so the big-cap cut costs nothing extra.

Neither schedules political speeches — no feed does. Those arrive the only way
they can: `live_stream_service` reports a curated channel going on air, and an
unscheduled broadcast is surfaced as an event in its own right.

Events are cached as a week, not as a filtered list. Whether something is live
is derived per request, so a fifteen-minute cache never freezes the LIVE badge.
"""

import asyncio
import hashlib
import html
import json
import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from config import settings
from services import http_client
from services.cache import market_cache
from services.home_service import UpstreamUnavailable
from services.live_stream_service import cached_live_channels

logger = logging.getLogger(__name__)

CACHE_KEY = "live_events"
BACKOFF_KEY = "live_events_backoff"
TTL_EVENTS = 900
# A week-long calendar ages gracefully: yesterday's entries are still correct
# and today's are still worth showing, so the fallback is allowed to run long.
MAX_STALE_EVENTS = 6 * 3600
# ForexFactory answers 429 to clients it does not recognise. A short negative
# cache keeps a rate-limited feed from being retried on every request; parking
# an empty list in the data cache would be indistinguishable from a quiet week.
TTL_EVENTS_BACKOFF = 300

FOREXFACTORY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FED_CALENDAR_URL = "https://www.federalreserve.gov/json/calendar.json"

# faireconomy.media rate-limits unfamiliar clients aggressively; the Fed does
# not, but sends the same header set no worse for being there.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}

FED_TZ = ZoneInfo("America/New_York")

# Fed calendar entry types worth a row. `Stat` is the H.4.1/H.8 statistical
# release drumbeat — a thousand entries of it, none of which moves a market on
# its own — and `events`/`Other` are unlabelled miscellany.
FED_TYPES = frozenset({"Speeches", "Testimony", "FOMC", "Beige", "Board"})

# How long an event occupies the screen once it starts, in minutes. A data print
# is instantaneous and needs only a grace window wide enough to be noticed; a
# press conference genuinely runs for an hour. Being wrong in either direction
# shows: too short and Powell vanishes mid-sentence, too long and a CPI that
# printed at lunch is still claiming to be live at close.
DURATION_BY_SHAPE: dict[str, int] = {
    "data": 15,
    "decision": 30,
    "speech": 45,
    "presser": 90,
    "fomc": 120,
    "earnings": 90,
}

# A broadcast starting within this much of a scheduled event is taken to be that
# event, which is what lets an on-air feed promote a row to live a few minutes
# before its published time.
PROMOTION_WINDOW = timedelta(minutes=30)

_PRESSER_WORDS = ("press conference", "testimony", "testifies", "hearing", "semiannual")
_DECISION_WORDS = (
    "rate statement",
    "rate decision",
    "interest rate",
    "official bank rate",
    "monetary policy statement",
    "cash rate",
    "policy rate",
)
_SPEECH_WORDS = ("speaks", "speech", "remarks", "discussion", "fireside", "testimony")
_CENTRAL_BANK_WORDS = (
    "fomc",
    "fed ",
    "federal reserve",
    "ecb",
    "lagarde",
    "boe",
    "boj",
    "rba",
    "rbnz",
    "snb",
    "boc",
    "pboc",
    "cbrt",
    "governor",
    "gov ",
    "chair",
    "member",
    "beige book",
    "monetary policy",
)
_POLITICAL_WORDS = (
    "trump",
    "president",
    "white house",
    "treasury secretary",
    "tariff",
    "congress",
    "senate",
    "house financial services",
)

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(raw: str | None) -> str:
    """Fed descriptions arrive as HTML-escaped markup; the UI wants prose."""
    if not raw:
        return ""
    return " ".join(_TAG_RE.sub(" ", html.unescape(raw)).split())


def _stable_id(source: str, title: str, starts_at: str) -> str:
    """
    A key that survives a refetch.

    The frontend keys rows and the selected event by this, so it has to be
    derived from the event rather than from its position in a list that
    reorders every time something starts.
    """
    digest = hashlib.sha1(f"{source}|{title}|{starts_at}".encode()).hexdigest()
    return f"{source[:2]}_{digest[:16]}"


def _shape(title: str) -> str:
    """Which duration bucket an event falls into, from its title alone."""
    lowered = title.lower()
    if "fomc" in lowered and any(word in lowered for word in ("meeting", "statement")):
        return "fomc"
    if any(word in lowered for word in _PRESSER_WORDS):
        return "presser"
    if any(word in lowered for word in _DECISION_WORDS):
        return "decision"
    if any(word in lowered for word in _SPEECH_WORDS):
        return "speech"
    return "data"


def _classify(title: str, source: str) -> str:
    """The event's kind, which is what the tab's filter strip switches on."""
    lowered = title.lower()
    if source == "nasdaq":
        return "corporate"
    if source == "federalreserve":
        # Fed testimony is delivered to Congress, so it reads political by
        # keyword. It is a central banker speaking about policy either way.
        return "central_bank"
    if any(word in lowered for word in _CENTRAL_BANK_WORDS):
        return "central_bank"
    if any(word in lowered for word in _POLITICAL_WORDS):
        return "political"
    return "macro_data"


def _speaker(title: str) -> str | None:
    """
    The person behind a Fed entry, e.g. "Speech - Governor Lisa D. Cook".

    Returned separately so a row can lead with the name — "Powell" is the part
    a trader scans for, and it sits at the end of the source's own title.
    """
    if " - " not in title:
        return None
    name = title.split(" - ", 1)[1].strip()
    return name or None


def _build(
    *,
    source: str,
    title: str,
    starts_at: datetime,
    impact: str,
    country: str | None = None,
    speaker: str | None = None,
    forecast: str | None = None,
    previous: str | None = None,
    watch_url: str | None = None,
    embed_url: str | None = None,
    location: str | None = None,
    detail: str | None = None,
    time_confirmed: bool = True,
    shape: str | None = None,
) -> dict[str, Any]:
    """Normalise one upstream entry into the shape the whole tab speaks."""
    resolved_shape = shape or _shape(title)
    ends_at = starts_at + timedelta(minutes=DURATION_BY_SHAPE[resolved_shape])
    starts_iso = starts_at.astimezone(UTC).isoformat()
    return {
        "id": _stable_id(source, title, starts_iso),
        "source": source,
        "kind": _classify(title, source),
        "shape": resolved_shape,
        "title": title,
        "detail": detail or None,
        "speaker": speaker,
        "country": country,
        "impact": impact,
        "starts_at": starts_iso,
        "ends_at": ends_at.astimezone(UTC).isoformat(),
        "time_confirmed": time_confirmed,
        "forecast": forecast or None,
        "previous": previous or None,
        "watch_url": watch_url,
        "embed_url": embed_url,
        "location": location or None,
    }


# ==========================================
# SOURCES
# ==========================================


async def _load_forexfactory() -> list[dict[str, Any]]:
    """The current week's calendar, every currency."""
    payload = await http_client.get_json(FOREXFACTORY_URL, headers=_BROWSER_HEADERS, timeout=12.0)
    if not isinstance(payload, list):
        raise ValueError("unexpected ForexFactory payload")

    events: list[dict[str, Any]] = []
    for entry in payload:
        title = (entry.get("title") or "").strip()
        raw_date = (entry.get("date") or "").strip()
        if not title or not raw_date:
            continue

        try:
            # Already carries its own offset, e.g. "2026-08-10T15:00:00-04:00",
            # so no timezone has to be assumed the way the XML feed forces.
            starts_at = datetime.fromisoformat(raw_date)
        except ValueError:
            logger.debug("Unparseable ForexFactory date %r for %r", raw_date, title[:60])
            continue
        if starts_at.tzinfo is None:
            continue

        impact = (entry.get("impact") or "").strip().lower()
        shape = _shape(title)
        # The Home widget's medium-and-up filter would drop "FOMC Member Barkin
        # Speaks", which the feed rates Low and which is exactly what this tab
        # exists to show. Anything a person says stays regardless of impact.
        if impact not in ("high", "medium") and shape == "data":
            continue

        events.append(
            _build(
                source="forexfactory",
                title=title,
                starts_at=starts_at,
                impact=impact if impact in ("high", "medium", "low") else "low",
                country=(entry.get("country") or "").strip() or None,
                forecast=(entry.get("forecast") or "").strip(),
                previous=(entry.get("previous") or "").strip(),
                shape=shape,
            )
        )
    return events


def _fed_start(entry: dict[str, Any]) -> tuple[datetime, bool] | None:
    """
    An entry's start instant, and whether the feed actually published a time.

    Dates arrive split across `month` ("2026-08") and `days`, in Eastern time.
    `days` is usually a single number but a recurring release writes the whole
    set into it — "3, 10, 17, 24" — and a two-day meeting writes a range, so the
    first number is taken and the rest ignored rather than parsed as an integer.
    `ZoneInfo` rather than a fixed offset, or every entry shifts by an hour
    either side of a DST change.
    """
    month = (entry.get("month") or "").strip()
    days = (entry.get("days") or "").strip()
    if not month or not days:
        return None

    try:
        year, month_number = (int(part) for part in month.split("-", 1))
        day = int(re.split(r"[,\-]", days, maxsplit=1)[0])
    except ValueError:
        return None

    raw_time = (entry.get("time") or "").strip().lower().replace(".", "").replace(" ", "")
    try:
        parsed = datetime.strptime(raw_time, "%I:%M%p")
    except ValueError:
        # A quarter of the feed carries no time. Placing those at end of day
        # keeps them listed for the whole day they belong to, and
        # `time_confirmed=False` stops them ever being called live.
        try:
            return (
                datetime(year, month_number, day, 23, 59, tzinfo=FED_TZ),
                False,
            )
        except ValueError:
            return None

    try:
        return (
            datetime(year, month_number, day, parsed.hour, parsed.minute, tzinfo=FED_TZ),
            True,
        )
    except ValueError:
        return None


async def _load_fed_calendar() -> list[dict[str, Any]]:
    """Fed speeches, testimony and FOMC days, with their broadcast links."""
    # The body is served with a UTF-8 BOM, which the JSON decoder rejects
    # outright ("Unexpected UTF-8 BOM"), so it is read as text and stripped
    # before parsing rather than fetched as JSON. It is also around half a
    # megabyte, comfortably past `get_text`'s default ceiling.
    body = await http_client.get_text(
        FED_CALENDAR_URL,
        headers=_BROWSER_HEADERS,
        timeout=12.0,
        max_bytes=4_000_000,
    )
    payload = json.loads(body.lstrip("﻿"))
    entries = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ValueError("unexpected Fed calendar payload")

    horizon = datetime.now(UTC) - timedelta(days=2)
    events: list[dict[str, Any]] = []
    for entry in entries:
        if not entry or entry.get("type") not in FED_TYPES:
            continue
        title = (entry.get("title") or "").strip()
        if not title:
            continue

        start = _fed_start(entry)
        if start is None:
            continue
        starts_at, time_confirmed = start
        # The feed reaches back to 2017. Only the tail is of any use here, and
        # discarding the rest early keeps the cached payload small.
        if starts_at < horizon:
            continue

        watch_url = (entry.get("live") or "").strip() or None
        events.append(
            _build(
                source="federalreserve",
                title=title,
                detail=_clean(entry.get("description")),
                starts_at=starts_at,
                # The Fed does not rate its own events. Everything that survives
                # the type filter is a policymaker on the record, which this tab
                # treats as high by definition.
                impact="high",
                country="USD",
                speaker=_speaker(title),
                watch_url=watch_url,
                location=_clean(entry.get("location")),
                time_confirmed=time_confirmed,
                shape=_shape(title),
            )
        )
    return events


def _market_cap(raw: str | None) -> float | None:
    """`"$478,608,411,371"` → 478608411371.0. `"N/A"` and friends → None."""
    if not raw:
        return None
    cleaned = raw.replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


async def _load_earnings() -> list[dict[str, Any]]:
    """
    Big-cap earnings dates for the week ahead.

    Nasdaq's calendar answers a whole day per request, which is why it is used
    over Yahoo's `quoteSummary`: that one needs a round trip per ticker, and the
    tracked universe is hundreds of them. It also ships a market cap, so the
    "big enough to move the tape" cut is free rather than a second lookup.

    Nasdaq publishes no clock time — only before-open or after-close. Rather
    than invent one, each row is anchored at the session edge it belongs to and
    flagged `time_confirmed=False`, which is what keeps it out of the live strip.
    """
    today = datetime.now(UTC).date()
    days = [today + timedelta(days=offset) for offset in range(7)]

    async def _day(day: date) -> list[dict[str, Any]]:
        # Nasdaq sits behind Akamai and refuses ordinary clients.
        payload = await http_client.get_json_impersonated(
            "https://api.nasdaq.com/api/calendar/earnings",
            params={"date": day.isoformat()},
            timeout=15.0,
        )
        rows = (payload or {}).get("data", {}).get("rows") or []
        return [row for row in rows if isinstance(row, dict)]

    results = await asyncio.gather(*(_day(day) for day in days), return_exceptions=True)

    events: list[dict[str, Any]] = []
    for day, result in zip(days, results):
        if isinstance(result, BaseException):
            logger.warning("Earnings calendar failed for %s: %s", day, result)
            continue

        for row in result:
            cap = _market_cap(row.get("marketCap"))
            if cap is None or cap < settings.LIVE_EARNINGS_MIN_MARKET_CAP:
                continue
            symbol = (row.get("symbol") or "").strip()
            if not symbol:
                continue

            # "time-pre-market" opens at 09:30 ET, "time-after-hours" reports
            # once the close is in. Both are anchors for ordering, not claims
            # about a minute.
            before_open = (row.get("time") or "") == "time-pre-market"
            hour = 8 if before_open else 16
            starts_at = datetime(day.year, day.month, day.day, hour, 30, tzinfo=FED_TZ)

            events.append(
                _build(
                    source="nasdaq",
                    title=f"{symbol} earnings",
                    detail=(row.get("name") or "").strip(),
                    starts_at=starts_at,
                    impact="high",
                    country="USD",
                    forecast=(row.get("epsForecast") or "").strip(),
                    previous=(row.get("lastYearEPS") or "").strip(),
                    location="Before open" if before_open else "After close",
                    time_confirmed=False,
                    shape="earnings",
                )
            )
    return events


# ==========================================
# AGGREGATION
# ==========================================


def _dedupe(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Drop entries the two feeds both carry.

    Exact collisions on time and title are the common case. FOMC days are the
    awkward one: ForexFactory splits the afternoon into "FOMC Statement" and
    "FOMC Press Conference" with forecasts attached, while the Fed publishes a
    single "FOMC Meeting". The split rows are the more useful pair, so a Fed
    meeting row is dropped when ForexFactory already describes that day.
    """
    forexfactory_fomc_days = {
        event["starts_at"][:10]
        for event in events
        if event["source"] == "forexfactory" and "fomc" in event["title"].lower()
    }

    seen: set[tuple[str, str]] = set()
    kept: list[dict[str, Any]] = []
    for event in events:
        lowered = event["title"].lower()
        if (
            event["source"] == "federalreserve"
            and "fomc" in lowered
            and event["starts_at"][:10] in forexfactory_fomc_days
        ):
            continue

        key = (event["starts_at"], lowered[:48])
        if key in seen:
            continue
        seen.add(key)
        kept.append(event)
    return kept


async def _load_events() -> list[dict[str, Any]]:
    """The cached week. See `fetch_live_events` for the per-request part."""
    cached = market_cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    if market_cache.is_valid(BACKOFF_KEY):
        stale = market_cache.get_with_fallback(CACHE_KEY, max_age=MAX_STALE_EVENTS)
        if stale is not None:
            return stale
        raise UpstreamUnavailable("live event calendar unavailable (backing off)")

    results = await asyncio.gather(
        _load_forexfactory(),
        _load_fed_calendar(),
        _load_earnings(),
        return_exceptions=True,
    )

    events: list[dict[str, Any]] = []
    failures = 0
    for name, result in zip(("forexfactory", "federalreserve", "nasdaq"), results):
        if isinstance(result, BaseException):
            failures += 1
            logger.error("Live calendar source %s failed: %s", name, result)
            continue
        events.extend(result)

    # One source surviving is a usable calendar, so a partial outage degrades
    # rather than 503s. Losing both is an outage.
    if not events:
        stale = market_cache.get_with_fallback(CACHE_KEY, max_age=MAX_STALE_EVENTS)
        if stale is not None:
            return stale
        market_cache.set(BACKOFF_KEY, True, TTL_EVENTS_BACKOFF)
        raise UpstreamUnavailable("live event calendar unavailable")

    events = _dedupe(events)
    events.sort(key=lambda event: event["starts_at"])
    market_cache.set(CACHE_KEY, events, TTL_EVENTS)
    if failures:
        logger.warning("Live calendar built from %d of 3 sources", 3 - failures)
    return events


def _broadcast_events(channels: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """
    Rows for broadcasts nothing scheduled.

    This is how an unannounced press conference reaches the tab at all: no feed
    schedules "the President speaks at 4pm", but the White House channel going
    live says so. Only channels whose going live is itself the news qualify —
    the rolling market channels are always on and would otherwise pin a
    permanent fake event to the top of the list.
    """
    events: list[dict[str, Any]] = []
    for channel in channels:
        if channel.get("implies") == "market":
            continue
        title = channel.get("title") or f"{channel['name']} is live"
        events.append(
            _build(
                source="youtube",
                title=title,
                starts_at=now,
                impact="high",
                speaker=channel["name"],
                watch_url=channel.get("watch_url"),
                embed_url=channel.get("embed_url"),
                shape="presser",
            )
            | {
                # Derived from a broadcast that is on air by definition, so the
                # window arithmetic below is bypassed rather than applied to a
                # start time that is really just "now".
                "kind": "political" if channel["implies"] == "political" else "central_bank",
                "status": "live",
            }
        )
    return events


def _with_status(
    event: dict[str, Any], now: datetime, live_channels: list[dict[str, Any]]
) -> dict[str, Any]:
    """Place an event against the clock, letting a live broadcast override."""
    if event.get("status") == "live":
        return event

    starts_at = datetime.fromisoformat(event["starts_at"])
    ends_at = datetime.fromisoformat(event["ends_at"])

    if starts_at <= now < ends_at and event["time_confirmed"]:
        status = "live"
    elif now >= ends_at:
        status = "ended"
    else:
        status = "scheduled"

    embed_url = event.get("embed_url")
    if status == "scheduled" and abs(starts_at - now) <= PROMOTION_WINDOW:
        # A channel already on air a few minutes before the published time is
        # the event starting early — the common case for a press conference.
        match = next(
            (channel for channel in live_channels if channel.get("implies") == event["kind"]),
            None,
        )
        if match is not None:
            status = "live"
            embed_url = embed_url or match.get("embed_url")

    return {**event, "status": status, "embed_url": embed_url}


async def fetch_live_events() -> dict[str, Any]:
    """
    The calendar, partitioned by the clock.

    `live` is what to look at now, `upcoming` is the rest of the week ahead, and
    `recent` is the last day's worth of prints kept for context — a CPI that
    landed an hour ago is still the reason the tape is moving.

    The partition is recomputed on every call rather than cached with the
    events, so a fifteen-minute cache never leaves the LIVE badge stuck on
    something that has finished.
    """
    events = await _load_events()
    now = datetime.now(UTC)
    live_channels = cached_live_channels()

    placed = [_with_status(event, now, live_channels) for event in events]
    placed.extend(_broadcast_events(live_channels, now))

    recent_horizon = now - timedelta(hours=24)
    live = [event for event in placed if event["status"] == "live"]
    upcoming = [event for event in placed if event["status"] == "scheduled"]
    recent = [
        event
        for event in placed
        if event["status"] == "ended" and datetime.fromisoformat(event["ends_at"]) >= recent_horizon
    ]

    live.sort(key=lambda event: event["starts_at"])
    upcoming.sort(key=lambda event: event["starts_at"])
    recent.sort(key=lambda event: event["starts_at"], reverse=True)

    age = market_cache.get_fallback_age(CACHE_KEY)
    return {
        "live": live,
        "upcoming": upcoming,
        "recent": recent,
        "as_of": now.isoformat(),
        "stale": not market_cache.is_valid(CACHE_KEY) and age is not None,
    }
