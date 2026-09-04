"""
İş Yatırım statements into quarters.

The fixtures are the live payloads for THYAO (industrial chart of accounts) and
AKBNK (bank layout) for the periods 2026/6, 2026/3, 2025/12, 2025/9, trimmed to
the item codes the parser reads. The property under test is the year-to-date
arithmetic: a quarter is a difference, Q1 is itself, and a quarter whose
previous point is missing is dropped rather than reported year-to-date.
"""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from services.bist import fundamentals as f

FIXTURES = Path(__file__).parent / "fixtures"
PERIODS = [(2026, 6), (2026, 3), (2025, 12), (2025, 9)]


def _rows(name: str) -> list[dict]:
    return json.loads((FIXTURES / f"isyatirim_{name}_2026Q2.json").read_text())["value"]


class TestCalendar:
    def test_quarter_ends_start_from_the_last_quarter_old_enough_to_be_filed(self):
        # 2 September: June is 64 days old and may be filed; nothing newer exists.
        assert f.quarter_ends(date(2026, 9, 2), 3) == [(2026, 6), (2026, 3), (2025, 12)]
        # 20 July: June is 20 days old, below the shortest deadline, so March leads.
        assert f.quarter_ends(date(2026, 7, 20), 2) == [(2026, 3), (2025, 12)]

    def test_year_boundary(self):
        # 1 February: December is 32 days old, under the deadline, so September leads.
        assert f.quarter_ends(date(2026, 2, 1), 2) == [(2025, 9), (2025, 6)]
        # 15 February: December is 46 days old and may be filed.
        assert f.quarter_ends(date(2026, 2, 15), 2) == [(2025, 12), (2025, 9)]
        assert f.expected_latest(date(2026, 2, 15)) == "2025Q4"


class TestIndustrialLayout:
    def test_quarters_are_differences_of_year_to_date_points(self):
        by_period = f.parse_periods(_rows("thyao"), PERIODS)
        quarters = f.build_quarters(by_period, f.LAYOUT_INDUSTRIAL)
        by_key = {q.period: q for q in quarters}

        # Revenue: 6M 585,069 − 3M 257,961 = Q2 327,108 (millions of lira).
        assert by_key["2026Q2"].revenue == pytest.approx(585_069_000_000 - 257_961_000_000)
        assert by_key["2026Q1"].revenue == pytest.approx(257_961_000_000)
        # Q4-2025 = 12M − 9M.
        assert by_key["2025Q4"].revenue == pytest.approx(1_125_149_219_659 - 690_825_000_000)

    def test_a_quarter_without_its_previous_point_is_dropped(self):
        by_period = f.parse_periods(_rows("thyao"), PERIODS)
        quarters = f.build_quarters(by_period, f.LAYOUT_INDUSTRIAL)
        # 2025/9 is the oldest point asked for; Q3-2025 needs 2025/6 and cannot be built.
        assert [q.period for q in quarters] == ["2026Q2", "2026Q1", "2025Q4"]

    def test_balances_are_taken_as_they_come_and_debt_is_summed(self):
        by_period = f.parse_periods(_rows("thyao"), PERIODS)
        latest = f.build_quarters(by_period, f.LAYOUT_INDUSTRIAL)[0]
        assert latest.equity == pytest.approx(1_018_453_000_000)
        assert latest.total_debt == pytest.approx(187_257_000_000 + 726_977_000_000)
        assert latest.short_term_debt == pytest.approx(187_257_000_000)
        assert latest.cash == pytest.approx(80_346_000_000)

    def test_ebitda_is_operating_profit_plus_depreciation(self):
        by_period = f.parse_periods(_rows("thyao"), PERIODS)
        q1 = {q.period: q for q in f.build_quarters(by_period, f.LAYOUT_INDUSTRIAL)}["2026Q1"]
        assert q1.ebitda == pytest.approx(-2_451_000_000 + 28_358_000_000)

    def test_layout_detection(self):
        assert f.detect_layout(_rows("thyao"), "XI_29") == f.LAYOUT_INDUSTRIAL
        assert f.detect_layout(_rows("akbnk"), "UFRS") == f.LAYOUT_BANK
        assert (
            f.detect_layout([{"itemCode": "3Z", "itemDescTr": "Kar"}], "UFRS") == f.LAYOUT_INSURANCE
        )


class TestBankLayout:
    def test_revenue_is_net_interest_plus_fees_and_equity_is_read(self):
        by_period = f.parse_periods(_rows("akbnk"), PERIODS)
        quarters = {q.period: q for q in f.build_quarters(by_period, f.LAYOUT_BANK)}
        q1 = quarters["2026Q1"]
        assert q1.revenue == pytest.approx(40_596_842_000 + 30_158_371_000)
        assert q1.net_income == pytest.approx(19_178_575_000)
        assert q1.equity is not None and q1.total_assets is not None
        assert q1.ebitda is None


class TestFreshness:
    def _fund(self, fetched_days_ago: float, latest: str) -> f.Fundamentals:
        year, q = int(latest[:4]), int(latest[-1])
        quarter = f.Quarter(period=latest, year=year, quarter=q, net_income=1.0)
        fetched = (datetime.now(UTC) - timedelta(days=fetched_days_ago)).isoformat()
        return f.Fundamentals("TEST", f.LAYOUT_INDUSTRIAL, (quarter,), fetched, "x")

    def test_fresh_when_the_expected_quarter_is_present(self):
        today = date(2026, 9, 2)
        assert f.is_fresh(self._fund(10, "2026Q2"), today)

    def test_rechecked_after_a_few_days_when_the_expected_quarter_is_missing(self):
        today = date(2026, 9, 2)
        assert f.is_fresh(self._fund(1, "2026Q1"), today)
        assert not f.is_fresh(self._fund(4, "2026Q1"), today)

    def test_hard_refresh_after_forty_five_days(self):
        assert not f.is_fresh(self._fund(46, "2026Q2"), date(2026, 9, 2))

    def test_roundtrip_through_dict(self):
        fund = self._fund(1, "2026Q2")
        assert f.Fundamentals.from_dict(fund.to_dict()) == fund
