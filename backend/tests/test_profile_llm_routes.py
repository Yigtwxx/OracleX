"""Tests for the per-user LLM settings endpoints."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import profile as profile_router
from services import llm_settings_service as svc


@pytest.fixture
def client(patch_supabase, monkeypatch):
    """App exposing the profile router, wired to the fake Supabase auth."""
    monkeypatch.setattr(profile_router.secret_box, "is_configured", lambda: True)

    app = FastAPI()
    app.include_router(profile_router.router)
    return TestClient(app)


AUTH = {"Authorization": "Bearer good-token"}


def test_get_requires_authentication(client):
    assert client.get("/api/profile/llm").status_code == 401


def test_get_returns_not_configured_when_unset(client, monkeypatch):
    async def none_settings(_user_id):
        return None

    monkeypatch.setattr(profile_router.llm_settings_service, "get_settings", none_settings)

    response = client.get("/api/profile/llm", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["configured"] is False


def test_put_stores_and_returns_hint_only(client, monkeypatch):
    captured = {}

    async def fake_save(user_id, **kwargs):
        captured.update(kwargs)
        captured["user_id"] = user_id
        return {
            "provider": "groq",
            "model": "",
            "key_hint": "abcd",
            "configured": True,
            "use_for_chat": True,
            "use_for_news": False,
            "use_for_reports": False,
        }

    monkeypatch.setattr(profile_router.llm_settings_service, "save_settings", fake_save)

    response = client.put(
        "/api/profile/llm",
        headers=AUTH,
        json={"provider": "groq", "api_key": "gsk_secret_abcd", "use_for_chat": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["key_hint"] == "abcd"
    assert "api_key" not in body
    # The user id comes from the verified token, never from the request body.
    assert captured["user_id"] == "user-abc"


def test_put_rejects_unknown_provider(client, monkeypatch):
    async def fake_save(_user_id, **_kwargs):
        raise svc.UnknownProvider("Unknown provider 'evil-host'.")

    monkeypatch.setattr(profile_router.llm_settings_service, "save_settings", fake_save)

    response = client.put(
        "/api/profile/llm", headers=AUTH, json={"provider": "evil-host", "api_key": "k"}
    )
    assert response.status_code == 400
    assert "evil-host" in response.json()["detail"]


def test_put_rejects_missing_key(client, monkeypatch):
    async def fake_save(_user_id, **_kwargs):
        raise svc.KeyRequired("An API key is required for this provider.")

    monkeypatch.setattr(profile_router.llm_settings_service, "save_settings", fake_save)

    response = client.put("/api/profile/llm", headers=AUTH, json={"provider": "gemini"})
    assert response.status_code == 400


def test_put_fails_when_encryption_unconfigured(client, monkeypatch):
    monkeypatch.setattr(profile_router.secret_box, "is_configured", lambda: False)

    response = client.put(
        "/api/profile/llm", headers=AUTH, json={"provider": "groq", "api_key": "k"}
    )
    assert response.status_code == 503


def test_delete_removes_settings(client, monkeypatch):
    async def fake_delete(_user_id):
        return True

    monkeypatch.setattr(profile_router.llm_settings_service, "delete_settings", fake_delete)
    assert client.delete("/api/profile/llm", headers=AUTH).status_code == 200


def test_test_endpoint_reports_failure_for_bad_key(client, monkeypatch):
    class DeadProvider:
        name = "groq"
        model = "m"

        async def health(self):
            return False

        async def list_models(self):
            return []

    monkeypatch.setattr(profile_router.llm, "build_provider", lambda *_a, **_k: DeadProvider())

    response = client.post(
        "/api/profile/llm/test", headers=AUTH, json={"provider": "groq", "api_key": "bad"}
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_test_endpoint_lists_models_for_good_key(client, monkeypatch):
    class LiveProvider:
        name = "groq"
        model = "m"

        async def health(self):
            return True

        async def list_models(self):
            return ["llama-3.3-70b-versatile", "qwen/qwen3.6-27b"]

    monkeypatch.setattr(profile_router.llm, "build_provider", lambda *_a, **_k: LiveProvider())

    response = client.post(
        "/api/profile/llm/test", headers=AUTH, json={"provider": "groq", "api_key": "good"}
    )
    body = response.json()
    assert body["ok"] is True
    assert "qwen/qwen3.6-27b" in body["models"]


def test_test_endpoint_never_echoes_the_key(client, monkeypatch):
    class LiveProvider:
        name = "groq"
        model = "m"

        async def health(self):
            return True

        async def list_models(self):
            return []

    monkeypatch.setattr(profile_router.llm, "build_provider", lambda *_a, **_k: LiveProvider())

    response = client.post(
        "/api/profile/llm/test",
        headers=AUTH,
        json={"provider": "groq", "api_key": "gsk_supersecret"},
    )
    assert "gsk_supersecret" not in response.text
