"""
Attribute AI usage recorded during this request to the caller.

`client.generate` never learns who asked — the caller resolves the reader and
passes only a provider — so without this every model call would be recorded as
background work. Binding once per request costs a `ContextVar.set` and leaves
the twelve call sites untouched.

Attached to the routers that can reach a model. A route that never calls one
binds a value nothing reads, which is why this is not global middleware.
"""

import logging
from typing import AsyncIterator, Optional

from fastapi import Depends, Request

from dependencies.auth import AuthUser, get_optional_user
from services.llm import usage

logger = logging.getLogger(__name__)

# Which surface a path belongs to, longest prefix first so /api/chat/history is
# not matched by a shorter rule meant for something else. These are the same
# names llm_settings_service.FEATURES uses, so the usage view and the per-user
# key toggles speak about the same things.
_FEATURE_BY_PREFIX: tuple[tuple[str, str], ...] = (
    ("/api/chat", "chat"),
    ("/api/news", "news"),
    ("/api/analysis", "reports"),
    ("/api/polymarket", "reports"),
    ("/api/ai/notes", "notes"),
)


def feature_for_path(path: str) -> str:
    """
    The feature label for a request path.

    Falls back to "other" rather than to "background": a signed-in reader's
    request is not background work even when it is on a route this map has not
    been taught about, and calling it that would put it in the bucket the usage
    view uses for the schedulers.
    """
    for prefix, feature in _FEATURE_BY_PREFIX:
        if path.startswith(prefix):
            return feature
    return "other"


async def track_ai_usage(
    request: Request,
    user: Optional[AuthUser] = Depends(get_optional_user),
) -> AsyncIterator[None]:
    """
    Record model calls made while serving this request against `user`.

    Anonymous callers still bind, with `user_id=None` — the row then reads as
    install-wide spend, which is true and is the number an operator wants.

    The binding is undone in a `finally` because worker tasks are reused: a
    leaked one would file the next reader's calls under this one.
    """
    tokens = usage.bind(user.id if user else None, feature_for_path(request.url.path))
    try:
        yield
    finally:
        usage.reset(tokens)
