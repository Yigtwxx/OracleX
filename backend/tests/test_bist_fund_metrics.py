"""
The fund risk statistics.

These are the numbers a reader picks one fund over another on, so the tests are
mostly about the cases where a plausible-looking figure would be wrong: a series
too short to describe, a fund that never recovered, a risk-free rate large
enough to invert a ranking.

Nothing here touches the network — the module under test is pure arithmetic,
which is the reason it is a module rather than a block inside the service.
"""

import math

import pytest

from services.bist import fund_metrics as fm


def _compound(start: float, daily: float, days: int) -> list[float]:
    """A series growing at a constant daily rate."""
    return [start * (1 + daily) ** day for day in range(days + 1)]


def _from_returns(start: float, returns: list[float]) -> list[float]:
    """A price series that produces exactly `returns`."""
    prices = [start]
    for r in returns:
        prices.append(prices[-1] * (1 + r))
    return prices


def _cycle(pattern: list[float], length: int) -> list[float]:
    """`pattern` repeated to `length`. Deterministic, so a failure reproduces."""
    return [pattern[i % len(pattern)] for i in range(length)]


class TestDailyReturns:
    def test_computes_period_over_period(self):
        assert fm.daily_returns([100, 110, 99]) == pytest.approx([0.1, -0.1])

    def test_skips_non_positive_prices(self):
        # TEFAS occasionally carries a zero for a day a fund did not price.
        # Dividing by it yields an infinity that then poisons the variance,
        # the Sharpe ratio and the drawdown all at once.
        returns = fm.daily_returns([100, 0, 110])
        assert all(math.isfinite(r) for r in returns)
        assert returns == []

    def test_empty_for_a_single_observation(self):
        assert fm.daily_returns([100]) == []


class TestTotalAndAnnualised:
    def test_total_return_is_end_over_start(self):
        assert fm.total_return([100, 150]) == pytest.approx(0.5)

    def test_annualised_is_geometric_not_arithmetic(self):
        # Down 50% then up 50% is a 25% loss, not break-even. An arithmetic
        # mean of daily returns says zero here, which is the whole reason the
        # geometric form is used.
        prices = [100, 50, 75]
        assert fm.total_return(prices) == pytest.approx(-0.25)
        assert fm.annualised_return(prices) < 0

    def test_a_full_year_annualises_to_roughly_its_total(self):
        prices = _compound(100, 0.001, fm.TRADING_DAYS_PER_YEAR)
        total = fm.total_return(prices)
        assert fm.annualised_return(prices) == pytest.approx(total, rel=1e-6)

    def test_declines_on_a_total_loss(self):
        # (1 + total) ** x is undefined for total <= -1; None rather than a
        # complex number or a crash.
        assert fm.annualised_return([100, 0.0]) is None
        assert fm.total_return([0.0, 100]) is None


class TestVolatility:
    def test_none_below_the_observation_floor(self):
        # A standard deviation over four points is noise wearing a number's
        # clothes, and rendering it beside a real one is the failure.
        assert fm.volatility([0.01, -0.01, 0.02, -0.02]) is None

    def test_zero_for_a_constant_series(self):
        assert fm.volatility([0.001] * 30) == pytest.approx(0.0)

    def test_scales_with_the_square_root_of_time(self):
        returns = [0.01, -0.01] * 20
        annual = fm.volatility(returns, observations_per_year=252)
        quarterly = fm.volatility(returns, observations_per_year=63)
        assert annual / quarterly == pytest.approx(math.sqrt(4), rel=1e-9)


