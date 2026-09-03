"""
A fear-and-greed reading for Borsa İstanbul, and what dominates the board.

Both are computed from the equity board the overview already fetched — no new
upstream, no new health-registry category, and no figure that is not already on
some other panel of this realm. That constraint is the design: an index built
from a private feed would be a number nobody could check, and this one exists
precisely so a reader can check it.

The crypto index everyone knows leans on volatility, social volume and BTC
dominance. None of those has an honest Borsa İstanbul analogue — there is no
public social feed for a Turkish ticker and no single instrument whose share of
the market means what Bitcoin's does — so the components here are drawn from
what this exchange actually publishes, and one of them (the daily price limit)
has no equivalent anywhere else.

The components are grouped by the horizon they measure, and the index gives
each horizon the same weight rather than each component. The first version
weighted components equally, and three of its five were read off today's
change column — so a red morning after a green afternoon moved the index thirty
points, which is not a mood, it is a tape. A session is now one third of the
reading whatever it does; the rest is what the board did over the past weeks
and where it sits in its year, and those do not reset at 10:00.

Nothing here raises. A component that cannot be measured says so and is left out
of the average rather than defaulted to fifty, and a board too thin to measure
at all answers `None` — the same refusal `/api/price` makes rather than emitting
a plausible placeholder.
"""

from dataclasses import dataclass, replace
from statistics import median
from typing import Optional, Sequence

from services.bist.equity_service import SectorStat
from services.bist.tradingview_client import EquityRow

# Borsa İstanbul caps most shares at ten percent a session in either direction.
# The tolerance is for a quote that lands a hair inside the cap after rounding.
DAILY_LIMIT = 0.10
LIMIT_TOLERANCE = 0.995

# Below this the board is not a market, it is a handful of quotes.
MIN_MEASURED = 20

# A reading needs most of its components: four of nine is the floor at which
# the average still describes the board rather than whichever few survived.
MIN_COMPONENTS = 4

# And it needs more than one horizon. An index made only of today's tape is
# today's tape, and an index made only of the yearly range is a chart.
MIN_HORIZONS = 2

# Ordered from fastest to slowest. Each present horizon takes an equal share
# of the index, and the components inside a horizon share that share equally.
HORIZONS: tuple[tuple[str, str], ...] = (
    ("session", "Seans"),
    ("trend", "Trend"),
    ("year", "Yıl"),
)
HORIZON_LABEL: dict[str, str] = dict(HORIZONS)


@dataclass(frozen=True)
class Component:
    """One input to the index, already scored and already explained."""

    key: str
    label: str
    """Turkish, because every surface that renders this is Turkish."""
    score: float
    """0 = maximum fear, 100 = maximum greed."""
    reading: str
    """What was measured, in the units it was measured in."""
    horizon: str
    """`session`, `trend` or `year` — which share of the index it competes for."""
    weight: float = 0.0
    """Share of the index, assigned when the index is assembled. Sums to one."""


@dataclass(frozen=True)
class Sentiment:
    score: int
    label: str
    components: list[Component]
    measured: int
    """Shares that contributed to at least one component."""


@dataclass(frozen=True)
class Dominance:
    """What moves the index whether or not the rest of the board agrees."""

    sector: Optional[str]
    sector_weight: Optional[float]
    sector_change_pct: Optional[float]
    """The largest sector's own capitalisation-weighted move, as a fraction."""
    top_ticker: Optional[str]
    top_turnover_share: Optional[float]
    top5_turnover_share: Optional[float]


# ── Scoring helpers ──────────────────────────────────────────────────────────


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return low if value < low else high if value > high else value


def _scale(value: float, low: float, high: float) -> float:
    """Map `value` from [low, high] onto [0, 100], clamped at both ends."""
    if high == low:
        return 50.0
    return _clamp((value - low) / (high - low) * 100.0)


def _finite(values: Sequence[Optional[float]]) -> list[float]:
    return [v for v in values if isinstance(v, (int, float)) and v == v]


def _pct(value: float) -> str:
    """A fraction as a Turkish percentage — the surface's own convention."""
    return f"%{value * 100:.1f}".replace(".", ",")


def _ratio(value: float) -> str:
    """A multiple, with the Turkish decimal comma. `1.4` renders as `1,4`."""
    return f"{value:.1f}".replace(".", ",")


def _share_up(values: Sequence[Optional[float]]) -> tuple[int, int]:
    """Advancers and decliners over whatever horizon `values` was measured on."""
    finite = _finite(values)
    up = sum(1 for v in finite if v > 0)
    down = sum(1 for v in finite if v < 0)
    return up, down


# ── Components: the session ──────────────────────────────────────────────────


def breadth_component(rows: Sequence[EquityRow]) -> Optional[Component]:
    """How much of the board is up. The plainest reading there is."""
    up = sum(1 for row in rows if (row.change_pct or 0) > 0)
    down = sum(1 for row in rows if (row.change_pct or 0) < 0)
    moved = up + down
    if moved == 0:
        return None
    share = up / moved
    return Component(
        key="breadth",
        label="Piyasa genişliği",
        score=share * 100.0,
        reading=f"{up} yükselen / {down} düşen",
        horizon="session",
    )


