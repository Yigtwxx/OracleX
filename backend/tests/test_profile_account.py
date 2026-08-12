"""
Tests for the profile photo and account-deletion endpoints.

The one that matters most is
`test_delete_account_uses_the_id_from_the_token_not_the_body`. This backend
connects with the service-role key and bypasses RLS, so nothing behind the
router would stop a request that named someone else's id — the only thing
standing there is that the handler takes the id from the verified JWT.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import profile as profile_router
from services import storage

AUTH = {"Authorization": "Bearer good-token"}
# Matches `fake_auth` in conftest: good-token -> ("user-abc", "abc@example.com")
USER_ID = "user-abc"
USER_EMAIL = "abc@example.com"

PNG = b"\x89PNG\r\n\x1a\n" + b"rest of the file"


@pytest.fixture
def client(patch_supabase):
    app = FastAPI()
    app.include_router(profile_router.router)
    return TestClient(app)


@pytest.fixture
def no_storage(monkeypatch):
    """Stub the bucket so nothing here touches a real Supabase project."""
    calls: dict = {"uploaded": [], "listed": [], "removed": []}

    async def _upload(*, bucket, user_id, data, max_bytes, declared_name=None):
        calls["uploaded"].append((bucket, user_id, len(data)))
        return (f"https://cdn.test/{bucket}/{user_id}/new.png", f"{user_id}/new.png")

    async def _list(*, bucket, user_id):
        calls["listed"].append((bucket, user_id))
        return [f"{user_id}/old.png", f"{user_id}/new.png"]

    async def _remove(*, bucket, paths):
        calls["removed"].append((bucket, list(paths)))

    monkeypatch.setattr(storage, "upload_image", _upload)
    monkeypatch.setattr(storage, "list_user_objects", _list)
    monkeypatch.setattr(storage, "remove_objects", _remove)
    return calls


@pytest.fixture
def profile_writes(monkeypatch):
    """Record every `update_user_profile` call and report success."""
    writes: list = []

    async def _update(user_id, data):
        writes.append((user_id, data))
        return True

    monkeypatch.setattr(profile_router.profile_service, "update_user_profile", _update)
    return writes


# ── Avatar upload ───────────────────────────────────────────────────────────


def test_upload_avatar_requires_authentication(client):
    assert client.post("/api/profile/avatar", files={"file": ("a.png", PNG)}).status_code == 401


def test_upload_avatar_stores_the_file_and_writes_the_url(client, no_storage, profile_writes):
    response = client.post(
        "/api/profile/avatar", headers=AUTH, files={"file": ("photo.png", PNG, "image/png")}
    )

    assert response.status_code == 200, response.text
    assert response.json()["url"].startswith("https://cdn.test/profile-avatars/")
    assert no_storage["uploaded"] == [("profile-avatars", USER_ID, len(PNG))]
    assert profile_writes == [(USER_ID, {"avatar_url": response.json()["url"]})]


def test_upload_avatar_prunes_the_previous_photo(client, no_storage, profile_writes):
    """One photo per account: the old object must not linger in the bucket."""
    client.post("/api/profile/avatar", headers=AUTH, files={"file": ("photo.png", PNG)})

    assert no_storage["removed"] == [("profile-avatars", [f"{USER_ID}/old.png"])], (
        "Only the superseded object should be removed"
    )


def test_upload_avatar_refuses_a_file_that_is_not_an_image(client, monkeypatch, profile_writes):
    async def _reject(**kwargs):
        raise storage.ImageRejected("only PNG, JPEG, WebP and GIF images are supported")

    monkeypatch.setattr(storage, "upload_image", _reject)

    response = client.post(
        "/api/profile/avatar",
        headers=AUTH,
        # A PHP script wearing a .png name and an image content type.
        files={"file": ("photo.png", b"<?php system($_GET['c']); ?>", "image/png")},
    )

    assert response.status_code == 400, response.text
    assert profile_writes == [], "A rejected upload must not touch the profile row"


def test_upload_avatar_refuses_an_oversized_file(client, no_storage, profile_writes):
    oversized = PNG + b"0" * (profile_router.AVATAR_MAX_BYTES + 16)

    response = client.post(
        "/api/profile/avatar", headers=AUTH, files={"file": ("big.png", oversized)}
    )

    assert response.status_code == 413, response.text
    assert no_storage["uploaded"] == [], "The body must be capped before it reaches the bucket"


def test_delete_avatar_clears_the_folder_and_the_column(client, no_storage, profile_writes):
    response = client.delete("/api/profile/avatar", headers=AUTH)

    assert response.status_code == 200, response.text
    assert no_storage["removed"] == [
        ("profile-avatars", [f"{USER_ID}/old.png", f"{USER_ID}/new.png"])
    ]
    assert profile_writes == [(USER_ID, {"avatar_url": None})]


# ── Account deletion ────────────────────────────────────────────────────────


@pytest.fixture
def deletions(monkeypatch):
    deleted: list = []

    async def _delete(user_id):
        deleted.append(user_id)

    monkeypatch.setattr(profile_router.profile_service, "delete_account", _delete)
    return deleted


def test_delete_account_requires_authentication(client):
    response = client.request("DELETE", "/api/profile/account", json={"confirm_email": USER_EMAIL})
    assert response.status_code == 401


def test_delete_account_refuses_a_mismatched_confirmation(client, deletions):
    response = client.request(
        "DELETE", "/api/profile/account", headers=AUTH, json={"confirm_email": "someone@else.com"}
    )

    assert response.status_code == 400, response.text
    assert deletions == [], "Nothing may be deleted without the right address"


def test_delete_account_refuses_an_empty_confirmation(client, deletions):
    response = client.request(
        "DELETE", "/api/profile/account", headers=AUTH, json={"confirm_email": ""}
    )

    assert response.status_code == 400
    assert deletions == []


def test_delete_account_accepts_the_matching_address(client, deletions):
    response = client.request(
        "DELETE", "/api/profile/account", headers=AUTH, json={"confirm_email": USER_EMAIL}
    )

    assert response.status_code == 204, response.text
    assert deletions == [USER_ID]


def test_delete_account_compares_the_address_case_insensitively(client, deletions):
    response = client.request(
        "DELETE",
        "/api/profile/account",
        headers=AUTH,
        json={"confirm_email": "  ABC@Example.COM  "},
    )

    assert response.status_code == 204, response.text
    assert deletions == [USER_ID]


def test_delete_account_uses_the_id_from_the_token_not_the_body(client, deletions):
    """
    The service-role key bypasses RLS, so this is the only thing stopping a
    request from naming somebody else's account.
    """
    response = client.request(
        "DELETE",
        "/api/profile/account",
        headers=AUTH,
        json={"confirm_email": USER_EMAIL, "user_id": "some-other-user"},
    )

    assert response.status_code == 204, response.text
    assert deletions == [USER_ID], f"Expected the token's id, got {deletions}"
