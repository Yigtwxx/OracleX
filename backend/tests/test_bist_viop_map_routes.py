"""
The VİOP margin map endpoints.

What is pinned here is which upstream failure costs what. The bulletin and the
scan range are both load-bearing — without either there is no book or no band,
and the endpoint declines rather than drawing one it invented. Yahoo's intraday
history is not: losing it costs the volume profile beside the map and nothing
else, and the map still answers.
"""

import pytest
from fastapi.testclient import TestClient

from main import app
from services.bist.takasbank_psr import PsrSnapshot, PsrUnavailable, UnderlyingPsr
from services.bist.viop_bulletin import BulletinHistory, BulletinUnavailable, SsfRow
from services.cache import bist_cache


@pytest.fixture(autouse=True)
def _clean_cache():
    bist_cache.clear()
    yield
    bist_cache.clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _row(day: str, underlying: str = "THYAO", **kwargs) -> SsfRow:
    defaults = {
        "day": day,
        "contract": f"F_{underlying}0826",
        "underlying": underlying,
        "expiry": "2026-08-31",
        "settlement": 101.0,
        "previous_settlement": 100.0,
        "high": 102.0,
        "low": 100.0,
        "weighted_average": 101.0,
        "volume_try": 5_000_000.0,
        "contracts_traded": 500.0,
        "open_interest": 100_000.0,
        "open_interest_change": 2_000.0,
        "multiplier": 100,
    }
    defaults.update(kwargs)
    return SsfRow(**defaults)


def _history() -> BulletinHistory:
    days = ["2026-08-26", "2026-08-27", "2026-08-28"]
    rows = [_row(day) for day in days] + [_row(day, underlying="AKBNK") for day in days]
    return BulletinHistory(rows=rows, holidays=set(), stored_at=0.0)


def _psr() -> PsrSnapshot:
    return PsrSnapshot(
        rates={
            code: UnderlyingPsr(underlying=code, psr=rate, contract_value=None, multiplier=100)
            for code, rate in (("THYAO", 0.134), ("AKBNK", 0.157))
        },
        as_of="20260828",
        run="1",
        created="202608282128",
        source_file="TAKASEOD_-CCP__-BI-_____-260828-001.zip",
        stored_at=0.0,
    )


def _candles() -> list[dict]:
    return [
        {
            "date": day,
            "time": 0,
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1_000_000,
        }
        for day in ("2026-08-26", "2026-08-27", "2026-08-28")
    ]


@pytest.fixture
def wired(monkeypatch):
    """Every upstream healthy, so each test only has to break the one it is about."""

    async def history():
        return _history()

    async def psr():
        return _psr()

    async def candles(ticker, *, range_="1y", interval="1d"):
        return _candles()

    monkeypatch.setattr("routers.bist.get_bulletin_history", history)
    monkeypatch.setattr("routers.bist.fetch_psr", psr)
    monkeypatch.setattr("routers.bist.fetch_candles", candles)
    monkeypatch.setattr(
        "services.bist.spot_volume_profile.fetch_candles",
        candles,
    )


class TestUnderlyings:
    def test_the_universe_comes_from_the_newest_session(self, client, wired):
        payload = client.get("/api/bist/viop-map/underlyings").json()
        assert payload["as_of"] == "2026-08-28"
        assert {row["ticker"] for row in payload["underlyings"]} == {"THYAO", "AKBNK"}

    def test_ranked_by_turnover_and_defaulted(self, client, wired):
        payload = client.get("/api/bist/viop-map/underlyings").json()
        # Both names carry the same fixture turnover, so the assertion that
        # matters is that `default` is a prefix of the ranking rather than a
        # separate hardcoded list.
        ranking = [row["ticker"] for row in payload["underlyings"]]
        assert payload["default"] == ranking[: len(payload["default"])]

    def test_an_unreadable_bulletin_is_a_503(self, client, monkeypatch):
        async def broken():
            raise BulletinUnavailable("archive down")

        monkeypatch.setattr("routers.bist.get_bulletin_history", broken)
        assert client.get("/api/bist/viop-map/underlyings").status_code == 503


class TestMap:
    def test_a_healthy_board_carries_both_layers(self, client, wired):
        response = client.get("/api/bist/viop-map/THYAO?sessions=30")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ticker"] == "THYAO"
        assert payload["cells"], "the field should not be empty"
        assert payload["max_value"] > 0
        assert payload["volume_profile"] is not None
        assert payload["warnings"] == []

    def test_the_model_block_names_its_source(self, client, wired):
        model = client.get("/api/bist/viop-map/THYAO").json()["model"]
        assert model["psr"] == 0.134
        assert model["psr_as_of"] == "20260828"
        assert model["psr_run"] == "1"
        assert model["direction_rule"] == "quadrant"

    def test_the_unpublished_maintenance_rate_is_named_not_omitted(self, client, wired):
        model = client.get("/api/bist/viop-map/THYAO").json()["model"]
        # Present and null, so the page can say why it is not drawing a call
        # level rather than silently not drawing one.
        assert "maintenance_margin_rate" in model
        assert model["maintenance_margin_rate"] is None
        assert model["maintenance_source"] == "unpublished"

    def test_the_scan_range_is_per_underlying_on_the_wire(self, client, wired):
        assert client.get("/api/bist/viop-map/THYAO").json()["model"]["psr"] == 0.134
        assert client.get("/api/bist/viop-map/AKBNK").json()["model"]["psr"] == 0.157

    def test_an_unlisted_ticker_is_a_404(self, client, wired):
        # It declines rather than serving an empty board — the same rule the
        # rest of this router follows.
        assert client.get("/api/bist/viop-map/ZZZZZ").status_code == 404


class TestFailureModes:
    def test_an_unreadable_bulletin_is_a_503(self, client, monkeypatch):
        async def broken():
            raise BulletinUnavailable("archive down")

        monkeypatch.setattr("routers.bist.get_bulletin_history", broken)
        assert client.get("/api/bist/viop-map/THYAO").status_code == 503

    def test_a_missing_scan_range_is_a_503(self, client, monkeypatch, wired):
        async def broken():
            raise PsrUnavailable("clearing house down")

        monkeypatch.setattr("routers.bist.fetch_psr", broken)
        # The band distance is a published number. Without it there is nothing
        # honest to draw, so the endpoint declines instead of inventing one.
        assert client.get("/api/bist/viop-map/THYAO").status_code == 503

    def test_losing_intraday_history_costs_the_profile_only(self, client, monkeypatch, wired):
        async def no_intraday(ticker, *, range_="1y", interval="1d"):
            return [] if interval != "1d" else _candles()

        monkeypatch.setattr("routers.bist.fetch_candles", no_intraday)
        monkeypatch.setattr("services.bist.spot_volume_profile.fetch_candles", no_intraday)

        payload = client.get("/api/bist/viop-map/THYAO").json()
        assert payload["volume_profile"] is None
        assert "spot_intraday_unavailable" in payload["warnings"]
        # The subject of the page still answers.
        assert payload["cells"]
