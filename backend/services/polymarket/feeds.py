"""
Reading a news feed and nothing else.

`news_service._fetch_rss` already reads feeds, and reusing it here would have
been the obvious move. It cannot be: that function calls
`news_attribution.get_or_detect` on every headline, which is an LLM round trip
per item. Four category feeds at fifteen items each would fire sixty model calls
inside a seventy-five second sweep whose whole budget is meant for reading the
web. Symbol attribution is also meaningless here — a market about a ceasefire has
no ticker to detect.

So this reads the feed, takes four fields, and stops.

`feedparser` is synchronous and does its own blocking I/O, so every call goes
through a worker thread. Left on the event loop it would stall every other
request in the process, which is the same mistake `rag_v2_service` documents.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

FEED_TIMEOUT_SECONDS = 8.0

#: Per feed. Beyond this the tail is older than the sweep cares about, and every
#: extra item is another candidate the ranking has to carry.
MAX_ITEMS = 15


def _published(entry: Any) -> datetime | None:
    """
    The entry's publication time, or None.

    None rather than now(). An undated item stamped with the current time is
    indistinguishable from breaking news, which is the one confusion a date is
    being read to prevent — and in the origin stage an undated item is
    explicitly ineligible to be named as a trigger.
    """
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _read(url: str) -> list[dict[str, Any]]:
    """Blocking. Always called through a thread."""
    import feedparser

    parsed = feedparser.parse(url)
    items: list[dict[str, Any]] = []
    for entry in (parsed.entries or [])[:MAX_ITEMS]:
        link = getattr(entry, "link", "") or ""
        title = getattr(entry, "title", "") or ""
        if not link or not title:
            continue
        published = _published(entry)
        items.append(
            {
                "title": title,
                "snippet": (getattr(entry, "summary", "") or "")[:600],
                "url": link,
                "published_at": published.isoformat() if published else None,
                "source": getattr(parsed.feed, "title", "") or "",
            }
        )
    return items


async def fetch_feed(url: str, *, timeout: float = FEED_TIMEOUT_SECONDS) -> list[dict[str, Any]]:
    """
    One feed's recent items. Returns [] rather than raising.

    A feed that will not load is a gap the sweep names, not a failure that ends
    it — the whole design here is that a partial evidence base gets judged on
    what it has.
    """
    try:
        return await asyncio.wait_for(asyncio.to_thread(_read, url), timeout=timeout)
    except TimeoutError:
        logger.info("Polymarket feed timed out: %s", url)
        raise
    except Exception as error:  # noqa: BLE001
        logger.info("Polymarket feed failed (%s): %s", url, error)
        return []
