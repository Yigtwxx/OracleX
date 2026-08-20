"""
Market snapshot builder for the analysis reports.

This module touches no LLM. Its only job is to assemble every data feed the app
already exposes into one consistent, deterministic picture of the market, and to
compute the derived metrics (breadth, ratios, deltas) in Python rather than
leaving them to the model.

The guiding rule is partial degradation: every feed is fetched independently and
a failure records the source in ``snapshot["unavailable"]`` instead of aborting
the run. A report built on eight of nine feeds is useful; no report is not.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from services.cache import ServiceCache

logger = logging.getLogger(__name__)

# Majors we always want technical levels for, plus how many top movers to add.
CORE_TECHNICAL_SYMBOLS = ["BINANCE:BTCUSDT", "BINANCE:ETHUSDT"]
MOVER_TECHNICAL_COUNT = 2

# Liquidation lookback per horizon — a daily report cares about the last day,
# a monthly one about the whole stored window.
LIQUIDATION_WINDOW_SECONDS = {
    "daily": 24 * 3600,
    "weekly": 7 * 24 * 3600,
    "monthly": 30 * 24 * 3600,
}

# How many headlines feed the report, per horizon (kept from the previous
# implementation so report scope does not silently change).
NEWS_LIMIT = {"daily": 30, "weekly": 60, "monthly": 100}

FEED_NAMES = {
    "crypto_market": "Crypto market overview",
    "crypto_fear_greed": "Crypto Fear & Greed index",
    "stock_market": "US equity market data",
    "global_indices": "Global equity indices",
    "macro_board": "Commodity & macro board",
    "technicals": "Technical levels",
    "liquidations": "Liquidation feed",
    "whales": "Large-transaction flow",
    "sectors": "Sector breadth",
    "news": "News headlines",
}

# Upper bound on any single feed. Feeds run concurrently, so this also bounds
# the whole collection stage. Generous, because a cold news cache means fetching
# every RSS source from scratch — but finite, so one wedged upstream cannot
# stall a report indefinitely. Interactive callers pass something far shorter:
# a report can wait a minute for a feed, a chat turn cannot.
FEED_TIMEOUT_SECONDS = 90.0


async def _safe(
    name: str, coro: Any, timeout: float = FEED_TIMEOUT_SECONDS
) -> Tuple[str, Optional[Any]]:
    """Await a feed coroutine, converting any failure or stall into a None result."""
    try:
        return name, await asyncio.wait_for(coro, timeout=timeout)
    except TimeoutError:
        logger.warning("Analysis feed '%s' timed out after %.0fs", name, timeout)
        return name, None
    except Exception as e:  # noqa: BLE001 — one bad feed must not kill the report
        logger.warning("Analysis feed '%s' failed: %s", name, e)
        return name, None


async def _fetch_technicals(movers: List[str]) -> Dict[str, Dict]:
    """Technical levels for the majors plus the biggest movers, keyed by symbol."""
    from services.technical_analysis_service import get_technical_analysis

    symbols = list(CORE_TECHNICAL_SYMBOLS)
    for symbol in movers:
        candidate = f"BINANCE:{symbol}USDT"
        if candidate not in symbols:
            symbols.append(candidate)

    results = await asyncio.gather(
        *(get_technical_analysis(s) for s in symbols), return_exceptions=True
    )

    out: Dict[str, Dict] = {}
    for symbol, result in zip(symbols, results):
        # None means no levels could be computed for that symbol; it is left out
        # of the snapshot entirely rather than carried as an empty row.
        if isinstance(result, dict):
            out[symbol.split(":")[-1]] = result
    return out


async def _fetch_news(timeframe: str) -> List[Any]:
    """Recent headlines, preferring the scheduler's warm cache over a re-fetch."""
    from utils import get_news_cache

    items = sorted(get_news_cache().values(), key=lambda x: x.published_at, reverse=True)
    if not items:
        from services.news_service import fetch_all_news

        items = await fetch_all_news()

    return items[: NEWS_LIMIT.get(timeframe, 30)]


# ═══════════════════════════════════════════════════════════════════════════════
# DERIVED METRICS — computed here so the model never has to do arithmetic
# ═══════════════════════════════════════════════════════════════════════════════


