"""
Threaded comments.

The database returns the thread flat; `build_tree` assembles it here. Depth is
capped at four levels by a trigger, so a recursive CTE would buy nothing over
one indexed scan — and a pure Python tree builder can be tested without a
database, which is most of the logic worth testing.
"""

import logging
from datetime import datetime, UTC
from typing import Any, Optional

from models.community import Comment, PostAuthor

from . import _db
from .errors import InvalidRequest, NotFound, NotOwner, UpstreamFailure

logger = logging.getLogger(__name__)

TABLE = "community_comments"

# Mirrors community_comments_depth_check in 007_community_reddit.sql. Kept here
# so a reply that would overflow is refused with a clear message instead of a
# raw Postgres check violation.
MAX_DEPTH = 3


def to_comment(row: dict) -> Comment:
    """Map one `community_comment_row` onto the API model."""
    is_deleted = row.get("deleted_at") is not None
    return Comment(
        id=row["id"],
        post_id=row["post_id"],
        parent_id=row.get("parent_id"),
        content=row.get("content"),
        score=row.get("score") or 0,
        depth=row.get("depth") or 0,
        is_edited=bool(row.get("is_edited")),
        is_deleted=is_deleted,
        created_at=row["created_at"],
        updated_at=row.get("updated_at"),
        author=PostAuthor(
            id=None if is_deleted else row.get("user_id"),
            full_name=row.get("author_name"),
            avatar_url=row.get("author_avatar_url"),
            subscription_plan=row.get("author_plan"),
        ),
        my_vote=row.get("my_vote") or 0,
    )


def build_tree(comments: list) -> list:
    """
    Turn a flat list of `Comment` objects into a forest of reply chains.

    Assumes the input is ordered parents-before-children, which the
    `get_community_comments` RPC guarantees by sorting on `depth` first. A
    comment whose parent is missing from the list — which should not happen,
    since the FK cascades — is promoted to the top level rather than dropped,
    because losing a reply silently is worse than showing it out of place.
    """
    by_id: dict = {}
    roots: list = []

    for comment in comments:
        comment.replies = []
        by_id[comment.id] = comment

    for comment in comments:
        parent = by_id.get(comment.parent_id) if comment.parent_id else None
        if parent is None:
            roots.append(comment)
        else:
            parent.replies.append(comment)

    return roots


async def list_comments(post_id: str, viewer_id: Optional[str] = None) -> tuple:
    """
    The full thread for a post, as a tree plus a flat count.

    Returns `([], 0)` rather than raising if the query fails: a post that
    renders without its comments beats a post that does not render.
    """
    try:
        rows = await _db.rpc(
            "get_community_comments", {"p_post_id": post_id, "p_viewer": viewer_id}
        )
    except Exception:
        logger.exception("community: comment query failed for post %s", post_id)
        return [], 0

    flat = [to_comment(row) for row in rows]
    return build_tree(flat), len(flat)


async def create_comment(
    *, user_id: str, post_id: str, content: str, parent_id: Optional[str] = None
) -> Comment:
    if parent_id:
        await _assert_parent_is_repliable(post_id=post_id, parent_id=parent_id)

    payload = {
        "user_id": user_id,
        "post_id": post_id,
        "content": content,
        "parent_id": parent_id,
    }

    try:
        data = await _db.table_op(
            lambda client: client.table(TABLE).insert(payload).execute(),
            what="insert comment",
        )
    except UpstreamFailure as exc:
        # The depth trigger raises a check violation for a reply that would sit
        # at level five. Translate it rather than surfacing raw SQL to the user.
        if "nesting" in str(exc).lower():
            raise InvalidRequest("replies are limited to four levels deep")
        raise

    if not data:
        raise InvalidRequest("the comment was rejected by the database")

    return await _get_one(data[0]["id"], viewer_id=user_id)


