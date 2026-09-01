"""
The KAP disclosure tape.

KAP — Kamuyu Aydınlatma Platformu — is where every material fact about a listed
Turkish company appears first, which makes it the closest thing this realm has
to a primary source.

**How this reads it, and why not the obvious way.** The *disclosure tape* has no
usable public API. The documented endpoints were retired with the 2026 rewrite;
the query page is a React Server Component app that streams its rows rather than
fetching JSON, so there is no XHR to call and rendering it in a browser produces
a page with no rows until a form is submitted. Six approaches were tried before
this one.

That is true of the tape and not of KAP as a whole: the *fund* surface on the
same host does have a queryable JSON API, and `services/bist/kap_fund_client.py`
uses it to reach a fund's monthly portfolio report. If the tape ever needs
revisiting, start by checking whether it grew an equivalent.

What does work: every disclosure has a **detail page that is server-rendered**,
at `/tr/Bildirim/<index>`, and the page embeds the disclosure as a flat JSON
object in its streamed payload. The indices are sequential integers.

That turns the feed into a cursor problem rather than a scraping problem, and it
has a property worth exploiting: **a published disclosure never changes.** Index
1655377 will say the same thing forever. So each one is cached permanently and
the service only ever fetches indices it has not seen — the steady-state cost of
the tape is the handful of filings published since the last poll, not the window.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

from services.bist.text import fold
from services.cache import bist_cache
from services.http_client import get_text_impersonated

logger = logging.getLogger(__name__)

BASE = "https://www.kap.org.tr/tr/Bildirim"

# The head moves by a few hundred a day. Two minutes keeps the tape live without
# probing on every reader's refresh.
TTL_HEAD = 2 * 60
TTL_TAPE = 2 * 60
# A disclosure is immutable once filed, so its page is cached for a week — long
# enough that a day of scrolling never refetches, short enough to bound memory.
TTL_ITEM = 7 * 24 * 60 * 60
MAX_STALE_TAPE = 24 * 60 * 60

# KAP rate-limits, and it does so by returning 429 rather than by slowing down.
# Two at a time with a pause between batches is what stays under it; six tripped
# the limiter within a few hundred requests during development and then every
# subsequent read failed for minutes.
#
# The pause is a second rather than the third it started as. Two at a time every
# 350ms is close to six a second, and it turned out to trip the limiter too —
# not in a burst, but over a long walk. A slower cold start costs a background
# task another minute; tripping the limiter costs the tape an hour, and takes
# kap.org.tr down for whoever is sitting at the browser on the same address.
CONCURRENCY = 2
BATCH_PAUSE_S = 1.0

# How long to stop asking after a 429, and how far that grows.
#
# Escalating rather than fixed. KAP holds a blocked address for far longer than
# the two flat minutes this used to wait, so the retry walked straight back into
# the block and re-armed it — an afternoon of that left the tape stuck at nine
# filings while every read still answered in a millisecond and looked healthy.
# Each consecutive 429 doubles the pause up to the cap; the first page that
# comes back clears it.
RATE_LIMIT_BACKOFF_S = 120
RATE_LIMIT_BACKOFF_MAX_S = 30 * 60
BACKOFF_LEVEL_KEY = "kap:backoff-level"

# How far past the last known head to look for new filings. Comfortably more
# than a day's volume, so a terminal left closed overnight still catches up in
# one pass.
HEAD_PROBE_SPAN = 4000

# Cold-start bounds for the binary search. The lower bound is a known-good index
# and the upper is far past any plausible present one.
_SEARCH_FLOOR = 1_500_000
_SEARCH_CEILING = 2_400_000

DISCLOSURE_CATEGORIES = {
    "ODA": "Özel durum açıklaması",
    "FR": "Finansal rapor",
    "DG": "Diğer",
    "FON": "Fon bildirimi",
    "DUY": "Duyuru",
}


class KapUnavailable(RuntimeError):
    """KAP did not answer, or answered with nothing parseable."""


@dataclass(frozen=True)
class Disclosure:
    index: int
    title: str
    company: str
    ticker: str
    category: str
    category_label: str
    published_at: Optional[str]
    """ISO 8601. None when KAP's own timestamp could not be read."""
    summary: str
    is_late: bool
    url: str


