"""Tests for per-user provider resolution and chain preference."""

from services import llm_settings_service
from services.llm import client, user_prefs
from services.llm.base import GenerationRequest, LLMProvider, LLMUnavailableError


class StubProvider(LLMProvider):
    """A provider that answers with a fixed string, or always fails."""

    def __init__(self, name, reply=None, fail=False):
        super().__init__(name=name, base_url="http://stub", model="m", api_key="")
        self.reply = reply
        self.fail = fail
        self.calls = 0

    async def generate(self, req: GenerationRequest) -> str:
        self.calls += 1
        if self.fail:
            raise LLMUnavailableError(f"{self.name} is down")
        return self.reply

    async def health(self) -> bool:
        return not self.fail


# ── build_provider ───────────────────────────────────────────────────────────


def test_build_provider_uses_preset_base_url():
    provider = client.build_provider("groq", "llama-3.3-70b-versatile", "gsk_x")
    assert provider is not None
    assert provider.base_url == "https://api.groq.com/openai/v1"
    assert provider.model == "llama-3.3-70b-versatile"


def test_build_provider_falls_back_to_preset_model():
    provider = client.build_provider("groq", "", "gsk_x")
    assert provider is not None
    assert provider.model != ""


def test_build_provider_rejects_unknown_name():
    assert client.build_provider("evil-host", "m", "k") is None


def test_build_provider_never_exposes_key_in_repr():
    provider = client.build_provider("groq", "m", "gsk_supersecret")
    assert "gsk_supersecret" not in repr(provider)


# ── generate(prefer=...) ─────────────────────────────────────────────────────


async def test_prefer_provider_is_used_first(monkeypatch):
    server = StubProvider("server", reply="from-server")
    monkeypatch.setattr(client, "get_chain", lambda: [server])

    preferred = StubProvider("user", reply="from-user")
    result = await client.generate("hi", prefer=preferred)

    assert result == "from-user"
    assert server.calls == 0


async def test_falls_back_to_server_chain_when_preferred_fails(monkeypatch):
    server = StubProvider("server", reply="from-server")
    monkeypatch.setattr(client, "get_chain", lambda: [server])

    preferred = StubProvider("user", fail=True)
    result = await client.generate("hi", prefer=preferred)

    assert result == "from-server"
    assert preferred.calls == 1


async def test_without_prefer_the_chain_is_unchanged(monkeypatch):
    server = StubProvider("server", reply="from-server")
    monkeypatch.setattr(client, "get_chain", lambda: [server])
    assert await client.generate("hi") == "from-server"


# ── provider_for ─────────────────────────────────────────────────────────────


async def test_provider_for_returns_none_without_user():
    assert await user_prefs.provider_for(None, "chat") is None


async def test_provider_for_builds_when_feature_enabled(monkeypatch):
    async def fake_credentials(_user_id):
        return {
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
            "api_key": "gsk_x",
            "use_for_chat": True,
            "use_for_news": False,
            "use_for_reports": False,
        }

    monkeypatch.setattr(llm_settings_service, "get_credentials", fake_credentials)

    provider = await user_prefs.provider_for("u1", "chat")
    assert provider is not None
    assert provider.name == "groq"


async def test_provider_for_respects_disabled_feature(monkeypatch):
    async def fake_credentials(_user_id):
        return {
            "provider": "groq",
            "model": "",
            "api_key": "gsk_x",
            "use_for_chat": True,
            "use_for_news": False,
            "use_for_reports": False,
        }

    monkeypatch.setattr(llm_settings_service, "get_credentials", fake_credentials)
    assert await user_prefs.provider_for("u1", "news") is None


async def test_provider_for_unknown_feature_is_none(monkeypatch):
    async def fake_credentials(_user_id):
        return {"provider": "groq", "model": "", "api_key": "k", "use_for_chat": True}

    monkeypatch.setattr(llm_settings_service, "get_credentials", fake_credentials)
    assert await user_prefs.provider_for("u1", "background") is None


async def test_provider_for_returns_none_when_unconfigured(monkeypatch):
    async def no_credentials(_user_id):
        return None

    monkeypatch.setattr(llm_settings_service, "get_credentials", no_credentials)
    assert await user_prefs.provider_for("u1", "chat") is None


# ── notes ────────────────────────────────────────────────────────────────────
#
# Notes are the widest surface behind one toggle — seventeen call sites share
# `ai_notes` — and were the last place a user who had switched everything on
# still met the server's model.


async def test_provider_for_resolves_the_notes_feature(monkeypatch):
    async def fake_credentials(_user_id):
        return {
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
            "api_key": "gsk_x",
            "use_for_chat": False,
            "use_for_news": False,
            "use_for_reports": False,
            "use_for_notes": True,
        }

    monkeypatch.setattr(llm_settings_service, "get_credentials", fake_credentials)

    provider = await user_prefs.provider_for("u1", "notes")
    assert provider is not None
    assert provider.name == "groq"


async def test_notes_stay_on_the_server_chain_when_the_toggle_is_off(monkeypatch):
    async def fake_credentials(_user_id):
        return {
            "provider": "groq",
            "model": "",
            "api_key": "gsk_x",
            "use_for_chat": True,
            "use_for_news": True,
            "use_for_reports": True,
            "use_for_notes": False,
        }

    monkeypatch.setattr(llm_settings_service, "get_credentials", fake_credentials)

    assert await user_prefs.provider_for("u1", "notes") is None


def test_notes_is_a_recognised_feature():
    """`provider_for` silently returns None for a name outside FEATURES."""
    assert "notes" in llm_settings_service.FEATURES