async def update_comment(*, comment_id: str, user_id: str, content: str) -> Comment:
    await _assert_owner(comment_id, user_id)
    await _db.table_op(
        lambda client: (
            client.table(TABLE)
            .update(
                {
                    "content": content,
                    "is_edited": True,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
            .eq("id", comment_id)
            .eq("user_id", user_id)
            .execute()
        ),
        what="update comment",
    )
    return await _get_one(comment_id, viewer_id=user_id)


async def delete_comment(*, comment_id: str, user_id: str) -> None:
    """
    Soft delete — a tombstone.

    A hard delete would cascade the entire reply subtree away, so a comment with
    three answers under it would take all three with it. Setting `deleted_at`
    keeps the children readable; `get_community_comments` withholds the text and
    the author, and the count trigger decrements `comments_count`.
    """
    await _assert_owner(comment_id, user_id)
    await _tombstone(comment_id, owner_id=user_id)


async def delete_comment_as_moderator(*, comment_id: str) -> None:
    """
    The same tombstone without the ownership check, for an admin removing
    someone else's comment. Authorization happened at the router.

    The existence check is not optional: an update matching zero rows is not an
    error in PostgREST, so without it a mistyped id would return 204 and the
    moderator would believe something was removed.
    """
    await _load_author(comment_id)
    await _tombstone(comment_id, owner_id=None)


async def _tombstone(comment_id: str, *, owner_id: Optional[str]) -> None:
    """
    Shared body. `.is_("deleted_at", "null")` makes the write idempotent, so a
    second delete is a no-op rather than a fresh timestamp — which matters
    because the comments_count trigger fires on the transition.
    """

    def _call(client: Any) -> Any:
        query = (
            client.table(TABLE)
            .update(
                {
                    "deleted_at": datetime.now(UTC).isoformat(),
                    "content": "",
                }
            )
            .eq("id", comment_id)
        )
        if owner_id is not None:
            query = query.eq("user_id", owner_id)
        return query.is_("deleted_at", "null").execute()

    await _db.table_op(_call, what="delete comment")


async def get_comment(comment_id: str) -> Comment:
    """
    A single comment, without its thread.

    The feed and the detail page both read whole threads, so this exists for the
    one caller that needs a row on its own: the moderation service, snapshotting
    a comment into the audit trail before tombstoning it.
    """
    return await _get_one(comment_id)


async def _get_one(comment_id: str, viewer_id: Optional[str] = None) -> Comment:
    data = await _db.table_op(
        lambda client: client.table(TABLE).select("*").eq("id", comment_id).execute(),
        what="load comment",
    )
    if not data:
        raise NotFound(f"comment {comment_id} does not exist")

    row = dict(data[0])
    # The plain table select has no author join; fill in what the caller needs
    # for an optimistic render and let the next thread fetch carry the rest.
    row.setdefault("author_name", None)
    row.setdefault("author_avatar_url", None)
    row.setdefault("author_plan", None)
    row["my_vote"] = 0
    return to_comment(row)


async def _assert_parent_is_repliable(*, post_id: str, parent_id: str) -> None:
    data = await _db.table_op(
        lambda client: (
            client.table(TABLE).select("post_id, depth, deleted_at").eq("id", parent_id).execute()
        ),
        what="load parent comment",
    )
    if not data:
        raise NotFound(f"comment {parent_id} does not exist")

    parent = data[0]
    if parent["post_id"] != post_id:
        raise InvalidRequest("the parent comment belongs to a different post")
    if (parent.get("depth") or 0) >= MAX_DEPTH:
        raise InvalidRequest("replies are limited to four levels deep")


async def _assert_owner(comment_id: str, user_id: str) -> None:
    if await _load_author(comment_id) != user_id:
        raise NotOwner(f"comment {comment_id} belongs to another user")


async def _load_author(comment_id: str) -> str:
    """The comment's author id, or `NotFound` if there is no such comment."""
    data = await _db.table_op(
        lambda client: client.table(TABLE).select("user_id").eq("id", comment_id).execute(),
        what="load comment owner",
    )
    if not data:
        raise NotFound(f"comment {comment_id} does not exist")
    return data[0]["user_id"]
