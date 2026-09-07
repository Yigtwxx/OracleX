"""Tests for the per-user data provider key endpoints."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import profile as profile_router

AUTH = {"Authorization": "Bearer good-token"}


@pytest.fixture
def client(patch_supabase, monkeypatch):
    monkeypatch.setattr(profile_router.secret_box, "is_configured", lambda: True)

    app = FastAPI()
    app.include_router(profile_router.router)
    return TestClient(app)


def _find(payload, name):
    return next(p for p in payload["providers"] if p["provider"] == name)


def test_get_requires_authentication(client):
    assert client.get("/api/profile/data-providers").status_code == 401


def test_put_requires_authentication(client):
    response = client.put("/api/profile/data-providers", json={"provider": "evds", "api_key": "k"})
    assert response.status_code == 401


def test_get_lists_the_registry(client, monkeypatch):
    async def providers(_user_id):
        return [
            {
                "provider": "evds",
                "label": "TCMB EVDS",
                "scope": "user",
                "editable": True,
                "configured": False,
                "source": "none",
                "key_hint": "",
                "signup_url": "https://example.com",
            }
        ]

    monkeypatch.setattr(profile_router.data_provider_settings_service, "get_settings", providers)

    response = client.get("/api/profile/data-providers", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["encryption_available"] is True
    assert _find(body, "evds")["signup_url"] == "https://example.com"


def test_put_never_echoes_the_key(client, monkeypatch):
    captured = {}

    async def save(user_id, provider, api_key):
        captured.update(user_id=user_id, provider=provider, api_key=api_key)
        return [{"provider": "evds", "key_hint": "-key", "source": "user", "configured": True}]

    monkeypatch.setattr(profile_router.data_provider_settings_service, "save_key", save)

    response = client.put(
        "/api/profile/data-providers",
        json={"provider": "evds", "api_key": "super-secret-key"},
        headers=AUTH,
    )

    assert response.status_code == 200
    assert captured["api_key"] == "super-secret-key"
    assert "super-secret-key" not in response.text
    assert _find(response.json(), "evds")["key_hint"] == "-key"


def test_put_takes_the_user_from_the_token_not_the_body(client, monkeypatch):
    """The rule the whole router exists to keep; asserted here too."""
    captured = {}

    async def save(user_id, provider, api_key):
        captured["user_id"] = user_id
        return []

    monkeypatch.setattr(profile_router.data_provider_settings_service, "save_key", save)

    client.put(
        "/api/profile/data-providers",
        json={"provider": "evds", "api_key": "k", "user_id": "somebody-else"},
        headers=AUTH,
    )

    assert captured["user_id"] != "somebody-else"


def test_put_rejects_an_unknown_provider(client, monkeypatch):
    async def save(_user_id, provider, _api_key):
        raise profile_router.data_provider_settings_service.UnknownProvider(
            f"Unknown data provider: {provider}"
        )

    monkeypatch.setattr(profile_router.data_provider_settings_service, "save_key", save)

    response = client.put(
        "/api/profile/data-providers",
        json={"provider": "nonesuch", "api_key": "k"},
        headers=AUTH,
    )
    assert response.status_code == 400


def test_put_503s_when_encryption_is_unconfigured(client, monkeypatch):
    monkeypatch.setattr(profile_router.secret_box, "is_configured", lambda: False)

    response = client.put(
        "/api/profile/data-providers",
        json={"provider": "evds", "api_key": "k"},
        headers=AUTH,
    )
    assert response.status_code == 503
    assert "LLM_KEY_ENCRYPTION_SECRET" in response.json()["detail"]


def test_delete_removes_the_named_provider(client, monkeypatch):
    captured = {}

    async def delete(user_id, provider):
        captured.update(user_id=user_id, provider=provider)
        return []

    monkeypatch.setattr(profile_router.data_provider_settings_service, "delete_key", delete)

    response = client.delete("/api/profile/data-providers/evds", headers=AUTH)
    assert response.status_code == 200
    assert captured["provider"] == "evds"
