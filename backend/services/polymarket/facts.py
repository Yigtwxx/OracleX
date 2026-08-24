"""
Everything about a market that needed no model to establish.

This stage is what makes an honest refusal affordable. It runs before any
search and without the LLM, so when the evidence sweep comes back empty the page
still shows odds, drift, concentration and the timeline of moves — and "no
verdict could be written" lands as a statement about the evidence rather than as
a broken page.

**Partial results survive here, by construction.** The obvious implementation —
one `asyncio.gather` inside one `asyncio.wait_for` — cancels every child the
moment the deadline passes, so four successful fetches and one slow one produce
nothing at all. That is survivable for an eight-second news gather where the
whole set is optional. It is not survivable here, where the point of the stage
is to hand the next one whatever could be read. `asyncio.wait` is used instead
and the `done` set is harvested; anything still pending is cancelled and
recorded as a named gap.

A gap is named rather than omitted. "No holder table was available" and "this
market has no concentrated holders" are opposite readings of the same blank
space, and only one of them is true at a time.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from models.polymarket import MarketFacts, Microstructure
from services.polymarket import clob, data_api, gamma, microstructure
from services.polymarket.moves import detect_sharp_moves
from services.polymarket.registry import HISTORY_FIDELITY_MINUTES

logger = logging.getLogger(__name__)

#: Ceiling for the whole stage. Each upstream already carries a tighter
#: per-call timeout, so reaching this means more than one of them stalled.
FACTS_BUDGET_SECONDS = 12.0

#: How many recent trades the activity histogram reads. Enough to see a daily
#: shape; far below the upstream's 10,000 cap, because the histogram gets no
#: sharper past a few hundred and every extra page costs the stage its budget.
TRADE_SAMPLE = 300


class MarketUnavailable(RuntimeError):
    """The market could not be read at all — not a thin market, an unread one."""


async def _named(name: str, coro):
    """Tag a result with its source so a gap can be named after it."""
    return name, await coro


async def gather_facts(
    raw: dict[str, Any],
    *,
    include_trades: bool = False,
) -> tuple[MarketFacts, Microstructure]:
    """
    Resolve one market's facts. Raises `MarketUnavailable` if it cannot be read.

    `include_trades` is off for the board and on for the detail view: the trade
    tape is only needed by the activity histogram, and fetching it for sixty
    rows would triple the board's upstream cost for a panel nobody is looking at.
    """
    market = gamma.parse_market(raw)
    if market is None or not market.outcomes:
        raise MarketUnavailable("market metadata could not be parsed")

    condition_id = str(raw.get("conditionId") or "").strip()
    leading = max(
        (o for o in market.outcomes if o.price is not None),
        key=lambda o: o.price or 0.0,
        default=market.outcomes[0],
    )

    tasks: dict[str, asyncio.Task] = {}
    if leading.token_id:
        tasks["price history"] = asyncio.create_task(
            _named("history", clob.fetch_history(leading.token_id))
        )
    if condition_id:
        tasks["holder table"] = asyncio.create_task(
            _named(
                "holders", data_api.fetch_holders(condition_id, [o.label for o in market.outcomes])
            )
        )
        if include_trades:
            tasks["trade tape"] = asyncio.create_task(
                _named("trades", data_api.fetch_trades(condition_id, TRADE_SAMPLE))
            )

    results: dict[str, Any] = {}
    unavailable: list[str] = []

    if tasks:
        done, pending = await asyncio.wait(
            tasks.values(), timeout=FACTS_BUDGET_SECONDS, return_when=asyncio.ALL_COMPLETED
        )
        for task in pending:
            task.cancel()

        finished = set()
        for task in done:
            try:
                key, value = task.result()
                results[key] = value
                finished.add(task)
            except Exception as error:  # noqa: BLE001 — one dead upstream is a gap
                logger.warning("Polymarket fact fetch failed: %s", error)

        for label, task in tasks.items():
            if task in pending:
                unavailable.append(f"{label} timed out")
            elif task not in finished:
                unavailable.append(f"{label} could not be read")

    if not leading.token_id:
        unavailable.append("price history has no token id on this market")
    if not condition_id:
        unavailable.append("holder table has no condition id on this market")

    history = results.get("history") or []
    moves = detect_sharp_moves(
        history,
        market.created_at,
        fidelity_minutes=HISTORY_FIDELITY_MINUTES,
        outcome_label=leading.label,
    )

    facts = MarketFacts(
        market=market,
        resolution_criteria=(str(raw.get("description") or "").strip() or None),
        history=history,
        moves=moves,
        holders=results.get("holders") or [],
        unavailable=unavailable,
    )

    spread = gamma.as_float(raw.get("spread"))
    return facts, microstructure.summarise(facts, spread=spread)


def trade_activity_hours(trades: list[dict[str, Any]]) -> dict[int, float]:
    """
    Traded value by UTC hour of day.

    This is the input to the map's third layer, and the layer is labelled an
    estimate for a reason that belongs next to the code producing it: a trading
    hour is a real measurement of when money moved, and says almost nothing
    about where it moved from. A UTC+1 cluster spans a dozen countries, and
    prediction-market flow is disproportionately nocturnal and bot-assisted,
    which smears it further. Weighted by size rather than count so one wallet
    clicking two hundred times does not outvote a real position.
    """

    buckets: dict[int, float] = dict.fromkeys(range(24), 0.0)
    for trade in trades:
        stamp, size = trade.get("timestamp"), trade.get("size")
        if stamp is None:
            continue
        try:
            hour = datetime.fromtimestamp(int(stamp), tz=UTC).hour
            price = float(trade.get("price") or 0.0)
            buckets[hour] += abs(float(size or 0.0)) * price
        except (TypeError, ValueError, OSError, OverflowError):
            continue
    return buckets
