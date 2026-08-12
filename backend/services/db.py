"""
Generic async wrapper around the blocking Supabase client.

`supabase-py` is synchronous. Calling it straight from an `async def` parks the
whole event loop for the duration of a network round-trip, so one slow query
stalls every other request the process is serving. `asyncio.to_thread` is the
pattern already used in `dependencies/auth.py`; this module makes it the only
way service code reaches the database.

This started life as `services/community/_db.py` and was lifted here when the
admin service needed the same three helpers. Each package binds it once:

    _ops = SupabaseOps(domain="admin", wrap=UpstreamFailure)

so a failure in the admin service raises an *admin* error rather than a
`CommunityError` its router would have to know how to translate.
"""

import asyncio
import logging
from typing import Any, Callable, Type, TypeVar

from services.supabase_service import get_supabase

logger = logging.getLogger(__name__)

T = TypeVar("T")


class SupabaseOps:
    """
    The three database helpers, bound to one domain's log prefix and exception.

    `wrap` is the exception every upstream failure is re-raised as. It is a
    constructor argument rather than a hard-coded type so the same code can
    serve packages whose routers map errors differently.
    """

    def __init__(self, *, domain: str, wrap: Type[Exception]) -> None:
        self._domain = domain
        self._wrap = wrap

    async def run(self, operation: Callable[[], T], *, what: str) -> T:
        """
        Execute a blocking Supabase call off the event loop.

        `operation` is a zero-argument callable so the caller can build the whole
        query chain — `.table(...).select(...).execute()` — and have every part
        of it, not just the final `.execute()`, run in the worker thread.

        `what` names the operation for the log line; it never carries user
        content or credentials.
        """
        try:
            return await asyncio.to_thread(operation)
        except Exception as exc:
            logger.error("%s: %s failed: %s", self._domain, what, exc)
            raise self._wrap(str(exc)) from exc

    async def rpc(self, name: str, params: dict) -> list:
        """Call a Postgres function and return its rows."""

        def _call() -> Any:
            return get_supabase().rpc(name, params).execute()

        response = await self.run(_call, what=f"rpc {name}")
        return response.data or []

    async def table_op(self, operation: Callable[[Any], Any], *, what: str) -> Any:
        """
        Run `operation(supabase_client)` off the event loop and return `.data`.

        Saves each caller from repeating the closure-plus-`get_supabase()` dance.
        """

        def _call() -> Any:
            return operation(get_supabase())

        response = await self.run(_call, what=what)
        return getattr(response, "data", None)
