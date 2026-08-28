"""
Risk statistics for a fund's net asset value series.

Pure arithmetic, no I/O — which is the point. Every other module in this package
is a shape adapter over somebody else's JSON, and the numbers a reader actually
makes a decision on are computed here, where they can be pinned by a test.

Two things about the Turkish context shape the signatures:

**The risk-free rate is not a rounding error.** A Sharpe ratio computed against
zero is standard practice where the policy rate is 2%; against a TRY policy rate
in the tens of percent it is arithmetic that flatters every fund on the list. So
`risk_free_rate` is a required argument rather than a defaulted one. Passing the
wrong rate is a mistake; forgetting there is one is a category error, and the
signature refuses to let it happen silently.

**Nominal is not the answer.** These functions describe a series in the currency
it was quoted in. Turning that into what a holder actually earned is
`real_return.py`'s job, deliberately kept separate: a Sharpe ratio is about the
shape of a return stream, and inflation adjustment is about its meaning.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

# Borsa İstanbul trades roughly 250 days a year. 252 is the convention every
# published Sharpe figure uses, and matching it is what makes this number
# comparable to the ones a reader has seen elsewhere.
TRADING_DAYS_PER_YEAR = 252

# Below this many observations a standard deviation is noise wearing a number's
# clothes. Two trading weeks is the floor; anything shorter returns None rather
# than a confident-looking figure.
MIN_OBSERVATIONS = 10

# The floor below which an annualised standard deviation is floating-point
# noise rather than a measurement.
#
# Not a theoretical concern: a fund whose net asset value compounds at a near
# constant rate — which is exactly what the fifty money-market funds on this
# board do — produces a variance around 1e-30 and an annualised volatility
# around 1e-15. That is not zero, so an `== 0` guard lets it through, and
# dividing an excess return by it yields a Sharpe ratio of -8.3e13. A cell
# reading "-83,318,213,983,522" is not obviously wrong to a reader skimming a
# table; it is just a very large number, which is the worst way for this to
# fail.
MIN_VOLATILITY = 1e-9


@dataclass(frozen=True)
class DrawdownStats:
    """The worst peak-to-trough fall in a series, and how long it lasted."""

    max_drawdown: float
    """Depth as a negative fraction: -0.1123 is a fall of 11.23%."""

    trough_index: Optional[int]
    """Position of the low. None when the series never fell."""

    recovery_days: Optional[int]
    """
    Observations from the trough back to the prior peak.

    None means it had not recovered by the end of the series — which is a
    materially different statement from "recovered instantly", and the reason
    this is not defaulted to zero.
    """


@dataclass(frozen=True)
class FundMetrics:
    """
    Everything computable about one fund from its price series alone.

    Fields are Optional because a fund listed three weeks ago genuinely has no
    one-year volatility. Reporting one anyway is the failure this guards.
    """

    observations: int
    total_return: Optional[float]
    annualised_return: Optional[float]
    volatility: Optional[float]
    sharpe: Optional[float]
    sortino: Optional[float]
    calmar: Optional[float]
    max_drawdown: Optional[float]
    recovery_days: Optional[int]


def daily_returns(prices: Sequence[float]) -> list[float]:
    """
    Simple period-over-period returns.

    Non-positive prices are skipped rather than divided by: TEFAS occasionally
    carries a zero for a day a fund did not price, and letting that through
    produces an infinite return that then poisons every statistic downstream.
    """
    out: list[float] = []
    for previous, current in zip(prices, prices[1:]):
        if previous <= 0 or current <= 0:
            continue
        out.append(current / previous - 1)
    return out


def total_return(prices: Sequence[float]) -> Optional[float]:
    """Return over the whole series, as a fraction."""
    if len(prices) < 2 or prices[0] <= 0:
        return None
    return prices[-1] / prices[0] - 1


def annualised_return(
    prices: Sequence[float], observations_per_year: int = TRADING_DAYS_PER_YEAR
) -> Optional[float]:
    """
    Geometric annualised return.

    Geometric rather than the arithmetic mean of daily returns: a fund that
    falls 50% and then rises 50% has an arithmetic mean of zero and has lost a
    quarter of its holder's money.
    """
    total = total_return(prices)
    if total is None or total <= -1:
        return None
    periods = len(prices) - 1
    if periods <= 0:
        return None
    return (1 + total) ** (observations_per_year / periods) - 1


def volatility(
    returns: Sequence[float], observations_per_year: int = TRADING_DAYS_PER_YEAR
) -> Optional[float]:
    """Annualised standard deviation of returns, sample-corrected."""
    if len(returns) < MIN_OBSERVATIONS:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(observations_per_year)


def downside_deviation(
    returns: Sequence[float],
    target: float = 0.0,
    observations_per_year: int = TRADING_DAYS_PER_YEAR,
) -> Optional[float]:
    """
    Annualised deviation of the returns that fell below `target`.

    Divided by the full observation count, not by the number of shortfalls —
    that is the standard definition, and the alternative rewards a fund for
    having few bad days rather than for having shallow ones.
    """
    if len(returns) < MIN_OBSERVATIONS:
        return None
    shortfalls = [min(0.0, r - target) for r in returns]
    variance = sum(s**2 for s in shortfalls) / len(returns)
    return math.sqrt(variance) * math.sqrt(observations_per_year)


def sharpe_ratio(
    prices: Sequence[float],
    risk_free_rate: float,
    observations_per_year: int = TRADING_DAYS_PER_YEAR,
) -> Optional[float]:
    """
    Excess annualised return per unit of total volatility.

    `risk_free_rate` is an annual fraction — 0.42 for a 42% policy rate, which
    is the order of magnitude this function is actually used at.
    """
    returns = daily_returns(prices)
    vol = volatility(returns, observations_per_year)
    annual = annualised_return(prices, observations_per_year)
    if vol is None or annual is None or vol < MIN_VOLATILITY:
        return None
    return (annual - risk_free_rate) / vol


def sortino_ratio(
    prices: Sequence[float],
    risk_free_rate: float,
    observations_per_year: int = TRADING_DAYS_PER_YEAR,
) -> Optional[float]:
    """
    Excess annualised return per unit of *downside* volatility.

    The one a reader should look at second: Sharpe punishes a fund for rising
    sharply, and in a market that moves in steps rather than drifts, that is
    most of what it is measuring.
    """
    returns = daily_returns(prices)
    annual = annualised_return(prices, observations_per_year)
    if annual is None:
        return None
    # The daily target that compounds to the annual risk-free rate. Dividing the
    # annual rate by 252 would set the bar slightly too low every day and
    # noticeably too low at Turkish rates.
    daily_target = (1 + risk_free_rate) ** (1 / observations_per_year) - 1
    deviation = downside_deviation(returns, daily_target, observations_per_year)
    if deviation is None or deviation < MIN_VOLATILITY:
        return None
    return (annual - risk_free_rate) / deviation


def drawdown(prices: Sequence[float]) -> DrawdownStats:
    """Worst peak-to-trough fall, where it happened, and whether it came back."""
    if len(prices) < 2:
        return DrawdownStats(0.0, None, None)

    peak = prices[0]
    peak_index = 0
    worst = 0.0
    trough_index: Optional[int] = None
    worst_peak_index = 0

    for index, price in enumerate(prices):
        if price > peak:
            peak = price
            peak_index = index
        if peak <= 0:
            continue
        fall = price / peak - 1
        if fall < worst:
            worst = fall
            trough_index = index
            worst_peak_index = peak_index

    if trough_index is None:
        return DrawdownStats(0.0, None, None)

    # Recovery is measured against the peak the fall started from, not against
    # the series maximum: a fund that set a new high later has still recovered
    # at the moment it regained the old one.
    prior_peak = prices[worst_peak_index]
    recovery_days: Optional[int] = None
    for index in range(trough_index + 1, len(prices)):
        if prices[index] >= prior_peak:
            recovery_days = index - trough_index
            break

    return DrawdownStats(worst, trough_index, recovery_days)


def calmar_ratio(
    prices: Sequence[float],
    observations_per_year: int = TRADING_DAYS_PER_YEAR,
) -> Optional[float]:
    """
    Annualised return divided by the depth of the worst fall.

    No risk-free rate here, unlike Sharpe and Sortino: Calmar is conventionally
    quoted on the raw return, and quietly redefining it would make this number
    incomparable to every other Calmar a reader has seen.
    """
    annual = annualised_return(prices, observations_per_year)
    stats = drawdown(prices)
    if annual is None or stats.max_drawdown >= 0:
        return None
    return annual / abs(stats.max_drawdown)


def compute(
    prices: Sequence[float],
    risk_free_rate: float,
    observations_per_year: int = TRADING_DAYS_PER_YEAR,
) -> FundMetrics:
    """Every statistic for one series, in a single pass over the inputs."""
    stats = drawdown(prices)
    returns = daily_returns(prices)
    return FundMetrics(
        observations=len(prices),
        total_return=total_return(prices),
        annualised_return=annualised_return(prices, observations_per_year),
        volatility=volatility(returns, observations_per_year),
        sharpe=sharpe_ratio(prices, risk_free_rate, observations_per_year),
        sortino=sortino_ratio(prices, risk_free_rate, observations_per_year),
        calmar=calmar_ratio(prices, observations_per_year),
        max_drawdown=stats.max_drawdown if stats.trough_index is not None else None,
        recovery_days=stats.recovery_days,
    )
