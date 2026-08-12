"""
Messages: reading a thread, sending into it, and the read cursor.

Reading is open to either participant unconditionally. Sending re-checks the
eligibility gate, because standing can change between opening a thread and
typing into it — the recipient may have blocked the sender or closed their inbox
while the composer sat on screen.
"""

from datetime import UTC, datetime
from typing import Any, Optional

from dependencies.auth import AuthUser

from . import _db, conversations, eligibility
from .errors import InvalidRequest, NotEligible

TABLE = "dm_messages"

# Matched by the CHECK constraint in 013 and by the composer's counter. Three
# places, on purpose: the database refuses what the API missed, and the UI stops
# the user before either has to.
MAX_BODY = 2000

# One page of history. The thread view asks for the newest page and walks
# backwards with `before`.
PAGE_SIZE = 50
MAX_PAGE_SIZE = 100


def normalise_body(raw: str) -> str:
    """
    Trim and validate one message body.

    Whitespace-only is rejected rather than stored: it renders as an empty
    bubble that the recipient cannot tell apart from a rendering bug.
    """
    body = (raw or "").strip()
    if not body:
        raise InvalidRequest("A message cannot be empty.")
    if len(body) > MAX_BODY:
        raise InvalidRequest(f"A message cannot be longer than {MAX_BODY} characters.")
    return body


async def list_messages(
    conversation_id: str,
    user_id: str,
    *,
    before: Optional[str] = None,
    limit: int = PAGE_SIZE,
) -> list[dict[str, Any]]:
    """
    One page of a thread, oldest-first for rendering, newest-first for paging.

    Keyset paginated on `created_at` rather than by offset: a message arriving
    mid-scroll would shift every offset and duplicate a row into the next page.
    """
    await conversations.require_participant(conversation_id, user_id)

    size = max(1, min(limit, MAX_PAGE_SIZE))

    def query(client: Any) -> Any:
        q = (
            client.table(TABLE)
            .select("id, conversation_id, sender_id, body, created_at")
            .eq("conversation_id", conversation_id)
            .order("created_at", desc=True)
            .limit(size)
        )
        if before:
            q = q.lt("created_at", before)
        return q.execute()

    rows = await _db.table_op(query, what="list messages")
    # Fetched newest-first so the page boundary is the cursor; reversed here so
    # the caller can append straight into a top-to-bottom thread.
    return list(reversed(rows or []))


async def send(conversation_id: str, sender: AuthUser, raw_body: str) -> dict[str, Any]:
    """
    Append a message, re-checking the gate against the *current* peer.

    Raises `NotEligible` with reasons, `NotAParticipant` if the thread is not
    the sender's, `InvalidRequest` for an unusable body.
    """
    body = normalise_body(raw_body)

    conversation = await conversations.require_participant(conversation_id, sender.id)
    peer_id = conversations.peer_of(conversation, sender.id)

    verdict = await eligibility.check_pair(sender, peer_id)
    if not verdict.can_send:
        raise NotEligible(verdict.reasons)

    rows = await _db.table_op(
        lambda client: (
            client.table(TABLE)
            .insert({"conversation_id": conversation_id, "sender_id": sender.id, "body": body})
            .execute()
        ),
        what="send message",
    )
    if not rows:
        # `_db` already raised for a failed call, so an empty result here means
        # the insert reported success without a row. Surfacing it as a failure
        # is the point: the composer must not clear on a write that may not
        # have landed.
        raise InvalidRequest("The message could not be saved.")

    # Sending is also reading: the sender has by definition seen everything up
    # to now, so leaving their own cursor behind would light up the nav badge
    # for a thread they are actively typing in.
    await mark_read(conversation_id, sender.id)
    return rows[0]


async def mark_read(conversation_id: str, user_id: str) -> None:
    """
    Advance this member's read cursor to now.

    Upserted on the composite primary key so the first read and the hundredth
    take the same path.

    The timestamp is built here rather than sent as a `now()` literal: that
    string would travel as JSON and Postgres would have to parse it as a
    timestamp, which it is not. An explicit ISO instant is unambiguous.
    """
    await _db.table_op(
        lambda client: (
            client.table("dm_reads")
            .upsert(
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "last_read_at": datetime.now(UTC).isoformat(),
                },
                on_conflict="conversation_id,user_id",
            )
            .execute()
        ),
        what="mark read",
    )
