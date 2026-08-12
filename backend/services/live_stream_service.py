"""
Live broadcast probe.

Answers one question per curated channel: is it on air right now, and on which
video? YouTube's Data API would answer it directly, but a `search.list` call
costs 100 of the 10,000 quota units a free key gets per day — polling a dozen
channels on any useful cadence would burn a day's quota before lunch. So this
reads the public `/channel/<id>/live` page instead, which needs no key and no
quota.

That page is unambiguous about the answer. When the channel is live YouTube
serves the broadcast there and the canonical link becomes a `watch?v=` URL; when
it is not, the canonical link stays on the channel itself. The player payload's
`"isLive":true` marker is required as well, so a channel that merely has a
recently-ended stream to redirect to does not read as on air.

Two things about the probe are worth knowing before changing it:

* **The page is ~1.2 MB and the markers sit around 700 KB in**, so most of it
  has to come down. A `Range` request does not help — YouTube answers it 200
  with the whole document — and streaming can only cut the tail. That cost is
  what splits the channel list into two cadences below.
* **Being live is not the same as being newsworthy.** Bloomberg, Reuters, CNBC
  and Yahoo run rolling 24/7 streams; the White House, the Fed and the ECB go
  live only when something is happening. Nothing here decides that a broadcast
  matters — it reports what is on air and lets `live_events_service` judge.
"""

import asyncio
import html
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from services import http_client
from services.cache import market_cache
from services.home_service import UpstreamUnavailable

logger = logging.getLogger(__name__)

EVENT_KEY = "live_streams_event"
MARKET_KEY = "live_streams_market"

# The two cadences the channel split exists to buy. An event channel going live
# *is* the news, so it is worth checking often; a rolling market channel is
# essentially always live and is only probed to keep its "on air" dot and video
# id honest.
#
# The arithmetic that sets these: one probe pulls ~1.2 MB. Three event channels
# every 3 minutes plus four market channels every 30 minutes is roughly 1,600
# fetches and 2 GB a day. Probing all seven every two minutes would have been
# 6 GB, which is not a reasonable steady state for a terminal left open.
TTL_EVENT_CHANNELS = 180
TTL_MARKET_CHANNELS = 1800
# Past this a probe result describes a broadcast that may well have ended, so it
# stops standing in for the current one.
MAX_STALE_STREAMS = 30 * 60

# The live/offline markers sit around 700 KB into a ~1.2 MB page, so this is
# the smallest cap that still reads them with room to spare. Set it too low and
# the failure is silent: every channel simply reports as never live.
#
# `get_text_impersonated` is passed double this, because `curl_cffi` truncates
# at `max_bytes // 2` rather than at `max_bytes`.
PROBE_MAX_BYTES = 900_000
PROBE_TIMEOUT = 12.0

# YouTube serves a stub to clients that do not look like browsers.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}


@dataclass(frozen=True)
class YouTubeLiveState:
    """What a probe established about one channel."""

    is_live: bool
    video_id: str | None
    title: str | None
    # False when the probe could not read the page at all. Kept separate from
    # `is_live` because "we could not tell" and "the channel is off air" are
    # different claims, and only one of them is safe to render.
    reachable: bool


@dataclass(frozen=True)
class Channel:
    """A broadcaster worth watching, and what its going live tends to mean."""

    key: str
    name: str
    channel_id: str
    # "market" for a rolling news channel, whose being live says nothing. The
    # others name the kind of scheduled event an on-air stream corroborates, and
    # are the only ones `live_events_service` will synthesize an event from.
    implies: str


