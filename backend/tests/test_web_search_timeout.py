"""
How long a web search is allowed to take, and what a failed one leaves behind.

The budget that matters lives inside the search library, not in the caller's
asyncio timeout: `DDGS()` defaults to 5s, and an outer `wait_for` cannot stop a
thread that is already blocked in it. So the service has to hand its own budget
down explicitly, and the chat layer's outer bound has to stay above it — widen
only the outer one and nothing gets more patient; widen only the inner one past
the outer and a stalled request is abandoned mid-flight instead of unwinding.

The cache is the other half: a search that came back empty must not be
remembered, or one slow moment answers the next five minutes of identical
questions with silence.
"""

import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from services import web_search_service


@pytest.fixture
def fake_ddgs(monkeypatch):
    """Install a stub `ddgs` module and capture how DDGS was constructed."""
    calls = {}

    def install(hits=None, raises=None):
        class FakeDDGS:
            def __init__(self, timeout=5, **kwargs):
                calls["timeout"] = timeout

            def text(self, query, max_results=5):
                calls["query"] = query
                if raises is not None:
                    raise raises
                return list(hits or [])

        module = ModuleType("ddgs")
        module.DDGS = FakeDDGS
        monkeypatch.setitem(sys.modules, "ddgs", module)
        return calls

    # Each test starts from an empty cache; the module keeps it at import scope.
    monkeypatch.setattr(web_search_service, "_search_cache", {})
    return SimpleNamespace(install=install, calls=calls)


def test_service_budget_is_handed_to_the_library(fake_ddgs, monkeypatch):
    """Without this the library silently applies its own 5s default."""
    calls = fake_ddgs.install(hits=[{"title": "t", "body": "b", "href": "u"}])
    monkeypatch.setattr(web_search_service, "SEARCH_TIMEOUT", 42.0)

    asyncio.run(web_search_service.search_web("btc", 3))

    assert calls["timeout"] == 42.0


def test_explicit_timeout_overrides_the_default(fake_ddgs):
    calls = fake_ddgs.install(hits=[{"title": "t", "body": "b", "href": "u"}])

    asyncio.run(web_search_service.search_web("btc", 3, timeout=7.5))

    assert calls["timeout"] == 7.5


def test_results_are_cached(fake_ddgs):
    fake_ddgs.install(hits=[{"title": "t", "body": "b", "href": "u"}])

    first = asyncio.run(web_search_service.search_web("btc", 3))
    # A second call with the stub torn down would fail if the cache were missed.
    fake_ddgs.install(raises=RuntimeError("must not be called"))
    second = asyncio.run(web_search_service.search_web("btc", 3))

    assert first == second == [{"title": "t", "snippet": "b", "url": "u"}]


def test_a_failed_search_is_not_cached(fake_ddgs):
    """A timeout must cost one turn, not the whole TTL window."""
    fake_ddgs.install(raises=TimeoutError("too slow"))

    assert asyncio.run(web_search_service.search_web("btc", 3)) == []
    assert web_search_service._search_cache == {}

    # The next identical question reaches the network again and succeeds.
    fake_ddgs.install(hits=[{"title": "t", "body": "b", "href": "u"}])
    assert asyncio.run(web_search_service.search_web("btc", 3)) == [
        {"title": "t", "snippet": "b", "url": "u"}
    ]


def test_chat_outer_bound_clears_the_inner_one():
    """
    `WEB_TIMEOUT` guards a coroutine; the thread under it keeps running. If the
    inner budget ever reached the outer one, chat would give up on a search that
    was still in flight and leak the thread it was waiting on.
    """
    from services import chat_tools

    # Two searches run concurrently, so the inner budget is paid once, not twice.
    assert chat_tools.WEB_TIMEOUT > web_search_service.SEARCH_TIMEOUT
