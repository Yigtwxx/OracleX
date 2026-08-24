"""
What the book and the holder table say, before any news is read.

This is the half of the analysis that needs no model and no internet beyond the
market itself, which is what makes an honest refusal affordable: when the
evidence sweep comes back empty the page still has something true to show, and
"we could not judge this" does not have to arrive on an empty screen.

The reading that matters most is concentration. A price of 0.62 set by four
hundred wallets and the same price set by one wallet that bought the book are
identical numbers and different facts. `top_holder_share` is the only place that
difference is visible, and it is the difference between a crowd's estimate and
one trader's position.

Every field is None rather than 0 when it could not be read. A market with no
spread and a market whose book failed to load must not render alike — the first
is a fact about the market and the second is a fact about us.
"""

from __future__ import annotations

from datetime import timedelta

from models.polymarket import Holder, MarketFacts, Microstructure, PricePoint

#: How concentrated the top holder has to be before it is worth saying out loud.
CONCENTRATION_NOTE_THRESHOLD = 0.35

#: Below this a spread is ordinary; above it, the quoted price is a wide guess
#: and treating it as a probability overstates how much anyone agreed on.
WIDE_SPREAD = 0.05


def _price_at_or_before(history: list[PricePoint], target) -> float | None:
    """The last reading no later than `target`, or None if the series is younger."""
    candidate = None
    for point in history:
        if point.t <= target:
            candidate = point.p
        else:
            break
    return candidate


def _drift(history: list[PricePoint], hours: int) -> float | None:
    """
    Change in price over the trailing window, in points.

    Anchored to the series' own last timestamp rather than to the wall clock, so
    a market whose history stops updating reports no drift instead of appearing
    to hold perfectly steady through a gap in our data.
    """
    if len(history) < 2:
        return None
    latest = history[-1]
    earlier = _price_at_or_before(history, latest.t - timedelta(hours=hours))
    if earlier is None:
        return None
    return round(latest.p - earlier, 4)


def _concentration(
    holders: list[Holder], outcome_label: str | None
) -> tuple[float | None, float | None]:
    """
    Share of the visible holder table held by the largest wallet, and by five.

    Computed within one outcome. Pooling both sides would divide a Yes holder's
    stake by the total of two opposing books, which is not a share of anything.
    """
    if not holders:
        return None, None

    side = [h for h in holders if h.outcome_label == outcome_label] if outcome_label else holders
    amounts = sorted((h.shares or 0.0 for h in side), reverse=True)
    total = sum(amounts)
    if not total:
        return None, None

    return round(amounts[0] / total, 4), round(sum(amounts[:5]) / total, 4)


def summarise(
    facts: MarketFacts,
    *,
    spread: float | None = None,
) -> Microstructure:
    """
    Read the market's own state. Pure: no clock, no network.

    `spread` comes from Gamma's market object rather than a separate order-book
    call — the field is already on the payload the board fetched, and a second
    round trip per market to re-derive it would cost the board its refresh rate.
    """
    outcomes = facts.market.outcomes
    priced = [o for o in outcomes if o.price is not None]
    leader = max(priced, key=lambda o: o.price or 0.0) if priced else None

    top1, top5 = _concentration(facts.holders, leader.label if leader else None)

    notes: list[str] = []
    if top1 is not None and top1 >= CONCENTRATION_NOTE_THRESHOLD:
        notes.append(
            f"One wallet holds {top1:.0%} of the visible position on "
            f"{leader.label if leader else 'the leading outcome'} — this price is "
            "closer to one trader's view than to a crowd's."
        )
    if spread is not None and spread >= WIDE_SPREAD:
        notes.append(
            f"The book is wide ({spread:.2f}); the quoted price is a rough "
            "midpoint rather than a level anyone is transacting at."
        )
    if not facts.holders:
        notes.append("No holder table was available, so concentration is unknown.")

    return Microstructure(
        leading_outcome=leader.label if leader else None,
        leading_price=leader.price if leader else None,
        drift_24h=_drift(facts.history, 24),
        drift_7d=_drift(facts.history, 24 * 7),
        spread=spread,
        liquidity_usd=facts.market.liquidity_usd,
        volume_usd=facts.market.volume_usd,
        top_holder_share=top1,
        top5_holder_share=top5,
        notes=notes,
    )


def render_facts_block(facts: MarketFacts, micro: Microstructure) -> str:
    """
    The market's numbers as the prompt sees them.

    This string is also the authority `attribution.verify_market_claim` checks
    MARKET-sourced claims against, so the two must be built from the same
    values — a figure formatted differently here than it is checked there would
    let a true claim be deleted as invented.
    """
    lines = [f"Question: {facts.market.question}"]
    if facts.resolution_criteria:
        lines.append(f"Resolves: {facts.resolution_criteria}")
    if facts.market.end_date:
        lines.append(f"Closes: {facts.market.end_date:%Y-%m-%d}")

    for outcome in facts.market.outcomes:
        price = f"{outcome.price:.4f}" if outcome.price is not None else "unknown"
        lines.append(f"Outcome {outcome.label}: {price}")

    def row(label: str, value, fmt: str = "") -> None:
        if value is not None:
            lines.append(f"{label}: {value:{fmt}}" if fmt else f"{label}: {value}")

    row("Volume USD", micro.volume_usd, ",.0f")
    row("Liquidity USD", micro.liquidity_usd, ",.0f")
    row("Spread", micro.spread, ".4f")
    row("Drift 24h (points)", micro.drift_24h, "+.4f")
    row("Drift 7d (points)", micro.drift_7d, "+.4f")
    row("Top holder share", micro.top_holder_share, ".4f")
    row("Top five holder share", micro.top5_holder_share, ".4f")

    for move in facts.moves:
        if move.kind == "spike" and move.delta is not None:
            lines.append(
                f"Sharp move {move.started_at:%Y-%m-%d %H:%M}Z: "
                f"{move.price_from:.4f} to {move.price_to:.4f} ({move.delta:+.4f})"
            )
        else:
            lines.append(f"Market opened {move.started_at:%Y-%m-%d %H:%M}Z")

    for gap in facts.unavailable:
        lines.append(f"Unavailable: {gap}")

    return "\n".join(lines)
