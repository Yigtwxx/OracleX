"""
Auto-titling a chat session from its first message.

Two properties matter here. The title is decoration around a sidebar row, so it
must never take the turn down with it — every LLM failure mode has to degrade to
the user's own text rather than raise. And whatever the model returns has to come
out as one short line, because the column that renders it has a fixed width.
"""

import pytest

from services import chat_service


@pytest.fixture
def llm_spy(monkeypatch):
    """Capture what `generate_session_title` sends to the LLM layer."""
    calls = {}

    async def fake_provider_for(user_id, feature):
        calls["resolved"] = (user_id, feature)
        return f"provider-for-{user_id}" if user_id else None

    def set_reply(reply):
        async def fake_generate(prompt, **kwargs):
            calls["prompt"] = prompt
            calls["kwargs"] = kwargs
            if isinstance(reply, Exception):
                raise reply
            return reply

        monkeypatch.setattr(chat_service.llm, "generate", fake_generate)

    monkeypatch.setattr(chat_service.llm, "provider_for", fake_provider_for)
    calls["set_reply"] = set_reply
    return calls


# ── Cleaning ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("BTC funding reset", "BTC funding reset"),
        ('"BTC funding reset"', "BTC funding reset"),  # quoted by the model
        ("**BTC funding reset**", "BTC funding reset"),  # markdown emphasis
        ("- BTC funding reset.", "BTC funding reset"),  # bullet + trailing stop
        ("BTC   funding\treset", "BTC funding reset"),  # collapsed whitespace
        ("BTC funding reset\n\nHere is why...", "BTC funding reset"),  # first line only
        ("\n\nBTC funding reset", "BTC funding reset"),  # leading blank lines
        ("", ""),
    ],
)
def test_clean_title_reduces_a_reply_to_one_bare_line(raw, expected):
    assert chat_service._clean_title(raw) == expected


def test_clean_title_caps_length_on_a_word_boundary():
    title = chat_service._clean_title("word " * 40)
    assert len(title) <= chat_service.TITLE_MAX_CHARS + 1  # + the ellipsis
    assert title.endswith("…")
    assert not title.endswith(" …")


def test_clean_title_caps_a_single_unbroken_token():
    """No space to cut on — the cap still has to hold."""
    title = chat_service._clean_title("x" * 200)
    assert len(title) == chat_service.TITLE_MAX_CHARS + 1
    assert title.endswith("…")


# ── Generation ────────────────────────────────────────────────────────────────


async def test_uses_the_model_reply_when_there_is_one(llm_spy):
    llm_spy["set_reply"]('"ETH ETF akışları"')
    assert (
        await chat_service.generate_session_title("ETH ETF akışları nasıl?") == "ETH ETF akışları"
    )


async def test_falls_back_to_the_message_when_no_provider_answers(llm_spy):
    """
    `llm.generate` returns None once the whole chain has failed. A generic label
    would tell the user nothing, so their own words stand in.
    """
    llm_spy["set_reply"](None)
    assert await chat_service.generate_session_title("Is BTC overbought?") == "Is BTC overbought?"


async def test_falls_back_to_the_message_when_the_provider_raises(llm_spy):
    llm_spy["set_reply"](RuntimeError("provider exploded"))
    assert await chat_service.generate_session_title("Is BTC overbought?") == "Is BTC overbought?"


async def test_falls_back_when_the_model_returns_only_decoration(llm_spy):
    """A reply that cleans down to nothing is as useless as no reply at all."""
    llm_spy["set_reply"]('"""')
    assert await chat_service.generate_session_title("Is BTC overbought?") == "Is BTC overbought?"


async def test_empty_message_has_nothing_to_title(llm_spy):
    llm_spy["set_reply"]("unused")
    assert await chat_service.generate_session_title("   ") is None
    assert "prompt" not in llm_spy, "an empty message must not reach the LLM"


async def test_long_first_messages_are_truncated_before_the_prompt(llm_spy):
    llm_spy["set_reply"]("Long question")
    await chat_service.generate_session_title("A" * 5000)
    body = llm_spy["prompt"]
    assert "A" * chat_service.TITLE_SOURCE_CHARS in body
    assert "A" * (chat_service.TITLE_SOURCE_CHARS + 1) not in body


async def test_the_users_own_provider_serves_their_titles(llm_spy):
    llm_spy["set_reply"]("BTC")
    await chat_service.generate_session_title("BTC?", user_id="u1")
    assert llm_spy["resolved"] == ("u1", "chat")
    assert llm_spy["kwargs"]["prefer"] == "provider-for-u1"


async def test_titling_without_a_user_uses_the_server_chain(llm_spy):
    llm_spy["set_reply"]("BTC")
    await chat_service.generate_session_title("BTC?")
    assert llm_spy["kwargs"]["prefer"] is None


async def test_titling_asks_for_a_bounded_reply(llm_spy):
    """
    A title is a fixed-length phrase. Hidden reasoning would spend the whole
    token budget before the title is emitted, and a chat-length timeout would
    let a stalled provider hold up the answer that is already done.
    """
    llm_spy["set_reply"]("BTC")
    await chat_service.generate_session_title("BTC?")
    kwargs = llm_spy["kwargs"]
    assert kwargs["reasoning"] is False
    assert kwargs["max_tokens"] == chat_service.TITLE_TOKENS
    assert kwargs["timeout"] == chat_service.TITLE_TIMEOUT
    assert kwargs["timeout"] < chat_service.CHAT_TIMEOUT
