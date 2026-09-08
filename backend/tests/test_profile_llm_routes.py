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


def test_unset_reader_is_told_chat_is_on(client, monkeypatch):
    """
    The zero state has to agree with migration 006's DEFAULT TRUE.

    The form posts all four toggles back on save, so whatever this reports is
    what the first save writes. Reporting False here stored False, and a reader
    who had just pasted their key kept running on the server's provider with
    nothing saying so — with the toggles disabled until a key exists, so they
    could not turn it on in the same visit either.
    """

    async def none_settings(_user_id):
        return None

    monkeypatch.setattr(profile_router.llm_settings_service, "get_settings", none_settings)

    body = client.get("/api/profile/llm", headers=AUTH).json()

    assert body["use_for_chat"] is True
    # The rest stay off: news, reports and notes each spend on a schedule or on
    # somebody else's behalf, so opting in is the reader's call.
    assert body["use_for_news"] is False
    assert body["use_for_reports"] is False
    assert body["use_for_notes"] is False


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


# ── Per-user endpoint ────────────────────────────────────────────────────────


@pytest.fixture
def public_dns(monkeypatch):
    """Resolve any host publicly; name resolution is tested in test_llm_base_url."""
    import ipaddress

    from services.llm import base_url as rules

    monkeypatch.setattr(
        rules, "_resolved_addresses", lambda host: [ipaddress.ip_address("93.184.216.34")]
    )


def test_get_advertises_which_providers_accept_an_endpoint(client, monkeypatch):
    """Without this the form cannot tell a reader the one thing that makes
    selecting Ollama on a hosted install actually work."""

    async def none_settings(_user_id):
        return None

    monkeypatch.setattr(profile_router.llm_settings_service, "get_settings", none_settings)

    body = client.get("/api/profile/llm", headers=AUTH).json()
    assert body["self_hosted_providers"] == ["ollama", "custom"]
    assert body["base_url"] == ""


def test_put_passes_the_endpoint_through(client, monkeypatch, public_dns):
    captured = {}

    async def save(_user_id, **kwargs):
        captured.update(kwargs)
        return {"provider": "ollama", "base_url": kwargs["base_url"]}

    monkeypatch.setattr(profile_router.llm_settings_service, "save_settings", save)

    response = client.put(
        "/api/profile/llm",
        json={"provider": "ollama", "base_url": "https://tunnel.example.com"},
        headers=AUTH,
    )

    assert response.status_code == 200
    assert captured["base_url"] == "https://tunnel.example.com"


def test_put_400s_on_an_unreachable_endpoint(client, monkeypatch):
    """
    The SSRF refusal has to reach the reader as a 400 they can act on, not as a
    500 that reads like the server broke.
    """

    async def save(_user_id, **kwargs):
        from services.llm.base_url import validate

        validate(kwargs.get("base_url"))
        return {}

    monkeypatch.setattr(profile_router.llm_settings_service, "save_settings", save)

    response = client.put(
        "/api/profile/llm",
        json={"provider": "ollama", "base_url": "http://169.254.169.254/"},
        headers=AUTH,
    )
    assert response.status_code == 400


def test_test_endpoint_refuses_an_unreachable_endpoint_without_dialling(client):
    """`/test` is pressed before saving, so it is the first place to refuse."""
    response = client.post(
        "/api/profile/llm/test",
        json={"provider": "ollama", "model": "m", "base_url": "http://127.0.0.1:11434"},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "public internet" in response.json()["error"]
