"""
Regression tests for the bring-your-own-key paths.

Each of these is a bug a reader hit rather than a hypothetical: a personal key
that worked but could not be used, and a personal key that failed in a way that
took every AI surface down with it instead of falling back.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.llm import client as llm_client
from services.llm import providers
from services.llm import usage
from services.llm.base import LLMProvider, LLMRequestError, LLMTransientError

AUTH = {"Authorization": "Bearer good-token"}


class FakeProvider(LLMProvider):
    """A provider that answers, or fails in a chosen way."""

    def __init__(self, name: str, answer: str = "", error: Exception | None = None):
        super().__init__(name=name, base_url="https://example.com", model="m", api_key="k")
        self._answer = answer
        self._error = error
        self.calls = 0

    async def generate(self, req):  # noqa: ANN001
        self.calls += 1
        if self._error is not None:
            raise self._error
        # Mirrors what the real adapters do on a successful call: the usage row
        # for a call that worked is written by the adapter, because it is the
        # only layer that sees the provider's token counts. The client supplies
        # `key_owner` through the context, which is what these tests check.
        providers._record_usage(self.name, self.model, {"prompt_tokens": 3, "completion_tokens": 1})
        return self._answer

    async def health(self) -> bool:
        return True

    async def list_models(self) -> list[str]:
        return ["m"]


@pytest.fixture(autouse=True)
def quiet_usage():
    usage.drain()
    yield
    usage.drain()


@pytest.fixture
def no_cooldowns(monkeypatch):
    monkeypatch.setattr(llm_client, "cooldown_remaining", lambda provider: 0.0)


class TestCallerProviderFallback:
    @pytest.mark.asyncio
    async def test_a_caller_400_falls_back_to_the_server_chain(self, monkeypatch, no_cooldowns):
        """
        The reader's own provider rejecting the request is not our bug.

        A 400 means "every provider would reject this" only when we composed the
        request against a provider we configured. At index 0 it is just as
        likely to be a model id the reader typed wrong, and raising past the
        loop turned that typo into an outage of every AI surface for them.
        """
        caller = FakeProvider("caller", error=LLMRequestError("caller: unknown model"))
        server = FakeProvider("server", answer="served by the chain")
        monkeypatch.setattr(llm_client, "get_chain", lambda: [server])

        answer = await llm_client.generate("hello", prefer=caller)

        assert answer == "served by the chain"
        assert caller.calls == 1
        assert server.calls == 1

    @pytest.mark.asyncio
    async def test_a_server_chain_400_still_surfaces(self, monkeypatch, no_cooldowns):
        """The original reasoning is intact where it applies."""
        server = FakeProvider("server", error=LLMRequestError("bad request"))
        monkeypatch.setattr(llm_client, "get_chain", lambda: [server])

        with pytest.raises(LLMRequestError):
            await llm_client.generate("hello")

    @pytest.mark.asyncio
    async def test_a_caller_transient_failure_still_falls_back(self, monkeypatch, no_cooldowns):
        caller = FakeProvider("caller", error=LLMTransientError("upstream is down"))
        server = FakeProvider("server", answer="ok")
        monkeypatch.setattr(llm_client, "get_chain", lambda: [server])

        assert await llm_client.generate("hello", prefer=caller) == "ok"


class TestUsageAttribution:
    @pytest.mark.asyncio
    async def test_a_call_on_the_readers_provider_is_marked_as_theirs(
        self, monkeypatch, no_cooldowns
    ):
        caller = FakeProvider("caller", answer="hi")
        monkeypatch.setattr(llm_client, "get_chain", lambda: [])

        await llm_client.generate("hello", prefer=caller)

        rows = [r for r in usage.drain() if r.provider == "caller"]
        assert rows, "the adapter records the successful call"
        assert all(r.key_owner == "user" for r in rows)

    @pytest.mark.asyncio
    async def test_key_owner_does_not_leak_to_the_next_provider(self, monkeypatch, no_cooldowns):
        """The reader's marker must not follow the chain onto the server's own."""
        caller = FakeProvider("caller", error=LLMTransientError("down"))
        server = FakeProvider("server", answer="ok")
        monkeypatch.setattr(llm_client, "get_chain", lambda: [server])

        await llm_client.generate("hello", prefer=caller)

        by_provider = {r.provider: r.key_owner for r in usage.drain()}
        assert by_provider.get("caller") == "user"
        assert by_provider.get("server", "server") == "server"

    @pytest.mark.asyncio
    async def test_a_failed_attempt_is_recorded(self, monkeypatch, no_cooldowns):
        """A chain that is quietly falling back should be visible in the view."""
        caller = FakeProvider("caller", error=LLMTransientError("down"))
        server = FakeProvider("server", answer="ok")
        monkeypatch.setattr(llm_client, "get_chain", lambda: [server])

        await llm_client.generate("hello", prefer=caller)

        failed = [r for r in usage.drain() if not r.ok]
        assert len(failed) == 1
        assert failed[0].provider == "caller"


class TestChatStatusSeesTheReadersKey:
    """
    The composer is disabled on `available: false`, and this endpoint used to
    report on the server chain alone — so on an install with no server LLM key,
    a reader with a working personal key could not type. The one scenario the
    whole feature exists for was the one it blocked.
    """

    @pytest.fixture
    def client(self, patch_supabase):
        from routers import chat as chat_router

        app = FastAPI()
        app.include_router(chat_router.router)
        return TestClient(app)

    def test_a_readers_own_provider_makes_chat_available(self, client, monkeypatch):
        from services import llm

        async def provider_for(_user_id, _feature):
            return FakeProvider("mistral", answer="hi")

        async def dead_chain(**_kw):
            return {"active": None}

        monkeypatch.setattr(llm, "provider_for", provider_for)
        monkeypatch.setattr(llm, "active_provider_info", dead_chain)

        body = client.get("/api/chat/status", headers=AUTH).json()
        assert body["available"] is True
        assert body["using_own_key"] is True
        assert body["provider"] == "mistral"

    def test_an_anonymous_caller_still_gets_the_server_answer(self, client, monkeypatch):
        from services import llm

        async def chain(**_kw):
            return {"active": {"provider": "groq", "model": "llama"}}

        monkeypatch.setattr(llm, "active_provider_info", chain)

        body = client.get("/api/chat/status").json()
        assert body["available"] is True
        assert body["using_own_key"] is False

    def test_no_provider_anywhere_still_reports_unavailable(self, client, monkeypatch):
        from services import llm

        async def no_provider(_user_id, _feature):
            return None

        async def dead_chain(**_kw):
            return {"active": None}

        monkeypatch.setattr(llm, "provider_for", no_provider)
        monkeypatch.setattr(llm, "active_provider_info", dead_chain)

        assert client.get("/api/chat/status", headers=AUTH).json()["available"] is False
