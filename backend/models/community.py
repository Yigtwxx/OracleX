"""
Pydantic schemas for the community board.

Request models deliberately never carry a `user_id`: the author is taken from
the verified JWT, never from the request body. Response models mirror the row
shapes returned by the `get_community_*` RPCs in
`supabase/migrations/007_community_reddit.sql`.
"""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# The topical flair, unchanged from 005. Orthogonal to PostKind.
PostType = Literal["question", "thought", "analysis"]

# How the post renders.
PostKind = Literal["text", "image", "link"]

FeedSort = Literal["hot", "new", "top"]

MAX_TITLE_LENGTH = 300
MAX_CONTENT_LENGTH = 20_000
MAX_COMMENT_LENGTH = 10_000


# ═══════════════════════════════════════════════════════════════════════════════
# REQUESTS
# ═══════════════════════════════════════════════════════════════════════════════


class CreatePostRequest(BaseModel):
    """A new post. `post_kind` decides which payload field is required."""

    type: PostType
    post_kind: PostKind = "text"
    title: Optional[str] = Field(default=None, max_length=MAX_TITLE_LENGTH)
    content: str = Field(min_length=1, max_length=MAX_CONTENT_LENGTH)
    asset_symbol: Optional[str] = Field(default=None, max_length=20)
    image_url: Optional[str] = None
    link_url: Optional[str] = None

    @field_validator("asset_symbol")
    @classmethod
    def _normalize_symbol(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        symbol = value.strip().upper()
        return symbol or None

    @field_validator("title", "content")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None


class UpdatePostRequest(BaseModel):
    """
    A partial edit. The post's kind is immutable — changing a text post into a
    link post after people have voted on it would misrepresent what they voted
    for, so a different kind means a different post.
    """

    title: Optional[str] = Field(default=None, max_length=MAX_TITLE_LENGTH)
    content: Optional[str] = Field(default=None, min_length=1, max_length=MAX_CONTENT_LENGTH)
    asset_symbol: Optional[str] = Field(default=None, max_length=20)

    @field_validator("asset_symbol")
    @classmethod
    def _normalize_symbol(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        symbol = value.strip().upper()
        return symbol or None


class CreateCommentRequest(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_COMMENT_LENGTH)
    # None for a top-level comment. Depth is derived from the parent by a
    # database trigger, never sent by the client.
    parent_id: Optional[str] = None


class UpdateCommentRequest(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_COMMENT_LENGTH)


class VoteRequest(BaseModel):
    """`1` upvote, `-1` downvote, `0` clears an existing vote."""

    value: Literal[-1, 0, 1]


class LinkPreviewRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


# ═══════════════════════════════════════════════════════════════════════════════
# RESPONSES
# ═══════════════════════════════════════════════════════════════════════════════


class PostAuthor(BaseModel):
    id: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    subscription_plan: Optional[str] = None


class LinkPreview(BaseModel):
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    site_name: Optional[str] = None


class Post(BaseModel):
    id: str
    type: PostType
    post_kind: PostKind
    title: Optional[str] = None
    content: str
    asset_symbol: Optional[str] = None
    image_url: Optional[str] = None
    link: Optional[LinkPreview] = None
    score: int
    comments_count: int
    is_edited: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    author: PostAuthor
    # The viewer's own vote: 1, -1, or 0 when they have not voted or are signed
    # out. This is the field whose absence made the old heart icon reset on
    # every page load.
    my_vote: int = 0


class PostFeed(BaseModel):
    posts: List[Post]
    # True when the page came back full, i.e. there is probably another one.
    has_more: bool


class Comment(BaseModel):
    id: str
    post_id: str
    parent_id: Optional[str] = None
    # None for a tombstoned comment — the row survives to hold its replies, the
    # text does not.
    content: Optional[str] = None
    score: int
    depth: int
    is_edited: bool
    is_deleted: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    author: PostAuthor
    my_vote: int = 0
    replies: List["Comment"] = Field(default_factory=list)


# `Comment.replies` is a forward reference to the class being defined; resolve it
# now rather than leaving the first request to discover an unbuilt model.
Comment.model_rebuild()


class CommentThread(BaseModel):
    comments: List[Comment]
    total: int


class VoteResult(BaseModel):
    score: int
    my_vote: int


class UploadedMedia(BaseModel):
    url: str
    path: str


class TrendingAsset(BaseModel):
    asset_symbol: str
    post_count: int
    total_score: int


class BoardStats(BaseModel):
    total_posts: int
    posts_today: int
    contributors: int


class CommunitySidebar(BaseModel):
    trending: List[TrendingAsset]
    stats: BoardStats
