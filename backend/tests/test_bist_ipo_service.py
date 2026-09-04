"""
The offering board's merge, windowing and return arithmetic.

Two things carry the most weight. The fetch budget, because the naive shape —
two hundred detail pages per request — is a production incident rather than a
slow endpoint. And the rule that an unmeasurable return is absent rather than
zero, because a listing drawn at zero reads as one that went nowhere, which is a
claim about a company.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from services.bist import halkarz_client as hz
from services.bist import ipo_service as ipo

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 9, 4)


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Disk cache into tmp, and no sleeping between fetches."""
    monkeypatch.setattr(ipo, "CACHE_DIR", str(tmp_path / "ipos"))
    monkeypatch.setattr(ipo, "REQUEST_SPACING_SECONDS", 0)
    from services.cache import bist_cache

    bist_cache.clear()
    yield
    bist_cache.clear()


def index_row(slug="acme-a-s", ticker="ACME", raw_date="26-27 Ağustos 2026", is_new=False):
    return hz.IndexRow(
        slug=slug,
        url=f"{hz.BASE}/{slug}/",
        company="Acme A.Ş.",
        ticker=ticker,
        offer_dates_raw=raw_date,
        is_new=is_new,
    )


def detail(**kw):
    base = {
        "ticker": "ACME",
        "offer_dates_raw": "26-27 Ağustos 2026",
        "listing_date_raw": "1 Eylül 2026",
        "price_raw": "50,00 TL",
        "lots_raw": "40.000.000 Lot",
        "free_float_lots_raw": "39.997.279 Lot",
        "free_float_pct_raw": "%24,99",
        "broker": "Bulls Yatırım Menkul Değerler A.Ş.",
        "method": "Eşit Dağıtım",
        "market": "Yıldız Pazar",
        "updated_at": "2026-09-03T17:01",
        "results": None,
        "structure": None,
        "use_of_proceeds": None,
        "proceeds_source": None,
        "labels_seen": (),
    }
    base.update(kw)
    return base


class Equity:
    def __init__(self, price=60.0):
        self.price = price
        self.market_cap = 1.2e10
        self.sector = "Sanayi"


CPI = {f"2026-{m:02d}": 100 * (1.02**m) for m in range(1, 10)}


class TestState:
    @pytest.mark.parametrize(
        "offer,listing,expected",
        [
            (None, None, ipo.STATE_UNDATED),
            (("2026-09-10", "2026-09-11"), None, ipo.STATE_UPCOMING),
            (("2026-09-04", "2026-09-05"), None, ipo.STATE_BOOK_OPEN),
            (("2026-09-03", "2026-09-04"), None, ipo.STATE_BOOK_OPEN),
            (("2026-08-01", "2026-08-02"), ("2026-09-01", "2026-09-01"), ipo.STATE_LISTED),
            (("2026-08-01", "2026-08-02"), None, ipo.STATE_UNDATED),
        ],
    )
    def test_boundaries(self, offer, listing, expected):
        def rng(pair):
            return (
                hz.DateRange(date.fromisoformat(pair[0]), date.fromisoformat(pair[1]))
                if pair
                else None
            )

        assert ipo.offering_state(rng(offer), rng(listing), TODAY) == expected

    def test_a_closed_book_with_an_assigned_code_is_trading(self):
        # The calendar carries offerings back to 2019 and a detail page is only
        # read once the budget reaches it, so hundreds of rows arrive with a
        # window years past and no listing date. Calling those upcoming put a
        # 2019 offering in the forward tray.
        closed = hz.DateRange(date(2019, 3, 5), date(2019, 3, 6))
        assert ipo.offering_state(closed, None, TODAY, has_ticker=True) == ipo.STATE_LISTED
        assert ipo.offering_state(closed, None, TODAY, has_ticker=False) == ipo.STATE_UNDATED

    def test_a_code_does_not_make_a_future_offering_listed(self):
        ahead = hz.DateRange(date(2026, 10, 1), date(2026, 10, 2))
        assert ipo.offering_state(ahead, None, TODAY, has_ticker=True) == ipo.STATE_UPCOMING

    def test_listing_today_counts_as_listed(self):
        listing = hz.DateRange(TODAY, TODAY)
        assert ipo.offering_state(None, listing, TODAY) == ipo.STATE_LISTED


