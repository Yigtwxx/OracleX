"""
Tests for the admin router.

The two parametrized tables at the top are the important ones. Under the
service-role key an unguarded admin route is not a weakened check, it is no
check — so every route is asserted to refuse an anonymous caller *and* a
signed-in non-admin, by table, so a route added later without a guard fails
here rather than in production.
"""

from datetime import datetime, UTC

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from models.admin import AdminOverview, AdminPostPage, AdminUser, AdminUserPage
from routers import admin as admin_router
from services import admin as admin_service
from services.admin import audit as audit_service
from services.admin import moderation as moderation_service
from services.admin import users as user_service

ADMIN = {"Authorization": "Bearer admin-token"}
PLAIN = {"Authorization": "Bearer good-token"}

# (method, path, body) — every route on the guarded router.
GUARDED_ROUTES = [
    ("get", "/api/admin/overview", None),
    ("get", "/api/admin/users", None),
    ("get", "/api/admin/users/user-1", None),
    ("post", "/api/admin/users/user-1/plan", {"plan": "pro"}),
    ("post", "/api/admin/users/user-1/ban", {"days": 7}),
    ("post", "/api/admin/users/user-1/unban", {}),
    ("get", "/api/admin/content/posts", None),
    ("delete", "/api/admin/posts/post-1", None),
    ("delete", "/api/admin/comments/c-1", None),
    ("get", "/api/admin/audit", None),
]


def _user(**overrides) -> AdminUser:
    base = {
        "id": "user-1",
        "email": "someone@example.com",
        "subscription_plan": "free",
        "created_at": datetime.now(UTC),
    }
    base.update(overrides)
    return AdminUser(**base)


@pytest.fixture
def client(patch_supabase, admin_emails):
    app = FastAPI()
    app.include_router(admin_router.session_router)
    app.include_router(admin_router.router)
    return TestClient(app)


def _call(client, method, path, body, headers=None):
    kwargs = {"json": body} if body is not None else {}
    if headers:
        kwargs["headers"] = headers
    return getattr(client, method)(path, **kwargs)


# ── the guard ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("method,path,body", GUARDED_ROUTES)
def test_every_admin_route_is_401_without_a_token(client, method, path, body):
    assert _call(client, method, path, body).status_code == 401


@pytest.mark.parametrize("method,path,body", GUARDED_ROUTES)
def test_every_admin_route_is_403_for_a_non_admin(client, method, path, body):
    response = _call(client, method, path, body, headers=PLAIN)
    assert response.status_code == 403, f"{method} {path} returned {response.status_code}"


def test_admin_me_answers_a_non_admin_with_false_not_403(client):
    """
    A 403 here would make the endpoint an admin-detector and would leave the
    client unable to tell "not an admin" from "the backend is down".
    """
    response = client.get("/api/admin/me", headers=PLAIN)
    assert response.status_code == 200
    assert response.json() == {"is_admin": False, "email": None}


def test_admin_me_is_401_signed_out(client):
    assert client.get("/api/admin/me").status_code == 401


def test_admin_me_names_the_admin(client):
    response = client.get("/api/admin/me", headers=ADMIN)
    assert response.json()["is_admin"] is True
    assert response.json()["email"] == "admin@example.com"


# ── the actor comes from the token ───────────────────────────────────────────


def test_the_actor_is_taken_from_the_token_not_the_body(client, monkeypatch):
    seen = {}

    async def _ban(**kwargs):
        seen.update(kwargs)
        return _user()

    monkeypatch.setattr(user_service, "ban_user", _ban)

    client.post(
        "/api/admin/users/user-1/ban",
        headers=ADMIN,
        json={"days": 3, "reason": "spam", "actor": "somebody-else"},
    )

    assert seen["actor"].id == "user-admin"
    assert seen["actor"].email == "admin@example.com"


# ── error mapping ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "error,expected",
    [
        (admin_service.NotFound("no such user"), 404),
        (admin_service.ProtectedTarget("not that one"), 409),
        (admin_service.InvalidRequest("bad plan"), 400),
        (admin_service.UpstreamFailure("supabase is down"), 502),
    ],
    ids=["not-found", "protected", "invalid", "upstream"],
)
def test_service_errors_map_onto_status_codes(client, monkeypatch, error, expected):
    async def _boom(*args, **kwargs):
        raise error

    monkeypatch.setattr(user_service, "get_user", _boom)

    assert client.get("/api/admin/users/user-1", headers=ADMIN).status_code == expected


def test_an_upstream_failure_does_not_leak_the_database_message(client, monkeypatch):
    async def _boom(*args, **kwargs):
        raise admin_service.UpstreamFailure("connection to 10.0.0.4 refused")

    monkeypatch.setattr(user_service, "get_user", _boom)

    detail = client.get("/api/admin/users/user-1", headers=ADMIN).json()["detail"]
    assert "10.0.0.4" not in detail


# ── validation happens before the service is reached ─────────────────────────


