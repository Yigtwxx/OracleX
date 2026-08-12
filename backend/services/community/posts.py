"""
Community posts: the feed, a single post, and the author's own writes.

Reads go through the `get_community_feed` RPC rather than a PostgREST select,
for two reasons. It computes the Hot ranking in SQL, and it returns the viewer's
own vote in the same round-trip — the thing whose absence made the old like
button reset on every page load.
"""

import logging
from datetime import datetime, UTC
from typing import Any, Optional

from models.community import (
    BoardStats,
    LinkPreview,
    Post,
    PostAuthor,
    TrendingAsset,
)

from . import _db
from .errors import InvalidRequest, NotFound, NotOwner

logger = logging.getLogger(__name__)

TABLE = "community_posts"


def to_post(row: dict) -> Post:
    """Map one `community_post_row` from the RPC onto the API model."""
    link: Optional[LinkPreview] = None
    if row.get("link_url"):
        link = LinkPreview(
            url=row["link_url"],
            title=row.get("link_title"),
            description=row.get("link_description"),
            image_url=row.get("link_image_url"),
            site_name=row.get("link_site_name"),
        )

    return Post(
        id=row["id"],
        type=row["type"],
        post_kind=row.get("post_kind") or "text",
        title=row.get("title"),
        content=row.get("content") or "",
        asset_symbol=row.get("asset_symbol"),
        image_url=row.get("image_url"),
        link=link,
        score=row.get("score") or 0,
        comments_count=row.get("comments_count") or 0,
        is_edited=bool(row.get("is_edited")),
        created_at=row["created_at"],
        updated_at=row.get("updated_at"),
        author=PostAuthor(
            id=row.get("user_id"),
            full_name=row.get("author_name"),
            avatar_url=row.get("author_avatar_url"),
            subscription_plan=row.get("author_plan"),
        ),
        my_vote=row.get("my_vote") or 0,
    )