def limit_component(rows: Sequence[EquityRow]) -> Component:
    """
    Shares pinned at the daily limit, both ways.

    This one has no analogue on an unbounded market and it is the sharpest
    signal here: a session with thirty limit-downs and no limit-ups is not a
    market drifting lower, it is one where sellers could not find a price. A
    session with neither is genuinely neutral rather than unmeasured, which is
    why this component never returns None.
    """
    floor = DAILY_LIMIT * LIMIT_TOLERANCE
    up = sum(1 for row in rows if (row.change_pct or 0) >= floor)
    down = sum(1 for row in rows if (row.change_pct or 0) <= -floor)
    total = up + down

    if total == 0:
        return Component(
            key="limit",
            label="Tavan / taban",
            score=50.0,
            reading="limit hareketi yok",
            horizon="session",
        )

    return Component(
        key="limit",
        label="Tavan / taban",
        score=(up / total) * 100.0,
        reading=f"{up} tavan / {down} taban",
        horizon="session",
    )


def flow_component(rows: Sequence[EquityRow]) -> Optional[Component]:
    """
    Which side of the market the volume is on.

    Breadth counts shares; this weighs them. Turnover running above average on
    the risers and below it on the fallers is a different session from the same
    advance-decline line with the volume the other way round, and the difference
    is the one thing breadth alone cannot say.
    """
    up = _finite([row.relative_volume for row in rows if (row.change_pct or 0) > 0])
    down = _finite([row.relative_volume for row in rows if (row.change_pct or 0) < 0])
    if len(up) < 5 or len(down) < 5:
        return None

    up_median, down_median = median(up), median(down)
    total = up_median + down_median
    if total <= 0:
        return None

    tilt = (up_median - down_median) / total
    return Component(
        key="flow",
        label="Para akışı",
        score=_clamp(50.0 + tilt * 50.0),
        reading=f"yükselende {_ratio(up_median)}× / düşende {_ratio(down_median)}× hacim",
        horizon="session",
    )


# ── Components: the trend ────────────────────────────────────────────────────


def _period_breadth(
    values: Sequence[Optional[float]], *, key: str, label: str, period: str
) -> Optional[Component]:
    """
    Breadth over a longer window than today.

    Same arithmetic as the session's advance-decline line, read off a column
    that does not reset every morning. A board where most names are up on the
    week is in a different mood from one where most are down, whatever today's
    tape says — and it stays in that mood for more than a session.
    """
    up, down = _share_up(values)
    moved = up + down
    if moved < MIN_MEASURED:
        return None
    return Component(
        key=key,
        label=label,
        score=(up / moved) * 100.0,
        reading=f"{period} {up} yükselen / {down} düşen",
        horizon="trend",
    )


def weekly_breadth_component(rows: Sequence[EquityRow]) -> Optional[Component]:
    return _period_breadth(
        [row.perf_1w for row in rows],
        key="breadth_1w",
        label="Haftalık genişlik",
        period="haftalık",
    )


def monthly_breadth_component(rows: Sequence[EquityRow]) -> Optional[Component]:
    return _period_breadth(
        [row.perf_1m for row in rows],
        key="breadth_1m",
        label="Aylık genişlik",
        period="aylık",
    )


def _above_average(
    rows: Sequence[EquityRow], *, average: str, key: str, label: str, days: int, horizon: str
) -> Optional[Component]:
    """
    Share of the board trading above one of its own moving averages.

    The oldest trend-participation measure there is, and self-calibrating: a
    share is either above its average or it is not, so the score needs no band
    that somebody would have to justify. A quote equal to its average counts
    as below — a board sitting exactly on the line has not broken out.
    """
    above = below = 0
    for row in rows:
        level = getattr(row, average)
        if row.price is None or level is None or level <= 0:
            continue
        if row.price > level:
            above += 1
        else:
            below += 1
    measured = above + below
    if measured < MIN_MEASURED:
        return None
    return Component(
        key=key,
        label=label,
        score=(above / measured) * 100.0,
        reading=f"{above} hisse {days} günlük ortalamanın üstünde / {below} altında",
        horizon=horizon,
    )


def trend_component(rows: Sequence[EquityRow]) -> Optional[Component]:
    return _above_average(
        rows,
        average="sma50",
        key="above_sma50",
        label="50 günlük ortalamanın üstündekiler",
        days=50,
        horizon="trend",
    )


def momentum_component(rows: Sequence[EquityRow]) -> Optional[Component]:
    """
    The board's median RSI. Fourteen sessions, so it belongs to the trend.

    Median rather than mean: a handful of shares pinned at 90 after a bid pulls
    an average far enough to describe a market that is not there. The band is
    the conventional 30–70, so a median of 50 scores 50 and the two ends of the
    index line up with the two ends of the indicator a reader already knows.
    """
    values = _finite([row.rsi for row in rows])
    if len(values) < MIN_MEASURED:
        return None
    mid = median(values)
    return Component(
        key="momentum",
        label="Momentum",
        score=_scale(mid, 30.0, 70.0),
        reading=f"medyan RSI {mid:.0f}",
        horizon="trend",
    )