def _breadth(coins: List[Dict]) -> Optional[Dict[str, Any]]:
    """Advance/decline statistics across the tracked coin universe."""
    changes = [c.get("change_24h") for c in coins if isinstance(c.get("change_24h"), (int, float))]
    if not changes:
        return None

    advancing = sum(1 for c in changes if c > 0)
    declining = sum(1 for c in changes if c < 0)

    total_cap = sum(c.get("market_cap", 0) or 0 for c in coins)
    weighted = (
        sum((c.get("market_cap", 0) or 0) * (c.get("change_24h", 0) or 0) for c in coins)
        / total_cap
        if total_cap
        else 0.0
    )

    return {
        "universe_size": len(changes),
        "advancing": advancing,
        "declining": declining,
        "advancing_percent": round(advancing / len(changes) * 100, 1),
        "median_change_24h": round(sorted(changes)[len(changes) // 2], 2),
        "cap_weighted_change_24h": round(weighted, 2),
    }


def _fear_greed_trend(fear_greed: Optional[Dict]) -> Optional[Dict[str, Any]]:
    """Current level plus the move over the stored history window."""
    if not fear_greed:
        return None

    history = fear_greed.get("history") or []
    current = fear_greed.get("value")
    if current is None:
        return None

    oldest = history[-1].get("value") if history else None
    delta = current - oldest if oldest is not None else None

    return {
        "value": current,
        "classification": fear_greed.get("classification"),
        "value_7d_ago": oldest,
        "delta_7d": delta,
        "direction": (
            "rising" if delta and delta > 2 else "falling" if delta and delta < -2 else "flat"
        ),
    }


def _liquidation_stats(rows: Optional[List[Dict]]) -> Optional[Dict[str, Any]]:
    """Total notional and the long/short balance across the liquidation window."""
    if not rows:
        return None

    long_usd = sum(r.get("long_liq", 0) or 0 for r in rows)
    short_usd = sum(r.get("short_liq", 0) or 0 for r in rows)
    total = long_usd + short_usd
    if total <= 0:
        return None

    return {
        "total_usd": round(total, 2),
        "long_usd": round(long_usd, 2),
        "short_usd": round(short_usd, 2),
        "long_share_percent": round(long_usd / total * 100, 1),
        "event_count": sum(r.get("count", 0) or 0 for r in rows),
        "top_symbols": rows[:5],
    }


def _sector_breadth(sectors_payload: Optional[Dict]) -> Optional[List[Dict[str, Any]]]:
    """
    Market-cap-weighted 24h move per sector, strongest first.

    The heatmap service now aggregates this itself, weighted, and hands over a
    list of sector rows. The older shape — a plain ``{sector: [coins]}`` mapping
    that had to be averaged here — is still accepted so a cached payload written
    before the change keeps rendering; it can only produce the unweighted mean,
    which let a $300M token move a sector as much as a $2T one.
    """
    if not sectors_payload:
        return None

    sectors = sectors_payload.get("sectors")
    rows: List[Dict[str, Any]] = []

    if isinstance(sectors, list):
        for entry in sectors:
            change = entry.get("weighted_change_24h")
            if not isinstance(change, (int, float)):
                continue
            rows.append(
                {
                    "sector": entry.get("sector") or "Unknown",
                    "coin_count": entry.get("coin_count") or len(entry.get("coins") or []),
                    "avg_change_24h": round(float(change), 2),
                    "weighted": True,
                }
            )
    else:
        for sector, coins in (sectors or {}).items():
            changes = [
                c.get("price_change_24h")
                for c in coins
                if isinstance(c.get("price_change_24h"), (int, float))
            ]
            if not changes:
                continue
            rows.append(
                {
                    "sector": sector,
                    "coin_count": len(changes),
                    "avg_change_24h": round(sum(changes) / len(changes), 2),
                    "weighted": False,
                }
            )

    rows.sort(key=lambda r: r["avg_change_24h"], reverse=True)
    return rows or None


# The verdict vocabulary the news pipeline writes, and the materiality levels
# worth pulling out of the pile. Anything outside these is treated as no verdict
# rather than passed through — an unrecognised label in a report is worse than a
# headline that simply carries no mark.
_VERDICT_SENTIMENTS = ("bullish", "bearish", "neutral")
_MATERIAL_LEVELS = ("extraordinary", "significant")


def _news_verdicts(items: Sequence[Any]) -> Optional[Dict[str, Any]]:
    """
    Stored news-pipeline verdicts for the headlines in this snapshot.

    Reads the analysis store and nothing else: no analysis is triggered here, so
    this costs a file read and no model time. That store is filled when a reader
    opens a headline, which makes coverage partial by construction — hence the
    scored/total counts travelling alongside the verdicts. A report that read
    three bullish verdicts out of thirty headlines as "the news is bullish" would
    be describing what people clicked on, not what was published.

    Keyword-fallback verdicts are skipped. They come from a word count over the
    title taken when no provider was reachable, and setting one beside a real
    analysis as the same kind of object is exactly the conflation the store's
    `source` field exists to prevent.
    """
    if not items:
        return None

    by_id: Dict[str, Dict[str, Any]] = {}
    try:
        from services import news_analysis_store

        for item in items:
            news_id = getattr(item, "id", None)
            if not news_id:
                continue
            entry = news_analysis_store.get(str(news_id))
            analysis = (entry or {}).get("analysis") or {}
            sentiment, confidence = analysis.get("sentiment"), analysis.get("confidence")
            if sentiment not in _VERDICT_SENTIMENTS:
                continue
            if not isinstance(confidence, (int, float)):
                continue
            if analysis.get("source") == "keyword-fallback":
                continue
            by_id[str(news_id)] = {
                "sentiment": sentiment,
                "confidence": round(float(confidence), 2),
                "materiality": analysis.get("materiality"),
                "time_horizon": analysis.get("time_horizon"),
                "price_impact": analysis.get("price_impact"),
                "title": (entry.get("news") or {}).get("title") or getattr(item, "title", ""),
            }
    except Exception as e:  # noqa: BLE001 — an unreadable store is a gap, not a failed report
        logger.warning("Could not read stored news verdicts: %s", e)

    if not by_id:
        return None

    verdicts = list(by_id.values())
    return {
        "by_id": by_id,
        "scored": len(verdicts),
        "total": len(items),
        "counts": {
            name: sum(1 for v in verdicts if v["sentiment"] == name) for name in _VERDICT_SENTIMENTS
        },
        "mean_confidence": round(sum(v["confidence"] for v in verdicts) / len(verdicts), 2),
        "material": [v for v in verdicts if v.get("materiality") in _MATERIAL_LEVELS][:5],
    }


def _movers(coins: List[Dict], count: int = 3) -> Dict[str, List[Dict]]:
    """Top gainers and losers by 24h change."""
    ranked = sorted(
        [c for c in coins if isinstance(c.get("change_24h"), (int, float))],
        key=lambda c: c["change_24h"],
        reverse=True,
    )
    return {"gainers": ranked[:count], "losers": list(reversed(ranked[-count:]))}


# ═══════════════════════════════════════════════════════════════════════════════
# SNAPSHOT
# ═══════════════════════════════════════════════════════════════════════════════


async def build_market_snapshot(
    timeframe: str, feed_timeout: float = FEED_TIMEOUT_SECONDS
) -> Dict[str, Any]:
    """
    Assemble every available market feed into a single snapshot.

    Feeds are fetched concurrently and independently: any that fail are named in
    ``snapshot["unavailable"]`` and their slot is left as None.

    `feed_timeout` bounds each individual feed. Lower it for interactive callers:
    a cold news cache takes the better part of a minute to refill, which is fine
    for a scheduled report and far too slow for a chat turn — the turn is better
    served by a snapshot that names news as a gap than by waiting for it.
    """
    from services.fear_greed_service import fetch_fear_greed_index
    from services.heatmap_service import fetch_heatmap_data
    from services.liquidation_service import liquidation_service
    from services.macro_board_service import fetch_macro_board
    from services.market_overview_service import fetch_market_overview
    from services.onchain_service import fetch_whale_trades
    from services.stock_market_service import fetch_global_indices, fetch_nasdaq_overview

    window = LIQUIDATION_WINDOW_SECONDS.get(timeframe, 24 * 3600)

    # Round one: everything that does not depend on another feed's result.
    first_pass = await asyncio.gather(
        _safe("crypto_market", fetch_market_overview(), feed_timeout),
        _safe("crypto_fear_greed", fetch_fear_greed_index(), feed_timeout),
        _safe("stock_market", fetch_nasdaq_overview(), feed_timeout),
        _safe("global_indices", fetch_global_indices(), feed_timeout),
        _safe("macro_board", fetch_macro_board(), feed_timeout),
        _safe("liquidations", liquidation_service.get_heatmap_data(window), feed_timeout),
        _safe("whales", fetch_whale_trades(), feed_timeout),
        _safe("sectors", fetch_heatmap_data(), feed_timeout),
        _safe("news", _fetch_news(timeframe), feed_timeout),
    )
    feeds: Dict[str, Any] = dict(first_pass)

    crypto_market = feeds.get("crypto_market") or {}
    coins = crypto_market.get("coins") or []
    movers = _movers(coins)

    # Round two: technicals need the movers from round one.
    mover_symbols = [c.get("symbol", "") for c in movers["gainers"][:MOVER_TECHNICAL_COUNT]]
    _, technicals = await _safe("technicals", _fetch_technicals(mover_symbols), feed_timeout)
    feeds["technicals"] = technicals

    # An empty result counts as a gap alongside an outright failure: the model
    # must not draw conclusions from a feed that returned nothing either way.
    unavailable = [
        FEED_NAMES[name] for name, value in feeds.items() if not value and name in FEED_NAMES
    ]

    news_items = feeds.get("news") or []
    news_sections = {
        "crypto": [n for n in news_items if getattr(n, "asset_type", None) == "crypto"][:15],
        "stock": [n for n in news_items if getattr(n, "asset_type", None) == "stock"][:15],
    }
    snapshot: Dict[str, Any] = {
        "timeframe": timeframe,
        "generated_at": datetime.now().isoformat(),
        "crypto_market": crypto_market or None,
        "crypto_fear_greed": feeds.get("crypto_fear_greed"),
        "stock_market": feeds.get("stock_market"),
        "global_indices": feeds.get("global_indices"),
        "macro_board": feeds.get("macro_board"),
        "technicals": technicals,
        "liquidations": feeds.get("liquidations"),
        "whales": feeds.get("whales"),
        "sectors": feeds.get("sectors"),
        "news": news_sections,
        "derived": {
            "breadth": _breadth(coins),
            "fear_greed_trend": _fear_greed_trend(feeds.get("crypto_fear_greed")),
            "liquidations": _liquidation_stats(feeds.get("liquidations")),
            "sector_breadth": _sector_breadth(feeds.get("sectors")),
            "movers": movers,
            "news_verdicts": _news_verdicts(news_sections["crypto"] + news_sections["stock"]),
            "liquidation_window_hours": round(window / 3600),
        },
        "unavailable": unavailable,
    }
    return snapshot


# ═══════════════════════════════════════════════════════════════════════════════
# PROMPT RENDERING
# ═══════════════════════════════════════════════════════════════════════════════


def _fmt_usd(value: Optional[float], decimals: int = 2) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"${value:,.{decimals}f}"


def _fmt_pct(value: Optional[float]) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{value:+.2f}%"


def _section(title: str, body: Optional[str]) -> List[str]:
    """A named block, or an explicit unavailability note when there is no body."""
    if not body:
        return [f"## {title}", "_Feed unavailable for this report._", ""]
    return [f"## {title}", body, ""]


def _render_crypto(snapshot: Dict[str, Any]) -> Optional[str]:
    market = snapshot.get("crypto_market")
    if not market:
        return None

    derived = snapshot["derived"]
    lines = [
        f"- Total market cap: {_fmt_usd(market.get('total_market_cap'), 0)}",
        f"- 24h volume: {_fmt_usd(market.get('total_volume_24h'), 0)}",
        f"- BTC dominance: {market.get('btc_dominance', 0):.2f}%",
        f"- ETH dominance: {market.get('eth_dominance', 0):.2f}%",
    ]

    breadth = derived.get("breadth")
    if breadth:
        lines += [
            f"- Breadth: {breadth['advancing']}/{breadth['universe_size']} advancing "
            f"({breadth['advancing_percent']}%), {breadth['declining']} declining",
            f"- Median 24h change: {_fmt_pct(breadth['median_change_24h'])}, "
            f"cap-weighted: {_fmt_pct(breadth['cap_weighted_change_24h'])}",
        ]

    coins = (market.get("coins") or [])[:10]
    if coins:
        lines += [
            "",
            "| # | Asset | Price | 24h | Market cap | 24h volume |",
            "|---|-------|-------|-----|------------|------------|",
        ]
        for i, c in enumerate(coins, 1):
            lines.append(
                f"| {i} | {c.get('symbol', '?')} | {_fmt_usd(c.get('price'))} | "
                f"{_fmt_pct(c.get('change_24h'))} | {_fmt_usd(c.get('market_cap'), 0)} | "
                f"{_fmt_usd(c.get('volume_24h'), 0)} |"
            )

    movers = derived.get("movers") or {}
    for label, key in (("Top gainers", "gainers"), ("Top losers", "losers")):
        rows = movers.get(key) or []
        if rows:
            joined = ", ".join(
                f"{c.get('symbol', '?')} {_fmt_pct(c.get('change_24h'))}" for c in rows
            )
            lines.append(f"- {label}: {joined}")

    return "\n".join(lines)


def _render_sentiment(snapshot: Dict[str, Any]) -> Optional[str]:
    trend = snapshot["derived"].get("fear_greed_trend")
    stock_market = snapshot.get("stock_market") or {}
    stock_fg = stock_market.get("fear_greed")

    lines = []
    if trend:
        lines.append(
            f"- Crypto Fear & Greed: {trend['value']} ({trend['classification']}), "
            f"7d ago {trend['value_7d_ago']}, delta {trend['delta_7d']} ({trend['direction']})"
        )
    if isinstance(stock_fg, dict):
        lines.append(
            f"- Equity Fear & Greed: {stock_fg.get('value', 'n/a')} "
            f"({stock_fg.get('classification', 'n/a')})"
        )
    return "\n".join(lines) if lines else None


def _fmt_band(zone: Dict[str, Any]) -> str:
    """A zone as the band it is. A single price would overstate the method."""
    low, high = zone.get("low"), zone.get("high")
    if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
        return "n/a"
    if low == high:
        return _fmt_usd(low)
    return f"{_fmt_usd(low)} – {_fmt_usd(high)}"


def _render_zone_rows(ta: Dict[str, Any]) -> List[str]:
    """The support and resistance bands for one asset, nearest side first."""
    zones = ta.get("zones") or {}
    rows: List[str] = []
    for side in ("resistance", "inside", "support"):
        for zone in zones.get(side) or []:
            confirmed = "+".join(zone.get("timeframes") or [zone.get("timeframe", "?")])
            distance = zone.get("distance_percent")
            rows.append(
                f"| {side} | {zone.get('horizon', 'n/a')} | {_fmt_band(zone)} | "
                f"{distance:+.2f}% | {confirmed} | {zone.get('touches', 0)} | "
                f"{zone.get('strength', 0)} | {'yes' if zone.get('flip') else 'no'} |"
            )
    return rows


def _render_structure(ta: Dict[str, Any]) -> List[str]:
    """The zoomed-out read: where this price sits in its own two-year history."""
    structure = ta.get("structure") or {}
    lines: List[str] = []

    position = structure.get("position_percent")
    if position is not None and structure.get("range_low") is not None:
        lines.append(
            f"- Range ({structure.get('range_bars')} {structure.get('range_timeframe')} bars): "
            f"{_fmt_usd(structure['range_low'])} – {_fmt_usd(structure['range_high'])}; "
            f"price is at {position:.1f}% of it, "
            f"{_fmt_pct(structure.get('distance_to_high_percent'))} from the high and "
            f"{_fmt_pct(structure.get('distance_to_low_percent'))} from the low"
        )
    if structure.get("sma200") is not None:
        lines.append(
            f"- 200-bar SMA {_fmt_usd(structure['sma200'])} "
            f"({_fmt_pct(structure.get('price_vs_sma200_percent'))} vs price), "
            f"50-bar SMA {_fmt_usd(structure.get('sma50'))}"
        )
    if structure.get("swing_structure"):
        lines.append(f"- Swing structure: {structure['swing_structure']}")
    if structure.get("timeframe_alignment"):
        lines.append(f"- Timeframes: {structure['timeframe_alignment']}")

    divergences = [
        f"{label} {read['rsi']['divergence']}"
        for label, read in (ta.get("timeframes") or {}).items()
        if (read.get("rsi") or {}).get("divergence")
    ]
    if divergences:
        lines.append(f"- RSI divergence: {'; '.join(divergences)}")
    return lines


def _render_asset_technicals(symbol: str, ta: Dict[str, Any]) -> List[str]:
    """One asset's multi-timeframe read: indicators, structure, then zones."""
    lines = [f"**{symbol} — {_fmt_usd(ta.get('current_price'))}**"]

    reads = ta.get("timeframes") or {}
    if reads:
        lines += [
            "",
            "| TF | Bars | Covers | Trend | RSI(14) | RSI 5-bar | ATR | ATR % |",
            "|----|------|--------|-------|---------|-----------|-----|-------|",
        ]
        for label, read in reads.items():
            rsi = read.get("rsi") or {}
            value = rsi.get("value")
            rsi_cell = (
                f"{value:.1f} ({rsi.get('signal', 'n/a')})"
                if isinstance(value, (int, float))
                else "n/a"
            )
            change = rsi.get("change_5_bars")
            change_cell = (
                f"{change:+.1f} {rsi.get('slope', '')}".strip()
                if isinstance(change, (int, float))
                else "n/a"
            )
            covers = read.get("covers_days")
            atr_percent = read.get("atr_percent")
            lines.append(
                f"| {label} | {read.get('bars', 0)} | "
                f"{f'{covers}d' if covers else 'n/a'} | {read.get('trend') or 'n/a'} | "
                f"{rsi_cell} | {change_cell} | {_fmt_usd(read.get('atr'))} | "
                f"{f'{atr_percent:.2f}%' if isinstance(atr_percent, (int, float)) else 'n/a'} |"
            )
        lines.append("")

    lines += _render_structure(ta)

    zone_rows = _render_zone_rows(ta)
    if zone_rows:
        lines += [
            "",
            "| Side | Horizon | Zone | Distance | Confirmed on | Touches | Strength | Flipped |",
            "|------|---------|------|----------|--------------|---------|----------|---------|",
        ]
        lines += zone_rows

    missing = [
        label for label, entry in (ta.get("coverage") or {}).items() if not entry.get("available")
    ]
    if missing:
        lines.append("")
        lines.append(
            f"- No {', '.join(missing)} history for this asset — that horizon was not read."
        )

    return lines


def _render_technicals(snapshot: Dict[str, Any]) -> Optional[str]:
    technicals = snapshot.get("technicals")
    if not technicals:
        return None

    lines: List[str] = []
    for symbol, ta in technicals.items():
        if not isinstance(ta, dict):
            continue
        if lines:
            lines.append("")
        lines += _render_asset_technicals(symbol, ta)

    if not lines:
        return None

    # Written out because every one of these is a constraint on what may be said
    # about the numbers above, and none of them is inferable from the table.
    lines += [
        "",
        "Zones are bands price reversed in, not single prices: quote the band. `Touches` "
        "counts those reversals, `strength` (0-100) weighs how often, how recently, on how "
        "much volume and whether the band has flipped between support and resistance, and "
        "`confirmed on` lists every timeframe that found it — a band three timeframes agree "
        "on is the one that matters. Horizon comes from the longest timeframe that confirmed "
        "the band, not from its distance to spot. Indicators are 14-period RSI and ATR per "
        "timeframe; the weekly read is capped at two years, so nothing here describes a "
        "level older than that.",
    ]
    return "\n".join(lines)


def _render_derivatives(snapshot: Dict[str, Any]) -> Optional[str]:
    derived = snapshot["derived"]
    liq = derived.get("liquidations")
    whales = snapshot.get("whales") or {}
    stats = whales.get("stats") or {}

    lines = []
    if liq:
        lines += [
            f"- Liquidations over the last {derived['liquidation_window_hours']}h: "
            f"{_fmt_usd(liq['total_usd'], 0)} across {liq['event_count']} events",
            f"- Longs liquidated: {_fmt_usd(liq['long_usd'], 0)} ({liq['long_share_percent']}%), "
            f"shorts: {_fmt_usd(liq['short_usd'], 0)}",
        ]
        if liq.get("top_symbols"):
            lines += [
                "",
                "| Symbol | Total | Long liq | Short liq | Events |",
                "|--------|-------|----------|-----------|--------|",
            ]
            for row in liq["top_symbols"]:
                lines.append(
                    f"| {row.get('symbol', '?')} | {_fmt_usd(row.get('value'), 0)} | "
                    f"{_fmt_usd(row.get('long_liq'), 0)} | {_fmt_usd(row.get('short_liq'), 0)} | "
                    f"{row.get('count', 0)} |"
                )
            lines.append("")

    # Guarded on observed volume rather than on `stats` being present: the feed
    # always returns a stats block, but an empty window carries no reading and
    # reports `buy_pressure_percent` as None to say so.
    volume = stats.get("observed_volume")
    if isinstance(volume, (int, float)) and volume > 0:
        pressure = stats.get("buy_pressure_percent")
        pressure_cell = f"{pressure:.1f}%" if isinstance(pressure, (int, float)) else "n/a"
        # The window is what this process has actually seen, not a fixed 24h
        # tape, so it is stated instead of being implied by the label.
        window_hours = (stats.get("window_seconds") or 0) / 3600
        lines += [
            f"- Large-transaction net flow: {_fmt_usd(stats.get('net_flow'), 0)} "
            f"on {_fmt_usd(volume, 0)} observed over the last {window_hours:.1f}h "
            f"({stats.get('whale_count', 0)} orders)",
            f"- Buy pressure: {pressure_cell} of large-trade value",
        ]

    return "\n".join(lines) if lines else None


def _render_equities(snapshot: Dict[str, Any]) -> Optional[str]:
    stock_market = snapshot.get("stock_market") or {}
    indices = snapshot.get("global_indices") or []
    if not stock_market and not indices:
        return None

    lines = []
    status = stock_market.get("market_status") or {}
    if status:
        lines.append(
            f"- US session status: {status.get('status', 'n/a')} — {status.get('next_event', '')}"
        )

    stocks = (stock_market.get("coins") or [])[:10]
    if stocks:
        lines += [
            "",
            "| Ticker | Price | 24h | Market cap |",
            "|--------|-------|-----|------------|",
        ]
        for s in stocks:
            lines.append(
                f"| {s.get('symbol', '?')} | {_fmt_usd(s.get('price'))} | "
                f"{_fmt_pct(s.get('change_24h'))} | {_fmt_usd(s.get('market_cap'), 0)} |"
            )
        lines.append("")

    if indices:
        lines += [
            "| Index | Region | Level | 24h |",
            "|-------|--------|-------|-----|",
        ]
        for idx in indices:
            lines.append(
                f"| {idx.get('name', idx.get('symbol', '?'))} | {idx.get('region', 'n/a')} | "
                f"{_fmt_usd(idx.get('price'))} | {_fmt_pct(idx.get('change_24h'))} |"
            )

    return "\n".join(lines) if lines else None


def _render_macro(snapshot: Dict[str, Any]) -> Optional[str]:
    """
    The commodity board and its ratios.

    The board's index rows are deliberately not rendered: those symbols already
    reach the prompt through `global_indices` in the equities block, and printing
    one index twice from two independently timed fetches hands the model two
    different levels for the same symbol — and licenses the review stage to
    strike whichever it meets second.
    """
    board = snapshot.get("macro_board") or {}
    commodities = [row for row in (board.get("commodities") or []) if row.get("price") is not None]
    ratios = [r for r in (board.get("ratios") or []) if r.get("value") is not None]
    if not commodities and not ratios:
        return None

    lines: List[str] = []
    if commodities:
        lines += [
            "| Commodity | Group | Price | Unit | 24h | 7d |",
            "|-----------|-------|-------|------|-----|-----|",
        ]
        for row in commodities:
            lines.append(
                f"| {row.get('name', row.get('symbol', '?'))} | {row.get('group', 'n/a')} | "
                f"{row['price']:,.2f} | {row.get('unit', 'n/a')} | "
                f"{_fmt_pct(row.get('change_24h'))} | {_fmt_pct(row.get('change_7d'))} |"
            )
        # The unit column is not decoration: grains and softs quote in US cents,
        # so a coffee price of 325.90 is cents per pound and reading it as
        # dollars is a hundredfold error the model has no other way to avoid.
        lines += [
            "",
            "Each price is in the unit beside it. The 7d column is measured across the "
            "board's own sparkline, so it covers the drawn window rather than a "
            "calendar week.",
        ]
    if ratios:
        lines.append("")
        lines.append(
            "- Ratios: "
            + ", ".join(f"{r['label']} {r['value']:,.{r.get('decimals', 2)}f}" for r in ratios)
        )
    if board.get("stale"):
        lines.append(
            f"- NOTE: this board is a replayed copy taken at {board.get('as_of')}, "
            "not a live reading. Treat it as the last known state, not the current one."
        )
    return "\n".join(lines)


def _render_sectors(snapshot: Dict[str, Any]) -> Optional[str]:
    rows = snapshot["derived"].get("sector_breadth")
    if not rows:
        return None

    # Named for what the number actually is. A market-cap-weighted sector move
    # and a plain mean of its members answer different questions, and the model
    # reading this table has no other way to tell which one it was handed.
    weighted = all(row.get("weighted") for row in rows)
    header = "Weighted 24h" if weighted else "Avg 24h"

    lines = [f"| Sector | Coins | {header} |", "|--------|-------|---------|"]
    for row in rows[:10]:
        lines.append(
            f"| {row['sector']} | {row['coin_count']} | {_fmt_pct(row['avg_change_24h'])} |"
        )
    return "\n".join(lines)


def _render_news(snapshot: Dict[str, Any]) -> Optional[str]:
    news = snapshot.get("news") or {}
    crypto, stock = news.get("crypto") or [], news.get("stock") or []
    if not crypto and not stock:
        return None

    verdicts = snapshot["derived"].get("news_verdicts") or {}
    by_id = verdicts.get("by_id") or {}

    def mark(item: Any) -> str:
        """The stored verdict for one headline, as a trailing clause."""
        verdict = by_id.get(str(getattr(item, "id", "") or ""))
        if not verdict:
            return ""
        fields = [f"{verdict['sentiment']} @ {verdict['confidence']:.2f} confidence"]
        for key in ("materiality", "time_horizon"):
            if verdict.get(key):
                fields.append(str(verdict[key]))
        return " — prior verdict: " + ", ".join(fields)

    def block(label: str, items: List[Any]) -> List[str]:
        if not items:
            return [f"**{label}:** none in the current window", ""]
        out = [f"**{label}:**"]
        for n in items:
            published = getattr(n, "published_at", None)
            stamp = published.strftime("%Y-%m-%d %H:%M") if published else "unknown time"
            out.append(
                f"- [{stamp}] ({getattr(n, 'source', '?')}) {getattr(n, 'title', '')}{mark(n)}"
            )
        out.append("")
        return out

    lines = block("Crypto headlines", crypto) + block("Equity & macro headlines", stock)

    if verdicts:
        counts = verdicts.get("counts") or {}
        lines += [
            f"**Prior verdicts:** {verdicts['scored']} of {verdicts['total']} headlines carry one "
            f"— {counts.get('bullish', 0)} bullish, {counts.get('bearish', 0)} bearish, "
            f"{counts.get('neutral', 0)} neutral, mean confidence "
            f"{verdicts['mean_confidence']:.2f}.",
        ]
        material = verdicts.get("material") or []
        if material:
            lines.append("")
            lines.append("Judged material:")
            lines += [
                f"- {v['title']} — {v['materiality']}, {v['sentiment']}"
                + (f", expected impact: {v['price_impact']}" if v.get("price_impact") else "")
                for v in material
            ]
        # Both halves of this caveat matter. A verdict is a model's reading of a
        # headline, never a measured outcome; and the pipeline runs when a reader
        # opens an item, so the scored subset is what an audience clicked on, not
        # a sample of the news.
        lines += [
            "",
            "A verdict is this app's own news pipeline judging that headline against price, "
            "technicals and precedent — an opinion on record, not a measured outcome. Verdicts "
            "exist only for headlines a reader has opened, so an unmarked headline is unscored "
            "rather than neutral, and the balance above is not a sentiment reading of the feed.",
        ]

    return "\n".join(lines)


_RENDERERS: List[Tuple[str, Callable[[Dict[str, Any]], Optional[str]]]] = [
    ("Crypto market", _render_crypto),
    ("Sentiment indices", _render_sentiment),
    ("Technical levels", _render_technicals),
    ("Derivatives & liquidity", _render_derivatives),
    ("Equities & indices", _render_equities),
    ("Commodities & macro", _render_macro),
    ("Sector breadth", _render_sectors),
    ("News headlines", _render_news),
]

SECTION_TITLES = [title for title, _ in _RENDERERS]


def render_snapshot_markdown(
    snapshot: Dict[str, Any], sections: Optional[Sequence[str]] = None
) -> str:
    """
    Render the snapshot as the markdown block that gets embedded in every prompt.

    Built once and reused across all three pipeline stages so the model is
    fact-checked against exactly the data it wrote from.

    `sections` restricts the output to the named blocks (see `SECTION_TITLES`);
    the default renders all of them. Chat uses a narrower set to stay inside a
    conversational context window — the data-coverage block is always emitted,
    since a caller must never be left unaware that a feed was missing.
    """
    parts: List[str] = [
        f"SNAPSHOT TAKEN: {snapshot.get('generated_at')}",
        f"REPORT HORIZON: {snapshot.get('timeframe')}",
        "",
    ]

    wanted = None if sections is None else set(sections)
    for title, renderer in _RENDERERS:
        if wanted is not None and title not in wanted:
            continue
        parts += _section(title, renderer(snapshot))

    unavailable = snapshot.get("unavailable") or []
    parts += _section(
        "Data coverage",
        "All feeds returned data."
        if not unavailable
        else "The following feeds were UNAVAILABLE and must be reported as gaps:\n"
        + "\n".join(f"- {name}" for name in unavailable),
    )

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# REGIME SNAPSHOT — the narrow, interactive sibling of build_market_snapshot
# ═══════════════════════════════════════════════════════════════════════════════

# Feeds that answer "what kind of market is this news landing in". Deliberately
# excludes the news feed: on a cold cache `_fetch_news` falls through to
# `fetch_all_news()`, which is a minute of RSS fetching. A news analysis already
# has its headline; what it lacks is the backdrop.
REGIME_FEED_TIMEOUT_SECONDS = 5.0

# The same event reads differently in euphoria than in a drawdown, but the
# backdrop itself does not turn over in seconds. Two minutes of reuse makes
# every click inside that window free.
REGIME_CACHE_TTL_SECONDS = 120

REGIME_LIQUIDATION_WINDOW_SECONDS = 24 * 3600

_regime_cache = ServiceCache(maxsize=8)


async def build_regime_snapshot(
    asset_type: str, *, feed_timeout: float = REGIME_FEED_TIMEOUT_SECONDS
) -> Dict[str, Any]:
    """
    Assemble the market backdrop a single news item is landing in.

    Same partial-degradation contract as `build_market_snapshot`: every feed is
    independent and a failure is named in ``["unavailable"]`` rather than raised.
    Equity feeds are only fetched for equity items — a crypto headline does not
    need the NASDAQ session to be judged, and skipping them halves the fan-out.
    """
    from services.fear_greed_service import fetch_fear_greed_index
    from services.heatmap_service import fetch_heatmap_data
    from services.liquidation_service import liquidation_service
    from services.market_overview_service import fetch_market_overview

    tasks = [
        _safe("crypto_market", fetch_market_overview(), feed_timeout),
        _safe("crypto_fear_greed", fetch_fear_greed_index(), feed_timeout),
        _safe(
            "liquidations",
            liquidation_service.get_heatmap_data(REGIME_LIQUIDATION_WINDOW_SECONDS),
            feed_timeout,
        ),
        _safe("sectors", fetch_heatmap_data(), feed_timeout),
    ]

    if asset_type == "stock":
        from services.stock_market_service import fetch_global_indices, fetch_nasdaq_overview

        tasks += [
            _safe("stock_market", fetch_nasdaq_overview(), feed_timeout),
            _safe("global_indices", fetch_global_indices(), feed_timeout),
        ]

    feeds: Dict[str, Any] = dict(await asyncio.gather(*tasks))

    crypto_market = feeds.get("crypto_market") or {}
    coins = crypto_market.get("coins") or []

    unavailable = [
        FEED_NAMES[name] for name, value in feeds.items() if not value and name in FEED_NAMES
    ]

    return {
        "asset_type": asset_type,
        "generated_at": datetime.now().isoformat(),
        "crypto_market": crypto_market or None,
        "crypto_fear_greed": feeds.get("crypto_fear_greed"),
        "stock_market": feeds.get("stock_market"),
        "global_indices": feeds.get("global_indices"),
        "liquidations": feeds.get("liquidations"),
        "sectors": feeds.get("sectors"),
        "derived": {
            "breadth": _breadth(coins),
            "fear_greed_trend": _fear_greed_trend(feeds.get("crypto_fear_greed")),
            "liquidations": _liquidation_stats(feeds.get("liquidations")),
            "sector_breadth": _sector_breadth(feeds.get("sectors")),
            "movers": _movers(coins),
            "liquidation_window_hours": round(REGIME_LIQUIDATION_WINDOW_SECONDS / 3600),
        },
        "unavailable": unavailable,
    }


def render_regime_markdown(regime: Dict[str, Any]) -> str:
    """
    Render the backdrop for the news prompt.

    Compact by design: this block exists so the model can say "the mechanism is
    bullish but breadth is 18% advancing and Fear & Greed has fallen 14 points",
    not so it can recite the market. It reuses the report renderers, which keeps
    one formatting of a given figure across both pipelines.
    """
    # The report renderers read `timeframe` for headings they do not emit here,
    # and `technicals`/`whales`/`news` which the regime snapshot never collects.
    view = {**regime, "timeframe": "news", "technicals": None, "whales": None}

    blocks: List[str] = []
    for title, renderer in _RENDERERS:
        if title in ("Technical levels", "News headlines"):
            continue
        if title in ("Equities & indices",) and regime.get("asset_type") != "stock":
            continue
        body = renderer(view)
        if body:
            blocks.append(f"### {title}\n{body}")

    header = (
        "MARKET REGIME (current backdrop, independent of this news item). Use it to "
        "judge how the market is positioned to receive this news — a bullish "
        "mechanism lands differently in a defensive tape than in a bid one. These "
        "figures are as admissible as the market data above."
    )

    if not blocks:
        return (
            "MARKET REGIME: not available for this analysis. No breadth, sentiment or "
            "positioning data could be collected — do not characterise the market "
            "backdrop, and report the gap."
        )

    parts = [header, ""] + blocks

    unavailable = regime.get("unavailable") or []
    if unavailable:
        parts += [
            "",
            "Regime feeds UNAVAILABLE (report as gaps): " + ", ".join(unavailable),
        ]

    return "\n".join(parts)


async def cached_regime_markdown(
    asset_type: str, *, feed_timeout: float = REGIME_FEED_TIMEOUT_SECONDS
) -> str:
    """`build_regime_snapshot` + `render_regime_markdown`, memoised per asset type."""
    key = f"news_regime:{asset_type}"
    cached = _regime_cache.get(key)
    if cached is not None:
        return cached

    rendered = render_regime_markdown(
        await build_regime_snapshot(asset_type, feed_timeout=feed_timeout)
    )
    _regime_cache.set(key, rendered, ttl=REGIME_CACHE_TTL_SECONDS)
    return rendered
