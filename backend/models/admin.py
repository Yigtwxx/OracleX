"""
Request and response models for the admin panel.

Mirrors `models/community.py`: `Literal` aliases for anything that reaches a SQL
ORDER BY or a CHECK constraint, `Field` constraints for lengths and ranges, and
requests that never carry the actor — the actor always comes from the verified
token, never from the body.
"""

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# Mirrors the CHECK constraint on profiles.subscription_plan (004).
PlanName = Literal["free", "pro", "whale"]
UserStatus = Literal["all", "active", "banned"]
# These two reach an ORDER BY inside get_admin_users, so they are closed sets
# rather than free text.
UserSort = Literal["created_at", "email", "subscription_plan"]
SortOrder = Literal["asc", "desc"]
AuditTargetType = Literal["user", "post", "comment"]

MAX_REASON_LENGTH = 500
MAX_SEARCH_LENGTH = 100


# ── Requests ────────────────────────────────────────────────────────────────


class SetPlanRequest(BaseModel):
    """
    `duration_days` omitted means the plan does not expire.

    That is the useful default for an admin grant: `get_subscription`
    auto-downgrades an expired plan, so a dated whale would silently revert.
    """

    plan: PlanName
    duration_days: Optional[int] = Field(default=None, ge=1, le=3650)


class BanUserRequest(BaseModel):
    """`days` omitted means a permanent suspension."""

    days: Optional[int] = Field(default=None, ge=1, le=3650)
    reason: Optional[str] = Field(default=None, max_length=MAX_REASON_LENGTH)


# ── Responses ───────────────────────────────────────────────────────────────


class AdminSession(BaseModel):
    """
    The answer to "does this caller get the panel".

    Returned with 200 and `is_admin: false` to a non-admin rather than a 403, so
    the client can tell "not an admin" from "the backend is down" — and so the
    endpoint is not itself an admin-detector.
    """

    is_admin: bool
    email: Optional[str] = None


class AdminUser(BaseModel):
    id: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    subscription_plan: str = "free"
    subscription_expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    banned_until: Optional[datetime] = None
    ban_reason: Optional[str] = None
    # Computed, not stored: `banned_until` in the future.
    is_banned: bool = False
    # Computed from ADMIN_EMAILS. Drives the disabled actions on the admin's own
    # row; the server refuses regardless.
    is_admin: bool = False
    posts_count: int = 0
    comments_count: int = 0


class AdminUserPage(BaseModel):
    users: List[AdminUser]
    total: int
    limit: int
    offset: int


class AdminPostSummary(BaseModel):
    id: str
    title: Optional[str] = None
    content_preview: str = ""
    type: str
    post_kind: str
    score: int = 0
    comments_count: int = 0
    created_at: Optional[datetime] = None
    author_id: Optional[str] = None
    author_name: Optional[str] = None
    author_email: Optional[str] = None


class AdminPostPage(BaseModel):
    posts: List[AdminPostSummary]
    total: int
    limit: int
    offset: int


class AdminOverview(BaseModel):
    total_users: int = 0
    banned_users: int = 0
    new_users_7d: int = 0
    plan_counts: Dict[str, int] = Field(default_factory=dict)
    total_posts: int = 0
    posts_today: int = 0
    total_comments: int = 0


class AuditEntry(BaseModel):
    id: str
    actor_id: Optional[str] = None
    actor_email: Optional[str] = None
    action: str
    target_type: str
    target_id: Optional[str] = None
    reason: Optional[str] = None
    metadata: Dict = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class AuditPage(BaseModel):
    entries: List[AuditEntry]
    total: int
    limit: int
    offset: int
