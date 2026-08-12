"""
Tests for `require_admin`.

Adminship is the whole security boundary of the admin panel — the backend holds
the service-role key, so behind these routes there is no second line of defence.
Every one of these tests is about who gets through.
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from dependencies.auth import AuthUser, require_admin

from conftest import ADMIN_EMAIL

ADMIN = {"Authorization": "Bearer admin-token"}
PLAIN = {"Authorization": "Bearer good-token"}
UNCONFIRMED = {"Authorization": "Bearer unconfirmed-admin-token"}


@pytest.fixture
def client(patch_supabase):
    app = FastAPI()

    @app.get("/admin-only")
    async def admin_only(user: AuthUser = Depends(require_admin)):
        return {"id": user.id, "email": user.email}

    return TestClient(app)


def test_without_a_token_it_is_401(client, admin_emails):
    """
    The 401/403 split falls out of the dependency chain: `get_current_user`
    raises before the email is ever looked at.
    """
    response = client.get("/admin-only")
    assert response.status_code == 401


def test_with_a_non_admin_token_it_is_403(client, admin_emails):
    response = client.get("/admin-only", headers=PLAIN)
    assert response.status_code == 403
    assert response.json()["detail"] == "Admin only"


def test_with_an_admin_token_it_resolves(client, admin_emails):
    response = client.get("/admin-only", headers=ADMIN)
    assert response.status_code == 200
    assert response.json() == {"id": "user-admin", "email": ADMIN_EMAIL}


def test_an_unconfirmed_email_is_not_an_admin(client, admin_emails):
    """
    The address matches the list, but GoTrue never confirmed it. If email
    confirmation is ever disabled on the Supabase project, signing up as the
    admin address must not be enough.
    """
    response = client.get("/admin-only", headers=UNCONFIRMED)
    assert response.status_code == 403


def test_an_empty_admin_list_denies_everyone(client, monkeypatch):
    """The closed default: ADMIN_EMAILS unset means nobody, not everybody."""
    from config import settings

    monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
    assert client.get("/admin-only", headers=ADMIN).status_code == 403


@pytest.mark.parametrize(
    "configured",
    [
        ADMIN_EMAIL.upper(),
        f"  {ADMIN_EMAIL}  ",
        f"someone@else.test,{ADMIN_EMAIL}",
        f"{ADMIN_EMAIL},,",
    ],
    ids=["uppercase", "padded", "second-in-list", "trailing-separator"],
)
def test_the_admin_list_is_parsed_forgivingly(client, monkeypatch, configured):
    from config import settings

    monkeypatch.setattr(settings, "ADMIN_EMAILS", configured)
    assert client.get("/admin-only", headers=ADMIN).status_code == 200


def test_a_suspended_admin_is_still_stopped(client, admin_emails, banned):
    """
    Suspension is checked before adminship. `ban_user` refuses to suspend an
    admin, so this can only be reached by a manual database edit — but if it is,
    the ban must win.
    """
    banned("user-admin")
    assert client.get("/admin-only", headers=ADMIN).status_code == 403
