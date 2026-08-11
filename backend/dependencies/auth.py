"""
Authentication dependencies.

The backend talks to Supabase with the *service role* key, which bypasses
Row Level Security (see `config.supabase_backend_key`). That means Supabase
provides no per-user protection here and authorization has to be enforced in
the application layer — which is exactly what this module does.

Every user-scoped endpoint must depend on `get_current_user` and take the
caller's identity from the returned `AuthUser`. A `user_id` supplied by the
client in a path, query, or body parameter is untrusted and must never be
used to select or mutate rows.

Usage:
    from dependencies.auth import AuthUser, get_current_user

    @router.get("/api/profile")
    async def read_profile(user: AuthUser = Depends(get_current_user)):
        return await profile_service.get_user_profile(user.id)

Two things happen on top of that:

  * `get_current_user` also refuses a suspended account. It is the one choke
    point every authenticated route already passes through, so a suspension
    cannot be forgotten on a route somebody adds later.
  * `require_admin` narrows the caller to the ADMIN_EMAILS list. Adminship is
    an environment variable rather than a database column precisely because a
    request can write the database and cannot write the environment.
"""

import asyncio
import logging
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from services.admin import bans
from services.admin.identity import is_admin_email
from services.supabase_service import get_supabase

logger = logging.getLogger(__name__)

# `auto_error=False` so a missing header produces our own 401 with a
# consistent body instead of FastAPI's default 403.
_bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)

_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Admin only",
)


def _suspended(ban: bans.BanState) -> HTTPException:
    """
    403, not 401.

    A 401 makes the Supabase client refresh the token, succeed, retry, and loop;
    the caller never sees why. 403 is terminal and the detail is renderable.
    """
    if ban.is_permanent:
        detail = "Your account has been suspended"
    else:
        detail = f"Your account is suspended until {ban.until:%Y-%m-%d %H:%M} UTC"
    if ban.reason:
        detail = f"{detail} — {ban.reason}"
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class AuthUser(BaseModel):
    """The authenticated caller, resolved from a verified Supabase JWT."""

    id: str
    email: Optional[str] = None
    # Whether GoTrue has confirmed the address. Adminship is decided by email,
    # so an unconfirmed one must not count: if email confirmation is ever turned
    # off on the Supabase project, signing up as the admin address would
    # otherwise be enough to become an admin.
    email_verified: bool = False


def _resolve_user(token: str) -> Optional[AuthUser]:
    """
    Verify `token` against Supabase and return the user it belongs to.

    Runs the blocking supabase-py call; callers must offload it to a thread.
    Returns None when the token is absent, expired, or otherwise invalid.
    """
    try:
        response = get_supabase().auth.get_user(token)
    except Exception as e:
        # Invalid/expired tokens surface as exceptions from gotrue. Log at
        # debug so a stream of bad tokens can't flood the logs, and never log
        # the token itself.
        logger.debug("Token verification failed: %s", type(e).__name__)
        return None

    user = getattr(response, "user", None)
    if user is None or not getattr(user, "id", None):
        return None

    return AuthUser(
        id=user.id,
        email=getattr(user, "email", None),
        email_verified=getattr(user, "email_confirmed_at", None) is not None,
    )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> AuthUser:
    """
    Resolve the caller from the `Authorization: Bearer <jwt>` header.

    Raises 401 if the header is missing or the token does not verify.
    """
    if credentials is None or not credentials.credentials:
        raise _UNAUTHENTICATED

    user = await asyncio.to_thread(_resolve_user, credentials.credentials)
    if user is None:
        raise _UNAUTHENTICATED

    # Suspensions are enforced here rather than route by route. Authenticated
    # writes are spread across five routers; an opt-in check is one forgotten
    # decorator away from being no check at all, and under the service-role key
    # there is no second line of defence behind it.
    ban = await bans.check(user.id)
    if ban is not None:
        raise _suspended(ban)

    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[AuthUser]:
    """
    Resolve the caller if a valid token was supplied, otherwise return None.

    For endpoints that are readable anonymously but personalize their response
    when the caller is known. Never use this to guard a mutation.

    Deliberately does not check for a suspension: every route that uses this is
    readable by a signed-out visitor anyway, so blocking a suspended reader
    would hide from them what it shows to everyone else.
    """
    if credentials is None or not credentials.credentials:
        return None

    return await asyncio.to_thread(_resolve_user, credentials.credentials)


def is_admin(user: Optional[AuthUser]) -> bool:
    """
    Whether `user` gets the admin panel.

    Two conditions, both required: the address is on the ADMIN_EMAILS list, and
    GoTrue has confirmed it.
    """
    if user is None or not user.email_verified:
        return False
    return is_admin_email(user.email)


async def require_admin(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    """
    Guard for every admin route.

    The 401/403 split falls out of the dependency chain: a caller with no token
    never gets here, because `get_current_user` has already raised. Only a valid
    token that is not on the list reaches the 403.
    """
    if not is_admin(user):
        # Worth a log line: on this backend an unexpected 403 here is either a
        # misconfigured ADMIN_EMAILS or somebody probing.
        logger.warning("admin: refused non-admin caller %s", user.id)
        raise _FORBIDDEN
    return user
