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
"""

import asyncio
import logging
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

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


class AuthUser(BaseModel):
    """The authenticated caller, resolved from a verified Supabase JWT."""

    id: str
    email: Optional[str] = None


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

    return AuthUser(id=user.id, email=getattr(user, "email", None))


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

    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[AuthUser]:
    """
    Resolve the caller if a valid token was supplied, otherwise return None.

    For endpoints that are readable anonymously but personalize their response
    when the caller is known. Never use this to guard a mutation.
    """
    if credentials is None or not credentials.credentials:
        return None

    return await asyncio.to_thread(_resolve_user, credentials.credentials)
