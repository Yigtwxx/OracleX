"""
What each model call actually cost, and who it was for.

Every provider already gets token counts back — OpenAI-compatible and Anthropic
return a `usage` object, Ollama returns `prompt_eval_count`/`eval_count` — and
until now all three were discarded at the line that pulled the text out. This
module is where they land instead.

The attribution problem is that `client.generate` does not know the reader. It
takes a `prefer` provider, resolved from the user by the caller, so the identity
is gone by the time a response arrives. Rather than add `user_id` and `feature`
to twelve call sites, the request binds them once — the same `ContextVar` shape
`services/provider_keys.py` uses, for the same reason and with the same
property: a task started by a scheduler inherits no binding, so background work
records as `user_id=None`, which is exactly what it is.

Writes are buffered and flushed by a scheduled job rather than written inline.
A model call is already slow and a database round-trip per call would make it
slower for a number nobody reads in real time; the buffer is bounded so a long
outage of the database costs a fixed amount of memory and some rows, not the
terminal.
"""

import asyncio
import logging
import os
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Optional

logger = logging.getLogger(__name__)

# Rows waiting to be written. Bounded: if the flush job is wedged or the database
# is unreachable, this drops the oldest rather than growing without limit —
# losing usage history is an acceptable failure, exhausting the process is not.
MAX_BUFFER = 5000

_buffer: list["UsageRow"] = []

# Who the current request is for, and which surface asked. Unset — the default —
# means background work, which is a real answer rather than a missing one.
_user_id: ContextVar[Optional[str]] = ContextVar("usage_user_id", default=None)
_feature: ContextVar[str] = ContextVar("usage_feature", default="background")
# Whose credential paid. Only `client.generate` knows — it is the one place that
# can see whether the provider being called is the reader's own or the chain's.
_key_owner: ContextVar[str] = ContextVar("usage_key_owner", default="server")


@dataclass(frozen=True)
class UsageRow:
    """One model call, in the shape migration 018 stores."""

    user_id: Optional[str]
    feature: str
    provider: str
    model: str
    key_owner: str
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]
    duration_ms: Optional[int]
    ok: bool
    created_at: str

    def as_payload(self) -> dict:
        return {
            "user_id": self.user_id,
            "feature": self.feature,
            "provider": self.provider,
            "model": self.model,
            "key_owner": self.key_owner,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "duration_ms": self.duration_ms,
            "ok": self.ok,
            "created_at": self.created_at,
        }


def bind(user_id: Optional[str], feature: str = "background") -> tuple[Token, Token]:
    """Attribute everything recorded in this context to `user_id`."""
    return _user_id.set(user_id), _feature.set(feature or "background")


def reset(tokens: tuple[Token, Token]) -> None:
    """Undo a `bind`, so a worker task cannot carry one reader into the next."""
    user_token, feature_token = tokens
    _user_id.reset(user_token)
    _feature.reset(feature_token)


def bind_key_owner(owner: str) -> Token:
    """Mark calls in this context as paid for by 'user' or 'server'."""
    return _key_owner.set(owner)


def reset_key_owner(token: Token) -> None:
    _key_owner.reset(token)


def current_feature() -> str:
    """The surface being served, for a caller that wants to label its own row."""
    return _feature.get()


def record(
    *,
    provider: str,
    model: str,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    duration_ms: Optional[int] = None,
    ok: bool = True,
    key_owner: Optional[str] = None,
    feature: Optional[str] = None,
) -> None:
    """
    Note one model call.

    Never raises and never blocks: this sits on the hot path of every AI reply,
    and a failure to measure must not become a failure to answer.
    """
    try:
        if total_tokens is None and (prompt_tokens is not None or completion_tokens is not None):
            total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

        row = UsageRow(
            user_id=_user_id.get(),
            feature=feature or _feature.get(),
            provider=provider,
            model=model,
            key_owner=key_owner or _key_owner.get(),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_ms=duration_ms,
            ok=ok,
            created_at=datetime.now(UTC).isoformat(),
        )

        if len(_buffer) >= MAX_BUFFER:
            # Drop the oldest. Newer rows describe what the install is doing now,
            # which is the question this table exists to answer.
            del _buffer[0]
        _buffer.append(row)
    except Exception as e:  # noqa: BLE001
        logger.debug("Could not record AI usage: %s", e)


def pending() -> int:
    """How many rows are waiting. For the health surface and for tests."""
    return len(_buffer)


def drain() -> list[UsageRow]:
    """Take everything buffered, leaving the buffer empty."""
    rows = list(_buffer)
    _buffer.clear()
    return rows


def restore(rows: list[UsageRow]) -> None:
    """
    Put rows back after a failed write, oldest first.

    Bounded the same way, so a database that is down for an hour costs the newest
    rows rather than the process.
    """
    _buffer[:0] = rows
    if len(_buffer) > MAX_BUFFER:
        del _buffer[: len(_buffer) - MAX_BUFFER]


def _under_test() -> bool:
    """
    Whether this process is a test run.

    pytest sets PYTEST_CURRENT_TEST for the duration of every test. Checking an
    environment variable to change behaviour is normally a smell, and it is the
    right call here for one reason: the suite exercises the real app, including
    its shutdown, and shutdown flushes. Six rows describing a stub provider
    called "gemini" with the model "m" reached the live project before this
    guard existed — telemetry written by a test run is not merely useless, it
    silently corrupts the numbers the view is for.

    The buffer still fills during a test, so `record` stays covered; only the
    write leaves.
    """
    return "PYTEST_CURRENT_TEST" in os.environ


async def flush() -> int:
    """
    Write the buffer to Supabase. Returns how many rows were written.

    Imported lazily: this module sits under `services/llm`, and reaching for the
    database at import time would put the storage layer in the import graph of
    every provider.
    """
    if _under_test():
        drain()
        return 0

    rows = drain()
    if not rows:
        return 0

    from services.supabase_service import get_supabase, run_with_reconnect

    payload = [row.as_payload() for row in rows]
    try:
        await asyncio.to_thread(
            run_with_reconnect,
            lambda: get_supabase().table("ai_usage").insert(payload).execute(),
        )
        return len(rows)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not flush %d AI usage rows: %s", len(rows), e)
        restore(rows)
        return 0
