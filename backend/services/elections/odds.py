"""
Polymarket's election markets, reduced to what the board can use.

Two constraints shape this module.

**Only `/events?tag_slug=elections` filters.** The `/markets` listing accepts the
same parameter, answers 200, and ignores it — a probe returned Premier League
fixtures and League of Legends matches under `tag_slug=elections`. The events
route is therefore the only usable entry point, and its payload is heavy: about
4.3MB for thirty events, because each one embeds every nested market with its
full description. `summarise_event` throws that away immediately so only the
summaries are ever cached, and the scheduler warms the cache so the download
never sits inside a request.

**The listing is ordered by volume, so it is a coverage cap, not a filter.**
Asking for the forty loudest election markets on Earth leaves most calendar rows
with no candidate at all. That is honest only if the board says so, which is why
the cap travels out in the payload rather than living here as a private number.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from config import settings
from services.http_client import get_json
from services.polymarket import gamma
from services.polymarket.registry import GAMMA_EVENTS

logger = logging.getLogger(__name__)

# The body is measured in megabytes; the shared 10s default is a coin flip on a
# slow link, and a timeout here costs the whole odds layer.
FETCH_TIMEOUT = 25.0

# How many outcomes a row shows before it stops being a board and starts being a
# table. The rest are counted, not dropped silently.
MAX_OUTCOMES = 4

# Polymarket seeds an event with unnamed legs before the field is known, and
# they trade at exactly 0.50 because nobody can price a letter. Nigeria's
# presidential market carries "Candidate A" and "Candidate B" beside a real
# name. They are not candidates, and a board that lists them as joint favourites
# is reporting a race that does not exist.
_PLACEHOLDER_OUTCOME = re.compile(r"^candidate\s+[a-z0-9]$", re.IGNORECASE)


@dataclass(frozen=True)
class Outcome:
    label: str
    # Deliberately "price", not "probability". An event's markets may be
    # mutually exclusive, independent, or margin buckets, so a set of them can
    # legitimately sum to well over 100%. Calling these probabilities would
    # invite a total that means nothing — see the module note in join.py.
    price: float
    change_1w: float | None


@dataclass(frozen=True)
class EventSummary:
    """One Polymarket event, stripped to the ten fields the board reads."""

    slug: str
    title: str
    url: str
    country_name: str | None
    election_type: str | None
    tag_slugs: tuple[str, ...]
    end_date: datetime | None
    volume_24h: float
    liquidity: float
    outcomes: tuple[Outcome, ...]
    others: int
    # True when Gamma marks the event negative-risk, which is its own statement
    # that the outcomes are mutually exclusive. Kept because it is the only
    # honest way to know whether the prices are a distribution.
    exclusive: bool


async def fetch_election_events(limit: int | None = None) -> list[dict[str, Any]]:
    """
    Open election events by 24-hour volume. Raises; the caller owns fallback.

    An empty list is raised rather than returned. Gamma's tag taxonomy churns —
    this repo already tracks six election slugs in
    `services/polymarket/registry.py` — and a renamed tag answers 200 with
    nothing in it. Reporting that as "no election markets exist" would be a
    claim about the world made out of a broken query string.
    """
    payload = await get_json(
        f"{settings.POLYMARKET_GAMMA_URL}{GAMMA_EVENTS}",
        params={
            "closed": "false",
            "archived": "false",
            "order": "volume24hr",
            "ascending": "false",
            "tag_slug": "elections",
            "limit": limit or settings.ELECTIONS_ODDS_LIMIT,
        },
        timeout=FETCH_TIMEOUT,
    )
    events = payload if isinstance(payload, list) else []
    if not events:
        raise ValueError("polymarket returned no election events")
    return events


def summarise_event(raw: dict[str, Any]) -> EventSummary | None:
    """
    One event reduced to a summary, or None when it carries nothing priceable.

    Called once per event and never per candidate pairing: the country matching
    downstream compiles ~174 regexes per call, and running it inside the join's
    nested loop would be roughly a million regex executions per refresh.
    """
    slug = raw.get("slug")
    title = raw.get("title")
    if not isinstance(slug, str) or not isinstance(title, str):
        return None

    outcomes = _outcomes(raw.get("markets") or [])
    if not outcomes:
        return None

    tags = tuple(
        tag.get("slug", "")
        for tag in (raw.get("tags") or [])
        if isinstance(tag, dict) and tag.get("slug")
    )

    return EventSummary(
        slug=slug,
        title=title,
        url=f"https://polymarket.com/event/{slug}",
        country_name=(raw.get("countryName") or None),
        election_type=(raw.get("electionType") or None),
        tag_slugs=tags,
        end_date=gamma._to_utc(gamma._as_datetime(raw.get("endDate"))),
        volume_24h=gamma.as_float(raw.get("volume24hr")) or 0.0,
        liquidity=gamma.as_float(raw.get("liquidity")) or 0.0,
        outcomes=outcomes[:MAX_OUTCOMES],
        others=max(0, len(outcomes) - MAX_OUTCOMES),
        exclusive=bool(raw.get("negRisk") or raw.get("negRiskMarketID")),
    )


def _outcomes(markets: list[Any]) -> tuple[Outcome, ...]:
    """
    Each nested market's Yes leg, highest first.

    The Yes leg is found by *label*, never by position. Gamma is consistent
    about ordering today, and a silently reversed pair would render the
    least-likely candidate as the favourite with nothing to indicate it.
    """
    priced: list[Outcome] = []
    for market in markets:
        if not isinstance(market, dict):
            continue
        labels = gamma._maybe_json(market.get("outcomes"))
        prices = gamma._maybe_json(market.get("outcomePrices"))
        price = _yes_price(labels, prices)
        if price is None:
            continue
        label = (market.get("groupItemTitle") or market.get("question") or "").strip()
        if not label or _PLACEHOLDER_OUTCOME.match(label):
            continue
        priced.append(
            Outcome(
                label=label,
                price=price,
                change_1w=gamma.as_float(market.get("oneWeekPriceChange")),
            )
        )

    priced.sort(key=lambda outcome: outcome.price, reverse=True)
    return tuple(priced)


def _yes_price(labels: list[Any], prices: list[Any]) -> float | None:
    for index, label in enumerate(labels):
        if isinstance(label, str) and label.strip().lower() == "yes" and index < len(prices):
            return gamma.as_float(prices[index])
    return None
