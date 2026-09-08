"""
Which key a data-provider call should use right now.

The caller's own key when they stored one, the server's `.env` value otherwise.

This is a `ContextVar` rather than an argument threaded through the call chain,
and that is a deliberate trade. `fetch_cpi_series` sits five frames below the
route — routers/bist -> financials_service -> deflator -> macro_service — and
three of those frames have no business knowing a key exists. Threading it would
have changed eight signatures across five modules to carry a value only the leaf
reads.

Two properties make the implicit form safe here:

  * A `ContextVar` set by a request dependency is scoped to that request's task.
    `asyncio` copies the context when a task is created, so the schedulers and
    the fire-and-forget refreshes — none of which carry a user — read the
    default and fall through to `.env`, which is exactly right for them.

  * The values fetched are public reference data — a CPI series, an
    open-interest history — so a response one reader's key paid for may be
    served to another without leaking anything. What that does *not* license is
    a single cache entry per question: where the answer's shape depends on
    whether a key was used at all, the entry has to say which it is, or a reader
    who just supplied a key is served the thin version someone else's keyless
    request cached. `open_interest_service` keys on that; `macro_service` does
    not need to, because its keyless path returns before the cache.

Nothing here ever logs a key.
"""

from contextvars import ContextVar, Token
from typing import Optional

from config import settings

# Empty default = "no caller key"; every accessor falls back to the environment.
_evds_key: ContextVar[str] = ContextVar("evds_key", default="")
_coinalyze_key: ContextVar[str] = ContextVar("coinalyze_key", default="")

# Maps a preset name to its context variable. Only "user"-scoped providers in
# services/data_provider_presets.DATA_PROVIDERS appear here.
_VARS: dict[str, ContextVar[str]] = {
    "evds": _evds_key,
    "coinalyze": _coinalyze_key,
}


def bind(provider: str, key: str) -> Optional[Token]:
    """
    Use `key` for `provider` for the rest of this request.

    Returns the token needed to undo it, or None when there was nothing to bind
    — an unknown provider or a blank key, both of which mean "leave the
    environment in charge" rather than "clear the key".
    """
    var = _VARS.get(provider)
    if var is None or not key:
        return None
    return var.set(key)


def reset(provider: str, token: Optional[Token]) -> None:
    """Undo a `bind`. A None token is a no-op, so callers need no branch."""
    var = _VARS.get(provider)
    if var is not None and token is not None:
        var.reset(token)


def evds_key() -> str:
    """The TCMB EVDS key to use, caller's first."""
    return _evds_key.get() or settings.TCMB_EVDS_API_KEY


def coinalyze_key() -> str:
    """The Coinalyze key to use, caller's first."""
    return _coinalyze_key.get() or settings.COINALYZE_API_KEY


def sec_user_agent() -> str:
    """
    The contact address EDGAR requires.

    Server-only by nature: the ownership board is one shared artefact rebuilt on
    a schedule, so there is no request whose caller could supply this.
    """
    return settings.SEC_USER_AGENT.strip()


def server_configured(provider: str) -> bool:
    """Whether the *server* has a key for `provider`, ignoring any caller key."""
    env_values = {
        "evds": settings.TCMB_EVDS_API_KEY,
        "coinalyze": settings.COINALYZE_API_KEY,
        "sec": settings.SEC_USER_AGENT.strip(),
    }
    return bool(env_values.get(provider, ""))
