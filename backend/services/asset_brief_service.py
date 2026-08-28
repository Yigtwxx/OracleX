"""
One asset, everything the Home board needs to say about it today.

This is a composer, not a source: price, candles, the technical read and funding
all already exist as services, and every one of them is reachable on its own.
What did not exist was a single answer to "what is going on with this symbol",
and building that in the browser meant four round-trips whose failures the page
then had to reconcile one by one.

Two decisions are worth recording.

**The symbol is resolved once, here.** `price_service.is_crypto_symbol` and the
technical router each carry their own inline heuristic — a `USDT` suffix, an
exchange prefix — and they do not agree at the edges. A brief that resolved
twice could price the OKX tokenised AAPL perp and then draw NASDAQ levels under
it, which is the exact failure `CLAUDE.md` warns about. So `resolve` runs first
and the venue-qualified symbol it returns is what every downstream call sees.

**Only the price is load-bearing.** A missing RSI costs the card a badge; a
missing price would make every other figure on it meaningless. So an unresolvable
symbol or an unanswerable price is a 404, and everything else degrades to null —
which the card renders as an absent reading rather than a zero.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Optional

from services import symbol_detection_service
from services.ai_notes import NoteSpec, get_note

logger = logging.getLogger(__name__)

# A week of hourly closes. Long enough for the sparkline to have a shape and for
# the 7d change to mean something; short enough that the card is not drawing a
# trend the reader did not ask about.
CRYPTO_SPARK_HOURS = 168
CRYPTO_SPARK_INTERVAL = "1h"

# Daily bars for equities — an hourly series would be mostly closed-market gaps.
EQUITY_SPARK_DAYS = 30

# The window a "is today busy" reading is measured against. Thirty sessions is
# roughly six trading weeks, which smooths earnings without burying it.
EQUITY_VOLUME_WINDOW = 30

# Liquidation clusters kept per side. Three is what fits the card without the
# bars becoming a chart the reader has to study; past that they are levels
# nobody would reach before the book has been rebuilt anyway.
LIQUIDITY_CLUSTERS_PER_SIDE = 3

# Bins either side of a chosen peak that are folded into it. The model deposits
# one entry per leverage tier per bin, so a single wall lands as three or four
# adjacent bins — picking the top three bins without this would return the same
# wall three times and call it three levels.
LIQUIDITY_MERGE_RADIUS = 2

# How many points the sparkline keeps. The card is ~180px wide, so more than
# this is drawing detail no one can see and shipping bytes no one reads.
SPARK_POINTS = 48

NOTE_SPEC = NoteSpec(
    kind="asset_brief",
    prompt="notes/asset_brief",
    # Two or three sentences. The card has room for a paragraph and no more, and
    # a longer note would push the numbers it is explaining off the card.
    max_tokens=180,
    temperature=0.2,
    # The fingerprint retires the note whenever any quantized fact moves, which
    # on an active symbol is well inside a day. This only covers the quiet case:
    # a symbol that has not crossed a bucket boundary since yesterday should not
    # still be described in yesterday's words.
    max_age_seconds=6 * 3600,
)


class SymbolNotFound(Exception):
    """The candidate resolved to nothing, or nothing could price it."""


# ── Fact helpers ─────────────────────────────────────────────────────────────


def _closes(candles: list[dict[str, Any]]) -> list[float]:
    """Closing prices, oldest first, from whichever candle shape arrived."""
    out: list[float] = []
    for candle in candles:
        close = candle.get("close") if isinstance(candle, dict) else None
        if isinstance(close, (int, float)) and close > 0:
            out.append(float(close))
    return out


def _downsample(values: list[float], points: int = SPARK_POINTS) -> list[float]:
    """
    Thin a series to at most `points`, always keeping the last value.

    The last point is the one the card's price label sits next to, so a
    downsample that dropped it would draw a line ending somewhere the headline
    number is not.
    """
    if len(values) <= points:
        return values
    step = len(values) / points
    thinned = [values[int(i * step)] for i in range(points)]
    thinned[-1] = values[-1]
    return thinned


def _change_over(closes: list[float], span: int) -> Optional[float]:
    """Percent change across the last `span` points, or None without the history."""
    if len(closes) <= span:
        return None
    first, last = closes[-span - 1], closes[-1]
    if first <= 0:
        return None
    return (last - first) / first * 100


def _zone_mid(analysis: Optional[dict[str, Any]], side: str) -> Optional[float]:
    """
    The nearest support or resistance band's midpoint.

    Reads `zones`, not the formatted `*_levels` strings — those are display
    text ("$64,200 – $64,900") and parsing them back into a number would be
    reconstructing something this payload already carries.
    """
    if not analysis:
        return None
    zones = (analysis.get("zones") or {}).get(side) or []
    for zone in zones:
        mid = zone.get("mid")
        if isinstance(mid, (int, float)):
            return float(mid)
    return None


def _numeric(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) else None


# ── Per-asset-class collection ───────────────────────────────────────────────


def _liquidity(profile: Any, price: float) -> Optional[dict[str, Any]]:
    """
    The standing liquidation book reduced to the few walls worth naming.

    The profile is one entry per `[bin, tier, side, notional]` — several hundred
    of them — and the card has room for a handful of bars. So bins are summed
    across leverage tiers, the tallest are taken per side, and each one absorbs
    its neighbours: the model deposits the same wall once per tier, so adjacent
    bins are one level seen four times rather than four levels.

    Returns None rather than an empty book when the simulation had no inputs.
    Zero clusters and "we could not model this venue" are different claims, and
    an empty bar chart makes the second one look like the first.
    """
    if not isinstance(profile, dict) or not profile.get("levels") or price <= 0:
        return None

    bin_size = profile.get("bin_size") or 0
    price_min = profile.get("price_min")
    if not bin_size or price_min is None:
        return None

    # side 0 is longs (liquidate below spot), side 1 is shorts (above).
    sums: dict[tuple[int, int], float] = {}
    for entry in profile["levels"]:
        try:
            index, _tier, side, notional = entry[0], entry[1], entry[2], entry[3]
        except (IndexError, TypeError):
            continue
        key = (int(side), int(index))
        sums[key] = sums.get(key, 0.0) + float(notional)

    clusters: list[dict[str, Any]] = []
    for side in (0, 1):
        candidates = sorted(
            ((index, total) for (s, index), total in sums.items() if s == side and total > 0),
            key=lambda row: -row[1],
        )
        picked: list[int] = []
        for index, total in candidates:
            if any(abs(index - taken) <= LIQUIDITY_MERGE_RADIUS for taken in picked):
                continue
            picked.append(index)
            level_price = price_min + (index + 0.5) * bin_size
            clusters.append(
                {
                    "price": round(level_price, 8),
                    "notional_usd": round(total),
                    "side": "long" if side == 0 else "short",
                    "distance_pct": (level_price - price) / price * 100,
                }
            )
            if len(picked) == LIQUIDITY_CLUSTERS_PER_SIDE:
                break

    if not clusters:
        return None

    clusters.sort(key=lambda row: row["price"])
    return {
        "clusters": clusters,
        "total_long_usd": profile.get("total_long"),
        "total_short_usd": profile.get("total_short"),
        "venue": profile.get("exchange"),
        # Said on the card, not buried here: these are levels a model puts in the
        # book from open interest and leverage assumptions, not liquidations
        # anyone observed.
        "modelled": True,
    }


async def _crypto_facts(clean: str) -> dict[str, Any]:
    """Price, series, funding and the standing liquidation book for a pair."""
    from services.home_service import fetch_funding_rates
    from services.liquidation_map_service import get_liquidation_profile
    from services.liquidation_service import liquidation_service
    from services.okx_market import fetch_ticker_24h, split_symbol

    # The profile runs on this service's defaults on purpose rather than on a
    # cheaper grid of its own: those are the parameters the Derivatives page
    # asks for, so the two surfaces share one cache entry instead of paying for
    # the same simulation twice under different keys.
    ticker, candles, funding_rows, profile = await asyncio.gather(
        fetch_ticker_24h(clean),
        liquidation_service.fetch_candles(clean, CRYPTO_SPARK_INTERVAL, CRYPTO_SPARK_HOURS),
        fetch_funding_rates(),
        get_liquidation_profile(clean),
        return_exceptions=True,
    )

    if isinstance(ticker, BaseException) or not ticker:
        raise SymbolNotFound(f"No spot price for {clean}")

    closes = _closes(candles) if isinstance(candles, list) else []

    # Funding comes off the board the widget above already renders rather than
    # from a per-symbol call: that list is fetched for the whole market and
    # cached, so reading one row out of it is free. A symbol that is not on it
    # has no listed perpetual — which is not the same as a funding rate of zero,
    # and is reported as null for exactly that reason.
    base = split_symbol(clean)[0]
    funding_row: Optional[dict[str, Any]] = None
    if isinstance(funding_rows, list):
        funding_row = next((row for row in funding_rows if row.get("symbol") == base), None)

    return {
        "price": float(ticker["price"]),
        "change_24h_pct": _numeric(ticker.get("change_pct")),
        "closes": closes,
        # 168 hourly closes; a week back is the whole series, a day back is 24.
        "change_7d_pct": _change_over(closes, CRYPTO_SPARK_HOURS - 1),
        "leg": {
            "funding_rate": _numeric(funding_row.get("rate")) if funding_row else None,
            "funding_interval_hours": (funding_row.get("interval_hours") if funding_row else None),
            "funding_is_extreme": bool(funding_row.get("is_extreme")) if funding_row else None,
            "volume_24h_usd": _numeric(ticker.get("volume_usd")),
            "liquidity": _liquidity(profile, float(ticker["price"])),
        },
    }


async def _equity_facts(clean: str) -> dict[str, Any]:
    """Price, series and a relative-volume read for an equity."""
    import httpx

    from services.stock_market_service import fetch_single_stock, fetch_stock_candles

    async with httpx.AsyncClient(timeout=20.0) as client:
        quote, candles = await asyncio.gather(
            fetch_single_stock(client, clean),
            fetch_stock_candles(clean),
            return_exceptions=True,
        )

    if isinstance(quote, BaseException) or not quote or not quote.get("price"):
        raise SymbolNotFound(f"No quote for {clean}")

    rows = candles if isinstance(candles, list) else []
    closes = _closes(rows)

    # Yahoo's quote reports today's volume in shares; the card compares it with
    # the same window's average so the number reads as "busy" or "quiet" rather
    # than as an unanchored count. The average deliberately excludes the current
    # session — including today in its own baseline flattens exactly the spike
    # the reading exists to surface.
    volumes = [
        float(row["volume"])
        for row in rows[:-1][-EQUITY_VOLUME_WINDOW:]
        if isinstance(row, dict) and isinstance(row.get("volume"), (int, float))
    ]
    avg_volume = sum(volumes) / len(volumes) if volumes else None
    volume_today = float(rows[-1]["volume"]) if rows and rows[-1].get("volume") else None

    return {
        "price": float(quote["price"]),
        "change_24h_pct": _numeric(quote.get("change_24h")),
        "closes": closes,
        # Daily bars, so a week is five sessions rather than seven days.
        "change_7d_pct": _change_over(closes, 5),
        "leg": {
            "name": quote.get("name"),
            "sector": quote.get("sector"),
            "volume": volume_today,
            "avg_volume": avg_volume,
            "relative_volume": (
                volume_today / avg_volume
                if volume_today and avg_volume and avg_volume > 0
                else None
            ),
            "fifty_two_week_high": _numeric(quote.get("fifty_two_week_high")),
            "fifty_two_week_low": _numeric(quote.get("fifty_two_week_low")),
        },
    }


# ── The AI note ──────────────────────────────────────────────────────────────


def _bucket(value: Optional[float], step: float) -> Optional[float]:
    """Round to a multiple of `step`, so a note survives an unremarkable tick."""
    if value is None:
        return None
    return round(round(value / step) * step, 4)


def note_facts(brief: dict[str, Any]) -> dict[str, Any]:
    """
    The quantized read the note is fingerprinted by — and rendered from.

    Everything here is rounded before it is stored, because the card refreshes
    every minute and fingerprinting raw prices would mean a fresh Ollama run per
    minute per symbol. The prompt is filled from these same rounded values, so a
    cached note can never quote a figure that has since moved.
    """
    leg = brief.get("crypto") or brief.get("equity") or {}
    facts: dict[str, Any] = {
        "symbol": brief["display_symbol"],
        "asset_type": brief["asset_type"],
        "change_24h_pct": _bucket(brief.get("change_24h_pct"), 0.5),
        "change_7d_pct": _bucket(brief.get("change_7d_pct"), 1.0),
        "rsi": _bucket(brief.get("rsi_14"), 5.0),
        "rsi_signal": brief.get("rsi_signal"),
        "trend": brief.get("trend"),
        # Levels as a distance rather than a price: the note's job is "how far
        # is the next wall", and a bucketed percentage keeps its fingerprint
        # stable while the price itself drifts.
        "support_distance_pct": _bucket(brief.get("support_distance_pct"), 0.5),
        "resistance_distance_pct": _bucket(brief.get("resistance_distance_pct"), 0.5),
    }

    if brief["asset_type"] == "crypto":
        rate = leg.get("funding_rate")
        facts["funding_bps"] = _bucket(rate * 10_000, 0.5) if rate is not None else None
        facts["funding_is_extreme"] = leg.get("funding_is_extreme")
    else:
        facts["relative_volume"] = _bucket(leg.get("relative_volume"), 0.1)

    return facts


def note_values(facts: dict[str, Any]) -> dict[str, str]:
    """Fill the prompt's placeholders from `facts`, and from nothing else."""
    unknown = "not available"

    def pct(key: str) -> str:
        value = facts.get(key)
        return f"{value:+.1f}%" if value is not None else unknown

    def distance(key: str, label: str) -> str:
        value = facts.get(key)
        return f"{label} {abs(value):.1f}% away" if value is not None else f"{label} {unknown}"

    lines = [
        f"- 24h change: {pct('change_24h_pct')}",
        f"- 7d change: {pct('change_7d_pct')}",
        f"- RSI: {facts['rsi']:.0f} ({facts.get('rsi_signal') or 'unclassified'})"
        if facts.get("rsi") is not None
        else f"- RSI: {unknown}",
        f"- Trend on the primary timeframe: {facts.get('trend') or unknown}",
        f"- {distance('support_distance_pct', 'nearest support')}",
        f"- {distance('resistance_distance_pct', 'nearest resistance')}",
    ]

    if facts["asset_type"] == "crypto":
        funding = facts.get("funding_bps")
        if funding is None:
            lines.append("- Perpetual funding: no listed perpetual for this pair")
        else:
            extreme = " — flagged extreme" if facts.get("funding_is_extreme") else ""
            side = "longs paying shorts" if funding > 0 else "shorts paying longs"
            lines.append(f"- Perpetual funding: {funding:+.1f} bps, {side}{extreme}")
    else:
        relative = facts.get("relative_volume")
        lines.append(
            f"- Volume today vs its 30-session average: {relative:.1f}x"
            if relative is not None
            else f"- Volume against its average: {unknown}"
        )

    return {
        "symbol": facts["symbol"],
        "asset_class": "crypto pair" if facts["asset_type"] == "crypto" else "equity",
        "facts": "\n".join(lines),
    }