class TestPerformance:
    def test_measures_against_the_struck_price(self):
        result = ipo.compute_performance(
            price=hz.Money(50.0, 50.0, False),
            listing=hz.DateRange(date(2026, 6, 1), date(2026, 6, 1)),
            equity=Equity(60.0),
            cpi_index=CPI,
            today=TODAY,
        )
        assert result["nominal"] == pytest.approx(0.2)
        assert result["real"] is not None
        # Inflation over the window eats into the lira gain.
        assert result["real"] < result["nominal"]

    def test_a_band_with_no_struck_price_yields_nothing(self):
        # A midpoint is a specific number nobody offered at, and a return
        # measured against it would look measured and be invented.
        assert (
            ipo.compute_performance(
                price=hz.Money(12.0, 14.5, True),
                listing=hz.DateRange(date(2026, 6, 1), date(2026, 6, 1)),
                equity=Equity(20.0),
                cpi_index=CPI,
                today=TODAY,
            )
            is None
        )

    def test_no_scanner_row_yields_nothing(self):
        assert (
            ipo.compute_performance(
                price=hz.Money(50.0, 50.0, False),
                listing=hz.DateRange(date(2026, 6, 1), date(2026, 6, 1)),
                equity=None,
                cpi_index=CPI,
                today=TODAY,
            )
            is None
        )

    def test_real_is_dropped_when_the_index_misses_the_listing_month(self):
        result = ipo.compute_performance(
            price=hz.Money(50.0, 50.0, False),
            listing=hz.DateRange(date(2019, 6, 1), date(2019, 6, 1)),
            equity=Equity(60.0),
            cpi_index=CPI,
            today=TODAY,
        )
        assert result["nominal"] == pytest.approx(0.2)
        assert result["real"] is None

    def test_a_listing_date_in_the_future_is_rejected_outright(self):
        # Same untrusted page as everything else; a wrong date makes a wrong
        # inflation window and therefore a wrong real return.
        assert (
            ipo.compute_performance(
                price=hz.Money(50.0, 50.0, False),
                listing=hz.DateRange(date(2027, 6, 1), date(2027, 6, 1)),
                equity=Equity(60.0),
                cpi_index=CPI,
                today=TODAY,
            )
            is None
        )

    def test_an_absurdly_old_listing_date_is_rejected(self):
        assert (
            ipo.compute_performance(
                price=hz.Money(50.0, 50.0, False),
                listing=hz.DateRange(date(1900, 1, 1), date(1900, 1, 1)),
                equity=Equity(60.0),
                cpi_index=CPI,
                today=TODAY,
            )
            is None
        )

    def test_a_very_new_listing_is_marked_rather_than_dropped(self):
        # A three-day return is a fact; excluding it would flatter the
        # distribution by dropping exactly the newest listings.
        fresh = ipo.compute_performance(
            price=hz.Money(50.0, 50.0, False),
            listing=hz.DateRange(TODAY - timedelta(days=2), TODAY - timedelta(days=2)),
            equity=Equity(60.0),
            cpi_index=CPI,
            today=TODAY,
        )
        assert fresh is not None
        assert fresh["seasoned"] is False
        assert fresh["days_listed"] == 2


