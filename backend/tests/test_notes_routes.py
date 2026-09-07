"""
Tests for the notes endpoints' auth boundary and owner scoping.

These endpoints were open, over a single shared file with no owner in it, so
any visitor read and deleted every account's notes. The backend runs with the
service-role key and bypasses row-level security, which makes the `user_id`
filter in every query the only thing enforcing ownership — so both halves are
pinned here: the router refuses an anonymous caller, and the service never
issues a query without the owner on it.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import analysis as analysis_router
from services import notes_service

GOOD = {"Authorization": "Bearer good-token"}


class FakeQuery:
    """Records the filters a call chained, then answers with `rows`."""

    def __init__(self, table: str, log: list, rows: list):
        self.table = table
        self.log = log
        self.rows = rows
        self.filters: dict = {}
        self.op = None
        self.payload = None

    def select(self, *_args, **_kwargs):
        self.op = "select"
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        self.log.append(
            {"table": self.table, "op": self.op, "filters": self.filters, "payload": self.payload}
        )
        if self.op == "insert":
            return SimpleNamespace(data=[self.payload])
        return SimpleNamespace(data=list(self.rows))


class FakeClient:
    def __init__(self, rows=None):
        self.log: list = []
        self.rows = rows if rows is not None else []

    def table(self, name):
        return FakeQuery(name, self.log, self.rows)


@pytest.fixture
def client(patch_supabase):
    app = FastAPI()
    app.include_router(analysis_router.router)
    return TestClient(app)


@pytest.fixture
def store(monkeypatch):
    fake = FakeClient(
        rows=[
            {
                "id": "note-1",
                "title": "A title",
                "content": "A body",
                "created_at": "2026-09-01T10:00:00+00:00",
            }
        ]
    )
    monkeypatch.setattr(notes_service, "_client", lambda: fake)
    return fake


# ── the endpoints refuse an anonymous caller ─────────────────────────────────


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/analysis/notes", None),
        ("post", "/api/analysis/notes", {"title": "t", "content": "c"}),
        ("delete", "/api/analysis/notes/note-1", None),
    ],
)
def test_notes_require_a_verified_caller(client, store, method, path, body):
    response = getattr(client, method)(path, **({"json": body} if body else {}))

    assert response.status_code == 401
    # The refusal happens before anything reaches the database.
    assert store.log == []


# ── every query carries the caller's id ──────────────────────────────────────


def test_read_is_scoped_to_the_caller(client, store):
    response = client.get("/api/analysis/notes", headers=GOOD)

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "note-1",
            "title": "A title",
            "content": "A body",
            "date": "2026-09-01T10:00:00+00:00",
        }
    ]
    assert store.log[0]["filters"] == {"user_id": "user-abc"}


def test_create_stamps_the_caller_as_the_owner(client, store):
    response = client.post(
        "/api/analysis/notes", headers=GOOD, json={"title": "  Idea  ", "content": "Body"}
    )

    assert response.status_code == 200
    insert = next(entry for entry in store.log if entry["op"] == "insert")
    assert insert["payload"]["user_id"] == "user-abc"
    assert insert["payload"]["title"] == "Idea"


def test_delete_filters_on_the_owner_as_well_as_the_id(client, store):
    response = client.delete("/api/analysis/notes/note-9", headers=GOOD)

    assert response.status_code == 200
    delete = next(entry for entry in store.log if entry["op"] == "delete")
    # Without the user_id, the service-role key would take any note whose id
    # was guessed — that filter is the authorisation.
    assert delete["filters"] == {"id": "note-9", "user_id": "user-abc"}


# ── the body is bounded ──────────────────────────────────────────────────────


def test_an_oversized_body_is_refused_before_it_is_written(client, store):
    response = client.post(
        "/api/analysis/notes",
        headers=GOOD,
        json={"title": "t", "content": "x" * (notes_service.MAX_CONTENT_LENGTH + 1)},
    )

    assert response.status_code == 422
    assert store.log == []


def test_an_empty_title_is_refused(client, store):
    response = client.post("/api/analysis/notes", headers=GOOD, json={"title": "", "content": "c"})

    assert response.status_code == 422
    assert store.log == []


# ── an owner is required at the service layer too ────────────────────────────


@pytest.mark.asyncio
async def test_the_service_refuses_a_write_with_no_owner(store):
    with pytest.raises(PermissionError):
        await notes_service.create_note("", "t", "c")
    with pytest.raises(PermissionError):
        await notes_service.delete_note("", "note-1")
    assert await notes_service.get_notes("") == []
    assert store.log == []
