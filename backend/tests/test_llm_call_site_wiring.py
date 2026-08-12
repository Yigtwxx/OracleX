"""
The user's own provider must reach the AI call sites, and background callers
(no user id) must keep using the server chain.
"""

import pytest

from services import ai_service


@pytest.fixture
def spy(monkeypatch):
    """Capture what ai_service passes to the LLM layer."""
    calls = {}

    async def fake_provider_for(user_id, feature):
        calls["resolved"] = (user_id, feature)
        return f"provider-for-{user_id}" if user_id else None

    async def fake_generate(_prompt, **kwargs):
        calls["prefer"] = kwargs.get("prefer")
        calls["extra"] = kwargs.get("extra")
        return '{"sentiment":"neutral","confidence":0.5,"reasoning":"ok"}'

    monkeypatch.setattr(ai_service.llm, "provider_for", fake_provider_for)
    monkeypatch.setattr(ai_service.llm, "generate", fake_generate)
    return calls


async def test_analyze_news_resolves_the_news_feature(spy):
    await ai_service.analyze_news(
        title="t", summary="s", symbol="NASDAQ:NVDA", asset_type="stock", user_id="u1"
    )
    assert spy["resolved"] == ("u1", "news")
    assert spy["prefer"] == "provider-for-u1"


async def test_analyze_news_without_user_uses_server_chain(spy):
    await ai_service.analyze_news(title="t", summary="s", symbol="NASDAQ:NVDA", asset_type="stock")
    assert spy["prefer"] is None


async def test_analyze_news_requests_an_explicit_context_window(spy):
    """
    Ollama defaults to a 4096-token context and truncates from the front, which
    drops the system prompt — the calibration and anti-fabrication rules. The
    news prompt is bigger than that, so `num_ctx` has to be sent explicitly.
    """
    await ai_service.analyze_news(title="t", summary="s", symbol="NASDAQ:NVDA", asset_type="stock")
    assert spy["extra"]["num_ctx"] == ai_service.NEWS_NUM_CTX
    assert ai_service.NEWS_NUM_CTX >= 8192


async def test_generate_completion_resolves_the_reports_feature(spy):
    await ai_service.generate_completion("prompt", user_id="u1")
    assert spy["resolved"] == ("u1", "reports")
    assert spy["prefer"] == "provider-for-u1"


async def test_generate_completion_without_user_uses_server_chain(spy):
    await ai_service.generate_completion("prompt")
    assert spy["prefer"] is None
