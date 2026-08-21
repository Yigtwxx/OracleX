"""
Nothing Ever Happens Index.

A companion novelty to the Pentagon Pizza Index and from the same publisher:
where that one reads pizza queues, this one reads Polymarket. The source keeps a
curated basket of high-impact geopolitical markets — strikes, invasions, nuclear
escalation, regime change — and the index is how close the most likely of them
has come to happening.

The reading is derived here rather than copied. The upstream JSON carries the
raw per-market probabilities and computes its gauge in the browser; recomputing
from those probabilities keeps the number ours, so a change in how the source
renders itself cannot silently redefine what the panel claims. The rule mirrors
the source's own and is deliberately not an average:

  * The index is the **highest** probability in the basket, not the mean. A
    basket of 27 mostly-dormant markets averages to a permanent low number that
    never moves; the point of the gauge is the one market that is moving.
  * `lowVolume` markets are excluded. The source separates them because a 2%
    print on a market with no depth is a quote, not a probability, and folding
    it in would let an untraded market set the headline.

Never a 0–100 sentiment score in disguise: the number *is* a probability in
percent — "the most likely tracked catastrophe currently sits at 27%" — and the
bands below are the source's own, so our label and its label cannot disagree.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Optional

from services.cache import home_cache
from services.http_client import get_json

logger = logging.getLogger(__name__)

# The human page, for the panel's attribution link. The data lives on the
# endpoint that page's client calls; both are the same origin, and the health
# registry already maps that host to `macro`.
SOURCE_URL = "https://www.pizzint.watch/nothingeverhappens"
DATA_URL = "https://www.pizzint.watch/api/neh-index/doomsday"
SOURCE_NAME = "pizzint.watch"

CACHE_KEY = "neh_index"
# Prediction-market odds move continuously, but this reading sits in a hover
# panel that is opened for a few seconds at a time. Two minutes is fresh enough
# to be honest and slow enough that repeated hovers cost one request.
TTL_SECONDS = 120
# How old a replayed reading may be. Past an hour the basket may have resolved
# or re-weighted, which makes it a claim about a different world.
MAX_STALE_SECONDS = 3600

# The source's own bands, upper bound inclusive. Kept in this order and read
# top-down by `_classify`, so the boundaries cannot drift apart from the labels.
BANDS: tuple[tuple[int, str, str], ...] = (
    (29, "calm", "Nothing Ever Happens"),
    (64, "watch", "Something Might Happen"),
    (98, "happening", "Something Is Happening"),
    (100, "happened", "It Happened"),
)

STATUS_LABELS = {key: label for _, key, label in BANDS} | {
    "unavailable": "Unavailable",
}


class NehSourceUnavailable(Exception):
    """The source could not be read, or carried nothing recognisable."""


# ── Scoring ─────────────────────────────────────────────────────────────────


def _classify(index: int) -> str:
    for upper, key, _ in BANDS:
        if index <= upper:
            return key
    return BANDS[-1][1]


def _probability(market: Any) -> Optional[float]:
    """
    A market's `price` as a probability, or None where it is not one.

    Polymarket prices a binary share between 0 and 1, so anything outside that
    range is a parsing accident rather than a long shot, and is dropped instead
    of being clamped into a plausible-looking reading.
    """
    if not isinstance(market, dict):
        return None
    price = market.get("price")
    if not isinstance(price, (int, float)) or isinstance(price, bool):
        return None
    if not 0.0 <= float(price) <= 1.0:
        return None
    return float(price)


def _market_row(market: dict[str, Any], probability: float) -> dict[str, Any]:
    return {
        "slug": market.get("slug"),
        "label": market.get("label"),
        "region": market.get("region"),
        "probability": round(probability, 4),
    }


def score(markets: list[Any]) -> dict[str, Any]:
    """
    The full payload for a fetched basket.

    `markets` is the tradeable basket only — the caller drops `lowVolume` before
    calling, because whether a market is thin is the source's judgement and not
    something to re-derive from a volume field that may not survive a schema
    change.
    """
    scored = [(market, p) for market in markets if (p := _probability(market)) is not None]

    if not scored:
        # A 200 carrying no usable market is a restructured payload, not a calm
        # world. Reported as an outage for the same reason the pizza scrape is.
        raise NehSourceUnavailable("no usable markets in the source payload")

    top_market, top_probability = max(scored, key=lambda pair: pair[1])
    index = round(top_probability * 100)
    status = _classify(index)

    return {
        "index": index,
        "status": status,
        "label": STATUS_LABELS[status],
        "top": _market_row(top_market, top_probability),
        # The sample size, so the panel can say what the number was drawn from
        # rather than presenting one market's odds as a survey of the world.
        "markets_tracked": len(scored),
        "as_of": datetime.now(UTC).isoformat(),
        "stale": False,
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
    }


# ── Fetch ───────────────────────────────────────────────────────────────────


async def _fetch_and_score() -> dict[str, Any]:
    payload = await get_json(DATA_URL)
    if not isinstance(payload, dict):
        raise NehSourceUnavailable("source payload was not an object")
    markets = payload.get("markets")
    if not isinstance(markets, list):
        raise NehSourceUnavailable("source payload carried no market list")
    return score(markets)


def _unavailable() -> dict[str, Any]:
    """The empty reading, for when there is not even a stale one to replay."""
    return {
        "index": None,
        "status": "unavailable",
        "label": STATUS_LABELS["unavailable"],
        "top": None,
        "markets_tracked": 0,
        "as_of": datetime.now(UTC).isoformat(),
        "stale": False,
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
    }


async def fetch_neh_index() -> dict[str, Any]:
    """
    The Nothing Ever Happens Index, cached and stale-tolerant.

    Never raises, for the same reason `fetch_pizza_index` never does: it shares a
    panel with that gauge, and one novelty failing must not blank the other or
    the chrome they both live in.
    """
    cached = home_cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    try:
        payload = await _fetch_and_score()
    except Exception as e:
        logger.warning("Nothing Ever Happens Index unavailable: %s", e)
        stale = home_cache.get_with_fallback(CACHE_KEY, max_age=MAX_STALE_SECONDS)
        if stale is not None:
            return {**stale, "stale": True}
        return _unavailable()

    home_cache.set(CACHE_KEY, payload, TTL_SECONDS)
    return payload