async def list_posts(
    *,
    sort: str = "hot",
    post_type: Optional[str] = None,
    symbol: Optional[str] = None,
    author_id: Optional[str] = None,
    viewer_id: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> list:
    """One page of the feed. Returns `[]` rather than raising if the DB is down."""
    try:
        rows = await _db.rpc(
            "get_community_feed",
            {
                "p_sort": sort,
                "p_type": post_type,
                "p_symbol": symbol,
                "p_author": author_id,
                "p_post_id": None,
                "p_viewer": viewer_id,
                "p_limit": limit,
                "p_offset": offset,
            },
        )
    except Exception:
        # A feed is a read: an empty board degrades better than a 500.
        logger.exception("community: feed query failed, serving an empty page")
        return []
    return [to_post(row) for row in rows]


async def get_post(post_id: str, viewer_id: Optional[str] = None) -> Post:
    rows = await _db.rpc("get_community_post", {"p_post_id": post_id, "p_viewer": viewer_id})
    if not rows:
        raise NotFound(f"post {post_id} does not exist")
    return to_post(rows[0])


async def create_post(
    *,
    user_id: str,
    post_type: str,
    post_kind: str,
    content: str,
    title: Optional[str] = None,
    asset_symbol: Optional[str] = None,
    image_url: Optional[str] = None,
    link: Optional[LinkPreview] = None,
) -> Post:
    """
    Insert a post authored by `user_id`.

    The OpenGraph metadata for a link post is written onto the row here, so the
    feed never re-fetches a third-party page just to render a card.
    """
    if post_kind == "link" and not (link and link.url):
        raise InvalidRequest("a link post needs a URL")
    if post_kind == "image" and not image_url:
        raise InvalidRequest("an image post needs an image")

    payload: dict = {
        "user_id": user_id,
        "type": post_type,
        "post_kind": post_kind,
        "content": content,
        "title": title,
        "asset_symbol": asset_symbol,
        "image_url": image_url if post_kind == "image" else None,
    }

    if post_kind == "link" and link:
        payload.update(
            {
                "link_url": link.url,
                "link_title": link.title,
                "link_description": link.description,
                "link_image_url": link.image_url,
                "link_site_name": link.site_name,
                "link_fetched_at": datetime.now(UTC).isoformat(),
            }
        )

    data = await _db.table_op(
        lambda client: client.table(TABLE).insert(payload).execute(),
        what="insert post",
    )
    if not data:
        raise InvalidRequest("the post was rejected by the database")

    return await get_post(data[0]["id"], viewer_id=user_id)


async def update_post(
    *,
    post_id: str,
    user_id: str,
    title: Optional[str] = None,
    content: Optional[str] = None,
    asset_symbol: Optional[str] = None,
) -> Post:
    await _assert_owner(post_id, user_id)

    patch: dict[str, Any] = {
        "is_edited": True,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if title is not None:
        patch["title"] = title
    if content is not None:
        patch["content"] = content
    if asset_symbol is not None:
        patch["asset_symbol"] = asset_symbol

    await _db.table_op(
        lambda client: (
            client.table(TABLE).update(patch).eq("id", post_id).eq("user_id", user_id).execute()
        ),
        what="update post",
    )
    return await get_post(post_id, viewer_id=user_id)


async def delete_post(*, post_id: str, user_id: str) -> None:
    """
    Hard delete. Comments and votes cascade away with the post, which is the
    right outcome here — unlike a comment, a post has no children that need to
    outlive it.
    """
    await _assert_owner(post_id, user_id)
    await _delete(post_id, owner_id=user_id)


async def delete_post_as_moderator(*, post_id: str) -> None:
    """
    The same delete without the ownership check, for an admin removing someone
    else's post. Authorization happened at the router (`require_admin`).

    The existence check is not optional: a delete matching zero rows is not an
    error in PostgREST, so without it a mistyped id would return 204 and the
    moderator would believe something was removed.
    """
    await _load_author(post_id)
    await _delete(post_id, owner_id=None)


async def _delete(post_id: str, *, owner_id: Optional[str]) -> None:
    """
    Shared body. `owner_id` adds a redundant second filter on the owner path —
    belt and braces after `_assert_owner` — and is omitted for a moderator.
    """

    def _call(client: Any) -> Any:
        query = client.table(TABLE).delete().eq("id", post_id)
        if owner_id is not None:
            query = query.eq("user_id", owner_id)
        return query.execute()

    await _db.table_op(_call, what="delete post")


async def get_trending_assets(days: int = 7, limit: int = 8) -> list:
    try:
        rows = await _db.rpc("get_community_trending_assets", {"p_days": days, "p_limit": limit})
    except Exception:
        logger.exception("community: trending assets query failed")
        return []
    return [
        TrendingAsset(
            asset_symbol=row["asset_symbol"],
            post_count=row.get("post_count") or 0,
            total_score=row.get("total_score") or 0,
        )
        for row in rows
    ]


async def get_stats() -> BoardStats:
    try:
        rows = await _db.rpc("get_community_stats", {})
    except Exception:
        logger.exception("community: stats query failed")
        rows = []
    if not rows:
        return BoardStats(total_posts=0, posts_today=0, contributors=0)
    row = rows[0]
    return BoardStats(
        total_posts=row.get("total_posts") or 0,
        posts_today=row.get("posts_today") or 0,
        contributors=row.get("contributors") or 0,
    )


async def _assert_owner(post_id: str, user_id: str) -> None:
    """
    Confirm the caller wrote the post before letting them change it.

    RLS would normally do this, but the backend holds the service-role key and
    bypasses it, so the check has to happen here.
    """
    if await _load_author(post_id) != user_id:
        raise NotOwner(f"post {post_id} belongs to another user")


async def _load_author(post_id: str) -> str:
    """The post's author id, or `NotFound` if there is no such post."""
    data = await _db.table_op(
        lambda client: client.table(TABLE).select("user_id").eq("id", post_id).execute(),
        what="load post owner",
    )
    if not data:
        raise NotFound(f"post {post_id} does not exist")
    return data[0]["user_id"]
