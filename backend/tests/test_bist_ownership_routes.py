"""
The `/api/bist/ownership/*` contract.

What is pinned is the status-code vocabulary, because it is what the page
reads: a board that does not exist is a 503 and never an empty grid, an
unknown holder and a ticker outside the universe are 404s with different
sentences, and the moves route is the one allowed to answer `[]`.
"""

import pytest
from fastapi.testclient import TestClient

from main import app
from models.bist_ownership import (
    AssetOwners,
    EntityDetail,
    EntitySummary,
    Holder,
    Move,
    OwnershipBoard,
    SourceHealth,
)
from services.bist.ownership import board as board_service
from services.bist.ownership.errors import BoardUnavailable, EntityNotFound, TickerNotCovered
from services.cache import bist_cache


@pytest.fixture(autouse=True)
def _clean_cache():
    bist_cache.clear()
    yield
    bist_cache.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _summary(entity_id: str = "tvf") -> EntitySummary:
    return EntitySummary(
        id=entity_id,
        name="Türkiye Varlık Fonu",
        category="state",
        total_value_try=1.0e12,
        positions_count=2,
        has_data=True,
        as_of="2026-09-02T06:00:00+00:00",
    )


def _move() -> Move:
    return Move(
        id="kap-1",
        ticker="THYAO",
        company="THYAO A.Ş.",
        event="icsel_islem",
        event_label="İçeriden pay işlemi",
        headline="THYAO · Pay Alım Satım Bildirimi",
        published_at="2026-09-01T10:00:00+03:00",
        url="https://www.kap.org.tr/tr/Bildirim/1",
        score=6,
        band="medium",
    )


def test_board_is_503_until_it_has_been_built(client, monkeypatch):
    async def missing():
        raise BoardUnavailable("not built")

    monkeypatch.setattr(board_service, "get_board", missing)

    response = client.get("/api/bist/ownership/board")

    assert response.status_code == 503
    assert "not built" in response.json()["detail"]


def test_board_carries_entities_sources_and_universe(client, monkeypatch):
    async def stored():
        return OwnershipBoard(
            entities=[_summary()],
            latest_moves=[_move()],
            category_counts={"state": 1},
            sources=[SourceHealth(kind="isyatirim_shareholders", ok=True, tickers_covered=100)],
            tickers_covered=100,
            tickers_total=100,
            as_of="2026-09-02T06:00:00+00:00",
        )

    monkeypatch.setattr(board_service, "get_board", stored)

    payload = client.get("/api/bist/ownership/board").json()

    assert payload["universe"] == "XU100"
    assert payload["entities"][0]["id"] == "tvf"
    assert payload["entities"][0]["total_value_try"] == 1.0e12
    assert payload["latest_moves"][0]["event"] == "icsel_islem"
    assert payload["sources"][0]["tickers_covered"] == 100


def test_unknown_entity_is_404(client, monkeypatch):
    async def missing(entity_id: str):
        raise EntityNotFound(f"unknown entity {entity_id!r}")

    monkeypatch.setattr(board_service, "get_entity", missing)

    response = client.get("/api/bist/ownership/entities/nobody")

    assert response.status_code == 404


def test_entity_detail_shape(client, monkeypatch):
    async def detail(entity_id: str):
        return EntityDetail(entity=_summary(entity_id), positions=[], moves=[_move()], sources=[])

    monkeypatch.setattr(board_service, "get_entity", detail)

    payload = client.get("/api/bist/ownership/entities/tvf").json()

    assert payload["entity"]["id"] == "tvf"
    assert payload["moves"][0]["id"] == "kap-1"


def test_a_ticker_outside_the_universe_is_404_with_the_reason(client, monkeypatch):
    async def missing(ticker: str):
        raise TickerNotCovered(f"{ticker} is not in the XU100 universe this board covers")

    monkeypatch.setattr(board_service, "get_asset_owners", missing)

    response = client.get("/api/bist/ownership/assets/SMALL")

    assert response.status_code == 404
    assert "XU100" in response.json()["detail"]


def test_asset_owners_shape(client, monkeypatch):
    async def owners(ticker: str):
        return AssetOwners(
            ticker="THYAO",
            name="Türk Hava Yolları",
            market_cap=400e9,
            free_float_pct=0.503,
            foreign_ratio_pct=0.2271,
            holders=[
                Holder(label="Türkiye Varlık Fonu", stake_pct=0.4912, entity_id="tvf", tracked=True)
            ],
        )

    monkeypatch.setattr(board_service, "get_asset_owners", owners)

    payload = client.get("/api/bist/ownership/assets/BIST:THYAO").json()

    assert payload["holders"][0]["tracked"] is True
    assert payload["foreign_ratio_pct"] == 0.2271
    assert payload["funds"] == []


def test_moves_may_be_empty_and_are_never_an_error(client, monkeypatch):
    async def nothing(limit: int = 20, ticker=None):
        return []

    monkeypatch.setattr(board_service, "get_moves", nothing)

    response = client.get("/api/bist/ownership/moves?ticker=THYAO&limit=5")

    assert response.status_code == 200
    assert response.json() == []


def test_refresh_is_behind_the_admin_gate(client):
    response = client.post("/api/admin/bist/ownership/refresh")

    assert response.status_code in (401, 403)
