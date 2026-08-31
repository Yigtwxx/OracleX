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

Nothing here raises. A component that cannot be measured says so and is left out
of the average rather than defaulted to fifty, and a board too thin to measure
at all answers `None` — the same refusal `/api/price` makes rather than emitting
a plausible placeholder.
"""

from dataclasses import dataclass
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

# A reading needs most of its components; three of five is the floor at which
# the average still describes the board rather than whichever two survived.
MIN_COMPONENTS = 3


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
    weight: float


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


# ── Components ───────────────────────────────────────────────────────────────


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
        weight=1.0,
    )


def momentum_component(rows: Sequence[EquityRow]) -> Optional[Component]:
    """
    The board's median RSI.

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
        weight=1.0,
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
        weight=1.0,
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
            weight=1.0,
        )

    return Component(
        key="limit",
        label="Tavan / taban",
        score=(up / total) * 100.0,
        reading=f"{up} tavan / {down} taban",
        weight=1.0,
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
        weight=1.0,
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


def compute_sentiment(rows: Sequence[EquityRow]) -> Optional[Sentiment]:
    """
    The index, or nothing.

    Equal weights on purpose. A weighting would have to come from somewhere —
    a backtest this project has no ground truth for, or a preference dressed as
    one — and an unexplainable weight in a number whose whole claim is that the
    reader can check it would be the wrong trade.
    """
    if len(rows) < MIN_MEASURED:
        return None

    candidates = [
        breadth_component(rows),
        momentum_component(rows),
        range_component(rows),
        limit_component(rows),
        flow_component(rows),
    ]
    components = [c for c in candidates if c is not None]
    if len(components) < MIN_COMPONENTS:
        return None

    total_weight = sum(c.weight for c in components)
    score = round(sum(c.score * c.weight for c in components) / total_weight)
    score = int(_clamp(score))

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
