"""
Pentagon Pizza Index.

The folklore: unusual late-evening activity at the pizza restaurants around the
Pentagon has, anecdotally, run ahead of announced military operations. It is a
piece of OSINT internet culture, not a model, and every surface that renders it
says so. It earns a place on the macro board the way a sentiment gauge does —
as a reading about attention, carrying its own caveat.

The reading is computed here rather than copied. `pizzint.watch` publishes its
own `percentage_of_usual` and `is_spike` alongside the raw numbers, and those
are passed through for cross-checking, but the index this service reports is
derived from `current_popularity` against each venue's own baseline curve. That
way a change in how the source presents itself cannot silently redefine what
the panel claims.

Three properties of the raw data forced the scoring rules below, each of them
observed in a real payload rather than guessed at:

  * A baseline of 9 makes `41/9 = 4.6x` — arithmetically true, meaningless as a
    reference. Hours below `MIN_BASELINE` are dropped instead.
  * Google quantizes `current_popularity` hard towards 0 and 100, so a single
    venue printing 100 against a baseline of 28 at two in the morning would own
    a mean outright. The index is a median.
  * After closing time only one venue is still reporting, and one venue is not
    an index. Below `MIN_VENUES` usable readings the service reports
    `insufficient_data` and no number at all.

The timezone conversion is load-bearing, not housekeeping. Snapshots are stamped
in UTC while the baseline curve is indexed by local weekday and hour, so reading
one against the other without converting shifts every comparison by four or five
hours depending on daylight saving — which yields a plausible index that is
quietly wrong, the worst possible failure for a gauge.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
from datetime import UTC, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from services.cache import home_cache
from services.http_client import get_text

logger = logging.getLogger(__name__)

SOURCE_URL = "https://www.pizzint.watch/"
SOURCE_NAME = "pizzint.watch"

CACHE_KEY = "pentagon_pizza_index"
# The source samples roughly hourly, so anything faster only re-reads the same
# snapshot at the cost of a megabyte of HTML.
TTL_SECONDS = 600
# How old a replayed reading may be. Past six hours the venues have opened or
# closed since it was taken, which makes it a claim about a different day part.
MAX_STALE_SECONDS = 6 * 3600

# The venues sit in Arlington, Virginia. `baseline_popular_times` is indexed by
# local weekday and hour, and this is that locale.
VENUE_TZ = ZoneInfo("America/New_York")

# Below this, the baseline is too small to divide by: the difference between a
# usual busyness of 4 and of 9 is noise in Google's own estimate, but as a
# denominator it is the difference between 10x and 4x.
MIN_BASELINE = 20

# Fewer usable venues than this and there is no index, only a venue. Reported as
# `insufficient_data` rather than averaged into a number that looks like a
# measurement.
MIN_VENUES = 3

# Ratios clamp here. A venue at 100 against a baseline of 20 is already the
# strongest statement the source's 0-100 scale can make; letting it run to 5x or
# 10x would only encode Google's quantization as apparent signal.
RATIO_CAP = 4.0

# Ratio thresholds for the label. Deliberately wide around 1.0: hour-to-hour
# swings of ±30% are ordinary in this data, and a gauge that called every one of
# them "elevated" would be describing the noise floor.
THRESHOLD_QUIET = 0.7
THRESHOLD_ELEVATED = 1.3
THRESHOLD_SPIKE = 2.0

STATUS_LABELS = {
    "quiet": "Quieter than usual",
    "normal": "Normal",
    "elevated": "Above normal",
    "spike": "Unusually busy",
    "insufficient_data": "Not enough open venues",
    "unavailable": "Unavailable",
}

# The page is a Next.js RSC payload: the data is embedded in the flight stream
# with its quotes backslash-escaped. Each venue record begins with these two
# keys in this order, which is what anchors the scan.
_VENUE_ANCHOR = re.compile(r'\{"place_id":"[^"]+","name"')

# The page ships around 1.4 MB. The ceiling is generous rather than tight
# because a truncated body loses whole venues from the tail, and a silently
# smaller sample is exactly the failure `MIN_VENUES` exists to prevent.
MAX_PAGE_BYTES = 6_000_000


class PizzaSourceUnavailable(Exception):
    """The source could not be read, or carried nothing recognisable."""


# ── Parsing ─────────────────────────────────────────────────────────────────


def _balanced_object(text: str, start: int) -> Optional[str]:
    """
    The complete JSON object beginning at `start`, or None if it never closes.

    Brace counting is string-aware: a venue's address is free text and a stray
    brace inside one would otherwise end the object early, silently truncating
    the record into something that still parses but has lost its later fields.
    """
    depth = 0
    in_string = False
    escaped = False

    for i in range(start, len(text)):
        char = text[i]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    return None


def parse_venues(html: str) -> list[dict[str, Any]]:
    """
    Every venue record embedded in the page, de-duplicated by `place_id`.

    The flight stream repeats a record whenever more than one component received
    it, so the last occurrence wins — later chunks carry the hydrated values
    rather than the placeholders an earlier shell was rendered with.
    """
    # Undo the flight stream's quote escaping. Applied to the whole document
    # rather than to matched regions because the records are split across
    # `self.__next_f.push` chunks and a per-chunk unescape would have to
    # reassemble them first.
    decoded = html.replace('\\"', '"')

    venues: dict[str, dict[str, Any]] = {}
    for match in _VENUE_ANCHOR.finditer(decoded):
        raw = _balanced_object(decoded, match.start())
        if raw is None:
            continue
        try:
            venue = json.loads(raw)
        except json.JSONDecodeError:
            # A record split across chunk boundaries decodes to garbage. Skipping
            # it is right: the same venue is repeated elsewhere in the stream.
            continue
        place_id = venue.get("place_id")
        if isinstance(place_id, str) and "baseline_popular_times" in venue:
            venues[place_id] = venue

    return list(venues.values())


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """
    A `recorded_at` string as an aware datetime, or None if unusable.

    The source emits fractional seconds at whatever width the value happened to
    need — `.14`, `.733`, `.733123` — and `fromisoformat` rejects everything
    except 3 or 6 digits, so the fraction is normalised before parsing.
    """
    if not isinstance(value, str) or not value:
        return None

    text = value.replace("Z", "+00:00")
    match = re.match(r"^(.*\.)(\d+)([+-]\d{2}:?\d{2})$", text)
    if match:
        head, fraction, offset = match.groups()
        text = f"{head}{fraction.ljust(6, '0')[:6]}{offset}"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # A naive stamp from this source is UTC; saying so beats discarding it.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# ── Scoring ─────────────────────────────────────────────────────────────────


def baseline_at(venue: dict[str, Any], moment: datetime) -> Optional[int]:
    """
    The venue's usual busyness for the local weekday and hour of `moment`.

    `moment` is converted to venue-local time here rather than by the caller,
    because getting this wrong is invisible: every reading still produces a
    number, just one compared against the wrong hour of the week.

    The source keys weekdays the way Google's own data does — 0 is Sunday —
    while Python's `weekday()` starts on Monday, hence the rotation.
    """
    local = moment.astimezone(VENUE_TZ)
    google_dow = (local.weekday() + 1) % 7

    hours = venue.get("baseline_popular_times", {})
    if not isinstance(hours, dict):
        return None
    rows = hours.get(str(google_dow))
    if not isinstance(rows, list):
        return None

    for row in rows:
        if isinstance(row, dict) and row.get("hour") == local.hour:
            popularity = row.get("popularity")
            return popularity if isinstance(popularity, int) else None
    return None


def _ratio(current: Any, baseline: Optional[int]) -> Optional[float]:
    """
    `current` as a multiple of `baseline`, or None where that is not meaningful.

    Returns None rather than 0.0 for a missing reading: a closed venue has no
    ratio, and folding it in as zero would drag the index down every night by
    reporting "quiet" for hours nobody was ever measured.
    """
    if not isinstance(current, (int, float)):
        return None
    if baseline is None or baseline < MIN_BASELINE:
        return None
    return min(current / baseline, RATIO_CAP)


def _classify(index: Optional[float], venues_used: int) -> str:
    if venues_used < MIN_VENUES or index is None:
        return "insufficient_data"
    if index >= THRESHOLD_SPIKE:
        return "spike"
    if index >= THRESHOLD_ELEVATED:
        return "elevated"
    if index < THRESHOLD_QUIET:
        return "quiet"
    return "normal"


def _index_from(ratios: list[float]) -> Optional[float]:
    """The median ratio, or None below the minimum sample."""
    if len(ratios) < MIN_VENUES:
        return None
    return round(statistics.median(ratios), 3)


def _venue_row(
    venue: dict[str, Any],
    moment: Optional[datetime],
    hours: list[str],
) -> dict[str, Any]:
    """One venue as the panel renders it: our reading and the source's, side by side."""
    current = venue.get("current_popularity")
    baseline = baseline_at(venue, moment) if moment else None
    ratio = _ratio(current, baseline)

    return {
        "place_id": venue.get("place_id"),
        "name": venue.get("name"),
        "address": venue.get("address"),
        "current": current if isinstance(current, (int, float)) else None,
        "baseline": baseline,
        "ratio": round(ratio, 3) if ratio is not None else None,
        "is_closed": bool(venue.get("is_closed_now")),
        # Why a venue contributed nothing, so the panel can say so rather than
        # leaving a blank row the reader has to explain to themselves.
        "excluded_reason": _exclusion_reason(current, baseline, venue),
        # The source's own derived figures, passed through untouched. When these
        # and `ratio` disagree, that disagreement is the useful signal.
        "source_pct_of_usual": venue.get("percentage_of_usual"),
        "source_is_spike": bool(venue.get("is_spike")),
        "source_spike_magnitude": venue.get("spike_magnitude"),
        "freshness": venue.get("data_freshness"),
        # This venue's own 24h, on the same hour grid as the aggregate trend so
        # a reader can line the two up. See `build_venue_history`.
        "history": build_venue_history(venue, hours),
    }


