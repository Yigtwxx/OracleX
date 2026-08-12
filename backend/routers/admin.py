"""
Admin Router.

Two router objects, and the split matters:

  * `session_router` carries only `/me`, guarded by `get_current_user`. A
    non-admin gets 200 with `is_admin: false`, not a 403 — otherwise the client
    cannot tell "not an admin" from "the backend is down", and the endpoint
    becomes an admin-detector that answers by which error it returns.
  * `router` carries everything else and declares `require_admin` as a
    *router-level* dependency, so a route added to this file later cannot be
    left unguarded by omission. Under the service-role key one unguarded admin
    route is not a weaker check, it is no check.

The actor always comes from the verified token. No request body carries one.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from dependencies.auth import AuthUser, get_current_user, is_admin, require_admin
from models.admin import (
    AdminOverview,
    AdminPostPage,
    AdminSession,
    AdminUser,
    AdminUserPage,
    AuditPage,
    BanUserRequest,
    MAX_REASON_LENGTH,
    MAX_SEARCH_LENGTH,
    SetPlanRequest,
    SortOrder,
    UserSort,
    UserStatus,
)
from services import admin
from services.admin import audit as audit_service
from services.admin import moderation as moderation_service
from services.admin import users as user_service

logger = logging.getLogger(__name__)

session_router = APIRouter(prefix="/api/admin", tags=["admin"])
router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


def _http_error(exc: admin.AdminError) -> HTTPException:
    """Map a service error onto a status code. The only place that knows both."""
    if isinstance(exc, admin.NotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, admin.ProtectedTarget):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, admin.InvalidRequest):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=502, detail="The admin service is unavailable right now")


def _actor(user: AuthUser) -> admin.AuditActor:
    return admin.AuditActor(id=user.id, email=user.email)


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION
# ═══════════════════════════════════════════════════════════════════════════════


@session_router.get("/me", response_model=AdminSession)
async def read_admin_session(user: AuthUser = Depends(get_current_user)) -> AdminSession:
    """
    Whether the caller gets the panel. Signed in is enough to ask; the answer is
    a boolean, not an error.
    """
    granted = is_admin(user)
    return AdminSession(is_admin=granted, email=user.email if granted else None)


# ═══════════════════════════════════════════════════════════════════════════════
# OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/overview", response_model=AdminOverview)
async def read_overview() -> AdminOverview:
    try:
        return await user_service.get_overview()
    except admin.AdminError as exc:
        raise _http_error(exc)


# ═══════════════════════════════════════════════════════════════════════════════
# USERS
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/users", response_model=AdminUserPage)
async def list_users(
    search: Optional[str] = Query(None, max_length=MAX_SEARCH_LENGTH),
    plan: Optional[str] = Query(None, pattern="^(free|pro|whale)$"),
    status: UserStatus = "all",
    # `sort` and `order` reach an ORDER BY inside the RPC. Closed sets, never
    # free text.
    sort: UserSort = "created_at",
    order: SortOrder = "desc",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AdminUserPage:
    try:
        return await user_service.list_users(
            search=search,
            plan=plan,
            status=status,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
        )
    except admin.AdminError as exc:
        raise _http_error(exc)


@router.get("/users/{user_id}", response_model=AdminUser)
async def read_user(user_id: str) -> AdminUser:
    try:
        return await user_service.get_user(user_id)
    except admin.AdminError as exc:
        raise _http_error(exc)


@router.post("/users/{user_id}/plan", response_model=AdminUser)
async def set_user_plan(
    user_id: str,
    payload: SetPlanRequest,
    actor: AuthUser = Depends(require_admin),
) -> AdminUser:
    try:
        return await user_service.set_plan(
            user_id=user_id,
            plan=payload.plan,
            duration_days=payload.duration_days,
            actor=_actor(actor),
        )
    except admin.AdminError as exc:
        raise _http_error(exc)


@router.post("/users/{user_id}/ban", response_model=AdminUser)
async def ban_user(
    user_id: str,
    payload: BanUserRequest,
    actor: AuthUser = Depends(require_admin),
) -> AdminUser:
    try:
        return await user_service.ban_user(
            user_id=user_id,
            days=payload.days,
            reason=payload.reason,
            actor=_actor(actor),
        )
    except admin.AdminError as exc:
        raise _http_error(exc)


@router.post("/users/{user_id}/unban", response_model=AdminUser)
async def unban_user(
    user_id: str,
    actor: AuthUser = Depends(require_admin),
) -> AdminUser:
    try:
        return await user_service.unban_user(user_id=user_id, actor=_actor(actor))
    except admin.AdminError as exc:
        raise _http_error(exc)


# ═══════════════════════════════════════════════════════════════════════════════
# MODERATION
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/content/posts", response_model=AdminPostPage)
async def list_posts(
    search: Optional[str] = Query(None, max_length=MAX_SEARCH_LENGTH),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> AdminPostPage:
    try:
        return await moderation_service.list_posts(search=search, limit=limit, offset=offset)
    except admin.AdminError as exc:
        raise _http_error(exc)


@router.delete("/posts/{post_id}", status_code=204, response_class=Response)
async def delete_post(
    post_id: str,
    reason: Optional[str] = Query(None, max_length=MAX_REASON_LENGTH),
    actor: AuthUser = Depends(require_admin),
) -> Response:
    try:
        await moderation_service.delete_post(post_id=post_id, actor=_actor(actor), reason=reason)
    except admin.AdminError as exc:
        raise _http_error(exc)
    return Response(status_code=204)


@router.delete("/comments/{comment_id}", status_code=204, response_class=Response)
async def delete_comment(
    comment_id: str,
    reason: Optional[str] = Query(None, max_length=MAX_REASON_LENGTH),
    actor: AuthUser = Depends(require_admin),
) -> Response:
    try:
        await moderation_service.delete_comment(
            comment_id=comment_id, actor=_actor(actor), reason=reason
        )
    except admin.AdminError as exc:
        raise _http_error(exc)
    return Response(status_code=204)


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/audit", response_model=AuditPage)
async def list_audit(
    target_type: Optional[str] = Query(None, pattern="^(user|post|comment)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AuditPage:
    try:
        entries, total = await audit_service.list_entries(
            limit=limit, offset=offset, target_type=target_type
        )
    except admin.AdminError as exc:
        raise _http_error(exc)
    return AuditPage(entries=entries, total=total, limit=limit, offset=offset)
