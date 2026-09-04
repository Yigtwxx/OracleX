"""
The Bilanço routes.

The behaviour under test is what happens when an upstream is missing, because
that is where a financial terminal does its real damage. The rule these pin: a
figure the board cannot measure is absent from the response, never zero and
never a nominal number wearing a real label.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import bist as bist_router
from services.bist import deflator, financials_service as fs, fundamentals as f
from tests.test_bist_financials import cpi, long_series


@pytest.fixture
def client() -> TestClient:
    """A bare app with just this router — the real one needs Supabase and a model chain."""
    app = FastAPI()
    app.include_router(bist_router.router)
    return TestClient(app)


class Equity:
    """Only the five readings the market header reads."""

    name = "Synthetic A.Ş."
    sector = "Sanayi"
    price = 312.5
    market_cap = 4.2e11
    pe = 6.1
    pb = 1.3


@pytest.fixture
def wire(monkeypatch):
    """Point the service's three upstreams at fakes, each independently switchable."""

    def install(*, fund=..., cpi_series=None, key=True, equity=Equity()):
        fundamentals = long_series(f.LAYOUT_INDUSTRIAL) if fund is ... else fund

        async def fake_fetch(ticker, *, force=False):
            return fundamentals

        async def fake_cpi(years=6):
            return cpi() if cpi_series is None else cpi_series

        async def fake_equity(ticker):
            if equity is None:
                raise RuntimeError("scanner down")
            return equity

        monkeypatch.setattr(fs, "fetch_fundamentals", fake_fetch)
        monkeypatch.setattr("services.bist.macro_service.fetch_cpi_series", fake_cpi)
        monkeypatch.setattr("services.bist.equity_service.fetch_equity", fake_equity)
        monkeypatch.setattr("config.settings.TCMB_EVDS_API_KEY", "x" if key else "")

    return install


class TestUnknownTicker:
    def test_declines_rather_than_serving_an_empty_board(self, client, wire):
        # A page of dashes reads as a company that reported nothing, which is a
        # different and much worse claim than "this code could not be resolved".
        wire(fund=None)
        response = client.get("/api/bist/financials/NOPE")
        assert response.status_code == 404
        assert "NOPE" in response.json()["detail"]

    def test_the_404_body_carries_no_board_shaped_keys(self, client, wire):
        wire(fund=None)
        body = client.get("/api/bist/financials/NOPE").json()
        assert "quarters" not in body
        assert "ttm" not in body

    def test_statements_upstream_down_with_no_cache_is_also_a_404(self, client, wire):
        # `fetch_fundamentals` returns the stale cache on an outage and None
        # when there is not one; neither may become a 200 full of zeros.
        wire(fund=None)
        assert client.get("/api/bist/financials/THYAO").status_code == 404

    def test_a_company_with_no_usable_quarter_is_a_404(self, client, wire):
        wire(fund=f.Fundamentals("EMPTY", f.LAYOUT_INDUSTRIAL, (), "", ""))
        assert client.get("/api/bist/financials/EMPTY").status_code == 404


class TestDegradation:
    def test_scanner_down_costs_the_header_and_nothing_else(self, client, wire):
        wire(equity=None)
        body = client.get("/api/bist/financials/SYNTH").json()
        assert body["market"] is None
        assert body["name"] is None
        assert len(body["quarters"]) == 12
        assert body["deflation"]["available"] is True

    def test_scanner_up_fills_the_header(self, client, wire):
        wire()
        body = client.get("/api/bist/financials/SYNTH").json()
        assert body["market"]["price"] == 312.5
        assert body["market"]["delay_minutes"] == 15
        assert body["name"] == "Synthetic A.Ş."

    def test_no_cpi_key_disables_the_real_frame_and_says_why(self, client, wire):
        wire(cpi_series=[], key=False)
        body = client.get("/api/bist/financials/SYNTH").json()
        assert body["deflation"]["available"] is False
        assert body["deflation"]["reason"] == deflator.REASON_KEY_MISSING
        assert all(q["real"] is None for q in body["quarters"])
        assert all(q["deflator"] is None for q in body["quarters"])
        # The nominal figures are untouched, and the board is still served.
        assert all(q["nominal"]["revenue"] is not None for q in body["quarters"])

    def test_cpi_outage_is_reported_as_an_outage_not_a_setup_gap(self, client, wire):
        wire(cpi_series=[], key=True)
        body = client.get("/api/bist/financials/SYNTH").json()
        assert body["deflation"]["reason"] == deflator.REASON_UNAVAILABLE


class TestParams:
    def test_quarters_window_is_honoured(self, client, wire):
        wire()
        assert len(client.get("/api/bist/financials/SYNTH?quarters=4").json()["quarters"]) == 4

    @pytest.mark.parametrize("bad", [0, 3, 13, 99])
    def test_out_of_range_window_is_rejected(self, client, wire, bad):
        wire()
        assert client.get(f"/api/bist/financials/SYNTH?quarters={bad}").status_code == 422


class TestNoteRoute:
    def test_short_history_yields_null_facts_rather_than_a_404(self, client, wire):
        # The board is drawable at four quarters and not narratable; that is a
        # missing paragraph, not a missing company.
        wire(fund=long_series(f.LAYOUT_INDUSTRIAL, count=4))
        response = client.get("/api/bist/financials/SYNTH/note")
        assert response.status_code == 200
        body = response.json()
        assert body["facts"] is None
        assert body["note"]["status"] in {"unavailable", "generating", "ready"}

    def test_unknown_ticker_is_a_404_here_too(self, client, wire):
        wire(fund=None)
        assert client.get("/api/bist/financials/NOPE/note").status_code == 404

    def test_facts_are_served_for_a_full_window(self, client, wire):
        wire()
        body = client.get("/api/bist/financials/SYNTH/note").json()
        assert body["facts"]["ticker"] == "SYNTH"
        assert body["facts"]["basis"] == "real"