# ── Entry point ──────────────────────────────────────────────────────────────


async def build_brief(candidate: str) -> dict[str, Any]:
    """
    The Home card's payload for one symbol.

    Raises `SymbolNotFound` when the candidate names nothing this app can price;
    the router turns that into a 404. Every other gap is a null field.
    """
    from services.technical_analysis_service import get_technical_analysis

    resolved = await symbol_detection_service.resolve(candidate)
    if not resolved:
        raise SymbolNotFound(f"{candidate} does not resolve to a known asset")

    asset_type = symbol_detection_service.asset_type_for_symbol(resolved)
    clean = resolved.split(":")[-1]

    # The technical read runs alongside the price rather than after it: it is the
    # slowest call here (three timeframes) and it does not need the price.
    facts_task = _crypto_facts(clean) if asset_type == "crypto" else _equity_facts(clean)
    facts, analysis = await asyncio.gather(
        facts_task, get_technical_analysis(resolved), return_exceptions=True
    )

    if isinstance(facts, BaseException):
        if isinstance(facts, SymbolNotFound):
            raise facts
        raise SymbolNotFound(f"Could not price {resolved}") from facts

    if isinstance(analysis, BaseException):
        logger.warning("[AssetBrief] technical read failed for %s: %s", resolved, analysis)
        analysis = None

    price = facts["price"]
    support = _zone_mid(analysis, "support")
    resistance = _zone_mid(analysis, "resistance")

    brief: dict[str, Any] = {
        "symbol": resolved,
        "display_symbol": clean,
        "asset_type": asset_type,
        "price": price,
        "change_24h_pct": facts["change_24h_pct"],
        "change_7d_pct": facts["change_7d_pct"],
        "spark": _downsample(facts["closes"]),
        "rsi_14": _numeric((analysis or {}).get("rsi_value")),
        "rsi_signal": (analysis or {}).get("rsi_signal"),
        "trend": (analysis or {}).get("trend"),
        "timeframe": (analysis or {}).get("primary_timeframe"),
        "support": support,
        "resistance": resistance,
        "support_distance_pct": ((support - price) / price * 100) if support and price else None,
        "resistance_distance_pct": (
            ((resistance - price) / price * 100) if resistance and price else None
        ),
        # Exactly one of these is ever populated. A `funding_rate: 0` on an
        # equity would be a number the reader could act on and a fact that does
        # not exist, so the leg the asset does not have is absent entirely.
        "crypto": facts["leg"] if asset_type == "crypto" else None,
        "equity": facts["leg"] if asset_type != "crypto" else None,
        "as_of": datetime.now(UTC).isoformat(),
    }

    note_input = note_facts(brief)
    brief["ai_note"] = await get_note(NOTE_SPEC, note_input, note_values(note_input))
    return brief
