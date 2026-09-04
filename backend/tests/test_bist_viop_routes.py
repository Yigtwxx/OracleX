"""
The two VİOP board endpoints.

What is pinned here is the contract the page's four panels are built on. The
curve and the roll split both put contracts on a time axis, so `expiry_date`
travelling with every row is load-bearing rather than a convenience — without it
the client would be sorting `31 Ağu 26` as a string, and October would come
before September.

The note endpoint is separate from the board on purpose, and the test that the
board still answers when the note cannot is what keeps that split honest: a
model outage must cost a paragraph, never a page.
"""

import pytest
from fastapi.testclient import TestClient

from main import app
from services.bist.viop_service import ViopBoard, ViopContract, ViopUnavailable, parse_expiry
from services.cache import bist_cache


@pytest.fixture(autouse=True)
def _clean_cache():
    bist_cache.clear()
    yield
    bist_cache.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _contract(underlying: str = "THYAO", expiry: str = "31 Ağu 26") -> ViopContract:
    return ViopContract(
        contract=f"{underlying} ({expiry}) Vadeli FIZ.",
        underlying=underlying,
        expiry=expiry,
        physical=True,
        last=310.5,
        change_pct=0.012,
        high=312.0,
        low=305.0,
        open_interest=42_000.0,
        open_interest_change=1_500.0,
        settlement=310.0,
        previous_settlement=306.0,
        traded_at="18:10",
        expiry_date=parse_expiry(expiry),
    )


@pytest.fixture
def board(monkeypatch):
    """A readable board, patched at the router's own import site."""
    state = {
        "contracts": [_contract("THYAO"), _contract("USDTRY", "30 Eki 26")],
        "error": None,
    }

    async def fetch():
        if state["error"] is not None:
            raise state["error"]
        return ViopBoard(
            contracts=state["contracts"],
            as_of="2026-08-28T11:08:49.967350+00:00",
            stale=False,
        )

    monkeypatch.setattr("routers.bist.fetch_viop_board", fetch)
    return state


def test_every_contract_carries_its_expiry_as_a_date(client, board):
    """The curve and the roll split order contracts by time. On the label alone
    `30 Eki 26` sorts ahead of `31 Ağu 26`, which inverts a term structure."""
    payload = client.get("/api/bist/viop").json()

    dates = {row["underlying"]: row["expiry_date"] for row in payload["contracts"]}
    assert dates == {"THYAO": "2026-08-31", "USDTRY": "2026-10-30"}


def test_an_unreadable_expiry_travels_as_null_rather_than_being_dropped(client, board):
    """The row is still a contract and still carries its quote; only its place
    on a time axis is unknown."""
    board["contracts"] = [_contract("THYAO", "202608")]
    payload = client.get("/api/bist/viop").json()

    assert payload["count"] == 1
    assert payload["contracts"][0]["expiry_date"] is None


def test_the_board_declines_rather_than_serving_an_empty_table(client, board):
    board["error"] = ViopUnavailable("scrape failed")
    assert client.get("/api/bist/viop").status_code == 503


# ── The note ─────────────────────────────────────────────────────────────────


def test_the_note_endpoint_answers_facts_and_prose(client, monkeypatch):
    async def facts():
        return {"stance": "long_build"}

    async def note(given, user_id=None):
        assert given == {"stance": "long_build"}
        return {"status": "ready", "note": "VİOP", "generated_at": None, "reason": None}

    monkeypatch.setattr("routers.bist.build_viop_facts", facts)
    monkeypatch.setattr("routers.bist.viop_note", note)

    payload = client.get("/api/bist/viop-note").json()
    assert payload["facts"] == {"stance": "long_build"}
    assert payload["note"]["status"] == "ready"


def test_an_unreadable_board_answers_null_facts_rather_than_a_quiet_session(client, monkeypatch):
    """This source is a scrape. The client must render a missing read as an
    absent panel, and it can only do that if the endpoint says so plainly."""

    async def facts():
        return None

    monkeypatch.setattr("routers.bist.build_viop_facts", facts)

    payload = client.get("/api/bist/viop-note").json()
    assert payload["facts"] is None
    assert payload["note"]["status"] == "unavailable"
    assert payload["note"]["reason"] == "insufficient_data"


def test_the_note_is_its_own_endpoint_so_a_model_outage_costs_no_board(client, board, monkeypatch):
    """The reason the two are split at all: the board is cached for five minutes
    and polled, and a note welded to it would tie one cadence to the other."""

    async def facts():
        raise AssertionError("the board endpoint must not build the note")

    monkeypatch.setattr("routers.bist.build_viop_facts", facts)
    assert client.get("/api/bist/viop").status_code == 200


# ── The margin map note ──────────────────────────────────────────────────────


def test_the_map_note_endpoint_is_scoped_like_the_map(client, monkeypatch):
    seen = {}

    async def facts(ticker, sessions):
        seen["ticker"], seen["sessions"] = ticker, sessions
        return {"stance": "long_heavy", "ticker": ticker}

    async def note(given, user_id=None):
        return {"status": "ready", "note": "Kitap", "generated_at": None, "reason": None}

    monkeypatch.setattr("routers.bist.build_viop_map_facts", facts)
    monkeypatch.setattr("routers.bist.viop_map_note", note)

    payload = client.get("/api/bist/viop-map/THYAO/note", params={"sessions": 60}).json()
    assert seen == {"ticker": "THYAO", "sessions": 60}
    assert payload["facts"]["stance"] == "long_heavy"
    assert payload["note"]["status"] == "ready"


def test_a_field_that_cannot_be_drawn_answers_null_facts_rather_than_an_error(client, monkeypatch):
    """The map route 404s and 503s because a field is either drawn or not; the
    note is a paragraph, and its absence is a null the page renders as nothing."""

    async def facts(ticker, sessions):
        return None

    monkeypatch.setattr("routers.bist.build_viop_map_facts", facts)

    response = client.get("/api/bist/viop-map/NOPE/note")
    assert response.status_code == 200
    payload = response.json()
    assert payload["facts"] is None
    assert payload["note"]["status"] == "unavailable"
    assert payload["note"]["reason"] == "insufficient_data"


def test_the_map_note_window_is_bounded_like_the_map(client):
    assert client.get("/api/bist/viop-map/THYAO/note", params={"sessions": 5}).status_code == 422
