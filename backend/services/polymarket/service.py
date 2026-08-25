"""
The prediction-market board, and one market's facts.

Cache policy follows the shape of the data rather than a house default. Odds can
move in a second, but a board of sixty rows re-fetched every second would spend
the rate limit on rows nobody is reading, so the board holds for fifteen
seconds — long enough to absorb a page of users arriving at once, short enough
that a price on screen is never a minute old. The stale fallback is longer: a
board replayed from two minutes ago with its age shown is worth more than an
empty screen, because the questions and their rough odds are still true.

Nothing here raises for an upstream failure. A dead Gamma is reported as an
outage by the router, and everything below it degrades to a named gap.
"""

from __future__ import annotations

import logging

from config import settings
from models.polymarket import MarketFacts, MarketSummary, Microstructure
from services.cache import ServiceCache
from services.polymarket import facts as facts_stage
from services.polymarket import gamma

logger = logging.getLogger(__name__)

_cache = ServiceCache(maxsize=64)

BOARD_KEY = "polymarket_board"
BOARD_TTL_SECONDS = 15
#: Past this the odds on screen are wrong in a way a reader would act on.
BOARD_MAX_STALE_SECONDS = 120

MARKET_TTL_SECONDS = 10
MARKET_MAX_STALE_SECONDS = 90


class UpstreamUnavailable(RuntimeError):
    """Gamma could not be reached and no cached board exists."""


async def get_board() -> dict:
    """
    Active markets by 24-hour volume, newest prices first.

    Returns a payload carrying its own staleness so the UI can say "2 minutes
    old" rather than implying the numbers are live.
    """
    cached = _cache.get(BOARD_KEY)
    if cached is not None:
        return cached

    try:
        raw = await gamma.fetch_markets(limit=settings.POLYMARKET_BOARD_LIMIT)
    except Exception as error:  # noqa: BLE001 — every upstream fault degrades alike
        logger.warning("Polymarket board fetch failed: %s", error)
        stale = _cache.get_with_fallback(BOARD_KEY, max_age=BOARD_MAX_STALE_SECONDS)
        if stale is not None:
            age = _cache.get_fallback_age(BOARD_KEY)
            return {**stale, "stale": True, "age_seconds": int(age or 0)}
        raise UpstreamUnavailable("Polymarket is unreachable") from error

    markets: list[MarketSummary] = []
    for row in raw:
        parsed = gamma.parse_market(row)
        # A row that cannot be parsed is dropped rather than rendered blank: an
        # empty question with no odds reads as a broken market rather than as a
        # market we failed to read.
        if parsed is not None and parsed.outcomes:
            markets.append(parsed)

    payload = {
        "markets": [m.model_dump(mode="json") for m in markets],
        "count": len(markets),
        "stale": False,
        "age_seconds": 0,
    }
    _cache.set(BOARD_KEY, payload, BOARD_TTL_SECONDS)
    return payload


async def get_market_facts(
    slug: str,
    *,
    include_trades: bool = True,
) -> tuple[MarketFacts, Microstructure, dict] | None:
    """
    One market's facts and microstructure, or None when the slug resolves to
    nothing.

    None is a 404 at the router, never an empty market. An unresolvable slug is
    a question we cannot answer; rendering it as a market with no outcomes would
    answer it wrongly.
    """
    key = f"polymarket_market:{slug}:{include_trades}"
    cached = _cache.get(key)
    if cached is not None:
        return cached

    raw = await gamma.fetch_market_by_slug(slug)
    if raw is None:
        return None

    market_facts, micro = await facts_stage.gather_facts(raw, include_trades=include_trades)
    result = (market_facts, micro, raw)
    _cache.set(key, result, MARKET_TTL_SECONDS)
    return result


def invalidate() -> None:
    """Drop every cached board and market. Used by tests and the admin refresh."""
    _cache.clear()
