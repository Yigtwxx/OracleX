"""
Gece Mesaisi Endeksi — the BIST realm's answer to the Pentagon Pizza Index.

The American gauge asks one question: are they working late? It answers it from
an involuntary trace — pizza orders around the Pentagon — because nobody
announces a long night in advance. Turkey has no equivalent trace at a building,
but it has one in print: the Resmî Gazete.

What this measures, stated plainly because the analogy would otherwise oversell
it: **how hard the state is legislating today, and whether any of it was urgent
enough to skip the queue.** Two of those are ordinary daily volume readings. The
third is the mükerrer sayı — an extra edition of the Gazette, published only
when something must be in force the same day rather than tomorrow.

Three honest limits, all measured rather than assumed, and all of them stated on
the panel rather than buried here:

  * **This is coincident, not leading.** The pizza spikes before the operation;
    a mükerrer *is* the decision being enacted. It tells a reader something
    urgent just happened, not that something is about to.
  * **A mükerrer is not automatically a crisis.** Of the three published in the
    150 days to 28 Aug 2026, two were routine (public-sector bonus timing,
    salaries for staff posted abroad) and one moved markets (ÖTV rates on fuel
    and tobacco, effective the same day so nobody could stockpile at the old
    price). It is the rate-change case that earns this gauge its place on a
    trading terminal.
  * **It fires rarely.** Three in 150 days. On its own the mükerrer would leave
    the needle pinned at "quiet" for months, which is why it is a flag on top of
    two continuous readings rather than a component of the average.

Structurally this mirrors `services/pentagon_pizza_service.py` exactly — the
same ratio-to-own-baseline scoring, the same median, the same
`insufficient_data` / `unavailable` refusals, the same stale replay — so the
badge, the panel and the reader's expectations all transfer.
"""

from __future__ import annotations

import asyncio
import logging
import re
import statistics
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from services.bist.gov_tls import gov_ssl_context
from services.cache import home_cache
from services.http_client import get_text

logger = logging.getLogger(__name__)

GAZETTE_HOME = "https://www.resmigazete.gov.tr/"
GAZETTE_INDEX = "https://www.resmigazete.gov.tr/fihrist?tarih={day}"
PRESIDENCY_NEWS = "https://www.tccb.gov.tr/haberler/"

SOURCE_NAME = "resmigazete.gov.tr · tccb.gov.tr"
SOURCE_URL = "https://www.resmigazete.gov.tr/"

CACHE_KEY = "bist_night_shift_index"
# The Gazette publishes once a day and the presidency feed a handful of times.
# Anything faster re-reads the same day at the cost of sixteen requests to a
# government host that owes this project nothing.
TTL_SECONDS = 3600
MAX_STALE_SECONDS = 12 * 3600

# Ankara. The Gazette's day boundary is local, and reading a UTC "today" against
# it would shift the whole comparison by three hours — which yields a plausible
# reading that is quietly about yesterday.
TZ = ZoneInfo("Europe/Istanbul")

# How much history the baselines are drawn from. Fourteen days spans two of
# every weekday, which is what the measured weekday/weekend gap (median 7.5 vs
# 6.0 items) needs to average out without a day-of-week model.
BASELINE_DAYS = 14

# Trailing window for the executive-decision reading. A single day carries the
# section or it does not, and a 0/1 series has no baseline to speak of; counted
# over a week it becomes a rate that does.
KARAR_WINDOW = 7

# Trailing window for the announcement reading, and the reason it is not one
# day. The presidency publishes through the day, so "today" is a partial count
# until the evening and scoring it against complete days reads every morning as
# quiet. Three days also survives the feed's own gaps — it carries nothing at
# all on roughly half the days in a fortnight, and a component that reports 0.0x
# on every one of those is describing the calendar rather than the state.
DUYURU_WINDOW = 3

# Ratios clamp here, mirroring `RATIO_CAP` in the pizza service. A day with five
# times the usual legislative volume is already the strongest thing this scale
# can say.
RATIO_CAP = 4.0

# Below this a baseline is too small to divide by: the difference between two
# and four items a day is noise, but as a denominator it is the difference
# between 5x and 2.5x.
MIN_BASELINE = 2.0

# Fewer than this and there is no index, only a reading.
MIN_SOURCES = 2

THRESHOLD_QUIET = 0.7
THRESHOLD_ELEVATED = 1.3
THRESHOLD_SPIKE = 2.0

