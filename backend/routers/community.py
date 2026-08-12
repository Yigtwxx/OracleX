"""
Community Router — a Reddit-style board.

Reads are public and take `get_optional_user`, because the viewer's own vote is
part of a feed row: signed out you still see the board, you just see `my_vote`
as 0 everywhere. Writes take `get_current_user`, and the author id always comes
from the verified JWT — never from the request body.

Ownership on PATCH and DELETE is enforced in the service layer. The backend
connects with the service-role key and therefore bypasses row-level security, so
those checks are not a second line of defence, they are the only one.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from dependencies.auth import AuthUser, get_current_user, get_optional_user
from models.community import (
    BoardStats,
    Comment,
    CommentThread,
    CommunitySidebar,
    CreateCommentRequest,
    CreatePostRequest,
    LinkPreview,
    LinkPreviewRequest,
    Post,
    PostFeed,
    UpdateCommentRequest,
    UpdatePostRequest,
    UploadedMedia,
    VoteRequest,
    VoteResult,
)
from services import community
from services.community import comments as comment_service
from services.community import link_preview as link_service
from services.community import media as media_service
from services.community import posts as post_service
from services.community import votes as vote_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/community", tags=["community"])

MAX_UPLOAD_BYTES = media_service.MAX_BYTES


def _http_error(exc: community.CommunityError) -> HTTPException:
    """Map a service error onto a status code. The only place that knows both."""
    if isinstance(exc, community.NotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, community.NotOwner):
        return HTTPException(status_code=403, detail="That is not yours to change")
    if isinstance(exc, community.InvalidRequest):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=502, detail="The board is unavailable right now")


def _viewer_id(user: Optional[AuthUser]) -> Optional[str]:
    return user.id if user else None


# ═══════════════════════════════════════════════════════════════════════════════
# FEED
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/posts", response_model=PostFeed)
async def get_posts(
    sort: str = Query("hot", pattern="^(hot|new|top)$"),
    type: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    user: Optional[AuthUser] = Depends(get_optional_user),
):
    """One page of the board. Public."""
    posts = await post_service.list_posts(
        sort=sort,
        post_type=None if type in (None, "", "all") else type,
        symbol=symbol.upper() if symbol else None,
        viewer_id=_viewer_id(user),
        limit=limit,
        offset=offset,
    )
    return PostFeed(posts=posts, has_more=len(posts) == limit)


@router.get("/posts/user/{user_id}", response_model=PostFeed)
async def get_user_posts(
    user_id: str,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    user: Optional[AuthUser] = Depends(get_optional_user),
):
    """Everything one author has written. Public — posts are world-readable."""
    posts = await post_service.list_posts(
        sort="new",
        author_id=user_id,
        viewer_id=_viewer_id(user),
        limit=limit,
        offset=offset,
    )
    return PostFeed(posts=posts, has_more=len(posts) == limit)


@router.get("/sidebar", response_model=CommunitySidebar)
async def get_sidebar():
    """Trending tickers and board counters. Public."""
    trending = await post_service.get_trending_assets()
    stats = await post_service.get_stats()
    return CommunitySidebar(trending=trending, stats=stats)


@router.get("/stats", response_model=BoardStats)
async def get_stats():
    return await post_service.get_stats()


# ═══════════════════════════════════════════════════════════════════════════════
# POSTS
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/posts/{post_id}", response_model=Post)
async def get_post(post_id: str, user: Optional[AuthUser] = Depends(get_optional_user)):
    try:
        return await post_service.get_post(post_id, viewer_id=_viewer_id(user))
    except community.CommunityError as exc:
        raise _http_error(exc)


@router.post("/posts", response_model=Post, status_code=201)
async def create_post(request: CreatePostRequest, user: AuthUser = Depends(get_current_user)):
    """
    Create a post.

    For a link post the OpenGraph metadata is fetched here and stored on the
    row, so rendering the feed never touches a third-party server. A preview
    that cannot be fetched is not fatal — the card falls back to the bare
    domain rather than refusing the post.
    """
    link: Optional[LinkPreview] = None
    if request.post_kind == "link" and request.link_url:
        try:
            link = await link_service.fetch_link_preview(request.link_url)
        except community.InvalidRequest as exc:
            raise _http_error(exc)
        except community.CommunityError as exc:
            logger.info("community: link preview unavailable, posting bare link (%s)", exc)
            link = LinkPreview(url=request.link_url)

    try:
        return await post_service.create_post(
            user_id=user.id,
            post_type=request.type,
            post_kind=request.post_kind,
            content=request.content,
            title=request.title,
            asset_symbol=request.asset_symbol,
            image_url=request.image_url,
            link=link,
        )
    except community.CommunityError as exc:
        raise _http_error(exc)


@router.patch("/posts/{post_id}", response_model=Post)
async def update_post(
    post_id: str,
    request: UpdatePostRequest,
    user: AuthUser = Depends(get_current_user),
):
    try:
        return await post_service.update_post(
            post_id=post_id,
            user_id=user.id,
            title=request.title,
            content=request.content,
            asset_symbol=request.asset_symbol,
        )
    except community.CommunityError as exc:
        raise _http_error(exc)


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(post_id: str, user: AuthUser = Depends(get_current_user)):
    try:
        await post_service.delete_post(post_id=post_id, user_id=user.id)
    except community.CommunityError as exc:
        raise _http_error(exc)


# ═══════════════════════════════════════════════════════════════════════════════
# COMMENTS
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/posts/{post_id}/comments", response_model=CommentThread)
async def get_comments(post_id: str, user: Optional[AuthUser] = Depends(get_optional_user)):
    """The whole thread as a tree. Public."""
    tree, total = await comment_service.list_comments(post_id, viewer_id=_viewer_id(user))
    return CommentThread(comments=tree, total=total)


@router.post("/posts/{post_id}/comments", response_model=Comment, status_code=201)
async def create_comment(
    post_id: str,
    request: CreateCommentRequest,
    user: AuthUser = Depends(get_current_user),
):
    try:
        return await comment_service.create_comment(
            user_id=user.id,
            post_id=post_id,
            content=request.content,
            parent_id=request.parent_id,
        )
    except community.CommunityError as exc:
        raise _http_error(exc)


@router.patch("/comments/{comment_id}", response_model=Comment)
async def update_comment(
    comment_id: str,
    request: UpdateCommentRequest,
    user: AuthUser = Depends(get_current_user),
):
    try:
        return await comment_service.update_comment(
            comment_id=comment_id, user_id=user.id, content=request.content
        )
    except community.CommunityError as exc:
        raise _http_error(exc)


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(comment_id: str, user: AuthUser = Depends(get_current_user)):
    """Tombstones the comment; its replies stay readable."""
    try:
        await comment_service.delete_comment(comment_id=comment_id, user_id=user.id)
    except community.CommunityError as exc:
        raise _http_error(exc)


# ═══════════════════════════════════════════════════════════════════════════════
# VOTES
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/posts/{post_id}/vote", response_model=VoteResult)
async def vote_on_post(
    post_id: str, request: VoteRequest, user: AuthUser = Depends(get_current_user)
):
    try:
        return await vote_service.set_post_vote(
            user_id=user.id, post_id=post_id, value=request.value
        )
    except community.CommunityError as exc:
        raise _http_error(exc)


@router.post("/comments/{comment_id}/vote", response_model=VoteResult)
async def vote_on_comment(
    comment_id: str, request: VoteRequest, user: AuthUser = Depends(get_current_user)
):
    try:
        return await vote_service.set_comment_vote(
            user_id=user.id, comment_id=comment_id, value=request.value
        )
    except community.CommunityError as exc:
        raise _http_error(exc)


# ═══════════════════════════════════════════════════════════════════════════════
# MEDIA & LINK PREVIEW
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/media", response_model=UploadedMedia, status_code=201)
async def upload_media(file: UploadFile = File(...), user: AuthUser = Depends(get_current_user)):
    """
    Upload one image for an image post.

    The body is read with a hard ceiling rather than trusting `content-length`,
    which a client controls.
    """
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Images must be 5 MB or smaller")

    try:
        return await media_service.upload_image(
            user_id=user.id, data=data, declared_name=file.filename
        )
    except community.CommunityError as exc:
        raise _http_error(exc)


@router.post("/link-preview", response_model=LinkPreview)
async def preview_link(request: LinkPreviewRequest, user: AuthUser = Depends(get_current_user)):
    """
    Fetch an OpenGraph card for a URL the composer is about to post.

    Behind auth deliberately: this endpoint makes the server fetch a URL of the
    caller's choosing, and an anonymous version of that is a scanning tool.
    """
    try:
        return await link_service.fetch_link_preview(request.url)
    except community.CommunityError as exc:
        raise _http_error(exc)
