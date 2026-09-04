"""
The offering routes.

The distinction these pin against the Bilanço routes: a missing company there is
a 404 because a symbol failed to resolve; a missing calendar here is a 503
because the source is down. An empty list would read as a market with no
offerings, which is a claim about Borsa İstanbul rather than about our uptime.
"""

from __future__ import annotations


import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import bist as bist_router
from services.bist import halkarz_client as hz
from services.bist import ipo_service as ipo


def _future_offer(days: int = 30) -> str:
    """
    A Turkish offer date a month out, written the way the calendar writes them.

    Computed rather than hardcoded so these rows stay "upcoming" whatever day
    the suite runs — a test about a failed detail page should not also be a test
    about the calendar rolling past a fixed date — and inside the board's
    120-day forward window, which a far-future literal would fall outside.
    """
    from datetime import date as _date, timedelta as _timedelta

    when = _date.today() + _timedelta(days=days)
    month = {number: name for name, number in hz.TR_MONTHS.items()}[when.month]
    return f"{when.day} {month.capitalize()} {when.year}"


FUTURE_OFFER = _future_offer()


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ipo, "CACHE_DIR", str(tmp_path / "ipos"))
    monkeypatch.setattr(ipo, "REQUEST_SPACING_SECONDS", 0)
    from services.cache import bist_cache

    bist_cache.clear()
    yield
    bist_cache.clear()


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(bist_router.router)
    return TestClient(app)


class Equity:
    def __init__(self, ticker: str, price: float = 60.0):
        self.ticker = ticker
        self.price = price
        self.market_cap = 1.2e10
        self.sector = "Sanayi"


class Board:
    def __init__(self, equities):
        self.equities = equities


def rows(count: int = 12) -> list[hz.IndexRow]:
    return [
        hz.IndexRow(
            slug=f"co-{index}",
            url=f"{hz.BASE}/co-{index}/",
            company=f"Şirket {index} A.Ş.",
            ticker=f"AB{index:03d}",
            offer_dates_raw=FUTURE_OFFER,
            is_new=False,
        )
        for index in range(count)
    ]


@pytest.fixture
def wire(monkeypatch):
    def install(*, index=..., cpi=None, equities=..., detail_fails=False):
        listing = rows() if index is ... else index

        async def fake_index():
            if listing is None:
                raise hz.HalkarzUnavailable("calendar down")
            return listing

        async def fake_detail(slug: str):
            if detail_fails:
                raise hz.HalkarzUnavailable("detail down")
            return hz.DetailFields(
                ticker=slug.replace("co-", "AB").zfill(0) or None,
                offer_dates_raw=FUTURE_OFFER,
                listing_date_raw="10 Şubat 2026" if not detail_fails else None,
                price_raw="50,00 TL",
                broker="Aracı A.Ş.",
                market="Yıldız Pazar",
                updated_at="2026-09-03T17:01",
            )

        async def fake_board():
            if equities is None:
                raise RuntimeError("scanner down")
            pool = [Equity(row.ticker) for row in (listing or [])] if equities is ... else equities
            return Board(pool)

        async def fake_cpi(years=6):
            if cpi is None:
                return [{"month": f"2026-{m:02d}", "index": 100 * (1.02**m)} for m in range(1, 10)]
            return cpi

        monkeypatch.setattr(hz, "fetch_index", fake_index)
        monkeypatch.setattr(hz, "fetch_detail", fake_detail)
        monkeypatch.setattr("services.bist.equity_service.fetch_equity_board", fake_board)
        monkeypatch.setattr("services.bist.macro_service.fetch_cpi_series", fake_cpi)
        monkeypatch.setattr("config.settings.TCMB_EVDS_API_KEY", "x")

    return install


class TestSourceDown:
    def test_an_unreachable_calendar_is_a_503_not_an_empty_board(self, client, wire):
        wire(index=None)
        response = client.get("/api/bist/ipos")
        assert response.status_code == 503
        body = response.json()
        assert "upcoming" not in body
        assert "past" not in body

    def test_the_note_route_fails_the_same_way(self, client, wire):
        wire(index=None)
        assert client.get("/api/bist/ipos/note").status_code == 503


class TestDegradation:
    def test_scanner_down_costs_every_return_and_nothing_else(self, client, wire):
        wire(equities=None)
        body = client.get("/api/bist/ipos").json()
        assert body["coverage"]["returns_measured"] == 0
        rows_seen = body["upcoming"] + body["past"]
        assert rows_seen, "the calendar itself must still render"
        assert all(row["performance"] is None for row in rows_seen)

    def test_no_cpi_leaves_nominal_returns_intact(self, client, wire, monkeypatch):
        wire(cpi=[])
        monkeypatch.setattr("config.settings.TCMB_EVDS_API_KEY", "")
        body = client.get("/api/bist/ipos").json()
        assert body["inflation"]["available"] is False
        assert body["inflation"]["reason"] == "cpi_key_missing"
        measured = [row for row in body["past"] if row["performance"]]
        assert measured, "returns must still be measured without an index"
        for row in measured:
            assert row["performance"]["real"] is None
            assert row["performance"]["nominal"] is not None

    def test_a_failing_detail_page_leaves_the_rows_and_is_counted(self, client, wire):
        wire(detail_fails=True)
        body = client.get("/api/bist/ipos").json()
        assert body["coverage"]["detail_pages_failed"] > 0
        assert body["upcoming"] or body["past"]
        assert all("detail" in row["unparsed"] for row in body["upcoming"] + body["past"])


class TestShape:
    def test_the_source_is_named_and_stamped_with_its_own_time(self, client, wire):
        wire()
        body = client.get("/api/bist/ipos").json()
        assert body["source"] == "halkarz.com"
        assert body["source_updated_at"] == "2026-09-03T17:01"
        assert body["delay_minutes"] == 15

    def test_coverage_accounts_for_every_row(self, client, wire):
        wire()
        body = client.get("/api/bist/ipos").json()
        coverage = body["coverage"]
        assert coverage["in_window"] == len(body["upcoming"]) + len(body["past"])
        assert coverage["returns_measured"] + coverage["returns_unmeasured"] == len(body["past"])

    def test_the_window_is_echoed_back(self, client, wire):
        wire()
        body = client.get("/api/bist/ipos?months_back=12&days_ahead=30").json()
        assert body["window"] == {"months_back": 12, "days_ahead": 30}


class TestParams:
    @pytest.mark.parametrize(
        "query", ["months_back=0", "months_back=999", "days_ahead=1", "days_ahead=400"]
    )
    def test_out_of_range_windows_are_rejected(self, client, wire, query):
        wire()
        assert client.get(f"/api/bist/ipos?{query}").status_code == 422


class TestNoteRoute:
    def test_a_thin_board_yields_null_facts_rather_than_a_404(self, client, wire):
        wire(index=rows(3))
        response = client.get("/api/bist/ipos/note")
        assert response.status_code == 200
        assert response.json()["facts"] is None
