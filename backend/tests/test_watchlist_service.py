"""
Tests for the watchlist store itself, below the router.

The routes are covered in `test_watchlist_routes.py`; what is pinned here is
everything the router cannot reach — the owner guards the service applies on its
own, what it does when Supabase is not configured at all, and `_clean_items`,
which is the only thing standing between a `jsonb` column any authenticated
client can write and a price fetcher.

Nothing here authenticates, so the `patch_supabase` fixture is not needed.
"""

from types import SimpleNamespace

import pytest

from services import watchlist_service
from services.watchlist_service import (
    MAX_ITEMS_PER_LIST,
    _clean_items,
    create_watchlist,
    delete_watchlist,
    get_watchlists,
    watchlist_symbols,
)


class FakeQuery:
    def __init__(self, table: str, log: list, rows: list, insert_rows=None):
        self.table = table
        self.log = log
        self.rows = rows
        self.insert_rows = insert_rows
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
            if self.insert_rows is not None:
                return SimpleNamespace(data=list(self.insert_rows))
            return SimpleNamespace(data=[{"id": "list-new", **self.payload}])
        return SimpleNamespace(data=list(self.rows))


class FakeClient:
    def __init__(self, rows=None, insert_rows=None):
        self.log: list = []
        self.rows = rows if rows is not None else []
        self.insert_rows = insert_rows

    def table(self, name):
        return FakeQuery(name, self.log, self.rows, self.insert_rows)


@pytest.fixture
def store(monkeypatch):
    """A fake table and a hydrator that records rather than fetches."""
    fake = FakeClient(
        rows=[
            {"id": "list-1", "name": "Majors", "items": [{"symbol": "BTC", "type": "CRYPTO"}]},
            {"id": "list-2", "name": "Rest", "items": [{"symbol": "eth", "type": "CRYPTO"}]},
        ]
    )
    monkeypatch.setattr("services.supabase_service.get_supabase", lambda: fake)

    fake.hydrated = []

    async def _passthrough(lists):
        fake.hydrated.append(lists)
        return lists

    monkeypatch.setattr(watchlist_service, "_hydrate_prices", _passthrough)
    return fake


# ── an owner is required ─────────────────────────────────────────────────────


async def test_reads_with_no_owner_return_nothing(store):
    assert await get_watchlists("") == []
    assert await watchlist_symbols("") == []
    # The guard is checked before the client is asked for, so no query was built.
    assert store.log == []


async def test_writes_with_no_owner_are_refused(store):
    with pytest.raises(PermissionError):
        await create_watchlist("", "Majors", [])
    with pytest.raises(PermissionError):
        await delete_watchlist("", "list-1")
    assert store.log == []


# ── an unconfigured Supabase is not an empty watchlist ───────────────────────


async def test_a_missing_client_reads_as_empty(monkeypatch):
    monkeypatch.setattr("services.supabase_service.get_supabase", lambda: None)

    assert await get_watchlists("user-abc") == []
    assert await watchlist_symbols("user-abc") == []


async def test_a_missing_client_refuses_a_write(monkeypatch):
    """
    A write cannot degrade the way a read can: silently accepting a list the
    store never received would leave the reader believing it exists.
    """
    monkeypatch.setattr("services.supabase_service.get_supabase", lambda: None)

    with pytest.raises(RuntimeError):
        await create_watchlist("user-abc", "Majors", [])
    with pytest.raises(RuntimeError):
        await delete_watchlist("user-abc", "list-1")


async def test_an_insert_that_returned_nothing_raises(monkeypatch):
    fake = FakeClient(insert_rows=[])
    monkeypatch.setattr("services.supabase_service.get_supabase", lambda: fake)

    with pytest.raises(RuntimeError):
        await create_watchlist("user-abc", "Majors", [])


# ── the price hydrator is only reached when there is something to price ──────


