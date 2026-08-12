"""
The numbers behind Social > Activity.

Nothing here is denormalized. `community_user_activity()` computes the counts
and karma on read for the same reason `community_user_karma()` does: a counter
column on `profiles` drifts the first time a post is deleted or a vote retracted,
and no trigger notices.
"""

import logging
from typing import Any

from . import _db

logger = logging.getLogger(__name__)

EMPTY: dict[str, Any] = {
    "post_count": 0,
    "comment_count": 0,
    "post_karma": 0,
    "comment_karma": 0,
    "total_karma": 0,
    "best_post": None,
}


async def get_activity(user_id: str) -> dict[str, Any]:
    """
    One member's community totals.

    Degrades to zeroes rather than raising: this is a read on a dashboard, and a
    tab that renders "0 posts" while the RPC is missing is more useful than one
    that renders an error. The log line is what says which happened — and on a
    fresh project the answer is usually "013 has not been run yet".
    """
    try:
        rows = await _db.rpc("community_user_activity", {"uid": user_id})
    except Exception as exc:
        logger.warning("social: activity rpc failed for %s: %s", user_id, exc)
        return dict(EMPTY)

    if not rows:
        return dict(EMPTY)

    row = rows[0]
    best_id = row.get("best_post_id")
    return {
        "post_count": row.get("post_count") or 0,
        "comment_count": row.get("comment_count") or 0,
        "post_karma": row.get("post_karma") or 0,
        "comment_karma": row.get("comment_karma") or 0,
        "total_karma": row.get("total_karma") or 0,
        # NULL rather than zero when the member has never posted, so the UI can
        # say "no posts yet" instead of rendering a card for a post that is not
        # there.
        "best_post": (
            {
                "id": best_id,
                "title": row.get("best_post_title"),
                "score": row.get("best_post_score") or 0,
            }
            if best_id
            else None
        ),
    }
