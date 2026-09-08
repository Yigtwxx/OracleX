"""
Tests for the watchlist endpoints' auth boundary and owner scoping.

These endpoints were open, over a single shared `data/watchlist.json` with no
owner in it, so any client read and deleted every account's lists. The backend
runs with the service-role key and bypasses row-level security, which makes the
`user_id` filter in every query the only thing enforcing ownership — so both
halves are pinned here: the router refuses an anonymous caller, and the service
never issues a query without the owner on it.

The store is faked rather than mocked per call, because what is worth asserting
is the *shape of the query that was issued* — which filters it carried — and a
return-value mock would let a query with no owner on it pass.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import watchlist as watchlist_router
from services import watchlist_service

GOOD = {"Authorization": "Bearer good-token"}


class FakeQuery:
    """Records the filters a call chained, then answers with `rows`."""

    def __init__(self, table: str, log: list, rows: list, fail: bool = False):
        self.table = table
        self.log = log
        self.rows = rows
        self.fail = fail
        self.filters: dict = {}
        self.op = None
        self.payload = None
        self.max_rows = None

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

    def limit(self, count, *_args, **_kwargs):
        # Recorded rather than swallowed: MAX_LISTS_PER_USER is expressed only
        # as this argument, so nothing else can show the bound is still applied.
        self.max_rows = count
        return self

    def execute(self):
        self.log.append(
            {
                "table": self.table,
                "op": self.op,
                "filters": self.filters,
                "payload": self.payload,
                "limit": self.max_rows,
            }
        )
        if self.fail:
            raise RuntimeError("upstream is down")
        if self.op == "insert":
            # `_rows_to_lists` reads `row["id"]`, which PostgREST supplies and a
            # bare echo of the payload would not.
            return SimpleNamespace(data=[{"id": "list-new", **self.payload}])
        return SimpleNamespace(data=list(self.rows))


class FakeClient:
    def __init__(self, rows=None, fail: bool = False):
        self.log: list = []
        self.rows = rows if rows is not None else []
        self.fail = fail

    def table(self, name):
        return FakeQuery(name, self.log, self.rows, self.fail)


@pytest.fixture
def client(patch_supabase):
    app = FastAPI()
    app.include_router(watchlist_router.router)
    return TestClient(app)


@pytest.fixture
def store(monkeypatch):
    """
    A fake table plus a hydrator that fetches nothing.

    `watchlist_service` imports `get_supabase` inside each function, so the name
    is resolved on the source module at call time and that is what has to be
    patched. `_hydrate_prices` is stubbed because a read otherwise reaches
    CoinGecko and Yahoo; it records its calls so a test can assert a read with
    nothing to price never went looking.
    """
    fake = FakeClient(
        rows=[
            {
                "id": "list-1",
                "name": "Majors",
                "items": [{"symbol": "BTC", "type": "CRYPTO"}],
            }
        ]
    )
    monkeypatch.setattr("services.supabase_service.get_supabase", lambda: fake)

    fake.hydrated = []

    async def _passthrough(lists):
        fake.hydrated.append(lists)
        return lists

    monkeypatch.setattr(watchlist_service, "_hydrate_prices", _passthrough)
    return fake


# ── the endpoints refuse an anonymous caller ─────────────────────────────────


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/home/watchlist", None),
        ("post", "/api/home/watchlist", {"name": "Majors", "items": []}),
        ("delete", "/api/home/watchlist/list-1", None),
    ],
)
def test_watchlist_endpoints_require_a_verified_caller(client, store, method, path, body):
    response = getattr(client, method)(path, **({"json": body} if body else {}))

    assert response.status_code == 401
    # The refusal happens before anything reaches the database.
    assert store.log == []


# ── every query carries the caller's id ──────────────────────────────────────


def test_read_is_scoped_to_the_caller(client, store):
    response = client.get("/api/home/watchlist", headers=GOOD)

    assert response.status_code == 200
    assert response.json() == [
        {"id": "list-1", "name": "Majors", "items": [{"symbol": "BTC", "type": "CRYPTO"}]}
    ]
    assert store.log[0]["filters"] == {"user_id": "user-abc"}


def test_the_read_is_capped_at_the_per_user_limit(client, store):
    client.get("/api/home/watchlist", headers=GOOD)

    assert store.log[0]["limit"] == watchlist_service.MAX_LISTS_PER_USER


def test_create_stamps_the_caller_as_the_owner(client, store):
    response = client.post(
        "/api/home/watchlist",
        headers=GOOD,
        json={"name": "Majors", "items": [{"symbol": "BTC", "type": "CRYPTO"}]},
    )

    assert response.status_code == 200
    insert = next(entry for entry in store.log if entry["op"] == "insert")
    assert insert["payload"]["user_id"] == "user-abc"


def test_delete_filters_on_the_owner_as_well_as_the_id(client, store):
    response = client.delete("/api/home/watchlist/list-9", headers=GOOD)

    assert response.status_code == 200
    delete = next(entry for entry in store.log if entry["op"] == "delete")
    # Without the user_id, the service-role key would take any list whose id was
    # guessed — that filter is the authorisation, not a convenience.
    assert delete["filters"] == {"id": "list-9", "user_id": "user-abc"}


def test_another_owners_list_id_is_a_no_op_rather_than_a_404(client, store):
    """
    The delete matches nothing rather than reporting whose it was.

    A 404 for a list that exists but belongs to someone else would confirm the
    id — the contract in the router's docstring is that the query simply matches
    nothing, so the two cases are indistinguishable from outside.
    """
    response = client.delete("/api/home/watchlist/someone-elses-list", headers=GOOD)

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    delete = next(entry for entry in store.log if entry["op"] == "delete")
    assert delete["filters"]["user_id"] == "user-abc"


# ── the write is normalised before it is stored ──────────────────────────────


def test_the_name_is_trimmed_and_capped(client, store):
    client.post("/api/home/watchlist", headers=GOOD, json={"name": "  " + "x" * 200, "items": []})

    insert = next(entry for entry in store.log if entry["op"] == "insert")
    assert insert["payload"]["name"] == "x" * 80


def test_a_blank_name_falls_back_rather_than_storing_an_empty_string(client, store):
    client.post("/api/home/watchlist", headers=GOOD, json={"name": "   ", "items": []})

    insert = next(entry for entry in store.log if entry["op"] == "insert")
    assert insert["payload"]["name"] == "Watchlist"


def test_items_are_cleaned_before_the_insert(client, store):
    """
    Cleaned on the way in, so the column never holds an entry the price
    hydrator would later be handed and refuse.
    """
    client.post(
        "/api/home/watchlist",
        headers=GOOD,
        json={
            "name": "Mixed",
            "items": [
                {"symbol": " btc ", "type": "crypto"},
                {"symbol": "BTC", "type": "CRYPTO"},
                {"symbol": "AAPL", "type": "STOCK"},
                {"symbol": "EURUSD", "type": "FOREX"},
                {"symbol": "", "type": "CRYPTO"},
            ],
        },
    )

    insert = next(entry for entry in store.log if entry["op"] == "insert")
    assert insert["payload"]["items"] == [
        {"symbol": "BTC", "type": "CRYPTO"},
        {"symbol": "AAPL", "type": "STOCK"},
    ]


def test_a_malformed_body_is_refused_before_it_is_written(client, store):
    response = client.post("/api/home/watchlist", headers=GOOD, json={"name": "Majors"})

    assert response.status_code == 422
    assert store.log == []


# ── an upstream failure is reported, not rendered as an empty list ───────────


@pytest.fixture
def broken_store(monkeypatch):
    fake = FakeClient(fail=True)
    monkeypatch.setattr("services.supabase_service.get_supabase", lambda: fake)
    return fake


@pytest.mark.parametrize(
    "method,path,body,detail",
    [
        ("get", "/api/home/watchlist", None, "Watchlists are unavailable right now"),
        (
            "post",
            "/api/home/watchlist",
            {"name": "Majors", "items": []},
            "The watchlist could not be created",
        ),
        ("delete", "/api/home/watchlist/list-1", None, "The watchlist could not be deleted"),
    ],
)
def test_an_upstream_failure_answers_503(client, broken_store, method, path, body, detail):
    """
    503 rather than an empty 200: a reader whose lists failed to load must not
    be shown the same screen as a reader who has none.
    """
    response = getattr(client, method)(path, headers=GOOD, **({"json": body} if body else {}))

    assert response.status_code == 503
    assert response.json()["detail"] == detail
