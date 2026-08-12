"""
Tests for HTTP 429 handling: delay extraction, backoff, and quota cooldowns.

The bug these pin down: Gemini's free tier answers 429 with "retry in 38s",
while the old backoff waited about three seconds in total and then handed the
same exhausted provider the next request a moment later.
"""

import functools
from typing import Optional

import httpx
import pytest

from services.llm import client, providers
from services.llm.base import (
    GenerationRequest,
    LLMProvider,
    LLMRateLimitError,
    LLMRequestError,
    LLMTransientError,
    LLMUnavailableError,
)

# A real Gemini free-tier rejection, trimmed to the fields that matter.
GEMINI_429_BODY = """[{
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details.\\n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3.6-flash\\nPlease retry in 38.457219637s.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "38s"}
    ]
  }
}]"""

# A real Groq rejection: the *daily* token budget is spent, yet the accompanying
# Retry-After is barely a minute.
GROQ_DAILY_429_BODY = """{
  "error": {
    "message": "Rate limit reached for model `qwen/qwen3.6-27b` in organization `org_01ky` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199854, Requested 297. Please try again in 1m6s.",
    "type": "tokens",
    "code": "rate_limit_exceeded"
  }
}"""


def _response(status: int, body: str = "{}", headers: Optional[dict] = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        content=body.encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        request=httpx.Request("POST", "https://example.test/chat/completions"),
    )


