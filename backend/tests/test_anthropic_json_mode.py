"""
Anthropic has no `response_format`, so `json_mode` has to be expressed as a
forced tool call. Without it the JSON stages fall back to brace-slicing prose.
"""

import json

import pytest

from services.llm import providers
from services.llm.base import GenerationRequest


@pytest.fixture
def provider():
    return providers.AnthropicProvider(
        name="anthropic",
        base_url="https://api.anthropic.com/v1",
        api_key="test-key",
        model="claude-sonnet-4-5",
    )


@pytest.fixture
def captured(monkeypatch):
    """Capture the outgoing payload and return a canned Messages API response."""
    seen = {}

    async def fake_post(_name, _url, *, json, headers, timeout):  # noqa: A002
        seen["payload"] = json
        return seen["response"]

    monkeypatch.setattr(providers, "_post", fake_post)
    return seen


async def test_json_mode_forces_the_emit_json_tool(provider, captured):
    captured["response"] = {
        "content": [
            {
                "type": "tool_use",
                "name": "emit_json",
                "input": {"sentiment": "bearish", "confidence": 0.72},
            }
        ]
    }

    raw = await provider.generate(
        GenerationRequest(prompt="p", system="s", json_mode=True, max_tokens=100)
    )

    payload = captured["payload"]
    assert payload["tool_choice"] == {"type": "tool", "name": "emit_json"}
    assert payload["tools"][0]["name"] == "emit_json"
    assert json.loads(raw) == {"sentiment": "bearish", "confidence": 0.72}


async def test_tool_use_wins_over_a_trailing_text_block(provider, captured):
    """
    The text filter drops tool_use blocks, so checking text first would return
    the model's preamble — or an empty string — instead of the JSON.
    """
    captured["response"] = {
        "content": [
            {"type": "text", "text": "Here is the JSON:"},
            {"type": "tool_use", "name": "emit_json", "input": {"ok": True}},
        ]
    }

    raw = await provider.generate(GenerationRequest(prompt="p", json_mode=True, max_tokens=100))

    assert json.loads(raw) == {"ok": True}


async def test_without_json_mode_no_tool_is_sent_and_text_is_returned(provider, captured):
    captured["response"] = {"content": [{"type": "text", "text": "  plain prose  "}]}

    raw = await provider.generate(GenerationRequest(prompt="p", max_tokens=100))

    assert "tools" not in captured["payload"]
    assert "tool_choice" not in captured["payload"]
    assert raw == "plain prose"
