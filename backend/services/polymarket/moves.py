"""
When a market changed its mind — the windows worth looking for news in.

This is the mechanism behind "why was this bet opened". A market's price history
is the only record of *when* the crowd re-priced something, and a timestamp is
what turns an open-ended question ("why does this market exist?") into a
searchable one ("what broke on the afternoon of 14 March?"). The dates this
emits are not guesses; they are the timestamps of measured moves.

Three decisions here are load-bearing.

**Deltas are absolute probability points, never percentages.** A move from 0.02
to 0.04 is a 100% rise and means almost nothing — it is two cents of noise on a
market nobody believes. A move from 0.45 to 0.62 is seventeen points and is the
one that had a cause. Ranking by percentage puts every long shot above every
real event, which is precisely backwards.

**A move must be large in its own terms and unusual for this market.** The
absolute floor alone flags nothing on a quiet market and everything on a
volatile one. Requiring the move to also stand well clear of the market's own
median lets a normally-flat question surface a nine-point shift while stopping a
question that swings all day from offering three meaningless "spikes".

**Creation is always a window.** Even on a perfectly flat tape the market was
opened by somebody, at a moment, for a reason — so the search stage always has
at least one place to look. A market that never moved is not a market with no
story; it is usually a market whose story was told before it opened.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from models.polymarket import PricePoint, SharpMove

#: Smallest move worth explaining, in probability points. Below eight points a
#: prediction market is mostly absorbing order flow, and the news search would
#: be reading tea leaves.
MIN_DELTA = 0.08

#: How far above the market's own median move a candidate must sit. Three is
#: high enough that ordinary churn never qualifies and low enough that a genuine
#: repricing on an already-jumpy market still does.
MEDIAN_MULTIPLE = 3.0

#: Width of the window a move is measured over.
WINDOW_HOURS = 6

#: Minimum gap between two reported moves. Without it a single event produces a
#: cluster of overlapping windows that all describe the same afternoon, and the
#: search stage spends its budget asking the same question three times.
MIN_SEPARATION_HOURS = 24

#: How long after creation to treat as the opening window. Long enough to catch
#: the story a market was written in response to, short enough not to swallow
#: the first week of unrelated news.
CREATION_WINDOW_HOURS = 48

MAX_MOVES = 3


def _clean(history: list[PricePoint]) -> list[PricePoint]:
    """Sorted, one point per timestamp. Later readings win a collision."""
    by_time: dict[datetime, float] = {}
    for point in history:
        by_time[point.t] = point.p
    return [PricePoint(t=t, p=by_time[t]) for t in sorted(by_time)]


def detect_sharp_moves(
    history: list[PricePoint],
    created_at: datetime | None,
    *,
    fidelity_minutes: int = 60,
    outcome_label: str | None = None,
    max_moves: int = MAX_MOVES,
) -> list[SharpMove]:
    """
    The windows this market re-priced in, plus the window it opened in.

    Pure: no clock, no network. `history` may be empty, unsorted or duplicated.
    """
    moves: list[SharpMove] = []

    points = _clean(history)
    span = max(1, round(WINDOW_HOURS * 60 / max(1, fidelity_minutes)))

    if len(points) > span:
        deltas = [(points[i + span].p - points[i].p, i) for i in range(len(points) - span)]
        magnitudes = [abs(d) for d, _ in deltas]
        # A flat market has a median of zero, which makes the relative test
        # vacuous and leaves MIN_DELTA governing on its own. That is the
        # intended reading: on a market that never moves, any real move is
        # unusual by definition.
        threshold = max(MIN_DELTA, median(magnitudes) * MEDIAN_MULTIPLE)

        candidates = sorted(
            (d for d in deltas if abs(d[0]) >= threshold),
            key=lambda d: abs(d[0]),
            reverse=True,
        )

        separation = timedelta(hours=MIN_SEPARATION_HOURS)
        chosen: list[tuple[float, int]] = []
        for delta, i in candidates:
            start = points[i].t
            # Greedy non-maximum suppression: the biggest move in a
            # neighbourhood is the one that gets reported, and everything
            # within a day of it is treated as the same event.
            if any(abs(start - points[j].t) < separation for _, j in chosen):
                continue
            chosen.append((delta, i))
            if len(chosen) >= max_moves:
                break

        for delta, i in sorted(chosen, key=lambda c: points[c[1]].t, reverse=True):
            moves.append(
                SharpMove(
                    kind="spike",
                    started_at=points[i].t,
                    ended_at=points[i + span].t,
                    price_from=round(points[i].p, 4),
                    price_to=round(points[i + span].p, 4),
                    delta=round(delta, 4),
                    outcome_label=outcome_label,
                )
            )

    if created_at is not None:
        moves.append(
            SharpMove(
                kind="creation",
                started_at=created_at,
                ended_at=created_at + timedelta(hours=CREATION_WINDOW_HOURS),
                outcome_label=outcome_label,
            )
        )

    return moves