class StubProvider(LLMProvider):
    """Replays a scripted sequence of outcomes, one per call."""

    def __init__(self, name: str, outcomes: list, api_key: str = "k"):
        super().__init__(name=name, base_url="http://stub", model="m", api_key=api_key)
        self.outcomes = list(outcomes)
        self.calls = 0

    async def generate(self, req: GenerationRequest) -> str:
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else self.outcomes
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def health(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _no_leftover_cooldowns():
    """Cooldowns are process-global; keep them from leaking between tests."""
    client.clear_cooldowns()
    yield
    client.clear_cooldowns()


@pytest.fixture
def instant_sleep(monkeypatch):
    """
    Record what the retry logic waits for instead of actually waiting.

    tenacity takes its sleep function as a constructor default, so it has to be
    injected where the client builds the retryer rather than patched globally.
    """
    slept: list = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(
        client,
        "AsyncRetrying",
        functools.partial(client.AsyncRetrying, sleep=fake_sleep),
    )
    return slept


# ── 429 parsing ──────────────────────────────────────────────────────────────


def test_raise_for_status_429_raises_rate_limit_error():
    with pytest.raises(LLMRateLimitError):
        providers._raise_for_status("gemini", _response(429, GEMINI_429_BODY))


def test_raise_for_status_extracts_retry_delay_from_body():
    with pytest.raises(LLMRateLimitError) as excinfo:
        providers._raise_for_status("gemini", _response(429, GEMINI_429_BODY))
    assert excinfo.value.retry_after == 38.0, (
        f"Expected the RetryInfo delay of 38s, got {excinfo.value.retry_after}"
    )


def test_raise_for_status_prefers_retry_after_header():
    response = _response(429, GEMINI_429_BODY, headers={"Retry-After": "12"})
    with pytest.raises(LLMRateLimitError) as excinfo:
        providers._raise_for_status("gemini", response)
    assert excinfo.value.retry_after == 12.0


def test_raise_for_status_429_without_any_delay_is_none():
    with pytest.raises(LLMRateLimitError) as excinfo:
        providers._raise_for_status("groq", _response(429, '{"error": {"message": "slow down"}}'))
    assert excinfo.value.retry_after is None


def test_rate_limit_error_is_still_transient():
    """Existing `except LLMTransientError` call sites must keep working."""
    assert issubclass(LLMRateLimitError, LLMTransientError)


# ── daily budgets are told apart from rolling windows ────────────────────────


def test_spent_daily_budget_is_flagged_as_daily():
    with pytest.raises(LLMRateLimitError) as excinfo:
        providers._raise_for_status("groq", _response(429, GROQ_DAILY_429_BODY))
    assert excinfo.value.daily is True, "'tokens per day (TPD)' must be read as a daily budget"


def test_per_minute_quota_is_not_flagged_as_daily():
    with pytest.raises(LLMRateLimitError) as excinfo:
        providers._raise_for_status("gemini", _response(429, GEMINI_429_BODY))
    assert excinfo.value.daily is False


async def test_daily_budget_is_never_retried(monkeypatch, instant_sleep):
    """A spent daily budget will still be spent a few seconds from now."""
    limited = StubProvider("groq", [LLMRateLimitError("429", retry_after=66.0, daily=True)])
    backup = StubProvider("ollama", ["from-backup"], api_key="")
    monkeypatch.setattr(client, "get_chain", lambda: [limited, backup])

    assert await client.generate("hi") == "from-backup"
    assert limited.calls == 1
    assert instant_sleep == []


async def test_daily_budget_ignores_the_providers_optimistic_delay(monkeypatch):
    """Groq says 66s; believing it means re-probing a dead provider all day."""
    monkeypatch.setattr(client.settings, "LLM_DAILY_QUOTA_COOLDOWN", 1800.0)
    limited = StubProvider("groq", [LLMRateLimitError("429", retry_after=66.0, daily=True)])
    monkeypatch.setattr(client, "get_chain", lambda: [limited])

    assert await client.generate("hi") is None
    remaining = client.cooldown_remaining(limited)
    assert remaining > 1700, f"Expected a ~1800s cooldown, got {remaining:.0f}s"


async def test_concurrent_failures_do_not_restate_the_cooldown(monkeypatch, caplog):
    """
    Five callers hit the limit in the same instant; one cooldown is announced.

    The old behaviour logged a fresh line per caller and pushed the deadline out
    each time, so the log said "skipping for 66s" five times in one second.
    """
    monkeypatch.setattr(client.settings, "LLM_DAILY_QUOTA_COOLDOWN", 1800.0)
    limited = StubProvider("groq", [LLMRateLimitError("429", retry_after=66.0, daily=True)] * 5)
    monkeypatch.setattr(client, "get_chain", lambda: [limited])

    def announcements():
        return [r for r in caplog.records if "over its" in r.message]

    with caplog.at_level("WARNING", logger="services.llm.client"):
        # The first caller to lose the race records and announces the cooldown.
        await client.generate("hi")
        announcements_before = announcements()

        # The other four arrive with the cooldown already in force.
        for _ in range(4):
            client._start_cooldown(limited, LLMRateLimitError("429", retry_after=66.0, daily=True))
        announcements_after = announcements()

    assert len(announcements_before) == 1
    assert len(announcements_after) == 1, "A second caller restated a cooldown already in force"


# ── log hygiene ──────────────────────────────────────────────────────────────


def test_error_detail_keeps_only_the_provider_message():
    detail = providers._error_detail(_response(429, GEMINI_429_BODY))
    assert "You exceeded your current quota" in detail
    assert "RetryInfo" not in detail, f"Raw envelope leaked into the log line: {detail}"


def test_error_detail_is_a_single_bounded_line():
    detail = providers._error_detail(_response(429, GEMINI_429_BODY))
    assert "\n" not in detail
    assert len(detail) <= providers._DETAIL_LIMIT


def test_error_detail_falls_back_to_text_for_non_json():
    detail = providers._error_detail(_response(500, "<html>gateway error</html>"))
    assert "gateway error" in detail


# ── status mapping is unchanged for everything else ──────────────────────────


@pytest.mark.parametrize(
    "status,expected",
    [
        (400, LLMRequestError),
        (401, LLMUnavailableError),
        (403, LLMUnavailableError),
        (404, LLMUnavailableError),
        (418, LLMUnavailableError),
        (500, LLMTransientError),
        (503, LLMTransientError),
    ],
)
def test_status_mapping_is_preserved(status, expected):
    with pytest.raises(expected):
        providers._raise_for_status("groq", _response(status))


def test_success_status_does_not_raise():
    providers._raise_for_status("groq", _response(200))


# ── backoff honours the provider's own delay ─────────────────────────────────


async def test_short_rate_limit_is_waited_out_and_retried(monkeypatch, instant_sleep):
    monkeypatch.setattr(client.settings, "LLM_RATE_LIMIT_MAX_WAIT", 30.0)
    provider = StubProvider("groq", [LLMRateLimitError("429", retry_after=5.0), "ok"])
    monkeypatch.setattr(client, "get_chain", lambda: [provider])

    assert await client.generate("hi") == "ok"
    assert provider.calls == 2
    # The provider's clock, not ours: its delay plus a one second margin.
    assert instant_sleep == [6.0], f"Expected a single 6s wait, got {instant_sleep}"


async def test_long_rate_limit_falls_through_instead_of_stalling(monkeypatch, instant_sleep):
    """38s > the 30s budget, so the chain moves on rather than blocking."""
    monkeypatch.setattr(client.settings, "LLM_RATE_LIMIT_MAX_WAIT", 30.0)
    limited = StubProvider("gemini", [LLMRateLimitError("429", retry_after=38.0)], api_key="a")
    backup = StubProvider("ollama", ["from-backup"], api_key="")
    monkeypatch.setattr(client, "get_chain", lambda: [limited, backup])

    assert await client.generate("hi") == "from-backup"
    assert limited.calls == 1, "A delay past the budget must not be retried"
    assert instant_sleep == []


async def test_rate_limit_without_a_delay_still_retries(monkeypatch, instant_sleep):
    provider = StubProvider("groq", [LLMRateLimitError("429", retry_after=None), "ok"])
    monkeypatch.setattr(client, "get_chain", lambda: [provider])

    assert await client.generate("hi") == "ok"
    assert instant_sleep, "A 429 with no stated delay should still back off exponentially"


# ── cooldowns ────────────────────────────────────────────────────────────────


async def test_rate_limited_provider_is_skipped_by_the_next_request(monkeypatch):
    monkeypatch.setattr(client.settings, "LLM_RATE_LIMIT_MAX_WAIT", 30.0)
    limited = StubProvider("gemini", [LLMRateLimitError("429", retry_after=38.0)], api_key="a")
    backup = StubProvider("ollama", ["first", "second"], api_key="")
    monkeypatch.setattr(client, "get_chain", lambda: [limited, backup])

    assert await client.generate("one") == "first"
    assert await client.generate("two") == "second"
    assert limited.calls == 1, (
        f"The exhausted provider was asked again inside its quota window ({limited.calls} calls)"
    )


async def test_cooldown_expires(monkeypatch):
    monkeypatch.setattr(client.settings, "LLM_RATE_LIMIT_MAX_WAIT", 30.0)
    limited = StubProvider(
        "gemini", [LLMRateLimitError("429", retry_after=38.0), "recovered"], api_key="a"
    )
    backup = StubProvider("ollama", ["from-backup"], api_key="")
    monkeypatch.setattr(client, "get_chain", lambda: [limited, backup])

    assert await client.generate("one") == "from-backup"
    assert client.cooldown_remaining(limited) > 0

    # Jump past the window rather than sleeping through it.
    now = client.time.monotonic()
    monkeypatch.setattr(client.time, "monotonic", lambda: now + 100)

    assert client.cooldown_remaining(limited) == 0.0
    assert await client.generate("two") == "recovered"


async def test_cooldown_is_per_credential_not_per_provider_name(monkeypatch):
    """One user's exhausted key must not sideline the server's own key."""
    monkeypatch.setattr(client.settings, "LLM_RATE_LIMIT_MAX_WAIT", 30.0)
    user_key = StubProvider("gemini", [LLMRateLimitError("429", retry_after=38.0)], api_key="user")
    server_key = StubProvider("gemini", ["from-server"], api_key="server")
    monkeypatch.setattr(client, "get_chain", lambda: [server_key])

    assert await client.generate("hi", prefer=user_key) == "from-server"
    assert client.cooldown_remaining(user_key) > 0
    assert client.cooldown_remaining(server_key) == 0.0


async def test_returns_none_when_every_provider_is_cooling(monkeypatch):
    monkeypatch.setattr(client.settings, "LLM_RATE_LIMIT_MAX_WAIT", 30.0)
    limited = StubProvider("gemini", [LLMRateLimitError("429", retry_after=38.0)], api_key="a")
    monkeypatch.setattr(client, "get_chain", lambda: [limited])

    assert await client.generate("one") is None
    assert await client.generate("two") is None
    assert limited.calls == 1, "The second request must not touch an exhausted provider"


async def test_malformed_request_still_surfaces(monkeypatch):
    """A 400 is our bug; a cooldown or fallback must never hide it."""
    provider = StubProvider("groq", [LLMRequestError("400: bad payload")])
    monkeypatch.setattr(client, "get_chain", lambda: [provider])

    with pytest.raises(LLMRequestError):
        await client.generate("hi")
