"""
Tests for the per-request data-provider key resolution.

The property that matters most here is the one a leak would violate: a key bound
for one request must not survive into the next.
"""

import asyncio

import pytest

from config import settings
from services import provider_keys


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """No server keys unless a test asks for one."""
    monkeypatch.setattr(settings, "TCMB_EVDS_API_KEY", "")
    monkeypatch.setattr(settings, "COINALYZE_API_KEY", "")
    monkeypatch.setattr(settings, "SEC_USER_AGENT", "")


def test_falls_back_to_the_server_key(monkeypatch):
    monkeypatch.setattr(settings, "TCMB_EVDS_API_KEY", "server-evds")
    assert provider_keys.evds_key() == "server-evds"


def test_caller_key_wins_over_the_server_key(monkeypatch):
    monkeypatch.setattr(settings, "TCMB_EVDS_API_KEY", "server-evds")
    token = provider_keys.bind("evds", "caller-evds")
    try:
        assert provider_keys.evds_key() == "caller-evds"
    finally:
        provider_keys.reset("evds", token)

    assert provider_keys.evds_key() == "server-evds"


def test_reset_restores_the_previous_value():
    token = provider_keys.bind("coinalyze", "caller-key")
    provider_keys.reset("coinalyze", token)
    assert provider_keys.coinalyze_key() == ""


def test_blank_key_does_not_bind(monkeypatch):
    """A blank means "leave the environment in charge", not "clear the key"."""
    monkeypatch.setattr(settings, "COINALYZE_API_KEY", "server-coinalyze")
    assert provider_keys.bind("coinalyze", "") is None
    assert provider_keys.coinalyze_key() == "server-coinalyze"


def test_unknown_provider_does_not_bind():
    assert provider_keys.bind("nonesuch", "key") is None


def test_reset_tolerates_a_none_token():
    """So the dependency needs no branch for the nothing-was-bound case."""
    provider_keys.reset("evds", None)
    provider_keys.reset("nonesuch", None)


def test_binding_does_not_leak_across_tasks():
    """
    The guarantee the request dependency rests on.

    asyncio copies the context at task creation, so a task started before the
    bind never sees it, and a sibling task cannot read another's key.
    """
    seen = {}

    async def bound():
        token = provider_keys.bind("evds", "task-a-key")
        try:
            await asyncio.sleep(0)
            seen["a"] = provider_keys.evds_key()
        finally:
            provider_keys.reset("evds", token)

    async def unbound():
        await asyncio.sleep(0)
        seen["b"] = provider_keys.evds_key()

    async def main():
        await asyncio.gather(asyncio.create_task(bound()), asyncio.create_task(unbound()))

    asyncio.run(main())

    assert seen["a"] == "task-a-key"
    assert seen["b"] == ""


def test_server_configured_ignores_a_caller_key(monkeypatch):
    """The panel uses this to say who is carrying the upstream."""
    assert provider_keys.server_configured("evds") is False

    token = provider_keys.bind("evds", "caller-evds")
    try:
        assert provider_keys.server_configured("evds") is False
    finally:
        provider_keys.reset("evds", token)

    monkeypatch.setattr(settings, "TCMB_EVDS_API_KEY", "server-evds")
    assert provider_keys.server_configured("evds") is True


def test_sec_is_server_only(monkeypatch):
    """There is no bind path for it, by design — see the preset's scope."""
    monkeypatch.setattr(settings, "SEC_USER_AGENT", "  Oracle-X me@example.com  ")
    assert provider_keys.sec_user_agent() == "Oracle-X me@example.com"
    assert provider_keys.bind("sec", "someone@else.com") is None