STATUS_LABELS = {
    "quiet": "Her zamankinden sakin",
    "normal": "Normal",
    "elevated": "Normalin üstünde",
    "spike": "Olağandışı yoğun",
    "insufficient_data": "Ölçüm için yeterli kaynak yok",
    "unavailable": "Kaynaklara ulaşılamadı",
}

# Item links in a day's index carry the edition's date and a sequence number.
# A mükerrer edition's files carry an `M1` before the dash, which is what keeps
# the two from being counted together.
_ITEM = re.compile(r"eskiler/\d{4}/\d{2}/\d{8}-(\d+)")
# The home page links its most recent extra edition. One request, no probing.
_LAST_MUKERRER = re.compile(r"/fihrist\?tarih=(\d{4}-\d{2}-\d{2})&(?:amp;)?mukerrer=(\d+)")
_KARAR_SECTION = re.compile(r"CUMHURBA[SŞ]KANI KARAR", re.IGNORECASE)
_PRESIDENCY_DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")

# The Gazette index is ~80 KB and the presidency feed ~60 KB. Generous rather
# than tight: a truncated body loses items from the tail, and a silently smaller
# count is exactly the failure the baselines cannot see.
MAX_PAGE_BYTES = 4_000_000

# The Gazette's index route answers a default client with a read timeout and a
# browser with a page. The home page does not care, but `/fihrist` does, and a
# fourteen-day baseline is fourteen of those.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9",
}


async def _fetch(url: str) -> str:
    """One page, with the chain completed and a header set these hosts answer."""
    return await get_text(
        url,
        headers=_BROWSER_HEADERS,
        max_bytes=MAX_PAGE_BYTES,
        verify=gov_ssl_context(),
    )


class NightShiftUnavailable(Exception):
    """Neither source could be read, or carried nothing recognisable."""


# ── Parsing ─────────────────────────────────────────────────────────────────


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def parse_gazette_day(html: str) -> dict[str, Any]:
    """
    One day's edition: how many items it carried, and whether it carried a
    Cumhurbaşkanı Kararı section.

    Items are counted by distinct sequence number rather than by link, because
    the index lists most of them twice — once as a PDF and once as HTML.
    """
    return {
        "items": len(set(_ITEM.findall(html))),
        "karar": bool(_KARAR_SECTION.search(_strip_tags(html))),
    }


def parse_last_mukerrer(html: str) -> Optional[date]:
    """The date of the most recent extra edition, or None if none is linked."""
    matches = _LAST_MUKERRER.findall(html)
    days: list[date] = []
    for raw, _ in matches:
        try:
            days.append(date.fromisoformat(raw))
        except ValueError:
            continue
    return max(days) if days else None


def parse_presidency(html: str) -> dict[str, int]:
    """
    Announcements per day from the presidency's news feed.

    The feed carries about forty items spanning three weeks, which is both the
    reading and its own baseline in a single request.
    """
    counts: dict[str, int] = {}
    for day, month, year in _PRESIDENCY_DATE.findall(html):
        try:
            key = date(int(year), int(month), int(day)).isoformat()
        except ValueError:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


# ── Scoring ─────────────────────────────────────────────────────────────────


def _ratio(value: float, baseline: float) -> Optional[float]:
    if baseline < MIN_BASELINE:
        return None
    return min(RATIO_CAP, value / baseline)


def _median(values: list[float]) -> Optional[float]:
    return statistics.median(values) if values else None


def _classify(index: Optional[float], used: int, *, mukerrer_today: bool) -> str:
    if index is None or used < MIN_SOURCES:
        return "insufficient_data"
    if index >= THRESHOLD_SPIKE:
        return "spike"
    # An extra edition floors the reading. The volume components can sit at
    # normal on a day the state published something it could not hold until
    # tomorrow, and a gauge that called that day "normal" would be answering a
    # question nobody asked.
    if mukerrer_today or index >= THRESHOLD_ELEVATED:
        return "elevated"
    if index <= THRESHOLD_QUIET:
        return "quiet"
    return "normal"


