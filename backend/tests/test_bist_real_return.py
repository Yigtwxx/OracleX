"""
Real returns.

The arithmetic this realm exists for. Every test here is really the same
assertion from a different angle: at Turkish rates, the intuitive shortcut is
not a rounding error, it is a different answer.
"""

import pytest

from services.bist.real_return import (
    annualise,
    cumulative_inflation,
    deflate,
    enrich_returns,
    in_usd,
    rate_months_ago,
    summarise_real_losses,
    triplet,
)


class TestDeflate:
    def test_uses_the_fisher_relation_not_subtraction(self):
        # 148% nominal against 89% inflation. Subtracting gives 59%; the true
        # figure is 31%. The gap grows with the rate, which is exactly why the
        # shortcut is unusable in this market.
        assert deflate(1.48, 0.89) == pytest.approx(0.3122, abs=1e-4)
        assert deflate(1.48, 0.89) != pytest.approx(0.59, abs=0.01)

    def test_a_return_that_matches_inflation_is_zero_real(self):
        assert deflate(0.45, 0.45) == pytest.approx(0.0)

    def test_a_return_below_inflation_is_a_real_loss(self):
        assert deflate(0.20, 0.45) < 0

    def test_declines_when_inflation_is_undefined(self):
        # A guard rather than a real case, but a ZeroDivisionError inside a
        # screener is worse than a missing cell.
        assert deflate(0.5, -1.0) is None
        assert deflate(0.5, -1.5) is None


class TestInUsd:
    def test_a_weakening_lira_reduces_the_return(self):
        # fx is lira per dollar, so a larger end value means a weaker lira.
        # Getting this direction wrong would flatter every figure on the board.
        assert in_usd(1.0, 30.0, 45.0) < 1.0

    def test_a_flat_currency_leaves_the_return_alone(self):
        assert in_usd(0.6, 40.0, 40.0) == pytest.approx(0.6)

    def test_declines_on_a_missing_or_impossible_rate(self):
        assert in_usd(0.5, 0.0, 40.0) is None
        assert in_usd(0.5, 40.0, -1.0) is None


class TestTriplet:
    def test_missing_inputs_leave_frames_empty_rather_than_failing(self):
        frames = triplet(0.5)
        assert frames.nominal == 0.5
        assert frames.real is None and frames.usd is None

    def test_reports_all_three_when_everything_resolves(self):
        frames = triplet(1.0, inflation=0.3, fx_start=40.0, fx_end=48.0)
        assert frames.real is not None and frames.usd is not None
        assert frames.nominal > frames.usd > frames.real


class TestCumulativeAndAnnualise:
    def test_monthly_rates_compound_rather_than_sum(self):
        # Twelve months of 3% is 42.6%, not 36%. At Turkish rates that error is
        # larger than most of the returns it would be applied to.
        assert cumulative_inflation([0.03] * 12) == pytest.approx(0.4258, abs=1e-4)

    def test_annualise_scales_a_partial_window(self):
        assert annualise(0.2, 6) == pytest.approx(0.44, abs=1e-2)

    def test_annualise_declines_on_a_total_loss(self):
        assert annualise(-1.0, 12) is None
        assert annualise(0.2, 0) is None


class TestRateMonthsAgo:
    def test_counts_back_by_trading_days(self):
        series = [{"date": f"d{i}", "rate": float(i)} for i in range(300)]
        # 12 months ≈ 252 trading days back from the end.
        assert rate_months_ago(series, 12) == pytest.approx(299 - 252)

    def test_none_when_the_series_is_too_short(self):
        assert rate_months_ago([{"rate": 1.0}], 12) is None
        assert rate_months_ago([], 1) is None

    def test_ignores_a_non_positive_rate(self):
        assert rate_months_ago([{"rate": 0.0}, {"rate": 5.0}], 0) == pytest.approx(5.0)


class TestEnrichReturns:
    def test_reports_every_window_that_has_a_nominal_figure(self):
        # A window that could not be deflated still appears, with a null real
        # column. Absent and unknown have to look different to a reader.
        out = enrich_returns(
            {"1y": 1.0, "3y": 4.0},
            deflators={"1y": 0.3, "3y": None},
        )
        assert set(out) == {"1y", "3y"}
        assert out["1y"]["real"] is not None
        assert out["3y"]["real"] is None

    def test_skips_windows_with_no_nominal_figure(self):
        out = enrich_returns({"1y": None, "6a": 0.2}, deflators={"6a": 0.1})
        assert set(out) == {"6a"}

    def test_uses_the_exchange_rate_from_the_start_of_each_window(self):
        series = [{"rate": 30.0 + i * 0.05} for i in range(300)]
        out = enrich_returns(
            {"1y": 1.0},
            deflators={"1y": 0.3},
            fx_series=series,
            window_months={"1y": 12},
        )
        assert out["1y"]["usd"] is not None
        # The lira weakened over the window, so the dollar return trails the
        # nominal one.
        assert out["1y"]["usd"] < out["1y"]["nominal"]

    def test_no_fx_series_leaves_the_dollar_column_empty(self):
        out = enrich_returns({"1y": 1.0}, deflators={"1y": 0.3}, window_months={"1y": 12})
        assert out["1y"]["usd"] is None
        assert out["1y"]["real"] is not None


class TestSummariseRealLosses:
    def _rows(self, spec: list[tuple[str, float, float | None]]):
        return [
            (key, {"1y": {"nominal": nominal, "real": real, "usd": None}})
            for key, nominal, real in spec
        ]

    def test_counts_only_gains_that_became_losses(self):
        summary = summarise_real_losses(
            self._rows(
                [
                    ("FLIP", 0.31, -0.004),  # gained in lira, lost purchasing power
                    ("REALGAIN", 0.80, 0.36),  # beat inflation
                    ("BOTHDOWN", -0.10, -0.32),  # lost either way — not the claim
                ]
            )
        )
        assert summary.measured == 3
        assert summary.count == 1
        assert summary.example_key == "FLIP"

    def test_ignores_rows_with_no_deflator(self):
        # Without an EVDS key most windows have no real figure at all. Those
        # rows are not evidence either way and must not inflate the denominator.
        summary = summarise_real_losses(self._rows([("A", 0.5, None), ("B", 0.2, -0.1)]))
        assert summary.measured == 1
        assert summary.count == 1

    def test_example_is_the_largest_gain_that_still_lost(self):
        # Not the worst case. A fund up 31% that returned nothing makes the
        # point; one up 2% that lost 28% just looks like a bad fund.
        summary = summarise_real_losses(self._rows([("SMALL", 0.02, -0.28), ("BIG", 0.31, -0.004)]))
        assert summary.example_key == "BIG"
        assert summary.example_nominal == pytest.approx(0.31)
        assert summary.example_real == pytest.approx(-0.004)

    def test_no_example_when_nothing_flipped(self):
        summary = summarise_real_losses(self._rows([("A", 0.8, 0.36)]))
        assert summary.count == 0
        assert summary.example_key is None

    def test_handles_an_empty_board(self):
        summary = summarise_real_losses([])
        assert summary.measured == 0 and summary.count == 0