# ── Components: the year ─────────────────────────────────────────────────────


def long_trend_component(rows: Sequence[EquityRow]) -> Optional[Component]:
    """
    The two-hundred-day line, which on this exchange is most of a year.

    Sits beside the 52-week position rather than beside the 50-day average
    because it answers the year's question — is the board still in the move it
    made — and not the month's.
    """
    return _above_average(
        rows,
        average="sma200",
        key="above_sma200",
        label="200 günlük ortalamanın üstündekiler",
        days=200,
        horizon="year",
    )


def range_component(rows: Sequence[EquityRow]) -> Optional[Component]:
    """
    Where the board sits inside its own year.

    A share trading at its 52-week high scores 100 and one at its low scores 0.
    Prices outside the band they were measured against are dropped rather than
    clamped — that is almost always an unadjusted capital action, and clamping
    it would add a fake extreme to the median.
    """
    positions: list[float] = []
    for row in rows:
        price, low, high = row.price, row.week52_low, row.week52_high
        if price is None or low is None or high is None:
            continue
        if not (high > low) or price < low or price > high:
            continue
        positions.append((price - low) / (high - low))

    if len(positions) < MIN_MEASURED:
        return None
    mid = median(positions)
    return Component(
        key="range",
        label="Yıllık aralıktaki konum",
        score=mid * 100.0,
        reading=f"medyan {_pct(mid)} noktasında",
        horizon="year",
    )


# ── Bands ────────────────────────────────────────────────────────────────────

# Upper bound, inclusive, and the word for everything at or below it.
BANDS: tuple[tuple[int, str], ...] = (
    (24, "Aşırı korku"),
    (44, "Korku"),
    (55, "Nötr"),
    (75, "Açgözlülük"),
    (100, "Aşırı açgözlülük"),
)


def band_label(score: int) -> str:
    for ceiling, label in BANDS:
        if score <= ceiling:
            return label
    return BANDS[-1][1]


# ── Entry points ─────────────────────────────────────────────────────────────


def _weighted(components: Sequence[Component]) -> list[Component]:
    """
    Hand out the index's weight: equal per horizon, then equal within it.

    Equal weights *per horizon* rather than per component, on purpose. A
    weighting between components would have to come from somewhere — a
    backtest this project has no ground truth for, or a preference dressed as
    one. A weighting between horizons needs no backtest: it is the statement
    that what the board did today, what it did this month and where it sits in
    its year are three questions of the same size, and that one of them is not
    allowed to answer for the other two. It also happens to be what stops the
    index swinging with every session.
    """
    present = [code for code, _ in HORIZONS if any(c.horizon == code for c in components)]
    per_horizon = 1.0 / len(present)
    weighted: list[Component] = []
    for code in present:
        members = [c for c in components if c.horizon == code]
        share = per_horizon / len(members)
        weighted.extend(replace(c, weight=share) for c in members)
    return weighted


def compute_sentiment(rows: Sequence[EquityRow]) -> Optional[Sentiment]:
    """The index, or nothing."""
    if len(rows) < MIN_MEASURED:
        return None

    candidates = [
        # Today.
        breadth_component(rows),
        limit_component(rows),
        flow_component(rows),
        # The past weeks.
        weekly_breadth_component(rows),
        monthly_breadth_component(rows),
        trend_component(rows),
        momentum_component(rows),
        # The year.
        range_component(rows),
        long_trend_component(rows),
    ]
    components = [c for c in candidates if c is not None]
    if len(components) < MIN_COMPONENTS:
        return None
    if len({c.horizon for c in components}) < MIN_HORIZONS:
        return None

    components = _weighted(components)
    score = int(_clamp(round(sum(c.score * c.weight for c in components))))

    return Sentiment(
        score=score,
        label=band_label(score),
        components=components,
        measured=len(rows),
    )


def compute_dominance(rows: Sequence[EquityRow], sectors: Sequence[SectorStat]) -> Dominance:
    """
    What carries the index.

    Two readings, because they answer different questions. The largest sector's
    share of capitalisation is structural — on this exchange banks are a third
    of the market, so the index cannot go far against them. Turnover
    concentration is today's: when one name is a fifth of the session's money,
    the tape is about that name rather than about the market.
    """
    largest = sectors[0] if sectors else None

    traded = sorted(
        ((row.ticker, row.traded_value) for row in rows if row.traded_value),
        key=lambda pair: pair[1],
        reverse=True,
    )
    total_traded = sum(value for _, value in traded)

    top_ticker = traded[0][0] if traded else None
    top_share = (traded[0][1] / total_traded) if traded and total_traded > 0 else None
    top5_share = (
        sum(value for _, value in traded[:5]) / total_traded
        if traded and total_traded > 0
        else None
    )

    return Dominance(
        sector=largest.sector if largest else None,
        sector_weight=largest.weight if largest else None,
        sector_change_pct=largest.change_pct if largest else None,
        top_ticker=top_ticker,
        top_turnover_share=top_share,
        top5_turnover_share=top5_share,
    )