@pytest.mark.parametrize(
    "query",
    ["sort=password", "order=sideways", "status=maybe", "limit=0", "limit=500", "offset=-1"],
)
def test_bad_list_parameters_are_422(client, monkeypatch, query):
    async def _never(**kwargs):
        raise AssertionError("the service should not have been reached")

    monkeypatch.setattr(user_service, "list_users", _never)

    assert client.get(f"/api/admin/users?{query}", headers=ADMIN).status_code == 422


def test_an_unknown_plan_is_422(client, monkeypatch):
    async def _never(**kwargs):
        raise AssertionError("the service should not have been reached")

    monkeypatch.setattr(user_service, "set_plan", _never)

    response = client.post("/api/admin/users/user-1/plan", headers=ADMIN, json={"plan": "platinum"})
    assert response.status_code == 422


# ── happy paths ──────────────────────────────────────────────────────────────


def test_the_user_list_passes_its_filters_through(client, monkeypatch):
    seen = {}

    async def _list_users(**kwargs):
        seen.update(kwargs)
        return AdminUserPage(users=[_user()], total=1, limit=kwargs["limit"], offset=0)

    monkeypatch.setattr(user_service, "list_users", _list_users)

    response = client.get(
        "/api/admin/users?search=mira&plan=pro&status=banned&sort=email&order=asc&limit=10",
        headers=ADMIN,
    )

    assert response.status_code == 200
    assert seen["search"] == "mira"
    assert seen["plan"] == "pro"
    assert seen["status"] == "banned"
    assert seen["sort"] == "email"
    assert seen["order"] == "asc"
    assert seen["limit"] == 10


def test_the_overview_is_served(client, monkeypatch):
    async def _overview():
        return AdminOverview(total_users=7, total_posts=3)

    monkeypatch.setattr(user_service, "get_overview", _overview)

    body = client.get("/api/admin/overview", headers=ADMIN).json()
    assert body["total_users"] == 7


def test_deleting_a_post_is_204_and_forwards_the_reason(client, monkeypatch):
    seen = {}

    async def _delete(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(moderation_service, "delete_post", _delete)

    response = client.delete("/api/admin/posts/post-1?reason=spam", headers=ADMIN)

    assert response.status_code == 204
    assert seen["post_id"] == "post-1"
    assert seen["reason"] == "spam"


def test_deleting_a_comment_is_204(client, monkeypatch):
    async def _delete(**kwargs):
        return None

    monkeypatch.setattr(moderation_service, "delete_comment", _delete)

    assert client.delete("/api/admin/comments/c-1", headers=ADMIN).status_code == 204


def test_deleting_a_missing_post_is_404(client, monkeypatch):
    async def _delete(**kwargs):
        raise admin_service.NotFound("post post-9 does not exist")

    monkeypatch.setattr(moderation_service, "delete_post", _delete)

    assert client.delete("/api/admin/posts/post-9", headers=ADMIN).status_code == 404


def test_the_content_browser_is_served(client, monkeypatch):
    async def _list_posts(**kwargs):
        return AdminPostPage(posts=[], total=0, limit=25, offset=0)

    monkeypatch.setattr(moderation_service, "list_posts", _list_posts)

    assert client.get("/api/admin/content/posts", headers=ADMIN).status_code == 200


def test_the_audit_log_is_served(client, monkeypatch):
    async def _list_entries(**kwargs):
        return [], 0

    monkeypatch.setattr(audit_service, "list_entries", _list_entries)

    body = client.get("/api/admin/audit", headers=ADMIN).json()
    assert body == {"entries": [], "total": 0, "limit": 50, "offset": 0}


# ── the route that used to be a privilege-escalation hole ────────────────────
# Lives here rather than with the profile tests because it is now an admin
# surface: POST /api/profile/subscription used to accept any signed-in caller,
# which let anyone grant themselves `whale`.


@pytest.fixture
def profile_client(patch_supabase, admin_emails):
    from routers import profile as profile_router

    app = FastAPI()
    app.include_router(profile_router.router)
    return TestClient(app)


def test_setting_your_own_plan_is_403_for_a_non_admin(profile_client):
    response = profile_client.post(
        "/api/profile/subscription", headers=PLAIN, json={"plan": "whale"}
    )
    assert response.status_code == 403


def test_setting_your_own_plan_is_401_signed_out(profile_client):
    response = profile_client.post("/api/profile/subscription", json={"plan": "whale"})
    assert response.status_code == 401


def test_an_admin_setting_a_plan_targets_their_own_id(profile_client, monkeypatch):
    seen = {}

    async def _set_plan(**kwargs):
        seen.update(kwargs)
        return _user(subscription_plan=kwargs["plan"])

    monkeypatch.setattr(user_service, "set_plan", _set_plan)

    response = profile_client.post(
        "/api/profile/subscription", headers=ADMIN, json={"plan": "whale"}
    )

    assert response.status_code == 200
    assert seen["user_id"] == "user-admin"
    assert response.json() == {"success": True, "plan": "whale"}