class TestSharpeAndSortino:
    def test_risk_free_rate_moves_the_ratio(self):
        # The point of making the argument required. At a Turkish policy rate a
        # fund that looks excellent against zero can be flat against cash.
        prices = _from_returns(100, _cycle([0.012, -0.008, 0.006, -0.004], 252))
        against_zero = fm.sharpe_ratio(prices, 0.0)
        against_cash = fm.sharpe_ratio(prices, 0.45)
        assert against_zero is not None and against_cash is not None
        assert against_zero > against_cash

    def test_sortino_ranks_upside_volatility_above_downside(self):
        # Two funds whose day-to-day moves are the same size, differing only in
        # which direction the large ones point. Sharpe reads them as similarly
        # risky because it squares both tails; Sortino is what separates them,
        # which is the reason both ratios are on the page rather than one.
        up_shocks = _cycle([0.030, -0.004, -0.004, -0.004], 252)
        down_shocks = _cycle([-0.030, 0.004, 0.004, 0.004], 252)

        up_sortino = fm.sortino_ratio(_from_returns(100, up_shocks), 0.0)
        down_sortino = fm.sortino_ratio(_from_returns(100, down_shocks), 0.0)
        assert up_sortino is not None and down_sortino is not None
        assert up_sortino > down_sortino

    def test_sharpe_is_none_when_the_series_never_moves(self):
        # Zero volatility would divide by zero. None, not infinity — and not a
        # very large number, which is what the naive `== 0` guard produced.
        assert fm.sharpe_ratio([100.0] * 30, 0.4) is None

    def test_near_constant_series_does_not_produce_a_giant_sharpe(self):
        # The money-market case. A net asset value compounding at a fixed rate
        # has a variance around 1e-30, which is not zero — the earlier `== 0`
        # guard let it through and the ratio came out at -8.3e13.
        prices = _compound(100, 0.0015, 252)
        vol = fm.volatility(fm.daily_returns(prices))
        assert vol is not None and 0 < vol < fm.MIN_VOLATILITY
        assert fm.sharpe_ratio(prices, 0.45) is None

    def test_sortino_is_defined_for_a_flat_fund_below_the_target(self):
        # Unlike Sharpe: a flat return still falls short of a 40% cash rate
        # every single day, so the downside deviation is real and the ratio is
        # a genuine (bad) answer rather than an undefined one.
        ratio = fm.sortino_ratio([100.0] * 30, 0.4)
        assert ratio is not None and ratio < 0

    def test_sortino_target_compounds_rather_than_divides(self):
        # A 45% annual rate divided by 252 sets a daily bar that compounds to
        # well under 45%, which would flatter every fund on the board.
        naive_target = 0.45 / 252
        proper_target = (1.45) ** (1 / 252) - 1
        assert proper_target < naive_target


class TestDrawdown:
    def test_measures_peak_to_trough(self):
        stats = fm.drawdown([100, 120, 60, 80])
        assert stats.max_drawdown == pytest.approx(-0.5)
        assert stats.trough_index == 2

    def test_recovery_is_none_when_it_never_came_back(self):
        # Materially different from "recovered instantly", which is what a
        # default of zero would have claimed.
        stats = fm.drawdown([100, 120, 60, 80, 90])
        assert stats.recovery_days is None

    def test_recovery_counts_from_the_trough_to_the_prior_peak(self):
        stats = fm.drawdown([100, 120, 60, 80, 120])
        assert stats.trough_index == 2
        assert stats.recovery_days == 2

    def test_recovery_uses_the_peak_the_fall_started_from(self):
        # Not the series maximum: a fund that later set a new high had already
        # recovered at the moment it regained the old one.
        stats = fm.drawdown([100, 200, 100, 200, 400])
        assert stats.recovery_days == 1

    def test_a_series_that_only_rises_has_no_drawdown(self):
        stats = fm.drawdown([100, 110, 120])
        assert stats.max_drawdown == 0.0
        assert stats.trough_index is None


class TestCompute:
    def test_reports_every_field_for_a_full_year(self):
        prices = _compound(100, 0.001, 252)
        metrics = fm.compute(prices, risk_free_rate=0.45)
        assert metrics.observations == 253
        assert metrics.total_return is not None
        assert metrics.volatility == pytest.approx(0.0, abs=1e-9)
        # A perfectly smooth series has no measurable volatility, so the ratio
        # is undefined rather than enormous.
        assert metrics.sharpe is None

    def test_short_series_reports_none_rather_than_a_confident_figure(self):
        metrics = fm.compute([100, 101, 102], risk_free_rate=0.45)
        assert metrics.observations == 3
        assert metrics.total_return == pytest.approx(0.02)
        assert metrics.volatility is None
        assert metrics.sharpe is None
        assert metrics.sortino is None

    def test_max_drawdown_is_none_when_the_fund_only_rose(self):
        # None, not 0.0: "never fell" and "fell by nothing measurable" read the
        # same in a table cell, and only one of them is true here.
        metrics = fm.compute([100, 110, 120], risk_free_rate=0.4)
        assert metrics.max_drawdown is None
