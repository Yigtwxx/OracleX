"""
News Attribution — remembers which asset each headline was found to be about.

The news cache is rebuilt from scratch every couple of minutes, and the feeds
return largely the same items each time. Without a memory, every refresh sent
~150 headlines back through the LLM: expensive, slow enough that many calls
timed out, and — because a timeout downgrades detection to the heuristic path —
the reason a story could be filed under one asset at 10:00 and another at 10:02.

Attribution is a property of the text, and the text does not change. So it is
worked out once per headline and kept, on disk as well as in memory so a restart
does not repeat the whole batch. Results that came out of a degraded path are
marked and revisited later, rather than being frozen in.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from services.asset_registry import read_json_cache, write_json_cache
from services.symbol_detection_service import Attribution, detect_symbol_smart

logger = logging.getLogger(__name__)

ATTRIBUTION_FILE = "data/news_attribution.json"

# Bump this whenever detection changes in a way that would give a stored
# headline a different answer. Cached entries are the point of this module, but
# they would also keep an improvement from ever reaching the items already in
# the store — a rule that stops "AI infrastructure" resolving to a token is
# worth nothing if every such item is already answered.
ATTRIBUTION_LOGIC_VERSION = 3

# Roughly a fortnight of feed history at the current fetch volume. Old entries
# are dropped oldest-first; the item they describe has long since fallen off
# every feed.
MAX_ATTRIBUTION_ENTRIES = 5000

# Writing the file on every new headline would mean ~150 rewrites on a cold
# start. Batch them; `flush()` covers the tail.
_PERSIST_EVERY = 25

_entries: Optional[dict[str, dict[str, Any]]] = None
_unsaved = 0
_lock = asyncio.Lock()


def _load() -> dict[str, dict[str, Any]]:
    """The stored attributions, read from disk once per process."""
    global _entries
    if _entries is not None:
        return _entries

    stored = read_json_cache(ATTRIBUTION_FILE) or {}
    if not isinstance(stored, dict):
        _entries = {}
        return _entries

    if stored.get("version") != ATTRIBUTION_LOGIC_VERSION:
        logger.info(
            "News attribution logic changed (stored v%s, now v%s) — re-detecting",
            stored.get("version"),
            ATTRIBUTION_LOGIC_VERSION,
        )
        _entries = {}
        return _entries

    _entries = stored.get("entries") or {}
    if _entries:
        logger.info("Loaded %d cached news attributions", len(_entries))
    return _entries


def _persist() -> None:
    """Write the store out, oldest entries dropped past the cap."""
    global _entries, _unsaved
    entries = _load()
    if len(entries) > MAX_ATTRIBUTION_ENTRIES:
        newest = sorted(entries.items(), key=lambda row: row[1].get("ts", ""), reverse=True)
        entries = dict(newest[:MAX_ATTRIBUTION_ENTRIES])
        _entries = entries
    write_json_cache(
        ATTRIBUTION_FILE,
        {"version": ATTRIBUTION_LOGIC_VERSION, "entries": entries},
    )
    _unsaved = 0


async def flush() -> None:
    """Persist anything still only in memory. Called once per fetch cycle."""
    async with _lock:
        if _unsaved:
            _persist()


def _to_attribution(record: dict[str, Any]) -> Attribution:
    return Attribution(
        symbol=record.get("symbol"),
        asset_type=record.get("asset_type") or "crypto",
        confident=bool(record.get("confident", True)),
    )


async def get_or_detect(
    news_id: str, title: str, summary: str, hint: str = "crypto"
) -> Attribution:
    """
    The asset this item is about, detected once and remembered.

    A stored `symbol: None` is a result in its own right — "this headline is
    about no single tradeable asset" is an answer the model gives often and one
    that costs just as much to work out as any other, so it is cached too. Only
    entries flagged as unconfident are worked out again.
    """
    cached = _load().get(news_id)
    if cached and cached.get("confident", True):
        return _to_attribution(cached)

    attribution = await detect_symbol_smart(summary, title, hint)

    # A retry that also failed keeps whatever the previous degraded pass found,
    # rather than replacing a plausible symbol with nothing.
    if cached and not attribution.confident and not attribution.symbol:
        return _to_attribution(cached)

    async with _lock:
        global _unsaved
        # Re-read rather than reusing the dict from before the await: pruning
        # replaces the store wholesale, and a write to the old one would vanish.
        entries = _load()
        entries[news_id] = {
            "symbol": attribution.symbol,
            "asset_type": attribution.asset_type,
            "confident": attribution.confident,
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        _unsaved += 1
        if _unsaved >= _PERSIST_EVERY:
            _persist()

    return attribution