def score(
    gazette: dict[str, dict[str, Any]],
    presidency: dict[str, int],
    last_mukerrer: Optional[date],
    *,
    today: date,
) -> dict[str, Any]:
    """
    The full payload from parsed sources.

    `today` is injectable so the tests can score a fixture against the day it
    was captured on, the same reason the pizza service takes `now`.
    """
    days = [today - timedelta(days=i) for i in range(BASELINE_DAYS)]
    keys = [d.isoformat() for d in days]

    items = {k: gazette[k]["items"] for k in keys if k in gazette}
    karar = {k: gazette[k]["karar"] for k in keys if k in gazette}

    sources: list[dict[str, Any]] = []

    # 1. Legislative volume — the day's item count against its own fortnight.
    history_items = [float(v) for k, v in items.items() if k != keys[0]]
    if keys[0] in items and history_items:
        baseline = _median(history_items) or 0.0
        sources.append(
            _source(
                "mevzuat",
                "Mevzuat hacmi",
                float(items[keys[0]]),
                baseline,
                f"{items[keys[0]]} madde · olağan {baseline:.0f}",
                [(k, _ratio(float(v), baseline)) for k, v in sorted(items.items())],
            )
        )

    # 2. Executive decisions — days carrying one, over a week, against the
    #    fortnight's own rate for the same window length.
    recent = [karar[k] for k in keys[:KARAR_WINDOW] if k in karar]
    older = [karar[k] for k in keys[KARAR_WINDOW:] if k in karar]
    if len(recent) >= 3 and len(older) >= 3:
        rate = sum(older) / len(older) * len(recent)
        count = float(sum(recent))
        sources.append(
            _source(
                "karar",
                "Cumhurbaşkanı kararı",
                count,
                rate,
                f"son {len(recent)} günde {int(count)} gün · olağan {rate:.1f}",
                [(k, 1.0 if karar[k] else 0.0) for k in sorted(karar)],
            )
        )

    # 3. Presidency announcements — a trailing few days against the feed's own
    #    daily rate. Counted over a window rather than on the day for the reason
    #    `DUYURU_WINDOW` gives.
    #
    #    The window is the fortnight this whole reading is scored against, and
    #    it is fixed rather than derived from the feed's own extent. The page
    #    carries a stray date in its furniture — a 2014 line under forty items
    #    from the last three weeks — and measuring the span between the oldest
    #    and newest date it mentions stretched the denominator over twelve
    #    years, which drove every ratio to zero.
    #    The sparkline is scored on that same rolling window, not day by day.
    #    Scoring it per day contradicted the paragraph above twice over. It
    #    divided by the *daily* rate, which for this feed is around one and
    #    therefore below `MIN_BASELINE` — so every bar came back unmeasured and
    #    the row rendered with an empty grid beside a live 2.0x. And even where
    #    the arithmetic had worked, a bar would have been measuring something
    #    the number next to it was not.
    counts = {k: presidency.get(k, 0) for k in keys}
    if any(counts.values()):
        per_day = sum(counts.values()) / BASELINE_DAYS
        baseline = per_day * DUYURU_WINDOW
        recent = sum(counts[k] for k in keys[:DUYURU_WINDOW])
        # Zero-filled rather than restricted to the days the feed carried
        # something: a silent day is a nought inside the window, and dropping it
        # both shortens the row and overstates every window that spans it.
        #
        # The oldest `DUYURU_WINDOW - 1` days score as None because their window
        # runs off the end of the fortnight. A partial window would read as a
        # quiet stretch that never happened.
        rolling = [
            (
                key,
                _ratio(float(sum(counts[k] for k in keys[i : i + DUYURU_WINDOW])), baseline)
                if i + DUYURU_WINDOW <= len(keys)
                else None,
            )
            for i, key in enumerate(keys)
        ]
        sources.append(
            _source(
                "duyuru",
                "Cumhurbaşkanlığı duyurusu",
                float(recent),
                baseline,
                f"son {DUYURU_WINDOW} günde {recent} · olağan {baseline:.1f}",
                sorted(rolling, key=lambda pair: pair[0]),
            )
        )

    ratios = [s["ratio"] for s in sources if s["ratio"] is not None]
    index = _median(ratios)
    mukerrer_today = last_mukerrer == today
    status = _classify(index, len(ratios), mukerrer_today=mukerrer_today)

    # A refused reading carries no number. One source's ratio is a fact about
    # that source, not an index, and letting it through as `index` would render
    # in the badge as a measurement the panel below then says was not taken.
    if status == "insufficient_data":
        index = None

    return {
        "index": round(index, 2) if index is not None else None,
        "status": status,
        "label": STATUS_LABELS[status],
        "sources_used": len(ratios),
        "sources_total": len(sources),
        "sources": sources,
        "history": _history(sources, keys),
        "last_mukerrer": last_mukerrer.isoformat() if last_mukerrer else None,
        "days_since_mukerrer": (today - last_mukerrer).days if last_mukerrer else None,
        "mukerrer_today": mukerrer_today,
        "as_of": datetime.now(UTC).isoformat(),
        "stale": False,
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
    }


