"""Tests for per-user LLM settings storage."""

import pytest
from cryptography.fernet import Fernet

from services import llm_settings_service as svc
from services import secret_box


class FakeTable:
    """Minimal stand-in for supabase-py's query builder, backed by a dict."""

    def __init__(self, store):
        self._store = store
        self._filter_id = None
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

    def eq(self, _column, value):
        self._filter_id = value
        return self

    def execute(self):
        if self._op == "select":
            row = self._store.get(self._filter_id)
            return type("R", (), {"data": [row] if row else []})()
        if self._op == "insert":
            self._store[self._pending["user_id"]] = dict(self._pending)
        elif self._op == "update":
            self._store.setdefault(self._filter_id, {"user_id": self._filter_id})
            self._store[self._filter_id].update(self._pending)
        elif self._op == "delete":
            self._store.pop(self._filter_id, None)
        return type("R", (), {"data": []})()


class FakeSupabase:
    def __init__(self):
        self.rows = {}

    def table(self, _name):
        return FakeTable(self.rows)


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(svc, "get_supabase", lambda: fake)
    monkeypatch.setattr(
        secret_box.settings, "LLM_KEY_ENCRYPTION_SECRET", Fernet.generate_key().decode()
    )
    return fake


async def test_save_then_get_hides_the_key(db):
    await svc.save_settings(
        "u1", provider="groq", model="qwen/qwen3.6-27b", api_key="gsk_secret_abcd"
    )

    public = await svc.get_settings("u1")
    assert public["provider"] == "groq"
    assert public["model"] == "qwen/qwen3.6-27b"
    assert public["configured"] is True
    assert public["key_hint"] == "abcd"
    assert "api_key" not in public
    assert "encrypted_key" not in public


async def test_key_is_encrypted_at_rest(db):
    await svc.save_settings("u1", provider="groq", api_key="gsk_secret_abcd")
    stored = db.rows["u1"]["encrypted_key"]
    assert "gsk_secret_abcd" not in stored


async def test_get_credentials_returns_plaintext(db):
    await svc.save_settings("u1", provider="groq", api_key="gsk_secret_abcd")
    creds = await svc.get_credentials("u1")
    assert creds["api_key"] == "gsk_secret_abcd"
    assert creds["provider"] == "groq"


async def test_get_settings_returns_none_when_absent(db):
    assert await svc.get_settings("nobody") is None


async def test_toggles_default_to_chat_only(db):
    await svc.save_settings("u1", provider="groq", api_key="gsk_secret_abcd")
    public = await svc.get_settings("u1")
    assert public["use_for_chat"] is True
    assert public["use_for_news"] is False
    assert public["use_for_reports"] is False


async def test_partial_update_keeps_existing_key(db):
    await svc.save_settings("u1", provider="groq", api_key="gsk_secret_abcd")
    await svc.save_settings("u1", provider="groq", use_for_news=True)

    assert (await svc.get_credentials("u1"))["api_key"] == "gsk_secret_abcd"
    assert (await svc.get_settings("u1"))["use_for_news"] is True


async def test_changing_provider_without_key_is_rejected(db):
    """The stored key belongs to the old provider and cannot work with the new one."""
    await svc.save_settings("u1", provider="groq", api_key="gsk_secret_abcd")
    with pytest.raises(svc.KeyRequired):
        await svc.save_settings("u1", provider="gemini")


async def test_changing_provider_with_key_succeeds(db):
    await svc.save_settings("u1", provider="groq", api_key="gsk_secret_abcd")
    await svc.save_settings("u1", provider="gemini", api_key="AQ.newkey_wxyz")
    public = await svc.get_settings("u1")
    assert public["provider"] == "gemini"
    assert public["key_hint"] == "wxyz"


async def test_unknown_provider_is_rejected(db):
    with pytest.raises(svc.UnknownProvider):
        await svc.save_settings("u1", provider="evil-host", api_key="k")


async def test_first_save_requires_a_key(db):
    with pytest.raises(svc.KeyRequired):
        await svc.save_settings("u1", provider="groq")


async def test_delete_removes_the_row(db):
    await svc.save_settings("u1", provider="groq", api_key="gsk_secret_abcd")
    assert await svc.delete_settings("u1") is True
    assert await svc.get_settings("u1") is None


async def test_switching_to_a_keyless_provider_needs_no_key(db):
    """
    The way back to Ollama.

    A user who stored a cloud key could not return to the local daemon, because
    the form demanded a credential Ollama has never issued.
    """
    await svc.save_settings("u1", provider="mistral", api_key="ms_secret_abcd")

    await svc.save_settings("u1", provider="ollama", model="qwen3.6:35b-a3b")

    public = await svc.get_settings("u1")
    assert public["provider"] == "ollama"
    assert public["requires_key"] is False


async def test_leaving_a_keyed_provider_drops_its_key(db):
    """The old provider's credential must not survive the move."""
    await svc.save_settings("u1", provider="mistral", api_key="ms_secret_abcd")
    await svc.save_settings("u1", provider="ollama")

    # Asserted as an empty string, not merely falsey: the column is NOT NULL in
    # the live table, so writing None passes against this in-memory fake and
    # fails with a 23502 against Postgres.
    assert db.rows["u1"]["encrypted_key"] == ""
    assert db.rows["u1"]["key_hint"] == ""
    public = await svc.get_settings("u1")
    assert public["configured"] is False


async def test_keyed_provider_still_requires_a_key(db):
    """The exemption is for keyless providers only, not for everyone."""
    await svc.save_settings("u1", provider="ollama")

    with pytest.raises(svc.KeyRequired):
        await svc.save_settings("u1", provider="mistral")


async def test_first_save_of_a_keyless_provider_is_allowed(db):
    await svc.save_settings("u1", provider="ollama", model="qwen3.6:35b-a3b")
    assert (await svc.get_settings("u1"))["provider"] == "ollama"


async def test_requires_key_is_reported_for_keyed_providers(db):
    await svc.save_settings("u1", provider="mistral", api_key="ms_secret_abcd")
    assert (await svc.get_settings("u1"))["requires_key"] is True
