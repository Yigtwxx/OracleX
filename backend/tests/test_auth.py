"""
Tests for the authentication dependency.

These are the one set of tests here that assert *new* behaviour rather than
characterizing existing behaviour — before this, the backend had no auth at
all and `user_id` was an unvalidated client-supplied parameter.
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from dependencies.auth import AuthUser, get_current_user, get_optional_user


@pytest.fixture
def client(patch_supabase):
    """A minimal app exposing both dependencies, wired to the fake Supabase."""
    app = FastAPI()

    @app.get("/protected")
    async def protected(user: AuthUser = Depends(get_current_user)):
        return {"id": user.id, "email": user.email}

    @app.get("/optional")
    async def optional(user=Depends(get_optional_user)):
        return {"id": user.id if user else None}

    return TestClient(app)


# ── get_current_user ─────────────────────────────────────────────────────────


def test_valid_token_resolves_user(client):
    response = client.get("/protected", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    assert response.json() == {"id": "user-abc", "email": "abc@example.com"}


def test_missing_header_is_401(client):
    response = client.get("/protected")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


def test_invalid_token_is_401(client):
    response = client.get("/protected", headers={"Authorization": "Bearer bogus-token"})
    assert response.status_code == 401


def test_malformed_authorization_header_is_401(client):
    """A non-Bearer scheme must not be accepted."""
    response = client.get("/protected", headers={"Authorization": "good-token"})
    assert response.status_code == 401


def test_empty_bearer_token_is_401(client):
    response = client.get("/protected", headers={"Authorization": "Bearer "})
    assert response.status_code == 401


def test_401_advertises_bearer_scheme(client):
    response = client.get("/protected")
    assert response.headers.get("www-authenticate") == "Bearer"


def test_token_is_verified_against_supabase(client, patch_supabase):
    """The dependency must actually call out to verify, not trust the token."""
    client.get("/protected", headers={"Authorization": "Bearer good-token"})
    assert patch_supabase.calls == ["good-token"]


# ── get_optional_user ────────────────────────────────────────────────────────


def test_optional_user_without_token_is_none(client):
    response = client.get("/optional")
    assert response.status_code == 200
    assert response.json() == {"id": None}


def test_optional_user_with_invalid_token_is_none(client):
    """An invalid token degrades to anonymous rather than erroring."""
    response = client.get("/optional", headers={"Authorization": "Bearer bogus-token"})
    assert response.status_code == 200
    assert response.json() == {"id": None}


def test_optional_user_with_valid_token_resolves(client):
    response = client.get("/optional", headers={"Authorization": "Bearer good-token"})
    assert response.json() == {"id": "user-abc"}


# ── suspensions ──────────────────────────────────────────────────────────────
# Enforced inside `get_current_user` rather than route by route, so these tests
# stand in for every authenticated route in the app.


def test_a_suspended_user_is_403_not_401(client, banned):
    """
    401 would make the Supabase client refresh the token, succeed, retry, and
    loop — the caller would never see why. 403 is terminal.
    """
    banned("user-abc")
    response = client.get("/protected", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 403, response.text


def test_the_suspension_403_names_the_end_date(client, banned):
    from datetime import datetime, UTC

    banned("user-abc", until=datetime(2030, 6, 1, 12, 0, tzinfo=UTC))
    response = client.get("/protected", headers={"Authorization": "Bearer good-token"})
    assert "2030-06-01" in response.json()["detail"]


def test_the_suspension_403_includes_the_reason(client, banned):
    banned("user-abc", reason="spam")
    detail = client.get("/protected", headers={"Authorization": "Bearer good-token"}).json()[
        "detail"
    ]
    assert "spam" in detail


def test_a_permanent_suspension_does_not_quote_a_date(client, banned):
    from services.admin import bans

    banned("user-abc", until=bans.PERMANENT_UNTIL)
    detail = client.get("/protected", headers={"Authorization": "Bearer good-token"}).json()[
        "detail"
    ]
    assert "9999" not in detail


def test_another_user_is_unaffected_by_a_suspension(client, banned):
    banned("somebody-else")
    response = client.get("/protected", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200


def test_optional_user_is_unchanged_for_a_suspended_user(client, banned):
    """
    Reads stay open. Every route using `get_optional_user` is readable by a
    signed-out visitor anyway, so blocking a suspended reader would hide from
    them what it shows to everyone else.
    """
    banned("user-abc")
    response = client.get("/optional", headers={"Authorization": "Bearer good-token"})
    assert response.status_code == 200
    assert response.json() == {"id": "user-abc"}
