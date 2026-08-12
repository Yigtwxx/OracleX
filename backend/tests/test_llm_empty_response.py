"""
Tests for a provider that answers 200 with nothing usable in the body.

The bug these pin down: asking Ollama for `format: json` from a thinking model
makes it emit the whole JSON answer on the `thinking` channel and leave
`response` empty. The pipeline saw an empty string, reported "no LLM provider
could serve it", and never tried the fallback chain — the report failed while
two working providers sat unused behind a local model that had, in fact,
answered.
"""

from typing import Any, Optional

import httpx
import pytest

from services.llm import client, providers
from services.llm.base import GenerationRequest, LLMProvider

pytestmark = pytest.mark.asyncio


def _request() -> GenerationRequest:
    return GenerationRequest(prompt="p", system="s", json_mode=True, reasoning=True)


class _StubAsyncClient:
    """Stands in for httpx.AsyncClient, replaying one canned JSON body."""

    def __init__(self, body: dict[str, Any], **_: Any) -> None:
        self._body = body

    async def __aenter__(self) -> "_StubAsyncClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def post(self, url: str, json: Optional[dict] = None) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json=self._body,
            request=httpx.Request("POST", url),
        )


def _patch_ollama_body(monkeypatch, body: dict[str, Any]) -> None:
    monkeypatch.setattr(
        providers.httpx,
        "AsyncClient",
        lambda **kwargs: _StubAsyncClient(body, **kwargs),
    )


class StubProvider(LLMProvider):
    """Returns a fixed string, counting how often it was asked."""

    def __init__(self, name: str, text: str) -> None:
        super().__init__(name=name, base_url="http://stub", model="m", api_key="k")
        self.text = text
        self.calls = 0

    async def generate(self, req: GenerationRequest) -> str:
        self.calls += 1
        return self.text

    async def health(self) -> bool:
        return True


# ── Ollama: the answer arrives on the thinking channel ───────────────────────


async def test_ollama_empty_response_falls_back_to_the_thinking_channel(monkeypatch):
    _patch_ollama_body(
        monkeypatch,
        {"response": "", "thinking": '{"facts": ["BTC is up"]}', "done_reason": "stop"},
    )
    provider = providers.OllamaProvider(
        name="ollama", base_url="http://x", model="qwen3.6:35b-a3b", api_key=""
    )

    result = await provider.generate(_request())

    assert result == '{"facts": ["BTC is up"]}', (
        f"The answer was on the thinking channel and must be recovered, got {result!r}"
    )


async def test_ollama_prefers_the_response_body_over_the_thinking_scratchpad(monkeypatch):
    _patch_ollama_body(
        monkeypatch,
        {"response": "the answer", "thinking": "let me reason about this first"},
    )
    provider = providers.OllamaProvider(name="ollama", base_url="http://x", model="m", api_key="")

    result = await provider.generate(_request())

    assert result == "the answer", f"A real scratchpad must not shadow the answer, got {result!r}"


async def test_ollama_blank_on_both_channels_stays_blank(monkeypatch):
    _patch_ollama_body(monkeypatch, {"response": "", "thinking": "   "})
    provider = providers.OllamaProvider(name="ollama", base_url="http://x", model="m", api_key="")

    assert await provider.generate(_request()) == "", "Whitespace is not an answer"


# ── Chain: an empty answer is a failed provider ──────────────────────────────


async def test_empty_answer_falls_through_to_the_next_provider(monkeypatch):
    empty = StubProvider("empty", "")
    working = StubProvider("working", "real content")
    monkeypatch.setattr(client, "get_chain", lambda: [empty, working])

    result = await client.generate("p")

    assert result == "real content", f"The chain must not stop on an empty answer, got {result!r}"
    assert working.calls == 1, f"The fallback provider must be tried once, got {working.calls}"


async def test_every_provider_empty_returns_none(monkeypatch):
    monkeypatch.setattr(
        client, "get_chain", lambda: [StubProvider("a", ""), StubProvider("b", "  ")]
    )

    result = await client.generate("p")

    assert result is None, f"No provider produced content, so the caller gets None, got {result!r}"
