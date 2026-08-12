"""
Per-person blocking.

The escape hatch that makes an inbox open to every member tolerable. A block is
one-directional in storage and two-directional in effect: `eligibility.check_pair`
refuses the pairing whichever side put the row there, so blocking somebody also
stops you messaging them.

Existing threads stay *readable* after a block. Hiding the history would delete
evidence of whatever prompted the block, which is exactly backwards.
"""

from typing import Any

from . import _db
from .errors import InvalidRequest

TABLE = "dm_blocks"


async def block(blocker_id: str, blocked_id: str) -> None:
    """Stop `blocked_id` reaching `blocker_id`. Idempotent."""
    if blocker_id == blocked_id:
        raise InvalidRequest("You cannot block yourself.")

    await _db.table_op(
        lambda client: (
            client.table(TABLE)
            .upsert(
                {"blocker_id": blocker_id, "blocked_id": blocked_id},
                on_conflict="blocker_id,blocked_id",
            )
            .execute()
        ),
        what="create block",
    )


async def unblock(blocker_id: str, blocked_id: str) -> None:
    """Undo a block. Idempotent — removing one that is not there is a no-op."""
    await _db.table_op(
        lambda client: (
            client.table(TABLE)
            .delete()
            .eq("blocker_id", blocker_id)
            .eq("blocked_id", blocked_id)
            .execute()
        ),
        what="delete block",
    )


async def list_blocked(blocker_id: str) -> list[dict[str, Any]]:
    """Who this member has blocked, with enough profile to render a list."""
    rows = await _db.table_op(
        lambda client: (
            client.table(TABLE)
            .select("blocked_id, created_at")
            .eq("blocker_id", blocker_id)
            .order("created_at", desc=True)
            .execute()
        ),
        what="list blocks",
    )
    if not rows:
        return []

    ids = [row["blocked_id"] for row in rows]
    profiles = await _db.table_op(
        lambda client: (
            client.table("profiles").select("id, full_name, avatar_url").in_("id", ids).execute()
        ),
        what="load blocked profiles",
    )
    by_id = {profile["id"]: profile for profile in profiles or []}

    return [
        {
            "user_id": row["blocked_id"],
            "full_name": by_id.get(row["blocked_id"], {}).get("full_name"),
            "avatar_url": by_id.get(row["blocked_id"], {}).get("avatar_url"),
            "created_at": row.get("created_at"),
        }
        for row in rows
    ]