def _exclusion_reason(
    current: Any, baseline: Optional[int], venue: dict[str, Any]
) -> Optional[str]:
    if venue.get("is_closed_now"):
        return "closed"
    if not isinstance(current, (int, float)):
        return "no reading"
    if baseline is None:
        return "no baseline for this hour"
    if baseline < MIN_BASELINE:
        return "baseline too low to compare"
    return None


def build_history(venues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    The last 24 hours of the index, scored by the same rules as the live reading.

    Built by bucketing every venue's snapshots into the local hour they were
    taken in, so the trend line and the headline number can never be computed
    two different ways.
    """
    buckets: dict[str, list[float]] = {}
    stamps: dict[str, datetime] = {}

    for venue in venues:
        for snapshot in venue.get("sparkline_24h") or []:
            if not isinstance(snapshot, dict):
                continue
            moment = _parse_timestamp(snapshot.get("recorded_at"))
            if moment is None:
                continue
            ratio = _ratio(snapshot.get("current_popularity"), baseline_at(venue, moment))
            if ratio is None:
                continue
            local = moment.astimezone(VENUE_TZ)
            key = local.strftime("%Y-%m-%dT%H")
            buckets.setdefault(key, []).append(ratio)
            # Truncated to the hour rather than kept at the first snapshot's own
            # minute: the bucket is an hour, and stamping it 10:10 would invite
            # the chart to plot it ten minutes off the gridline it belongs on.
            stamps.setdefault(key, local.replace(minute=0, second=0, microsecond=0))

    history = []
    for key in sorted(buckets):
        ratios = buckets[key]
        history.append(
            {
                "hour_et": stamps[key].isoformat(),
                # Hours that fall short of the minimum sample keep their slot and
                # report a null: dropping them would close the gap and draw a
                # continuous line across hours nothing was measured in.
                "index": _index_from(ratios),
                "venues_used": len(ratios),
            }
        )
    return history


def build_venue_history(venue: dict[str, Any], hours: list[str]) -> list[dict[str, Any]]:
    """
    One venue's last 24 hours, scored by the same rules as the index it feeds.

    Plotted on `hours` — the grid the aggregate trend already uses — rather than
    on whatever hours this venue happened to report in. A venue that was shut
    from 02:00 to 06:00 has to render four empty slots there, because bars drawn
    only over the hours a venue was open would compress its night into nothing
    and place its 07:00 reading under the aggregate's 03:00 one.

    Where a venue logged more than one snapshot in an hour the median is taken,
    for the same reason the index is a median: a single quantized 100 should not
    own the bar.
    """
    buckets: dict[str, list[float]] = {}

    for snapshot in venue.get("sparkline_24h") or []:
        if not isinstance(snapshot, dict):
            continue
        moment = _parse_timestamp(snapshot.get("recorded_at"))
        if moment is None:
            continue
        ratio = _ratio(snapshot.get("current_popularity"), baseline_at(venue, moment))
        if ratio is None:
            continue
        local = moment.astimezone(VENUE_TZ)
        key = local.replace(minute=0, second=0, microsecond=0).isoformat()
        buckets.setdefault(key, []).append(ratio)

    return [
        {
            "hour_et": hour,
            "ratio": round(statistics.median(buckets[hour]), 3) if hour in buckets else None,
        }
        for hour in hours
    ]


def score(venues: list[dict[str, Any]], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """
    The full payload for a parsed page.

    `now` is injectable so the tests can score a saved fixture against the hour
    it was actually captured in.
    """
    moment = now or datetime.now(UTC)

    # Built first because it defines the hour grid every venue's own bars are
    # then drawn on — the panel stacks them, and two grids would not line up.
    history = build_history(venues)
    hours = [hour["hour_et"] for hour in history]

    rows = [_venue_row(venue, moment, hours) for venue in venues]
    ratios = [row["ratio"] for row in rows if row["ratio"] is not None]

    index = _index_from(ratios)
    status = _classify(index, len(ratios))

    return {
        "index": index,
        "status": status,
        "label": STATUS_LABELS[status],
        "venues_used": len(ratios),
        "venues_total": len(rows),
        "venues": sorted(rows, key=lambda row: (row["ratio"] is None, -(row["ratio"] or 0))),
        "history": history,
        "as_of": moment.isoformat(),
        "stale": False,
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
    }


# ── Fetch ───────────────────────────────────────────────────────────────────


async def _fetch_and_score() -> dict[str, Any]:
    html = await get_text(SOURCE_URL, max_bytes=MAX_PAGE_BYTES)
    venues = parse_venues(html)
    if not venues:
        # A 200 that carries no venues means the page was restructured. Treated
        # as an outage rather than as "no pizza activity", which is the same
        # distinction the macro board draws between empty and unavailable.
        raise PizzaSourceUnavailable("no venue records found in the source page")
    return score(venues)


def _unavailable() -> dict[str, Any]:
    """The empty reading, for when there is not even a stale one to replay."""
    return {
        "index": None,
        "status": "unavailable",
        "label": STATUS_LABELS["unavailable"],
        "venues_used": 0,
        "venues_total": 0,
        "venues": [],
        "history": [],
        "as_of": datetime.now(UTC).isoformat(),
        "stale": False,
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
    }


async def fetch_pizza_index() -> dict[str, Any]:
    """
    The Pentagon Pizza Index, cached and stale-tolerant.

    Never raises. This is a novelty gauge sharing a page with the macro board,
    and a failed pizza scrape must not be able to take that board down — so a
    failure degrades to the last good reading, and past that to an explicit
    `unavailable` the panel renders as its own state.
    """
    cached = home_cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    try:
        payload = await _fetch_and_score()
    except Exception as e:
        logger.warning("Pentagon Pizza Index unavailable: %s", e)
        stale = home_cache.get_with_fallback(CACHE_KEY, max_age=MAX_STALE_SECONDS)
        if stale is not None:
            return {**stale, "stale": True}
        return _unavailable()

    home_cache.set(CACHE_KEY, payload, TTL_SECONDS)
    return payload
