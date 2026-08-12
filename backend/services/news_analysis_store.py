"""
Persistence for finished news analyses.

Two reasons this exists rather than a plain in-memory dict:

* **Re-clicking a headline should be instant.** The pipeline costs tens of
  seconds; the news itself does not change.
* **The outcome job outlives the process.** Measuring what the price actually
  did happens hours after the verdict, so the verdict has to survive a restart
  for the feedback loop to close at all.

Entries are keyed by news id *and* pipeline version. A prompt edit changes the
version, which retires every cached analysis — otherwise stale reasoning is
served forever and an evaluation run silently measures the old pipeline.
"""

import hashlib
import json
import logging
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STORE_FILE = "data/news_analyses.json"

# Prompts whose contents take part in the pipeline fingerprint.
_VERSIONED_PROMPTS = (
    "news/system_sentiment",
    "news/analyze",
)

# Bumped by hand when the pipeline's *code* changes in a way the prompt hashes
# would not catch (a new stage, a different parser).
PIPELINE_REVISION = "1"

_lock = threading.Lock()
_entries: Optional[Dict[str, Dict[str, Any]]] = None
_pipeline_version: Optional[str] = None


def _load_json(filepath: str, default: Any) -> Any:
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(filepath: str, data: Any) -> None:
    directory = os.path.dirname(filepath)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)


def pipeline_version() -> str:
    """
    Short digest of everything that determines what an analysis looks like.

    Computed once per process: the prompt files do not change under a running
    server, and hashing them on every cache lookup would be silly.
    """
    global _pipeline_version
    if _pipeline_version is not None:
        return _pipeline_version

    from config import settings
    from services.prompts import load_prompt

    digest = hashlib.sha256()
    digest.update(PIPELINE_REVISION.encode())
    digest.update((settings.LLM_MODEL or "").encode())
    for name in _VERSIONED_PROMPTS:
        try:
            digest.update(load_prompt(name).encode())
        except Exception as e:  # noqa: BLE001 — a missing prompt is a louder failure elsewhere
            logger.warning("Could not hash prompt %s for the pipeline version: %s", name, e)

    _pipeline_version = digest.hexdigest()[:12]
    return _pipeline_version


def cache_key(news_id: str) -> str:
    return f"{news_id}:{pipeline_version()}"


def _all() -> Dict[str, Dict[str, Any]]:
    global _entries
    if _entries is None:
        _entries = _load_json(STORE_FILE, {})
    return _entries


def get(news_id: str) -> Optional[Dict[str, Any]]:
    """The stored analysis for this item under the current pipeline, if any."""
    with _lock:
        entry = _all().get(cache_key(news_id))
        return dict(entry) if entry else None


def put(
    news_id: str,
    analysis: Dict[str, Any],
    *,
    news_snapshot: Dict[str, Any],
) -> None:
    """
    Store a finished analysis together with the item it was made from.

    The `NewsItem` is snapshotted rather than referenced: `utils.update_news_cache`
    replaces the whole news cache every ten minutes, so by the time the outcome
    job runs, the original item is usually gone.
    """
    with _lock:
        entries = _all()
        entries[cache_key(news_id)] = {
            "news_id": news_id,
            "pipeline_version": pipeline_version(),
            "analysis": analysis,
            "news": news_snapshot,
            "stored_at": datetime.now().isoformat(),
            # Filled in later by the outcome job; None means "not measured yet".
            "outcome": None,
        }
        _save_json(STORE_FILE, entries)


def record_outcome(news_id: str, outcome: Dict[str, Any]) -> bool:
    """Attach a measured price outcome to a stored analysis. False if unknown."""
    with _lock:
        entries = _all()
        entry = entries.get(cache_key(news_id))
        if not entry:
            return False
        entry["outcome"] = outcome
        _save_json(STORE_FILE, entries)
        return True


def pending_outcomes() -> List[Dict[str, Any]]:
    """
    Stored analyses that have no measured outcome yet.

    Returns every pipeline version, not just the current one: a verdict made
    before a prompt edit still happened, and what the price did afterwards is
    still worth learning from.
    """
    with _lock:
        return [dict(entry) for entry in _all().values() if entry.get("outcome") is None]


def reset_state() -> None:
    """Drop the in-memory view and the cached version. For tests."""
    global _entries, _pipeline_version
    with _lock:
        _entries = None
        _pipeline_version = None
