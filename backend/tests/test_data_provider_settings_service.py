"""Tests for per-user data provider key storage."""

import pytest
from cryptography.fernet import Fernet

from config import settings
from services import data_provider_settings_service as svc
from services import secret_box

USER = "user-1"


class FakeTable:
    """
    Stand-in for supabase-py's query builder.

    Unlike the LLM one, this keys on (user_id, provider): the table has a
    composite primary key, and chained `.eq()` calls are how the service selects
    a single row.
    """

    def __init__(self, store):
        self._store = store
        self._filters = {}
        self._pending = None
        self._op = None

    def select(self, *_args):
        self._op = "select"
        return self

    def insert(self, values):
        self._op, self._pending = "insert", values
        return self

    def update(self, values):
        self._op, self._pending = "update", values
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, column, value):
        self._filters[column] = value
        return self

    def _matches(self, row):
        return all(row.get(column) == value for column, value in self._filters.items())

    def execute(self):
        if self._op == "select":
            return type("R", (), {"data": [dict(r) for r in self._store if self._matches(r)]})()
        if self._op == "insert":
            self._store.append(dict(self._pending))
        elif self._op == "update":
            for row in self._store:
                if self._matches(row):
                    row.update(self._pending)
        elif self._op == "delete":
            self._store[:] = [r for r in self._store if not self._matches(r)]
        return type("R", (), {"data": []})()


class FakeSupabase:
    def __init__(self):
        self.rows = []

    def table(self, _name):
        return FakeTable(self.rows)


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeSupabase()
    monkeypatch.setattr(svc, "get_supabase", lambda: db)
    return db


@pytest.fixture(autouse=True)
def encryption(monkeypatch):
    monkeypatch.setattr(settings, "LLM_KEY_ENCRYPTION_SECRET", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "TCMB_EVDS_API_KEY", "")
    monkeypatch.setattr(settings, "COINALYZE_API_KEY", "")
    monkeypatch.setattr(settings, "SEC_USER_AGENT", "")


def _find(providers, name):
    return next(p for p in providers if p["provider"] == name)


@pytest.mark.asyncio
async def test_lists_every_provider_when_nothing_is_stored(fake_db):
    providers = await svc.get_settings(USER)

    assert [p["provider"] for p in providers] == ["evds", "coinalyze", "sec"]
    assert all(p["source"] == "none" for p in providers)
    assert all(p["configured"] is False for p in providers)


@pytest.mark.asyncio
async def test_key_is_encrypted_at_rest_and_absent_from_the_view(fake_db):
    providers = await svc.save_key(USER, "evds", "super-secret-key")

    stored = fake_db.rows[0]
    assert stored["encrypted_key"] != "super-secret-key"
    assert secret_box.decrypt(stored["encrypted_key"]) == "super-secret-key"

    evds = _find(providers, "evds")
    assert "super-secret-key" not in str(providers)
    assert evds["key_hint"] == "-key"
    assert evds["source"] == "user"
    assert evds["user_configured"] is True


@pytest.mark.asyncio
async def test_get_keys_returns_plaintext_for_user_providers_only(fake_db):
    await svc.save_key(USER, "evds", "evds-key")
    await svc.save_key(USER, "coinalyze", "coinalyze-key")

    assert await svc.get_keys(USER) == {"evds": "evds-key", "coinalyze": "coinalyze-key"}


@pytest.mark.asyncio
async def test_saving_twice_replaces_rather_than_duplicates(fake_db):
    await svc.save_key(USER, "evds", "first-key")
    await svc.save_key(USER, "evds", "second-key")

    assert len(fake_db.rows) == 1
    assert (await svc.get_keys(USER))["evds"] == "second-key"


@pytest.mark.asyncio
async def test_one_users_key_is_not_visible_to_another(fake_db):
    await svc.save_key(USER, "evds", "mine")

    assert await svc.get_keys("someone-else") == {}
    assert _find(await svc.get_settings("someone-else"), "evds")["user_configured"] is False


@pytest.mark.asyncio
async def test_delete_removes_only_the_named_provider(fake_db):
    await svc.save_key(USER, "evds", "evds-key")
    await svc.save_key(USER, "coinalyze", "coinalyze-key")

    await svc.delete_key(USER, "evds")

    assert await svc.get_keys(USER) == {"coinalyze": "coinalyze-key"}


@pytest.mark.asyncio
async def test_blank_key_is_rejected_rather_than_clearing(fake_db):
    """Deleting is explicit; an empty form field must not wipe a working key."""
    await svc.save_key(USER, "evds", "evds-key")

    with pytest.raises(ValueError):
        await svc.save_key(USER, "evds", "   ")

    assert (await svc.get_keys(USER))["evds"] == "evds-key"


@pytest.mark.asyncio
async def test_server_scoped_provider_cannot_be_written(fake_db):
    with pytest.raises(svc.UnknownProvider):
        await svc.save_key(USER, "sec", "me@example.com")

    with pytest.raises(svc.UnknownProvider):
        await svc.delete_key(USER, "sec")


@pytest.mark.asyncio
async def test_unknown_provider_is_rejected(fake_db):
    with pytest.raises(svc.UnknownProvider):
        await svc.save_key(USER, "nonesuch", "key")


@pytest.mark.asyncio
async def test_server_key_reports_as_the_source(fake_db, monkeypatch):
    monkeypatch.setattr(settings, "COINALYZE_API_KEY", "server-key")

    coinalyze = _find(await svc.get_settings(USER), "coinalyze")
    assert coinalyze["source"] == "server"
    assert coinalyze["configured"] is True
    assert coinalyze["user_configured"] is False
    assert coinalyze["key_hint"] == ""


@pytest.mark.asyncio
async def test_a_users_key_outranks_the_server_in_the_view(fake_db, monkeypatch):
    monkeypatch.setattr(settings, "COINALYZE_API_KEY", "server-key")
    await svc.save_key(USER, "coinalyze", "caller-key")

    coinalyze = _find(await svc.get_settings(USER), "coinalyze")
    assert coinalyze["source"] == "user"
    assert coinalyze["server_configured"] is True


@pytest.mark.asyncio
async def test_sec_is_reported_but_not_editable(fake_db, monkeypatch):
    monkeypatch.setattr(settings, "SEC_USER_AGENT", "Oracle-X me@example.com")

    sec = _find(await svc.get_settings(USER), "sec")
    assert sec["scope"] == "server"
    assert sec["editable"] is False
    assert sec["source"] == "server"


@pytest.mark.asyncio
async def test_undecryptable_key_is_dropped_rather_than_raising(fake_db, monkeypatch):
    """A rotated secret means re-entry, not a broken market-data route."""
    await svc.save_key(USER, "evds", "evds-key")
    monkeypatch.setattr(settings, "LLM_KEY_ENCRYPTION_SECRET", Fernet.generate_key().decode())

    assert await svc.get_keys(USER) == {}


@pytest.mark.asyncio
async def test_database_failure_degrades_to_the_server_view(monkeypatch):
    """The settings screen still renders; it just cannot show the reader's keys."""

    class Broken:
        def table(self, _name):
            raise RuntimeError("supabase is down")

    monkeypatch.setattr(svc, "get_supabase", Broken)
    monkeypatch.setattr(settings, "TCMB_EVDS_API_KEY", "server-evds")

    providers = await svc.get_settings(USER)
    assert _find(providers, "evds")["source"] == "server"
    assert await svc.get_keys(USER) == {}
