"""
Tests for the RAG router's guard and its failure reporting.

This surface has no frontend caller — it is read by the MCP server and the
agent skills — so nothing about it fails loudly. That is what let three
problems sit here: the corpus rebuild was open to anyone, every handler
reported through `print` and so wrote nothing at the configured log level, and
every handler returned `str(e)` to the caller.

The `/api/rag/stats` case is the one worth stating plainly. It used to answer
200 with `news_count: 0` when the vector store could not be reached at all, and
`agent-skill/oracle-x-api/references/recipes.md` instructs an agent to call it
"when a query comes back thin" — so an outage was reported to the one consumer
that exists as a legitimately empty corpus.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import rag as rag_router

ADMIN = {"Authorization": "Bearer admin-token"}
PLAIN = {"Authorization": "Bearer good-token"}

# Anything whose exception text would name a path or a host. The handlers catch
# `Exception`, so the type does not matter — only that the message never
# reaches the response body.
LEAKY_MESSAGE = "could not reach chroma at /srv/oracle/data/chroma: connection refused"


@pytest.fixture
def client(patch_supabase, admin_emails):
    app = FastAPI()
    app.include_router(rag_router.router)
    return TestClient(app)


def _explode(*_args, **_kwargs):
    raise RuntimeError(LEAKY_MESSAGE)


# ── the guard ────────────────────────────────────────────────────────────────


def test_initialize_refuses_an_anonymous_caller(client):
    """
    The regression: a full corpus re-embed was reachable with no token at all.

    401 rather than 403 — `get_current_user` raises before `require_admin` is
    ever consulted, which is the same split every other admin route has.
    """
    assert client.post("/api/rag/initialize").status_code == 401


def test_initialize_refuses_a_signed_in_non_admin(client):
    assert client.post("/api/rag/initialize", headers=PLAIN).status_code == 403


def test_initialize_admits_an_admin(client, monkeypatch):
    """The guard must not have closed the endpoint to the people it is for."""
    import services.rag_v2_service as rag_v2

    async def _ok(**_kwargs):
        return {"news": 1}

    monkeypatch.setattr(rag_v2, "initialize_rag_v2", _ok, raising=False)

    response = client.post("/api/rag/initialize", headers=ADMIN)

    assert response.status_code == 200
    assert response.json() == {"success": True, "stats": {"news": 1}}


def test_the_read_routes_stay_open(client, monkeypatch):
    """
    Only the rebuild is guarded.

    The agent skills read this surface unauthenticated, so closing the queries
    along with the write would have been a different outage — asserted so a
    future tightening has to be deliberate rather than a slipped decorator.
    """
    import services.rag_v2_service as rag_v2

    monkeypatch.setattr(rag_v2, "query_historical_context", lambda **_kw: [], raising=False)

    assert client.get("/api/rag/query", params={"q": "btc halving"}).status_code == 200


# ── failure reporting ────────────────────────────────────────────────────────


def test_stats_reports_an_unreachable_store_as_unavailable(client, monkeypatch):
    """
    Not a 200 with zeroes.

    An agent told the corpus holds no news reports a confident absence of
    evidence; an agent told the index is unavailable can retry or say so.
    """
    import services.rag_v2_service as rag_v2

    monkeypatch.setattr(rag_v2, "get_rag_stats", _explode, raising=False)

    response = client.get("/api/rag/stats")

    assert response.status_code == 503
    assert "news_count" not in response.text


def test_query_failure_does_not_leak_the_exception(client, monkeypatch):
    import services.rag_v2_service as rag_v2

    monkeypatch.setattr(rag_v2, "query_historical_context", _explode, raising=False)

    response = client.get("/api/rag/query", params={"q": "btc halving"})

    assert response.status_code == 503
    assert LEAKY_MESSAGE not in response.text
    assert "/srv/oracle" not in response.text


def test_initialize_failure_does_not_leak_the_exception(client, monkeypatch):
    import services.rag_v2_service as rag_v2

    monkeypatch.setattr(rag_v2, "initialize_rag_v2", _explode, raising=False)

    response = client.post("/api/rag/initialize", headers=ADMIN)

    assert response.status_code == 503
    assert LEAKY_MESSAGE not in response.text


def test_a_failure_is_logged_at_error_level(client, monkeypatch, caplog):
    """
    `print` bypasses the `LOG_LEVEL` handler `main.py` installs, so a RAG
    outage used to leave no line anywhere a log collector would see it. With no
    frontend on this surface, that line is the only signal there is.
    """
    import services.rag_v2_service as rag_v2

    monkeypatch.setattr(rag_v2, "get_rag_stats", _explode, raising=False)

    with caplog.at_level("ERROR", logger="routers.rag"):
        client.get("/api/rag/stats")

    assert any(LEAKY_MESSAGE in record.getMessage() for record in caplog.records)


# ── the property, over the whole router ──────────────────────────────────────


def test_no_handler_prints_or_returns_a_raw_exception():
    """
    Asserted against the source rather than per route.

    Eleven handlers shared the same two mistakes, and a twelfth added later
    would share them again — the shape is copied from the handler above it. A
    check per route would not have covered the route nobody thought to add.
    """
    import inspect

    source = inspect.getsource(rag_router)

    assert "print(" not in source
    assert "detail=str(e)" not in source
