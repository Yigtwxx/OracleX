"""
Shared test fixtures.

These tests are *characterization* tests: they pin down how the code behaves
today so the refactors that follow can be verified as behaviour-preserving.
Nothing here touches the network or the real Supabase project.
"""

from types import SimpleNamespace
from typing import Optional

import pytest


class FakeAuth:
    """Stand-in for `supabase.auth` that resolves a fixed token → user."""

    def __init__(self, valid_tokens: Optional[dict] = None, unverified: Optional[set] = None):
        # token -> (user_id, email)
        self.valid_tokens = valid_tokens or {}
        # Tokens whose email GoTrue has not confirmed. Adminship requires a
        # confirmed address, so this is how that path gets exercised.
        self.unverified = unverified or set()
        self.calls: list = []

    def get_user(self, jwt=None):
        self.calls.append(jwt)
        if jwt not in self.valid_tokens:
            # gotrue raises on an invalid/expired token rather than returning
            # an empty response, so mirror that.
            raise ValueError("invalid JWT")
        user_id, email = self.valid_tokens[jwt]
        confirmed_at = None if jwt in self.unverified else "2026-01-01T00:00:00+00:00"
        return SimpleNamespace(
            user=SimpleNamespace(id=user_id, email=email, email_confirmed_at=confirmed_at)
        )


class FakeSupabase:
    def __init__(self, auth: FakeAuth):
        self.auth = auth


# The address the admin fixtures use. Deliberately not the real admin email —
# the production value belongs in the environment, not in a test file.
ADMIN_EMAIL = "admin@example.com"


@pytest.fixture
def fake_auth():
    """A Supabase auth double where `good-token` maps to a known user."""
    return FakeAuth(
        {
            "good-token": ("user-abc", "abc@example.com"),
            "admin-token": ("user-admin", ADMIN_EMAIL),
            # Same admin address, but GoTrue never confirmed it.
            "unconfirmed-admin-token": ("user-ghost", ADMIN_EMAIL),
        },
        unverified={"unconfirmed-admin-token"},
    )


@pytest.fixture
def patch_supabase(monkeypatch, fake_auth):
    """
    Point `dependencies.auth.get_supabase` at the fake client, and stop the
    suspension lookup from reaching a real database.

    `get_current_user` asks `bans.check` about every authenticated request. That
    call goes through `services/db.py`, which the fake above does not cover — so
    without this the suite would query the live project (and its fail-open path
    would hide that it had). Tests that care about suspensions patch `check`
    themselves; see `banned`.
    """
    import dependencies.auth as auth_module
    from services.admin import bans

    monkeypatch.setattr(auth_module, "get_supabase", lambda: FakeSupabase(fake_auth))

    async def _never_banned(user_id: str):
        return None

    monkeypatch.setattr(bans, "check", _never_banned)
    bans.clear_cache()
    return fake_auth


@pytest.fixture
def admin_emails(monkeypatch):
    """
    Make ADMIN_EMAIL an admin for the duration of a test.

    Patching the setting works only because `is_admin_email` reads
    `settings.admin_emails` on every call rather than caching it at import.
    """
    from config import settings

    monkeypatch.setattr(settings, "ADMIN_EMAILS", ADMIN_EMAIL)
    return ADMIN_EMAIL


@pytest.fixture
def banned(monkeypatch):
    """
    Suspend a user id for the duration of a test.

    Returns a function: `banned("user-abc")`, optionally with a reason or an end
    date. Applied after `patch_supabase`, so it overrides the never-banned stub.
    """
    from datetime import datetime, timedelta, UTC

    from services.admin import bans

    def _apply(user_id: str, *, reason: Optional[str] = None, until: Optional[datetime] = None):
        state = bans.BanState(until=until or datetime.now(UTC) + timedelta(days=1), reason=reason)

        async def _check(candidate: str):
            return state if candidate == user_id else None

        monkeypatch.setattr(bans, "check", _check)
        return state

    return _apply