class TestBuildRow:
    def test_the_detail_page_wins_on_the_ticker(self):
        # The code is assigned after the index entry is written.
        row = ipo.build_row(
            index_row(ticker=None),
            detail(ticker="ACME"),
            equity=None,
            cpi_index={},
            today=TODAY,
        )
        assert row["ticker"] == "ACME"

    def test_a_row_with_no_detail_still_renders_and_says_so(self):
        row = ipo.build_row(index_row(), None, equity=None, cpi_index={}, today=TODAY)
        assert row["company"] == "Acme A.Ş."
        assert row["broker"] is None
        assert "detail" in row["unparsed"]

    def test_an_unparseable_date_is_recorded_rather_than_guessed(self):
        row = ipo.build_row(
            index_row(raw_date="Hazırlanıyor..."),
            detail(offer_dates_raw="Hazırlanıyor...", listing_date_raw=None),
            equity=None,
            cpi_index={},
            today=TODAY,
        )
        assert row["offer_dates"] is None
        assert row["state"] == ipo.STATE_UNDATED
        assert "offer_dates" in row["unparsed"]

    def test_allocation_shares_are_passed_through_unnormalised(self):
        # The source rounds; normalising to 1.0 invents precision it never
        # claimed, and the allocation bar is built to leave bare track.
        results = {
            "groups": [
                {
                    "key": "domestic_retail",
                    "label": "Yurt İçi Bireysel",
                    "investors": 1,
                    "lots": 2,
                    "share": 0.98,
                }
            ],
            "total_investors": 1,
            "total_lots": 2,
        }
        row = ipo.build_row(
            index_row(), detail(results=results), equity=None, cpi_index={}, today=TODAY
        )
        assert row["results"]["groups"][0]["share"] == 0.98

    def test_is_json_encodable(self):
        row = ipo.build_row(index_row(), detail(), equity=Equity(), cpi_index=CPI, today=TODAY)
        json.dumps(row)


class TestWindow:
    def test_a_listing_older_than_the_window_is_excluded(self):
        old = ipo.build_row(
            index_row(),
            detail(listing_date_raw="1 Ocak 2024"),
            equity=None,
            cpi_index={},
            today=TODAY,
        )
        assert ipo.in_window(old, months_back=12, days_ahead=120, today=TODAY) is False
        assert ipo.in_window(old, months_back=60, days_ahead=120, today=TODAY) is True

    def test_an_offering_beyond_the_forward_window_is_excluded(self):
        far = ipo.build_row(
            index_row(raw_date="1 Aralık 2026"),
            detail(offer_dates_raw="1 Aralık 2026", listing_date_raw=None),
            equity=None,
            cpi_index={},
            today=TODAY,
        )
        assert ipo.in_window(far, months_back=24, days_ahead=7, today=TODAY) is False
        assert ipo.in_window(far, months_back=24, days_ahead=365, today=TODAY) is True

    def test_a_genuinely_undated_offering_is_always_in_window(self):
        # No date to fall outside one, and the calendar exists for exactly these.
        undated = ipo.build_row(
            index_row(raw_date="Hazırlanıyor..."),
            detail(offer_dates_raw="Hazırlanıyor...", listing_date_raw=None),
            equity=None,
            cpi_index={},
            today=TODAY,
        )
        assert undated["state"] == ipo.STATE_UNDATED
        assert ipo.in_window(undated, months_back=3, days_ahead=7, today=TODAY) is True

    def test_a_row_nobody_has_read_yet_is_not_counted_as_pending(self):
        # Offer window closed, no code, no detail: undateable. Letting it into
        # the window would inflate every "listed in this window" figure.
        unread = ipo.build_row(
            index_row(ticker=None, raw_date="5-6 Mart 2019"),
            None,
            equity=None,
            cpi_index={},
            today=TODAY,
        )
        assert unread["state"] == ipo.STATE_UNDATED
        assert ipo.in_window(unread, months_back=24, days_ahead=120, today=TODAY) is False

    def test_a_listing_we_cannot_date_is_excluded_from_a_dated_window(self):
        undateable = ipo.build_row(
            index_row(raw_date="5-6 Mart 2019"),
            None,
            equity=None,
            cpi_index={},
            today=TODAY,
        )
        assert undateable["state"] == ipo.STATE_LISTED
        assert undateable["listing_date"] is None
        assert ipo.in_window(undateable, months_back=24, days_ahead=120, today=TODAY) is False


