"""
Reading back what the AI has cost.

Rows are written by `services/llm/usage.py`; this is the query side. Two
questions are worth answering separately and the table keeps them apart:

  * "What have I used?"       — rows with this user_id.
  * "What does this install use?" — every row, including the schedulers, which
    carry no user and on a self-hosted box are most of the spend.

Totals are computed in Python rather than in SQL because the volume is small —
one row per model call on a single-worker deployment — and because a grouped
RPC would be a migration every time a breakdown is added.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Optional

from services.supabase_service import get_supabase, run_with_reconnect

logger = logging.getLogger(__name__)

TABLE = "ai_usage"

# Windows the profile view offers. 0 means "since the first row".
WINDOWS: Dict[str, Optional[int]] = {"today": 1, "7d": 7, "30d": 30, "all": None}

# A ceiling so one query cannot pull an unbounded history into memory. Well past
# what a month of a single-worker install produces.
MAX_ROWS = 20000


def _empty_totals() -> Dict[str, Any]:
    return {
        "requests": 0,
        "failed": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        # Rows from a provider that reported nothing. Surfaced rather than
        # folded into zero, so a total that undercounts says so.
        "requests_without_token_data": 0,
    }


def _accumulate(totals: Dict[str, Any], row: Dict[str, Any]) -> None:
    totals["requests"] += 1
    if not row.get("ok", True):
        totals["failed"] += 1

    prompt = row.get("prompt_tokens")
    completion = row.get("completion_tokens")
    total = row.get("total_tokens")

    if prompt is None and completion is None and total is None:
        totals["requests_without_token_data"] += 1
        return

    totals["prompt_tokens"] += prompt or 0
    totals["completion_tokens"] += completion or 0
    totals["total_tokens"] += total or ((prompt or 0) + (completion or 0))


def _since(days: Optional[int]) -> Optional[str]:
    if days is None:
        return None
    # "today" is the last 24 hours rather than since local midnight: the server's
    # midnight is not the reader's, and a counter that resets at a time they
    # cannot predict reads as a bug.
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _fetch(user_id: Optional[str], days: Optional[int]) -> List[Dict[str, Any]]:
    def _query():
        table = get_supabase().table(TABLE).select("*")
        if user_id is not None:
            table = table.eq("user_id", user_id)
        since = _since(days)
        if since:
            table = table.gte("created_at", since)
        return table.order("created_at", desc=True).limit(MAX_ROWS).execute()

    response = run_with_reconnect(_query)
    return response.data or []


def summarise(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Totals plus the two breakdowns the view renders."""
    totals = _empty_totals()
    by_feature: Dict[str, Dict[str, Any]] = defaultdict(_empty_totals)
    by_provider: Dict[str, Dict[str, Any]] = defaultdict(_empty_totals)
    by_key_owner: Dict[str, Dict[str, Any]] = defaultdict(_empty_totals)

    for row in rows:
        _accumulate(totals, row)
        _accumulate(by_feature[row.get("feature") or "unknown"], row)
        _accumulate(by_provider[row.get("provider") or "unknown"], row)
        _accumulate(by_key_owner[row.get("key_owner") or "server"], row)

    return {
        "totals": totals,
        "by_feature": dict(by_feature),
        "by_provider": dict(by_provider),
        "by_key_owner": dict(by_key_owner),
    }


async def get_usage(user_id: Optional[str], window: str = "30d") -> Dict[str, Any]:
    """
    Usage for one reader, or install-wide when `user_id` is None.

    Returns an empty summary rather than raising when the table cannot be read:
    this is a reporting view, and failing the profile page over a statistic
    would be a worse trade than showing zeroes with `available: false`.
    """
    days = WINDOWS.get(window, 30)

    try:
        import asyncio

        rows = await asyncio.to_thread(_fetch, user_id, days)
    except Exception as e:  # noqa: BLE001
        logger.error("Could not read AI usage: %s", e)
        return {
            "window": window,
            "available": False,
            **summarise([]),
            "recent": [],
        }

    summary = summarise(rows)
    return {
        "window": window,
        "available": True,
        **summary,
        # The last handful, so a reader can see what a call actually looks like
        # rather than only an aggregate. Never includes prompt text — this table
        # stores none.
        "recent": [
            {
                "created_at": row.get("created_at"),
                "feature": row.get("feature"),
                "provider": row.get("provider"),
                "model": row.get("model"),
                "key_owner": row.get("key_owner"),
                "total_tokens": row.get("total_tokens"),
                "duration_ms": row.get("duration_ms"),
                "ok": row.get("ok", True),
            }
            for row in rows[:20]
        ],
    }