async def test_a_read_with_no_rows_skips_the_hydrator(monkeypatch):
    fake = FakeClient(rows=[])
    monkeypatch.setattr("services.supabase_service.get_supabase", lambda: fake)
    fake.hydrated = []

    async def _passthrough(lists):
        fake.hydrated.append(lists)
        return lists

    monkeypatch.setattr(watchlist_service, "_hydrate_prices", _passthrough)

    assert await get_watchlists("user-abc") == []
    assert fake.hydrated == []


# ── `watchlist_symbols` ──────────────────────────────────────────────────────


async def test_symbols_are_deduped_and_sorted_across_lists(monkeypatch):
    fake = FakeClient(
        rows=[
            {"items": [{"symbol": "BTC", "type": "CRYPTO"}, {"symbol": "SOL", "type": "CRYPTO"}]},
            {"items": [{"symbol": "btc", "type": "CRYPTO"}, {"symbol": "ETH", "type": "CRYPTO"}]},
        ]
    )
    monkeypatch.setattr("services.supabase_service.get_supabase", lambda: fake)

    assert await watchlist_symbols("user-abc") == ["BTC", "ETH", "SOL"]


async def test_symbols_are_scoped_to_the_caller(store):
    await watchlist_symbols("user-abc")

    assert store.log[0]["filters"] == {"user_id": "user-abc"}


async def test_symbols_do_not_hydrate_prices(store):
    """
    The whole reason the function exists beside `get_watchlists`: its callers
    want names, and pricing them would be a round of network work thrown away.
    """
    await watchlist_symbols("user-abc")

    assert store.hydrated == []


# ── `_clean_items` is the trust boundary on a jsonb column ───────────────────


@pytest.mark.parametrize("raw", [None, {}, "BTC", 42])
def test_a_non_list_is_dropped(raw):
    assert _clean_items(raw) == []


def test_non_dict_entries_are_dropped():
    assert _clean_items(["BTC", None, 1]) == []


def test_symbols_are_upper_cased_and_trimmed():
    assert _clean_items([{"symbol": " btc ", "type": "crypto"}]) == [
        {"symbol": "BTC", "type": "CRYPTO"}
    ]


@pytest.mark.parametrize("asset_type", ["FOREX", "stonk", "CRYPTOCURRENCY"])
def test_an_unknown_asset_type_is_dropped_rather_than_priced(asset_type):
    """An entry no price fetcher recognises is removed, not handed on."""
    assert _clean_items([{"symbol": "BTC", "type": asset_type}]) == []


@pytest.mark.parametrize("entry", [{"symbol": "BTC"}, {"symbol": "BTC", "type": ""}])
def test_an_absent_type_defaults_to_crypto(entry):
    """
    Absent and empty both fall back rather than being dropped — the column
    predates the type, so rows written before it exists are still priceable.
    """
    assert _clean_items([entry]) == [{"symbol": "BTC", "type": "CRYPTO"}]


def test_duplicates_are_collapsed():
    """One list must not make the hydrator fetch the same quote fifty times."""
    items = [
        {"symbol": "BTC", "type": "CRYPTO"},
        {"symbol": "btc", "type": "CRYPTO"},
        {"symbol": "ETH", "type": "CRYPTO"},
    ]

    assert _clean_items(items) == [
        {"symbol": "BTC", "type": "CRYPTO"},
        {"symbol": "ETH", "type": "CRYPTO"},
    ]


def test_the_item_count_is_capped():
    items = [{"symbol": f"SYM{i}", "type": "CRYPTO"} for i in range(MAX_ITEMS_PER_LIST + 50)]

    assert len(_clean_items(items)) == MAX_ITEMS_PER_LIST


def test_the_cap_is_applied_before_the_filter_rather_than_after():
    """
    Pinned as written, not as ideal: the slice runs on the raw input, so
    invalid entries inside the first hundred consume places rather than being
    replaced from further down. Changing that is a behaviour change, and this
    test is what makes it a deliberate one.
    """
    items = [{"symbol": f"BAD{i}", "type": "FOREX"} for i in range(10)]
    items += [{"symbol": f"SYM{i}", "type": "CRYPTO"} for i in range(MAX_ITEMS_PER_LIST + 50)]

    assert len(_clean_items(items)) == MAX_ITEMS_PER_LIST - 10