def _unescape(raw: str) -> str:
    """
    The payload arrives escaped inside a streamed script chunk.

    Only the quote escaping matters for field extraction; the rest of the
    stream is left alone rather than run through a full JSON decoder, which
    would need the chunk boundaries this deliberately does not model.
    """
    return raw.replace('\\"', '"')


def _field(text: str, name: str) -> Optional[str]:
    match = re.search(rf'"{name}":"(.*?)"', text)
    return match.group(1) if match else None


def _parse_published(raw: Optional[str]) -> Optional[str]:
    """KAP's `2026.08.27 15:06:10` as ISO 8601, or None."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y.%m.%d %H:%M:%S").isoformat()
    except ValueError:
        return None


def parse_disclosure(html: str, index: int) -> Optional[Disclosure]:
    """
    One disclosure out of its detail page, or None if the page is not one.

    Returns None rather than raising for a missing or withdrawn index: the tape
    walks a range of integers and gaps in it are ordinary, not errors.
    """
    text = _unescape(html)
    if f'"disclosureIndex":{index}' not in text:
        return None

    # Narrow to the object before reading fields. The streamed payload carries
    # several other records — the company's own metadata, the sector list — and
    # a whole-document search for `"title"` finds the wrong one.
    anchor = text.index(f'"disclosureIndex":{index}')
    start = text.rfind('{"title":"', 0, anchor)
    if start == -1:
        start = max(0, anchor - 2000)
    window = text[start : anchor + 2000]

    title = _field(window, "title") or ""
    company = _field(window, "companyTitle") or ""
    if not title and not company:
        return None

    category = (_field(window, "disclosureCategory") or "").upper()
    return Disclosure(
        index=index,
        title=title,
        company=company,
        ticker=(_field(window, "stockCode") or "").strip().upper(),
        category=category,
        category_label=DISCLOSURE_CATEGORIES.get(category, category or "Bildirim"),
        published_at=_parse_published(_field(window, "publishDate")),
        summary=(_field(window, "summary") or "").strip(),
        is_late='"isLate":true' in window,
        url=f"{BASE}/{index}",
    )


def _rate_limited() -> bool:
    return bist_cache.is_valid("kap:backoff")


def is_rate_limited() -> bool:
    """
    Whether KAP is currently refusing this address.

    Served alongside the tape so a throttled feed reads as throttled rather than
    as a quiet market. Nine filings under "Tümü" is a alarming number or a
    boring one depending entirely on this flag, and the board cannot tell.
    """
    return _rate_limited()


def _note_rate_limit() -> None:
    """Arm the pause, longer each time the block is still there when it lifts."""
    level = (bist_cache.get(BACKOFF_LEVEL_KEY) or 0) + 1
    pause = min(RATE_LIMIT_BACKOFF_S * 2 ** (level - 1), RATE_LIMIT_BACKOFF_MAX_S)
    bist_cache.set("kap:backoff", True, int(pause))
    # The level deliberately outlives the pause it set, so the 429 that greets
    # the first retry reads as an escalation rather than a fresh first offence.
    bist_cache.set(BACKOFF_LEVEL_KEY, level, int(pause * 4))
    logger.warning("KAP rate-limited; backing off for %ss (attempt %s)", int(pause), level)


def _note_rate_limit_cleared() -> None:
    """A page came back, so the next 429 starts counting from one again."""
    if bist_cache.get(BACKOFF_LEVEL_KEY) is not None:
        bist_cache.invalidate(BACKOFF_LEVEL_KEY)


def _is_rate_limit(error: Exception) -> bool:
    return "429" in str(error) or "Request Limit" in str(error)


async def _fetch_one(index: int) -> Optional[Disclosure]:
    """
    One disclosure, from cache when it has ever been seen.

    The distinction between the two failure modes here is load-bearing. A page
    that parses to nothing is a **gap** — a withdrawn or non-public index — and
    is tombstoned so the tape never asks for it again. A page that could not be
    *read* is a **transport failure**, and tombstoning that would blank out a
    real disclosure for a week.

    The first version did not draw that line, and a burst of 429s during
    development silently marked several hundred live filings as permanently
    missing. Cache only what the upstream actually told us.
    """
    key = f"kap:{index}"
    cached = bist_cache.get(key)
    if cached is not None:
        return cached or None

    if _rate_limited():
        return None

    try:
        html = await get_text_impersonated(f"{BASE}/{index}", timeout=20.0)
    except Exception as e:  # noqa: BLE001
        if _is_rate_limit(e):
            _note_rate_limit()
        else:
            logger.debug("KAP %s unreadable: %s", index, e)
        # Deliberately not cached: this says nothing about whether the
        # disclosure exists.
        return None

    _note_rate_limit_cleared()
    disclosure = parse_disclosure(html, index)
    bist_cache.set(key, disclosure or False, TTL_ITEM)
    return disclosure


async def _exists(index: int) -> bool:
    return await _fetch_one(index) is not None


async def find_head() -> int:
    """
    The highest disclosure index KAP will currently serve.

    Two strategies. On a cold start it binary-searches a wide range, which costs
    about twenty requests. Afterwards it walks forward from the last known head,
    which costs one request per new filing — the whole reason the head is cached
    separately from the tape.
    """
    cached = bist_cache.get("kap:head")
    if cached is not None:
        return cached

    previous = bist_cache.get_with_fallback("kap:head", max_age=MAX_STALE_TAPE)
    if previous is not None:
        head = await _walk_forward(previous)
    else:
        head = await _binary_search()

    if head is None:
        stale = bist_cache.get_with_fallback("kap:head", max_age=MAX_STALE_TAPE)
        if stale is not None:
            return stale
        raise KapUnavailable("could not locate the current KAP disclosure index")

    bist_cache.set("kap:head", head, TTL_HEAD)
    return head


async def _walk_forward(known: int) -> Optional[int]:
    """
    Step forward from a known-good index in blocks.

    Blocks rather than one at a time: KAP leaves gaps, so a single miss is not
    the end of the feed. A whole block of misses is.
    """
    head = known
    step = 64
    while head - known < HEAD_PROBE_SPAN:
        candidates = list(range(head + 1, head + 1 + step))
        results = await _gather(candidates)
        found = [d.index for d in results if d is not None]
        if not found:
            return head
        head = max(found)
    return head


async def _binary_search() -> Optional[int]:
    low, high = _SEARCH_FLOOR, _SEARCH_CEILING
    if not await _exists(low):
        return None
    while low + 1 < high:
        middle = (low + high) // 2
        if await _exists(middle):
            low = middle
        else:
            high = middle
    return low


async def _gather(indices: list[int]) -> list[Optional[Disclosure]]:
    """
    Fetch a set of indices in small batches, pausing between them.

    Indices already in cache cost nothing, so the pause only applies to batches
    that actually went to the network — which is what keeps a warm tape instant
    while a cold one stays polite.
    """
    results: list[Optional[Disclosure]] = []
    for start in range(0, len(indices), CONCURRENCY):
        chunk = indices[start : start + CONCURRENCY]
        needed_network = any(bist_cache.get(f"kap:{index}") is None for index in chunk)
        results.extend(await asyncio.gather(*(_fetch_one(index) for index in chunk)))
        if needed_network and start + CONCURRENCY < len(indices):
            if _rate_limited():
                # No point walking the rest of the window into a closed door.
                break
            await asyncio.sleep(BATCH_PAUSE_S)
    return results


# What a reader means by "the tape".
#
# Roughly nine filings in ten are fund housekeeping — a portfolio manager
# reporting an overnight repo, the same notice from forty funds at 15:02. They
# are genuine disclosures and they are also noise in front of the two categories
# somebody watching a company actually wants. The default excludes them; asking
# for FON explicitly still works.
SIGNAL_CATEGORIES = frozenset({"ODA", "FR", "DUY"})


# The rolling buffer.
#
# KAP rate-limits, so the tape cannot be "fetch the last N indices" on every
# read — that is a few hundred requests a minute against a host that answers
# 429. Instead the parsed rows are kept in one cache entry and each refresh
# fetches only the indices above the highest one already held. A cold start
# pays for the window once; every read after that costs one request per filing
# actually published since.
BUFFER_KEY = "kap:rows"
BUFFER_LIMIT = 600
COLD_START_SPAN = 150
TTL_BUFFER = 24 * 60 * 60


# Surviving a restart.
#
# `bist_cache` is per-process, so without this every restart threw away the
# whole window and the next reader paid a cold start — a binary search for the
# head plus a hundred and fifty pages, two at a time, against a host that
# answers 429. In development, where the server reloads on every save, that was
# most reads. A filed disclosure never changes, so the window is safe to write
# down and read back; only its *age* matters, and that is bounded exactly as the
# in-memory fallback is.
TAPE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "kap_tape.json",
)

_disk_read = False


def _read_tape_file() -> list[Disclosure]:
    """The last written window, or nothing if it is missing, stale or unreadable."""
    try:
        with open(TAPE_FILE) as handle:
            payload = json.load(handle)
        if time.time() - float(payload["stored_at"]) > MAX_STALE_TAPE:
            return []
        return [Disclosure(**row) for row in payload["rows"]]
    except FileNotFoundError:
        return []
    except Exception as e:  # noqa: BLE001
        # A truncated or reshaped file is not worth failing a read over; the
        # tape simply pays the cold start it would have paid anyway.
        logger.warning("KAP tape file unreadable, ignoring it: %s", e)
        return []


def _write_tape_file(rows: list[Disclosure]) -> None:
    try:
        os.makedirs(os.path.dirname(TAPE_FILE), exist_ok=True)
        temp = f"{TAPE_FILE}.tmp"
        with open(temp, "w") as handle:
            json.dump({"stored_at": time.time(), "rows": [asdict(d) for d in rows]}, handle)
        os.replace(temp, TAPE_FILE)
    except Exception as e:  # noqa: BLE001
        logger.warning("KAP tape file could not be written: %s", e)


def _held_rows() -> list[Disclosure]:
    """
    The buffer, hydrating from disk the first time this process asks for it.

    Seeding `kap:head` from the highest index read back matters as much as the
    rows do: it is known-good, so `find_head` walks forward from it instead of
    binary-searching for it, which is twenty requests saved on every restart.
    """
    global _disk_read
    rows: list[Disclosure] = bist_cache.get_with_fallback(BUFFER_KEY, max_age=MAX_STALE_TAPE) or []
    if rows or _disk_read:
        return rows

    _disk_read = True
    rows = _read_tape_file()
    if rows:
        bist_cache.set(BUFFER_KEY, rows, TTL_BUFFER)
        bist_cache.set("kap:head", max(d.index for d in rows), TTL_HEAD)
        logger.info("KAP tape restored from disk: %d filings", len(rows))
    return rows


async def _refresh_buffer() -> list[Disclosure]:
    """Bring the rolling buffer up to the current head and return it."""
    held: list[Disclosure] = _held_rows()

    try:
        head = await find_head()
    except KapUnavailable:
        if held:
            return held
        raise

    # What is missing from the newest span, rather than only what is newer than
    # the top of the buffer.
    #
    # "Everything above the highest index held" is the obvious rule and it
    # strands a partial window: a restore of nine rows whose top happens to be
    # the current head asks for nothing and stays nine rows forever. The span
    # between the lowest and highest index held has already been walked, so a
    # miss inside it is a disclosure that was withdrawn or never public — asking
    # again would spend a request to be told the same thing. Everything else in
    # the newest span is genuinely unseen.
    #
    # Bounded by `COLD_START_SPAN` so a terminal opened after a long gap does not
    # try to walk ten thousand indices in one request.
    held_indices = {d.index for d in held}
    walked = range(min(held_indices, default=1), max(held_indices, default=0) + 1)
    wanted = [
        index
        for index in range(head, max(head - COLD_START_SPAN, 0), -1)
        if index not in held_indices and index not in walked
    ]

    if wanted:
        fetched = [d for d in await _gather(wanted) if d is not None]
        held = fetched + held

    # Deduplicate on index and keep the newest slice.
    seen: dict[int, Disclosure] = {}
    for item in held:
        seen.setdefault(item.index, item)
    rows = sorted(seen.values(), key=lambda d: d.index, reverse=True)[:BUFFER_LIMIT]

    if rows:
        bist_cache.set(BUFFER_KEY, rows, TTL_BUFFER)
        _write_tape_file(rows)
    return rows


# Refreshing off the read path.
#
# `_refresh_buffer` walks from the highest index held up to the current head,
# and during a busy session that is a hundred-odd rate-limited requests at two
# at a time — tens of seconds. Paying for it inside a reader's request meant the
# KAP tab spun on every open that followed two idle minutes, because the poll
# that had been keeping the tape warm stops the moment the tab is unmounted.
#
# The buffer already holds up to 600 parsed filings and a disclosure never
# changes once filed, so the worst a stale read costs is the handful published
# in the last couple of minutes. Serve those 600 now, catch up behind.
_refresh_task: Optional[asyncio.Task] = None


def _schedule_refresh() -> None:
    """Start a background catch-up unless one is already in the air."""
    global _refresh_task
    # The handle is the stampede guard as much as it is a strong reference:
    # `asyncio` only holds a weak one, so a task nobody keeps can be collected
    # mid-walk, and without the guard every reader in the stale window would
    # start a second walk over the same indices.
    if _refresh_task is not None and not _refresh_task.done():
        return
    _refresh_task = asyncio.create_task(_refresh_quietly())


async def _refresh_quietly() -> None:
    """
    A catch-up whose failure is nobody's error.

    The reader that scheduled this was already served from the buffer, so an
    outage here means the next read is slightly staler — not that anything
    broke. `kap:fresh` is stamped only on success, which is what makes the
    following read try again rather than sit out the whole TTL on a failure.
    """
    try:
        await _refresh_buffer()
    except Exception as e:  # noqa: BLE001
        logger.warning("KAP background refresh failed: %s", e)
        return
    bist_cache.set("kap:fresh", True, TTL_TAPE)


async def fetch_tape(
    limit: int = 40,
    *,
    ticker: Optional[str] = None,
    categories: Optional[frozenset[str]] = None,
) -> list[Disclosure]:
    """
    The most recent disclosures, newest first.

    Filters are applied to the buffer rather than pushed upstream, because there
    is no upstream to push them to — the tape is a range of integers.

    `categories` defaults to `SIGNAL_CATEGORIES`. Pass an empty frozenset for
    everything, including the fund repo notices.
    """
    wanted_categories = SIGNAL_CATEGORIES if categories is None else categories

    rows = _held_rows()

    if bist_cache.get("kap:fresh") is None:
        if rows:
            _schedule_refresh()
        else:
            # Nothing in memory and nothing on disk, so there is nothing to
            # serve and no choice but to wait — a first run, or a machine that
            # was off for longer than the stale bound.
            rows = await _refresh_buffer()
            bist_cache.set("kap:fresh", True, TTL_TAPE)

    if ticker:
        wanted = ticker.strip().upper()
        if ":" in wanted:
            wanted = wanted.rsplit(":", 1)[1]
        rows = [d for d in rows if d.ticker == wanted]
    if wanted_categories:
        rows = [d for d in rows if d.category in wanted_categories]

    return sorted(rows, key=lambda d: d.index, reverse=True)[:limit]


# ── Trading restrictions ───────────────────────────────────────────────────
# VBTS — the Volatility Based Measures System — and the rest of the exchange's
# own notices arrive through KAP as ordinary disclosures rather than through a
# feed of their own. A short-selling ban, a gross-settlement measure or a
# circuit breaker is filed under `ODA` with a recognisable title, so the radar
# is a title filter over the tape rather than a separate source.
#
# Matched on the title because the summary is often empty for exchange notices
# and the body is an attachment. Substrings rather than a regex: these are
# Borsa İstanbul's own fixed phrasings and they do not vary.
RESTRICTION_PHRASES: tuple[str, ...] = (
    "Devre Kesici",
    "Tedbir",
    "Açığa Satış",
    "Kredili İşlem",
    "Brüt Takas",
    "Özsermaye Hallerine",
    "VBTS",
    "İşlem Sırası",
    "Sıra Kapatma",
    "Fiyat Limiti",
)


def is_restriction(disclosure: Disclosure) -> bool:
    """Whether a disclosure is an exchange measure rather than company news."""
    haystack = fold(f"{disclosure.title} {disclosure.summary}")
    return any(fold(phrase) in haystack for phrase in RESTRICTION_PHRASES)


def filter_restrictions(disclosures: list[Disclosure]) -> list[Disclosure]:
    return [d for d in disclosures if is_restriction(d)]