def _source(
    key: str,
    name: str,
    value: float,
    baseline: float,
    detail: str,
    history: list[tuple[str, Optional[float]]],
) -> dict[str, Any]:
    ratio = _ratio(value, baseline)
    return {
        "key": key,
        "name": name,
        "value": value,
        "baseline": round(baseline, 2),
        "ratio": round(ratio, 2) if ratio is not None else None,
        "detail": detail,
        "history": [
            {"day": day, "ratio": round(r, 2) if r is not None else None} for day, r in history
        ],
    }


def _history(sources: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    """
    The shared day grid every source's own bars are drawn on.

    Built from the sources rather than recomputed, so a day the panel stacks can
    never line up against a different day in the row above it.
    """
    grid: list[dict[str, Any]] = []
    for day in sorted(keys):
        ratios: list[float] = []
        for source in sources:
            for row in source["history"]:
                if row["day"] == day and row["ratio"] is not None:
                    ratios.append(row["ratio"])
        median = _median(ratios)
        grid.append(
            {
                "day": day,
                "index": round(median, 2) if median is not None else None,
                "sources_used": len(ratios),
            }
        )
    return grid


# ── Fetch ───────────────────────────────────────────────────────────────────


async def _gazette_day(day: date) -> tuple[str, Optional[dict[str, Any]]]:
    key = day.isoformat()
    try:
        html = await _fetch(GAZETTE_INDEX.format(day=key))
    except Exception as e:
        logger.debug("[NightShift] gazette %s unavailable: %s", key, e)
        return key, None
    return key, parse_gazette_day(html)


async def _fetch_and_score() -> dict[str, Any]:
    today = datetime.now(TZ).date()
    days = [today - timedelta(days=i) for i in range(BASELINE_DAYS)]

    home_task = _fetch(GAZETTE_HOME)
    news_task = _fetch(PRESIDENCY_NEWS)
    results = await asyncio.gather(
        home_task, news_task, *(_gazette_day(day) for day in days), return_exceptions=True
    )

    home_html, news_html, day_results = results[0], results[1], results[2:]

    last_mukerrer = parse_last_mukerrer(home_html) if isinstance(home_html, str) else None
    presidency = parse_presidency(news_html) if isinstance(news_html, str) else {}
    gazette = {
        key: parsed
        for item in day_results
        if isinstance(item, tuple)
        for key, parsed in [item]
        if parsed is not None
    }

    if not gazette and not presidency:
        # Both hosts unreachable. Treated as an outage rather than as a quiet
        # day, which is the same distinction the pizza service draws between
        # "the venues are shut" and "we could not see them".
        raise NightShiftUnavailable("neither source could be read")

    return score(gazette, presidency, last_mukerrer, today=today)


def _unavailable() -> dict[str, Any]:
    return {
        "index": None,
        "status": "unavailable",
        "label": STATUS_LABELS["unavailable"],
        "sources_used": 0,
        "sources_total": 0,
        "sources": [],
        "history": [],
        "last_mukerrer": None,
        "days_since_mukerrer": None,
        "mukerrer_today": False,
        "as_of": datetime.now(UTC).isoformat(),
        "stale": False,
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
    }


async def fetch_night_shift_index() -> dict[str, Any]:
    """
    The index, cached and stale-tolerant.

    Never raises, for the reason the pizza endpoint never raises: this is a
    novelty gauge in the chrome of every BIST page, and a government site that
    stopped answering must not be able to take those pages down with it.
    """
    cached = home_cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    try:
        payload = await _fetch_and_score()
    except Exception as e:
        logger.warning("Gece Mesaisi Endeksi unavailable: %s", e)
        stale = home_cache.get_with_fallback(CACHE_KEY, max_age=MAX_STALE_SECONDS)
        if stale is not None:
            return {**stale, "stale": True}
        return _unavailable()

    home_cache.set(CACHE_KEY, payload, TTL_SECONDS)
    return payload