# Every id below was round-tripped through `feeds/videos.xml?channel_id=` and
# confirmed to name the channel it claims to. This is not paranoia: scraping a
# handle page for a channel id can return a *linked* channel instead of the one
# asked for, and one of these was initially resolved to an unrelated personal
# account that way. An id that names the wrong channel fails silently — it just
# reports never being live — so verify replacements the same way.
CHANNELS: tuple[Channel, ...] = (
    Channel("bloomberg", "Bloomberg TV", "UCIALMKvObZNtJ6AmdCLP7Lg", "market"),
    Channel("reuters", "Reuters", "UChqUTb7kYRX8-EiaN3XFrSQ", "market"),
    Channel("cnbc", "CNBC", "UCvJJ_dzjViJCoLf5uKUTwoA", "market"),
    Channel("yahoo_finance", "Yahoo Finance", "UCEAZeUIeJs0IjQiqTCdVSIg", "market"),
    Channel("whitehouse", "The White House", "UCYxRlFDqcWM4y7FfpiAN3KQ", "political"),
    Channel("fed", "Federal Reserve", "UCAzhpt9DmG6PnHXjmJTvRGQ", "central_bank"),
    Channel("ecb", "European Central Bank", "UCXB8fM4VyQubRu3UVGhd3wA", "central_bank"),
)

EVENT_CHANNELS = tuple(c for c in CHANNELS if c.implies != "market")
MARKET_CHANNELS = tuple(c for c in CHANNELS if c.implies == "market")

_CANONICAL_RE = re.compile(r'<link\s+rel="canonical"\s+href="([^"]+)"')
_TITLE_RE = re.compile(r'<meta\s+name="title"\s+content="([^"]*)"')
_WATCH_RE = re.compile(r"[?&]v=([A-Za-z0-9_-]{6,})")
_LIVE_MARKER = '"isLive":true'

# Serialises cold-start probes so a burst of first requests waits on one pass
# rather than each starting its own.
_probe_lock = asyncio.Lock()


def channel_embed_url(channel_id: str) -> str:
    """
    The channel's current live stream, whatever it happens to be.

    This URL needs no API key and stays valid across broadcasts: YouTube
    resolves it at play time and renders its own "offline" placeholder when the
    channel is not live. It is why a market channel can be probed half-hourly
    and still be playable on demand — the player never needs to know the video
    id, only the probe's "on air" dot does.
    """
    return f"https://www.youtube-nocookie.com/embed/live_stream?channel={channel_id}"


def _offline(channel: Channel, *, probe_failed: bool = False) -> dict[str, Any]:
    return {
        "key": channel.key,
        "name": channel.name,
        "channel_id": channel.channel_id,
        "implies": channel.implies,
        "is_live": False,
        "video_id": None,
        "title": None,
        "watch_url": None,
        "embed_url": channel_embed_url(channel.channel_id),
        "probe_failed": probe_failed,
    }


async def probe_youtube_live(channel_id: str) -> YouTubeLiveState:
    """
    Whether one YouTube channel is on air, and on what.

    Shared with `streamer_service`, which asks the same question of a much
    longer list — hence the streaming fetch. `get_text` stops reading at
    `PROBE_MAX_BYTES`, and since the markers land around 700 KB that genuinely
    saves a quarter of the transfer on every probe; `get_text_impersonated`
    cannot, because `curl_cffi` reads the whole body before it slices.
    Impersonation is kept as the retry for when a plain client gets walled.

    Never raises. `reachable=False` means the probe could not establish
    anything, which is not the same as the channel being offline.
    """
    url = f"https://www.youtube.com/channel/{channel_id}/live"
    body: str | None = None
    try:
        body = await http_client.get_text(
            url, headers=_BROWSER_HEADERS, timeout=PROBE_TIMEOUT, max_bytes=PROBE_MAX_BYTES
        )
    except Exception as exc:  # noqa: BLE001 — fall through to the browser-TLS retry
        logger.debug("Plain live probe failed for %s: %s", channel_id, exc)

    if body is None or _CANONICAL_RE.search(body) is None:
        try:
            body = await http_client.get_text_impersonated(
                url, timeout=PROBE_TIMEOUT, max_bytes=PROBE_MAX_BYTES * 2
            )
        except Exception as exc:  # noqa: BLE001 — one channel must not sink the rest
            logger.warning("Live probe failed for %s: %s", channel_id, exc)
            return YouTubeLiveState(is_live=False, video_id=None, title=None, reachable=False)

    canonical_match = _CANONICAL_RE.search(body)
    watch_match = _WATCH_RE.search(canonical_match.group(1)) if canonical_match else None

    # Both signals are required. The canonical redirect alone also fires for a
    # stream that has just ended, and the marker alone appears on pages that
    # merely reference a live video.
    if watch_match is None or _LIVE_MARKER not in body:
        # A page that came back but named no live video is a real "offline". A
        # page with no canonical link at all is a consent wall or a bot-block,
        # which must not be reported as the channel being off air.
        return YouTubeLiveState(
            is_live=False, video_id=None, title=None, reachable=canonical_match is not None
        )

    title_match = _TITLE_RE.search(body)
    return YouTubeLiveState(
        is_live=True,
        video_id=watch_match.group(1),
        # The meta tag is HTML-escaped, so an ampersand in a stream title would
        # otherwise render as `&amp;`.
        title=html.unescape(title_match.group(1)).strip() if title_match else None,
        reachable=True,
    )


