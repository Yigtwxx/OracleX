"""
Tests for CPI level restatement.

The property these lean on hardest is monotonicity: an older quarter must take a
larger multiplier than a newer one, and the base must take exactly 1.0. An
inverted ratio still produces finite, plausible, well-scaled numbers — it just
makes every company look better in real terms than it was, in the one direction
nobody checks.
"""

from __future__ import annotations

import pytest

from services.bist import deflator as d


def cpi(*months: tuple[str, float]) -> list[dict]:
    return [{"month": m, "index": v} for m, v in months]


def monthly(start_year: int, start_month: int, count: int, *, step: float = 1.02) -> list[dict]:
    """A monotone synthetic index, one row per month, compounding by `step`."""
    out: list[dict] = []
    value = 100.0
    year, month = start_year, start_month
    for _ in range(count):
        out.append({"month": f"{year}-{month:02d}", "index": round(value, 4)})
        value *= step
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


class TestPeriodMonth:
    @pytest.mark.parametrize(
        "period,expected",
        [
            ("2026Q1", "2026-03"),
            ("2026Q2", "2026-06"),
            ("2026Q3", "2026-09"),
            ("2026Q4", "2026-12"),
            ("2024Q4", "2024-12"),
            ("2025Q1", "2025-03"),
        ],
    )
    def test_maps_quarter_to_its_closing_month(self, period, expected):
        assert d.period_month(period) == expected

    @pytest.mark.parametrize("bad", ["", "2026", "2026Q5", "2026Q0", "Q2", "26Q2", "2026-06"])
    def test_rejects_anything_that_is_not_a_period(self, bad):
        assert d.period_month(bad) is None


class TestIndexByMonth:
    def test_zero_pads_the_evds_month_shape(self):
        # EVDS states a monthly Tarih as "2026-6". Nothing downstream raises on
        # the unpadded form; every lookup simply misses.
        out = d.index_by_month(cpi(("2026-6", 120.0), ("2026-07", 122.0)))
        assert out == {"2026-06": 120.0, "2026-07": 122.0}

    def test_drops_a_non_numeric_row_without_raising(self):
        out = d.index_by_month(
            [
                {"month": "2026-06", "index": "abc"},
                {"month": "2026-07", "index": None},
                {"month": "2026-08", "index": "130,5"},
                {"month": "2026-09", "index": 140.0},
            ]
        )
        assert out == {"2026-09": 140.0}

    def test_drops_a_non_positive_index(self):
        # Dividing by it would produce an infinity that renders as a plausible bar.
        assert d.index_by_month(cpi(("2026-06", 0.0), ("2026-07", -3.0))) == {}

    def test_drops_a_malformed_month(self):
        assert d.index_by_month(cpi(("June 2026", 120.0), ("2026", 121.0))) == {}

    def test_empty_input(self):
        assert d.index_by_month([]) == {}


