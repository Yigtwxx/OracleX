"""
Conversations: the inbox, and opening a thread with somebody.

The pair is stored in a canonical order (`user_a < user_b`) so a unique index
can express "at most one thread per pair". Everything in this module that
touches the table sorts the two ids first; see `_ordered`.
"""

import logging
from typing import Any, Optional

from dependencies.auth import AuthUser

from . import _db, eligibility
from .errors import NotAParticipant, NotFound, NotEligible, UpstreamFailure

logger = logging.getLogger(__name__)

TABLE = "dm_conversations"


def _ordered(a: str, b: str) -> tuple[str, str]:
    """The pair as the table stores it. Sorting here is what the index relies on."""
    return (a, b) if a < b else (b, a)


def _is_duplicate(exc: Exception) -> bool:
    """
    Whether an insert failed because the row already exists.

    Matched on the message because supabase-py surfaces PostgREST errors as a
    generic exception and `_db` has already wrapped it — there is no error code
    to read by the time it reaches here. Both spellings appear depending on
    whether PostgREST or psycopg formatted the response.
    """
    text = str(exc).lower()
    return "23505" in text or "duplicate key" in text


async def get_or_create(sender: AuthUser, recipient_id: str) -> dict:
    """
    The thread between these two, opening one if it does not exist yet.

    Raises `NotEligible` when the gate refuses the pairing. That check happens
    here rather than only on send, so the UI can refuse before showing a
    composer the user cannot use.
    """
    verdict = await eligibility.check_pair(sender, recipient_id)
    if not verdict.can_send:
        raise NotEligible(verdict.reasons)

    if not await _member_exists(recipient_id):
        raise NotFound("No such member.")

    user_a, user_b = _ordered(sender.id, recipient_id)

    existing = await _find(user_a, user_b)
    if existing is not None:
        return existing

    try:
        rows = await _db.table_op(
            lambda client: (
                client.table(TABLE).insert({"user_a": user_a, "user_b": user_b}).execute()
            ),
            what="create conversation",
        )
    except UpstreamFailure as exc:
        # The other side opened the same thread between our SELECT and our
        # INSERT. The unique index is what makes that a duplicate-key error
        # instead of a second conversation, so re-reading is the whole fix.
        if not _is_duplicate(exc):
            raise
        found = await _find(user_a, user_b)
        if found is None:
            raise
        return found

    if not rows:
        raise UpstreamFailure("Conversation insert returned no row")
    return rows[0]


async def _find(user_a: str, user_b: str) -> Optional[dict]:
    rows = await _db.table_op(
        lambda client: (
            client.table(TABLE)
            .select("*")
            .eq("user_a", user_a)
            .eq("user_b", user_b)
            .limit(1)
            .execute()
        ),
        what="find conversation",
    )
    return rows[0] if rows else None


async def _member_exists(user_id: str) -> bool:
    rows = await _db.table_op(
        lambda client: client.table("profiles").select("id").eq("id", user_id).limit(1).execute(),
        what="check member exists",
    )
    return bool(rows)


async def require_participant(conversation_id: str, user_id: str) -> dict:
    """
    Load a conversation, refusing anyone who is not in it.

    Every message read and write goes through this. Under the service-role key
    there is no second line of defence behind it, so it returns the row rather
    than a boolean — a caller that has the row cannot forget to ask first.
    """
    rows = await _db.table_op(
        lambda client: client.table(TABLE).select("*").eq("id", conversation_id).limit(1).execute(),
        what="load conversation",
    )
    if not rows:
        raise NotFound("No such conversation.")

    row = rows[0]
    if user_id not in (row.get("user_a"), row.get("user_b")):
        # Logged because on this backend it is either a bug or somebody probing
        # for other people's threads. The conversation id is not user content.
        logger.warning("social: %s is not a participant of %s", user_id, conversation_id)
        raise NotAParticipant("This conversation is not yours.")
    return row


def peer_of(conversation: dict, user_id: str) -> str:
    """The other person in `conversation`."""
    user_a = conversation.get("user_a")
    return conversation["user_b"] if user_a == user_id else conversation["user_a"]


async def list_inbox(user_id: str) -> list[dict[str, Any]]:
    """
    Every thread this member is in, newest first, with peer, preview and unread.

    One RPC rather than a query per conversation: `dm_inbox` assembles the last
    message and the unread count in SQL. The inbox is polled every 15 seconds,
    so an N+1 here would be N+1 every 15 seconds per open tab.
    """
    rows = await _db.rpc("dm_inbox", {"uid": user_id})
    return [
        {
            "id": row["conversation_id"],
            "peer": {
                "id": row["peer_id"],
                "full_name": row.get("peer_full_name"),
                "avatar_url": row.get("peer_avatar_url"),
                "subscription_plan": row.get("peer_subscription_plan"),
            },
            "last_message": (
                {
                    "body": row["last_body"],
                    "sender_id": row.get("last_sender_id"),
                    "created_at": row.get("last_message_at"),
                }
                if row.get("last_body") is not None
                else None
            ),
            "last_message_at": row.get("last_message_at"),
            "unread_count": row.get("unread_count") or 0,
        }
        for row in rows
    ]


async def unread_total(user_id: str) -> int:
    """Unread messages across every thread — the number on the nav tab."""
    rows = await _db.rpc("dm_unread_total", {"uid": user_id})
    if not rows:
        return 0
    first = rows[0]
    # A scalar-returning function comes back as a bare value under some
    # postgrest versions and as a single-key row under others.
    if isinstance(first, dict):
        return int(next(iter(first.values())) or 0)
    return int(first or 0)