async def _probe(channel: Channel) -> dict[str, Any]:
    """One curated channel's current state, in the shape the Live tab renders."""
    state = await probe_youtube_live(channel.channel_id)
    if not state.is_live or state.video_id is None:
        return _offline(channel, probe_failed=not state.reachable)

    return {
        "key": channel.key,
        "name": channel.name,
        "channel_id": channel.channel_id,
        "implies": channel.implies,
        "is_live": True,
        "video_id": state.video_id,
        "title": state.title,
        "watch_url": f"https://www.youtube.com/watch?v={state.video_id}",
        "embed_url": f"https://www.youtube-nocookie.com/embed/{state.video_id}",
        "probe_failed": False,
    }


async def _probe_group(
    channels: tuple[Channel, ...], cache_key: str, ttl: int, *, force: bool
) -> list[dict[str, Any]]:
    """One cadence's worth of channels, cached under its own key."""
    if not force:
        cached = market_cache.get(cache_key)
        if cached is not None:
            return cached

    results = await asyncio.gather(
        *(_probe(channel) for channel in channels), return_exceptions=True
    )

    states: list[dict[str, Any]] = []
    for channel, result in zip(channels, results):
        if isinstance(result, BaseException):
            logger.warning("Live probe crashed for %s: %s", channel.key, result)
            states.append(_offline(channel, probe_failed=True))
        else:
            states.append(result)

    if all(state["probe_failed"] for state in states):
        # Every channel failing is a block, not seven simultaneous outages.
        # Replaying the last pass is honest; claiming nothing is live is not.
        stale = market_cache.get_with_fallback(cache_key, max_age=MAX_STALE_STREAMS)
        if stale is not None:
            return stale
        return states

    market_cache.set(cache_key, states, ttl)
    return states


async def probe_all(*, force: bool = False) -> dict[str, Any]:
    """
    Every curated channel's current state, each group on its own cadence.

    Raises `UpstreamUnavailable` only when nothing at all could be established —
    a probe that comes back empty must not be presented as "nothing is live",
    which is a claim about the world rather than an absence of information.
    `force` is for the scheduler, which refreshes on its own clock rather than
    on a cache miss.
    """
    async with _probe_lock:
        event_states, market_states = await asyncio.gather(
            _probe_group(EVENT_CHANNELS, EVENT_KEY, TTL_EVENT_CHANNELS, force=force),
            _probe_group(MARKET_CHANNELS, MARKET_KEY, TTL_MARKET_CHANNELS, force=force),
        )

    channels = event_states + market_states
    if all(state["probe_failed"] for state in channels):
        raise UpstreamUnavailable("no broadcast channel could be probed")

    return {
        "channels": channels,
        "as_of": datetime.now(UTC).isoformat(),
        "stale": not (market_cache.is_valid(EVENT_KEY) and market_cache.is_valid(MARKET_KEY)),
    }


def cached_live_channels() -> list[dict[str, Any]]:
    """
    The channels known to be live, read from cache without probing.

    `live_events_service` calls this on the request path to decide whether an
    on-air broadcast should promote a nearby calendar entry, and must not pay
    for seven page fetches to find out. An empty list means "nothing known to be
    live", which for that decision is the same as "nothing live".
    """
    live: list[dict[str, Any]] = []
    for key in (EVENT_KEY, MARKET_KEY):
        cached = market_cache.get_with_fallback(key, max_age=MAX_STALE_STREAMS)
        if cached:
            live.extend(state for state in cached if state.get("is_live"))
    return live
