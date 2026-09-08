"""
Tests for the request dependency that binds a caller's data provider keys.

These assert the wiring end to end — that a route body actually sees the
caller's key — because the resolution is implicit and a broken binding would
otherwise look exactly like a reader who never saved a key.
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from config import settings
from dependencies import provider_keys as caller_keys
from dependencies.provider_keys import use_caller_provider_keys
from services import data_provider_settings_service, provider_keys


@pytest.fixture(autouse=True)
def no_key_cache():
    """
    The dependency remembers a reader's keys for thirty seconds so a page load
    is one lookup rather than a dozen. These tests swap the stored keys between
    requests, which a real reader cannot do that fast, so the memory is cleared
    around each one.
    """
    caller_keys.clear()
    yield
    caller_keys.clear()


AUTH = {"Authorization": "Bearer good-token"}


@pytest.fixture
def app_client(patch_supabase, monkeypatch):
    """A route that reports which key it would use, behind the dependency."""
    monkeypatch.setattr(settings, "TCMB_EVDS_API_KEY", "server-evds")
    monkeypatch.setattr(settings, "COINALYZE_API_KEY", "")

    app = FastAPI()

    @app.get("/probe", dependencies=[Depends(use_caller_provider_keys)])
    async def probe():
        return {"evds": provider_keys.evds_key(), "coinalyze": provider_keys.coinalyze_key()}

    return TestClient(app)


def _stub_keys(monkeypatch, keys):
    async def get_keys(_user_id):
        return keys

    monkeypatch.setattr(data_provider_settings_service, "get_keys", get_keys)


def test_anonymous_caller_gets_the_server_key(app_client, monkeypatch):
    def explode(_user_id):
        raise AssertionError("an anonymous request must not hit the database")

    monkeypatch.setattr(data_provider_settings_service, "get_keys", explode)

    assert app_client.get("/probe").json()["evds"] == "server-evds"


def test_signed_in_caller_key_is_bound(app_client, monkeypatch):
    _stub_keys(monkeypatch, {"evds": "caller-evds"})

    assert app_client.get("/probe", headers=AUTH).json()["evds"] == "caller-evds"


def test_caller_without_a_key_still_gets_the_server_key(app_client, monkeypatch):
    _stub_keys(monkeypatch, {})

    assert app_client.get("/probe", headers=AUTH).json()["evds"] == "server-evds"


def test_binding_does_not_survive_the_request(app_client, monkeypatch):
    """The leak this dependency's `finally` exists to prevent."""
    _stub_keys(monkeypatch, {"evds": "caller-evds"})
    assert app_client.get("/probe", headers=AUTH).json()["evds"] == "caller-evds"
    # The binding is undone even while the request was in flight.
    assert provider_keys.evds_key() == "server-evds"

    _stub_keys(monkeypatch, {})
    # Cleared explicitly: the dependency's own memory would otherwise replay the
    # first stub, which is correct behaviour and not what this test is about.
    caller_keys.clear()
    assert app_client.get("/probe", headers=AUTH).json()["evds"] == "server-evds"
    assert provider_keys.evds_key() == "server-evds"


def test_the_lookup_is_cached_across_requests(app_client, monkeypatch):
    """
    A signed-in reader loading a BIST board fires many requests through here,
    and each one was a synchronous Supabase round trip plus a decrypt, on the
    event loop.
    """
    calls = {"n": 0}

    async def counting(_user_id):
        calls["n"] += 1
        return {"evds": "caller-evds"}

    monkeypatch.setattr(data_provider_settings_service, "get_keys", counting)

    for _ in range(5):
        assert app_client.get("/probe", headers=AUTH).json()["evds"] == "caller-evds"

    assert calls["n"] == 1, "five requests, one lookup"


def test_saving_a_key_takes_effect_without_waiting_for_the_cache(app_client, monkeypatch):
    """Otherwise a save reads as not having worked until the TTL expires."""
    _stub_keys(monkeypatch, {"evds": "old-key"})
    assert app_client.get("/probe", headers=AUTH).json()["evds"] == "old-key"

    _stub_keys(monkeypatch, {"evds": "new-key"})
    caller_keys.invalidate("user-abc")

    assert app_client.get("/probe", headers=AUTH).json()["evds"] == "new-key"


def test_a_settings_lookup_failure_does_not_break_the_route(app_client, monkeypatch):
    async def broken(_user_id):
        raise RuntimeError("supabase is down")

    monkeypatch.setattr(data_provider_settings_service, "get_keys", broken)

    response = app_client.get("/probe", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["evds"] == "server-evds"


def test_each_provider_binds_independently(app_client, monkeypatch):
    _stub_keys(monkeypatch, {"coinalyze": "caller-coinalyze"})

    body = app_client.get("/probe", headers=AUTH).json()
    assert body["coinalyze"] == "caller-coinalyze"
    assert body["evds"] == "server-evds"
