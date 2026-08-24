"""
Three layers over one world map, each labelled with what it actually is.

This module exists because the obvious version of this feature cannot be built.
"Where did the money come from" is the question everyone asks of a prediction
market, and Polymarket cannot answer it: the exchange is non-custodial on
Polygon, a counterparty is a `proxyWallet`, and no public endpoint anywhere
carries a trader's location. Any country-by-country breakdown of betting volume
would be invented.

So the map shows three different things that are true, and says which is which:

**measured** — where Polymarket may legally be traded from. Transcribed from
Polymarket's own published geoblock lists.

**derived** — where each market's *subject* is. The volume is a real
measurement; attaching it to a country is a rule applied to the question's text,
which is why it is not called measured.

**estimated** — when the trading happened, by hour of the UTC day. The timestamps
are real and the inference from them is weak: an hour of day spans a dozen
countries, and prediction-market flow is disproportionately nocturnal and
bot-assisted. It is rendered as bands over the map rather than as country
shading, because shading would state a country share that this data cannot
support.

The three are not merged, ranked or averaged into a single score. A reader has to
be able to tell them apart, and the only thing that lets them is keeping them
separate.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from services.cache import ServiceCache
from services.polymarket import data_api, gamma, jurisdictions
from services.polymarket.facts import trade_activity_hours
from services.polymarket.geography import CENTROIDS, countries_in
from services.polymarket.service import get_board

logger = logging.getLogger(__name__)

_cache = ServiceCache(maxsize=8)
MAP_KEY = "polymarket_map"
#: Five minutes. The jurisdiction layer never moves, the subject layer follows
#: the board, and the activity layer is a shape rather than a number — none of
#: them is improved by being a minute fresher, and the trade tapes behind the
#: third are the most expensive thing this endpoint fetches.
MAP_TTL_SECONDS = 300
MAP_MAX_STALE_SECONDS = 3600

#: How many markets contribute their trade tape to the activity histogram.
#: The shape stops changing well before this; every extra market is a round trip.
ACTIVITY_SAMPLE_MARKETS = 8
TRADES_PER_MARKET = 300


async def _subject_layer(markets: list[dict]) -> dict:
    """Volume by the country a market is *about*."""
    by_country: dict[str, dict] = {}

    for market in markets:
        names = countries_in(market.get("question", ""))
        if not names:
            continue
        volume = market.get("volume_usd") or 0.0
        # Split rather than duplicated: a market about both China and Taiwan is
        # one pot of money, and crediting the full amount to each would double
        # the total and make two-country questions look twice as big as they are.
        share = volume / len(names)
        for name in names:
            point = CENTROIDS.get(name)
            if point is None:
                continue
            entry = by_country.setdefault(
                name,
                {
                    "country": name,
                    "lon": point[0],
                    "lat": point[1],
                    "volume_usd": 0.0,
                    "market_count": 0,
                    "markets": [],
                },
            )
            entry["volume_usd"] += share
            entry["market_count"] += 1
            if len(entry["markets"]) < 5:
                entry["markets"].append(
                    {
                        "slug": market.get("slug"),
                        "question": market.get("question"),
                        "category": market.get("category"),
                    }
                )

    rows = sorted(by_country.values(), key=lambda r: r["volume_usd"], reverse=True)
    for row in rows:
        row["volume_usd"] = round(row["volume_usd"], 2)

    return {
        "provenance": "derived",
        "note": (
            "Volume is measured. The country is inferred from the question's own "
            "wording — this is where a bet is about, not where it came from."
        ),
        "countries": rows,
    }


async def _activity_layer(markets: list[dict]) -> dict:
    """Traded value by hour of the UTC day, across the busiest markets."""
    sample = markets[:ACTIVITY_SAMPLE_MARKETS]
    slugs = [m.get("slug") for m in sample]

    async def tape(slug: str) -> list[dict]:
        raw = await gamma.fetch_market_by_slug(slug)
        condition_id = str((raw or {}).get("conditionId") or "")
        if not condition_id:
            return []
        return await data_api.fetch_trades(condition_id, TRADES_PER_MARKET)

    tasks = [asyncio.create_task(tape(s)) for s in slugs if s]
    done, pending = await asyncio.wait(tasks, timeout=20.0)
    for task in pending:
        task.cancel()

    buckets: dict[int, float] = defaultdict(float)
    sampled = 0
    for task in done:
        try:
            trades = task.result()
        except Exception:  # noqa: BLE001 — one dead tape costs one market
            continue
        if not trades:
            continue
        sampled += 1
        for hour, value in trade_activity_hours(trades).items():
            buckets[hour] += value

    total = sum(buckets.values())
    hours = [
        {
            "hour": hour,
            "value_usd": round(buckets.get(hour, 0.0), 2),
            "share": round(buckets.get(hour, 0.0) / total, 4) if total else 0.0,
        }
        for hour in range(24)
    ]

    return {
        "provenance": "estimated",
        "note": (
            "When the money moved, by hour of the UTC day. The timestamps are "
            "measured; where the traders were is not knowable from them. An hour "
            "of day spans a dozen countries, so no country share is derived."
        ),
        "markets_sampled": sampled,
        "hours": hours,
    }


async def build_map() -> dict:
    """The three layers, cached. Never raises for a partial failure."""
    cached = _cache.get(MAP_KEY)
    if cached is not None:
        return cached

    board = await get_board()
    markets = board.get("markets") or []

    subject, activity = await asyncio.gather(
        _subject_layer(markets),
        _activity_layer(markets),
        return_exceptions=True,
    )

    if isinstance(subject, BaseException):
        logger.warning("Polymarket subject layer failed: %s", subject)
        subject = {"provenance": "derived", "countries": [], "note": "Could not be built."}
    if isinstance(activity, BaseException):
        logger.warning("Polymarket activity layer failed: %s", activity)
        activity = {
            "provenance": "estimated",
            "hours": [],
            "markets_sampled": 0,
            "note": "Could not be built.",
        }

    payload = {
        "jurisdictions": jurisdictions.as_layer(),
        "subjects": subject,
        "activity": activity,
        "market_count": len(markets),
    }
    _cache.set(MAP_KEY, payload, MAP_TTL_SECONDS)
    return payload


def invalidate() -> None:
    _cache.clear()
