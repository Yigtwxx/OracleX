"""
User administration: the list, the plan, the suspension.

Everything that needs a search, a filter, a sort, a page and per-user counts
goes through the `get_admin_users` RPC (010_admin.sql) rather than PostgREST.
Six things in one round-trip is the smaller reason; the larger one is that the
RPC takes the search as a *bound parameter*, whereas PostgREST's
`.or_("email.ilike.%q%,...")` takes a raw filter string that a comma or a
parenthesis in the search box could restructure.
"""

import logging
from datetime import datetime, timedelta, UTC
from typing import Optional

from models.admin import AdminOverview, AdminUser, AdminUserPage

from . import _db, audit, bans
from .audit import AuditActor
from .errors import InvalidRequest, NotFound, ProtectedTarget
from .identity import is_admin_email

logger = logging.getLogger(__name__)

TABLE = "profiles"
PLANS = ("free", "pro", "whale")


async def list_users(
    *,
    search: Optional[str] = None,
    plan: Optional[str] = None,
    status: str = "all",
    sort: str = "created_at",
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> AdminUserPage:
    rows = await _db.rpc(
        "get_admin_users",
        {
            "p_user_id": None,
            "p_search": search,
            "p_plan": plan,
            "p_status": status,
            "p_sort": sort,
            "p_order": order,
            "p_limit": limit,
            "p_offset": offset,
        },
    )
    users = [_to_user(row) for row in rows]
    # total_count is the same on every row; an empty page means an empty result.
    total = rows[0].get("total_count") or 0 if rows else 0
    return AdminUserPage(users=users, total=total, limit=limit, offset=offset)


async def get_user(user_id: str) -> AdminUser:
    rows = await _db.rpc(
        "get_admin_users",
        {
            "p_user_id": user_id,
            "p_search": None,
            "p_plan": None,
            "p_status": "all",
            "p_sort": "created_at",
            "p_order": "desc",
            "p_limit": 1,
            "p_offset": 0,
        },
    )
    if not rows:
        raise NotFound(f"user {user_id} does not exist")
    return _to_user(rows[0])


async def set_plan(
    *,
    user_id: str,
    plan: str,
    duration_days: Optional[int] = None,
    actor: AuditActor,
) -> AdminUser:
    """
    Move a user onto a plan, optionally with an expiry.

    Deliberately not `profile_service.update_subscription`: that helper always
    dates the plan (30 days by default), and `get_subscription` silently
    downgrades an expired plan to free. An admin grant with no `duration_days`
    has to mean *no expiry*, or the grant quietly undoes itself.
    """
    if plan not in PLANS:
        raise InvalidRequest(f"{plan} is not a plan")

    target = await get_user(user_id)

    expires_at: Optional[str] = None
    if duration_days is not None and plan != "free":
        expires_at = (datetime.now(UTC) + timedelta(days=duration_days)).isoformat()

    await _write(
        user_id,
        {
            "subscription_plan": plan,
            "subscription_expires_at": expires_at,
            "updated_at": datetime.now(UTC).isoformat(),
        },
        what="set plan",
    )

    await audit.record(
        actor=actor,
        action="user.plan",
        target_type="user",
        target_id=user_id,
        metadata={
            "email": target.email,
            "from": target.subscription_plan,
            "to": plan,
            "duration_days": duration_days,
        },
    )
    return await get_user(user_id)


async def ban_user(
    *,
    user_id: str,
    days: Optional[int] = None,
    reason: Optional[str] = None,
    actor: AuditActor,
) -> AdminUser:
    """
    Suspend an account. `days` omitted means permanently.

    The two refusals are not optional. A suspension is enforced in
    `get_current_user`, so an admin who suspends their own account — or the
    other way into the same hole, another admin account — locks away every
    authenticated route including the one that would undo it. Only a manual SQL
    edit would recover it.
    """
    target = await get_user(user_id)

    if user_id == actor.id:
        raise ProtectedTarget("you cannot suspend your own account")
    if is_admin_email(target.email):
        raise ProtectedTarget("admin accounts cannot be suspended")

    until = bans.PERMANENT_UNTIL if days is None else datetime.now(UTC) + timedelta(days=days)
    await _write(
        user_id,
        {
            "banned_until": until.isoformat(),
            "ban_reason": reason,
            "banned_at": datetime.now(UTC).isoformat(),
            "banned_by": actor.id,
            "updated_at": datetime.now(UTC).isoformat(),
        },
        what="ban user",
    )
    await bans.invalidate(user_id)

    await audit.record(
        actor=actor,
        action="user.ban",
        target_type="user",
        target_id=user_id,
        reason=reason,
        metadata={"email": target.email, "until": until.isoformat(), "days": days},
    )
    return await get_user(user_id)


async def unban_user(*, user_id: str, actor: AuditActor) -> AdminUser:
    target = await get_user(user_id)

    await _write(
        user_id,
        {
            "banned_until": None,
            "ban_reason": None,
            "banned_at": None,
            "banned_by": None,
            "updated_at": datetime.now(UTC).isoformat(),
        },
        what="unban user",
    )
    await bans.invalidate(user_id)

    await audit.record(
        actor=actor,
        action="user.unban",
        target_type="user",
        target_id=user_id,
        metadata={"email": target.email},
    )
    return await get_user(user_id)


async def get_overview() -> AdminOverview:
    rows = await _db.rpc("get_admin_overview", {})
    if not rows:
        return AdminOverview()
    row = rows[0]
    return AdminOverview(
        total_users=row.get("total_users") or 0,
        banned_users=row.get("banned_users") or 0,
        new_users_7d=row.get("new_users_7d") or 0,
        plan_counts={
            "free": row.get("free_users") or 0,
            "pro": row.get("pro_users") or 0,
            "whale": row.get("whale_users") or 0,
        },
        total_posts=row.get("total_posts") or 0,
        posts_today=row.get("posts_today") or 0,
        total_comments=row.get("total_comments") or 0,
    )


async def _write(user_id: str, patch: dict, *, what: str) -> None:
    await _db.table_op(
        lambda client: client.table(TABLE).update(patch).eq("id", user_id).execute(),
        what=what,
    )


def _to_user(row: dict) -> AdminUser:
    banned_until = row.get("banned_until")
    return AdminUser(
        id=str(row.get("id")),
        email=row.get("email"),
        full_name=row.get("full_name"),
        avatar_url=row.get("avatar_url"),
        subscription_plan=row.get("subscription_plan") or "free",
        subscription_expires_at=row.get("subscription_expires_at"),
        created_at=row.get("created_at"),
        banned_until=banned_until,
        ban_reason=row.get("ban_reason"),
        is_banned=_is_future(banned_until),
        is_admin=is_admin_email(row.get("email")),
        posts_count=row.get("posts_count") or 0,
        comments_count=row.get("comments_count") or 0,
    )


def _is_future(value: object) -> bool:
    parsed = bans.parse_timestamp(value)
    return parsed is not None and parsed > datetime.now(UTC)
