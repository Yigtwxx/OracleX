"""
Streamer board.

Answers "who covering markets is broadcasting right now, and where" for a
curated list that spans platforms. It only reports status — nothing here is
embedded or played; a live row links out to the platform it is on.

Two platforms, both keyless:

* **YouTube** reuses `live_stream_service.probe_youtube_live`. That probe costs
  most of a megabyte per channel, which is what shapes everything below: the
  board is built only when something asks for it, never on a timer, and it is
  cached long enough that a tab left open does not re-probe twenty channels
  every minute.
* **Kick** answers `/api/v2/channels/<slug>` with a few kilobytes of JSON whose
  `livestream` field is null when the channel is off air and an object — with
  the title and a viewer count — when it is not. It is cheap enough that its
  cost never entered the design.

Twitch is deliberately absent: its Helix API answers 401 without a registered
client id, and its web page carries no server-rendered live marker to read
instead. Adding it means adding a credential, which this feature does not have.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from services import http_client
from services.cache import market_cache
from services.home_service import UpstreamUnavailable
from services.live_stream_service import probe_youtube_live

logger = logging.getLogger(__name__)

CACHE_KEY = "live_streamers"
# Ten minutes. A streamer going live is not a market event, and the board is
# read by a human glancing at it — the freshness that buys is not worth
# re-downloading twenty YouTube pages for. See the module docstring.
TTL_STREAMERS = 600
MAX_STALE_STREAMERS = 60 * 60

# YouTube probes are the expensive half, so they are not all started at once —
# twenty simultaneous megabyte fetches is a burst worth spreading out.
MAX_CONCURRENT_PROBES = 6

KICK_TIMEOUT = 12.0

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "registry" / "streamers.json"


def load_registry() -> list[dict[str, Any]]:
    """The curated list, read from disk. Empty if the file is missing or broken."""
    try:
        with REGISTRY_PATH.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Streamer registry unreadable at %s: %s", REGISTRY_PATH, exc)
        return []

    entries = payload.get("streamers")
    return entries if isinstance(entries, list) else []


def _row(entry: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    base = {
        "key": entry.get("key", ""),
        "name": entry.get("name", ""),
        "platform": entry.get("platform", ""),
        "region": entry.get("region"),
        "focus": entry.get("focus"),
        "is_live": False,
        "title": None,
        "viewers": None,
        "url": None,
        # True when the platform could not be reached. Distinct from being off
        # air: only one of the two is a fact about the streamer.
        "probe_failed": False,
    }
    return base | overrides


async def _probe_youtube(entry: dict[str, Any]) -> dict[str, Any]:
    channel_id = entry.get("channel_id")
    if not channel_id:
        return _row(entry, probe_failed=True)

    state = await probe_youtube_live(channel_id)
    if not state.reachable:
        return _row(entry, probe_failed=True, url=f"https://www.youtube.com/channel/{channel_id}")
    if not state.is_live:
        return _row(entry, url=f"https://www.youtube.com/channel/{channel_id}")

    return _row(
        entry,
        is_live=True,
        title=state.title,
        # YouTube does not publish a concurrent-viewer count anywhere the probe
        # can read, so this stays null rather than being guessed at.
        url=f"https://www.youtube.com/watch?v={state.video_id}",
    )


async def _probe_kick(entry: dict[str, Any]) -> dict[str, Any]:
    slug = entry.get("slug")
    if not slug:
        return _row(entry, probe_failed=True)

    channel_url = f"https://kick.com/{slug}"
    try:
        # Kick sits behind Cloudflare and answers an ordinary client with a
        # challenge page, so this is one of the upstreams that needs the browser
        # TLS fingerprint rather than merely a browser User-Agent.
        payload = await http_client.get_json_impersonated(
            f"https://kick.com/api/v2/channels/{slug}", timeout=KICK_TIMEOUT
        )
    except Exception as exc:  # noqa: BLE001 — one streamer must not sink the board
        logger.warning("Kick probe failed for %s: %s", slug, exc)
        return _row(entry, probe_failed=True, url=channel_url)

    livestream = payload.get("livestream") if isinstance(payload, dict) else None
    if not isinstance(livestream, dict):
        return _row(entry, url=channel_url)

    return _row(
        entry,
        is_live=True,
        title=(livestream.get("session_title") or "").strip() or None,
        viewers=livestream.get("viewer_count"),
        url=channel_url,
    )


async def _probe(entry: dict[str, Any], gate: asyncio.Semaphore) -> dict[str, Any]:
    platform = entry.get("platform")
    if platform == "kick":
        # Kick costs kilobytes, so it is not made to queue behind the YouTube
        # probes for a slot it does not need.
        return await _probe_kick(entry)
    if platform == "youtube":
        async with gate:
            return await _probe_youtube(entry)

    logger.warning("Unknown streamer platform %r for %r", platform, entry.get("key"))
    return _row(entry, probe_failed=True)


async def fetch_streamers() -> dict[str, Any]:
    """
    Who is on air, live first.

    Raises `UpstreamUnavailable` only when nothing could be established at all.
    A board where every probe failed must not render as "nobody is streaming" —
    that is a claim about the world, and the point of this panel is to make that
    claim honestly.
    """
    cached = market_cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    registry = load_registry()
    if not registry:
        raise UpstreamUnavailable("streamer registry is empty or unreadable")

    gate = asyncio.Semaphore(MAX_CONCURRENT_PROBES)
    results = await asyncio.gather(
        *(_probe(entry, gate) for entry in registry), return_exceptions=True
    )

    rows: list[dict[str, Any]] = []
    for entry, result in zip(registry, results):
        if isinstance(result, BaseException):
            logger.warning("Streamer probe crashed for %r: %s", entry.get("key"), result)
            rows.append(_row(entry, probe_failed=True))
        else:
            rows.append(result)

    if all(row["probe_failed"] for row in rows):
        stale = market_cache.get_with_fallback(CACHE_KEY, max_age=MAX_STALE_STREAMERS)
        if stale is not None:
            return {**stale, "stale": True}
        raise UpstreamUnavailable("no streaming platform could be reached")

    # Live first, then by viewer count where a platform reports one, then by
    # name so the offline half keeps a stable order between refreshes.
    rows.sort(key=lambda row: (not row["is_live"], -(row["viewers"] or 0), row["name"].lower()))

    payload = {
        "streamers": rows,
        "live_count": sum(1 for row in rows if row["is_live"]),
        "as_of": datetime.now(UTC).isoformat(),
        "stale": False,
    }
    market_cache.set(CACHE_KEY, payload, TTL_STREAMERS)
    return payload
