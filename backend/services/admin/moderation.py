"""
Moderation: removing someone else's post or comment, and the content browser.

The deletes themselves live in the community package — `delete_post_as_moderator`
and `delete_comment_as_moderator` — because the semantics are community domain
knowledge (a post is hard-deleted, a comment leaves a tombstone so its replies
survive). This module orchestrates: snapshot, delete, audit.

The snapshot is taken **before** the delete. A post delete cascades its comments
and votes away, so afterwards there is nothing left to describe.
"""

import logging
from typing import Any, Awaitable, Optional

from models.admin import AdminPostPage, AdminPostSummary
from services import community

from . import _db, audit
from .audit import AuditActor
from .errors import AdminError, InvalidRequest, NotFound, UpstreamFailure

logger = logging.getLogger(__name__)

# How much of the body the audit entry keeps. Enough to recognise the post,
# short enough that the log does not become a second copy of the board.
SNAPSHOT_CONTENT_CHARS = 500


async def list_posts(
    *,
    search: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
) -> AdminPostPage:
    rows = await _db.rpc(
        "get_admin_posts",
        {"p_search": search, "p_limit": limit, "p_offset": offset},
    )
    posts = [
        AdminPostSummary(
            id=str(row.get("id")),
            title=row.get("title"),
            content_preview=row.get("content_preview") or "",
            type=row.get("type") or "thought",
            post_kind=row.get("post_kind") or "text",
            score=row.get("score") or 0,
            comments_count=row.get("comments_count") or 0,
            created_at=row.get("created_at"),
            author_id=row.get("author_id"),
            author_name=row.get("author_name"),
            author_email=row.get("author_email"),
        )
        for row in rows
    ]
    total = rows[0].get("total_count") or 0 if rows else 0
    return AdminPostPage(posts=posts, total=total, limit=limit, offset=offset)


async def delete_post(*, post_id: str, actor: AuditActor, reason: Optional[str] = None) -> None:
    snapshot = await _translate(community.posts.get_post(post_id))
    await _translate(community.posts.delete_post_as_moderator(post_id=post_id))
    await audit.record(
        actor=actor,
        action="post.delete",
        target_type="post",
        target_id=post_id,
        reason=reason,
        metadata={
            "title": snapshot.title,
            "content": (snapshot.content or "")[:SNAPSHOT_CONTENT_CHARS],
            "author_id": snapshot.author.id if snapshot.author else None,
            "author_name": snapshot.author.full_name if snapshot.author else None,
            "post_kind": snapshot.post_kind,
            "score": snapshot.score,
            "comments_count": snapshot.comments_count,
        },
    )


async def delete_comment(
    *, comment_id: str, actor: AuditActor, reason: Optional[str] = None
) -> None:
    snapshot = await _translate(community.comments.get_comment(comment_id))
    await _translate(community.comments.delete_comment_as_moderator(comment_id=comment_id))
    await audit.record(
        actor=actor,
        action="comment.delete",
        target_type="comment",
        target_id=comment_id,
        reason=reason,
        metadata={
            "post_id": snapshot.post_id,
            "content": (snapshot.content or "")[:SNAPSHOT_CONTENT_CHARS],
            "author_id": snapshot.author.id if snapshot.author else None,
            "author_name": snapshot.author.full_name if snapshot.author else None,
        },
    )


async def _translate(awaitable: Awaitable[Any]) -> Any:
    """
    Run a community call and re-raise its failures as admin ones.

    Without this the admin router would have to know how to map a
    `CommunityError`, which would make every community error type part of the
    admin router's contract.
    """
    try:
        return await awaitable
    except community.NotFound as exc:
        raise NotFound(str(exc)) from exc
    except community.InvalidRequest as exc:
        raise InvalidRequest(str(exc)) from exc
    except community.CommunityError as exc:
        raise UpstreamFailure(str(exc)) from exc
    except AdminError:
        raise