class TestBuildDeflation:
    def test_factors_decrease_with_recency_and_the_base_is_exactly_one(self):
        # The sanity property. An inverted ratio passes every other assertion
        # here while making each real figure wrong in the flattering direction.
        periods = [f"{y}Q{q}" for y in (2024, 2025, 2026) for q in (1, 2, 3, 4)][:12]
        result = d.build_deflation(periods, monthly(2023, 1, 48), key_configured=True)

        assert result.available is True
        assert result.reason is None
        assert result.base_period == "2026Q4"
        assert result.base_month == "2026-12"
        assert result.factors["2026Q4"] == pytest.approx(1.0)

        ordered = [result.factors[p] for p in sorted(result.factors)]
        assert all(earlier > later for earlier, later in zip(ordered, ordered[1:])), (
            "an older quarter must take a larger multiplier than a newer one"
        )

    def test_restates_an_older_quarter_upward(self):
        result = d.build_deflation(
            ["2025Q4", "2026Q2"],
            cpi(("2025-12", 100.0), ("2026-03", 110.0), ("2026-06", 120.0)),
            key_configured=True,
        )
        assert result.factors["2025Q4"] == pytest.approx(1.2)
        assert result.factors["2026Q2"] == pytest.approx(1.0)

    def test_newest_quarter_one_month_past_the_series_is_provisional(self):
        # CPI lands early in the following month; statements land up to forty
        # days after the quarter closes. This is the ordinary case, not an edge.
        result = d.build_deflation(
            ["2026Q1", "2026Q2"],
            cpi(("2026-03", 100.0), ("2026-04", 102.0), ("2026-05", 104.0)),
            key_configured=True,
        )
        assert result.available is True
        assert result.cpi_latest_month == "2026-05"
        assert result.provisional == ("2026Q2",)
        assert result.factors["2026Q2"] == pytest.approx(1.0)
        assert result.factors["2026Q1"] == pytest.approx(1.04)

    def test_three_months_past_the_series_is_still_only_provisional(self):
        # Pins the tolerance so it cannot quietly widen into a second rule.
        result = d.build_deflation(
            ["2026Q1", "2026Q2"],
            cpi(("2026-02", 98.0), ("2026-03", 100.0)),
            key_configured=True,
        )
        assert result.available is True
        assert result.provisional == ("2026Q2",)
        assert result.uncovered == ()

    def test_periods_older_than_the_series_are_uncovered_and_get_no_factor(self):
        # Extending the index backwards would invent a price level, and the
        # resulting bar would be indistinguishable from a measured one.
        result = d.build_deflation(
            ["2023Q1", "2023Q2", "2026Q1", "2026Q2"],
            cpi(("2025-12", 100.0), ("2026-03", 110.0), ("2026-06", 120.0)),
            key_configured=True,
        )
        assert result.available is True
        assert result.uncovered == ("2023Q1", "2023Q2")
        assert "2023Q1" not in result.factors
        assert set(result.factors) == {"2026Q1", "2026Q2"}

    def test_no_key_reports_the_setup_gap(self):
        result = d.build_deflation(["2026Q2"], [], key_configured=False)
        assert result.available is False
        assert result.reason == d.REASON_KEY_MISSING
        assert result.factors == {}

    def test_key_present_but_no_series_reports_an_outage(self):
        # Only the no-key case is fixable by the operator, so the two cannot
        # share a sentence.
        result = d.build_deflation(["2026Q2"], [], key_configured=True)
        assert result.available is False
        assert result.reason == d.REASON_UNAVAILABLE

    def test_series_that_stops_before_the_base_quarter(self):
        result = d.build_deflation(
            ["2026Q1", "2026Q2"],
            cpi(("2019-01", 40.0), ("2019-02", 41.0)),
            key_configured=True,
        )
        assert result.available is False
        assert result.reason == d.REASON_TOO_SHORT
        assert result.base_period == "2026Q2"

    def test_carry_forward_stops_at_the_documented_bound(self):
        # Four months ahead is the last position that still deflates; five is a
        # stale series, and carrying an index across a Turkish year would
        # understate every restatement while still producing finite, monotone,
        # entirely wrong factors.
        at_bound = d.build_deflation(["2026Q2"], cpi(("2026-02", 100.0)), key_configured=True)
        assert at_bound.available is True
        assert at_bound.provisional == ("2026Q2",)

        past_bound = d.build_deflation(["2026Q2"], cpi(("2026-01", 100.0)), key_configured=True)
        assert past_bound.available is False
        assert past_bound.reason == d.REASON_TOO_SHORT

    def test_the_base_falls_back_to_the_newest_quarter_the_index_can_reach(self):
        # EVDS runs months behind on occasion — it was eight months behind when
        # this was written. Pinning the base to a quarter the index cannot cover
        # would take the whole board nominal over one unreachable bar.
        result = d.build_deflation(
            ["2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"],
            monthly(2023, 1, 37),  # ends 2026-01
            key_configured=True,
        )
        assert result.available is True
        assert result.cpi_latest_month == "2026-01"
        # 2026Q2 closes in June, five months past the index: out of reach.
        assert result.base_period == "2026Q1"
        assert result.uncovered == ("2026Q2",)
        assert result.provisional == ("2026Q1",)
        assert result.factors["2026Q1"] == pytest.approx(1.0)
        assert "2026Q2" not in result.factors
        # And the older quarters are still properly restated.
        assert result.factors["2025Q2"] > result.factors["2025Q4"] > 1.0

    def test_a_period_far_past_the_index_is_uncovered_not_carried_forward(self):
        # The complement of the fallback: reaching the base does not license
        # dragging every later quarter along with it.
        result = d.build_deflation(
            ["2025Q4", "2026Q1", "2026Q2", "2026Q3"],
            monthly(2024, 1, 25),  # ends 2026-01
            key_configured=True,
        )
        assert result.available is True
        assert set(result.uncovered) == {"2026Q2", "2026Q3"}
        assert result.base_period == "2026Q1"

    def test_no_usable_periods(self):
        result = d.build_deflation(["garbage"], cpi(("2026-06", 120.0)), key_configured=True)
        assert result.available is False
        assert result.reason == d.REASON_TOO_SHORT

    def test_unpadded_evds_months_still_resolve(self):
        # The normalisation is load-bearing end to end, not only in isolation.
        result = d.build_deflation(
            ["2026Q1", "2026Q2"],
            cpi(("2026-3", 100.0), ("2026-6", 120.0)),
            key_configured=True,
        )
        assert result.available is True
        assert result.uncovered == ()
        assert result.factors["2026Q1"] == pytest.approx(1.2)


class TestRestate:
    def test_multiplies(self):
        assert d.restate(100.0, 1.4) == pytest.approx(140.0)

    @pytest.mark.parametrize("value,factor", [(None, 1.4), (5.0, None), (None, None)])
    def test_either_half_missing_yields_none(self, value, factor):
        # A company that did not report a line and a quarter the index does not
        # reach are indistinguishable to a reader, so both produce one empty cell.
        assert d.restate(value, factor) is None

    def test_zero_is_preserved_rather_than_treated_as_missing(self):
        assert d.restate(0.0, 1.4) == 0.0