class TestFreshness:
    def test_a_listed_offering_with_results_never_changes_again(self):
        settled = detail(
            listing_date_raw="1 Eylül 2026", results={"groups": [{"key": "domestic_retail"}]}
        )
        assert ipo.is_settled(settled, TODAY) is True
        entry = ipo.CachedDetail(
            slug="x",
            fetched_at=(datetime.now(UTC) - timedelta(days=400)).isoformat(),
            fields=settled,
        )
        assert ipo.is_fresh(entry, TODAY) is True

    def test_a_pending_offering_is_re_read_after_the_recheck_window(self):
        pending = detail(listing_date_raw=None, results=None)
        stale = ipo.CachedDetail(
            slug="x",
            fetched_at=(datetime.now(UTC) - timedelta(hours=48)).isoformat(),
            fields=pending,
        )
        warm = ipo.CachedDetail(slug="x", fetched_at=datetime.now(UTC).isoformat(), fields=pending)
        assert ipo.is_fresh(stale, TODAY) is False
        assert ipo.is_fresh(warm, TODAY) is True

    def test_a_listed_offering_without_results_is_still_pending(self):
        assert ipo.is_settled(detail(results=None), TODAY) is False

    def test_round_trips_through_disk(self):
        entry = ipo.CachedDetail(
            slug="acme", fetched_at="2026-09-01T00:00:00+00:00", fields=detail()
        )
        ipo.write_cached(entry)
        assert ipo.read_cached("acme").fields["broker"] == entry.fields["broker"]
        assert ipo.read_cached("missing") is None


class TestBudget:
    @pytest.mark.asyncio
    async def test_a_cold_cache_never_exceeds_the_fetch_budget(self, monkeypatch):
        # Two hundred detail pages at ninety kilobytes is nineteen megabytes and
        # two hundred requests, which is not something a page load may do.
        calls: list[str] = []

        async def fake_detail(slug: str):
            calls.append(slug)
            return hz.DetailFields(ticker="ACME")

        monkeypatch.setattr(hz, "fetch_detail", fake_detail)
        rows = [index_row(slug=f"row-{i}") for i in range(219)]
        details, read, failed = await ipo.load_details(rows, today=TODAY)

        assert len(calls) == ipo.DETAIL_BUDGET
        assert read == ipo.DETAIL_BUDGET
        assert failed == 0
        # Newest first: the rows the board shows are the rows that get filled.
        assert calls == [f"row-{i}" for i in range(ipo.DETAIL_BUDGET)]

    @pytest.mark.asyncio
    async def test_a_failed_detail_is_counted_and_the_row_survives(self, monkeypatch):
        async def fake_detail(slug: str):
            raise hz.HalkarzUnavailable("nope")

        monkeypatch.setattr(hz, "fetch_detail", fake_detail)
        details, read, failed = await ipo.load_details([index_row()], today=TODAY)
        assert failed == 1
        assert read == 0
        assert details == {}

    @pytest.mark.asyncio
    async def test_a_warm_cache_issues_no_requests(self, monkeypatch):
        settled = detail(results={"groups": [{"key": "domestic_retail"}]})
        ipo.write_cached(
            ipo.CachedDetail(
                slug="acme-a-s", fetched_at=datetime.now(UTC).isoformat(), fields=settled
            )
        )

        async def fail(slug: str):
            raise AssertionError("should not fetch a settled row")

        monkeypatch.setattr(hz, "fetch_detail", fail)
        details, read, failed = await ipo.load_details([index_row()], today=TODAY)
        assert read == 0 and failed == 0
        assert details["acme-a-s"]["broker"] == settled["broker"]
