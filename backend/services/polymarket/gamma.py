"""
Gamma — what markets exist, and what each one is asking.

Gamma is the only required upstream: a market with no metadata cannot be
rendered at all, while a missing holder table or price history is a gap the page
can name and carry on around.

**The JSON-string trap.** Gamma returns `outcomes`, `outcomePrices` and
`clobTokenIds` as JSON-encoded *strings*, not arrays — the field holds
`'["Yes", "No"]'`, so `market["outcomePrices"][0]` yields the character `[`
rather than a price. Nothing about this fails loudly; it produces plausible
garbage. Everything crossing this boundary goes through `_maybe_json`.

Tags only arrive when the market was fetched with `include_tag=true`, and they
are what settles a market's category with any confidence — 379 of 400 live
markets were classified off a tag and only 21 fell through to keywords. The flag
is therefore not an optimisation, and the listing call always sets it.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, UTC
from typing import Any

from config import settings
from models.polymarket import MarketSummary, Outcome
from services.http_client import get_json
from services.polymarket.category import infer_category
from services.polymarket.registry import GAMMA_MARKETS, METADATA_TIMEOUT

logger = logging.getLogger(__name__)


def _maybe_json(value: Any) -> list[Any]:
    """
    Coerce Gamma's JSON-encoded array fields into real lists.

    Tolerates all three shapes seen in the wild: a proper list, a JSON string,
    and a bare comma-separated string. Returns [] rather than raising — a
    market whose outcomes cannot be read is a market we decline to price, not
    an exception that takes the board down with it.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                logger.warning("Gamma returned an unparseable array field: %.80s", text)
                return []
        return [part.strip() for part in text.split(",") if part.strip()]
    return []


def as_float(value: Any) -> float | None:
    """None, not 0.0, when a figure is absent — the house rule for Unknown."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_utc(moment: datetime | None) -> datetime | None:
    """Gamma is consistent about UTC; a naive value would still break maths."""
    if moment is None:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def parse_market(raw: dict[str, Any]) -> MarketSummary | None:
    """
    One Gamma market as a board row, or None when it cannot be read.

    Declining is deliberate. A market rendered with no outcomes and no price is
    a row that says nothing and invites the reader to think the market itself is
    empty rather than that we failed to parse it.
    """
    market_id = str(raw.get("id") or "").strip()
    slug = str(raw.get("slug") or "").strip()
    question = str(raw.get("question") or "").strip()
    if not market_id or not question:
        return None

    labels = [str(label) for label in _maybe_json(raw.get("outcomes"))]
    prices = [as_float(price) for price in _maybe_json(raw.get("outcomePrices"))]
    tokens = [str(token) for token in _maybe_json(raw.get("clobTokenIds"))]

    outcomes = [
        Outcome(
            label=label,
            price=prices[i] if i < len(prices) else None,
            token_id=tokens[i] if i < len(tokens) else None,
        )
        for i, label in enumerate(labels)
    ]

    tags = tuple(
        str(tag.get("slug", "")) for tag in (raw.get("tags") or []) if isinstance(tag, dict)
    )
    verdict = infer_category(question, str(raw.get("description") or ""), tags)

    events = raw.get("events") or []
    event_slug = None
    if events and isinstance(events[0], dict):
        event_slug = events[0].get("slug")

    return MarketSummary(
        market_id=market_id,
        slug=slug,
        question=question,
        category=verdict.category,
        outcomes=outcomes,
        volume_usd=as_float(raw.get("volumeNum")) or as_float(raw.get("volume")),
        liquidity_usd=as_float(raw.get("liquidityNum")) or as_float(raw.get("liquidity")),
        end_date=_to_utc(_as_datetime(raw.get("endDate"))),
        created_at=_to_utc(_as_datetime(raw.get("createdAt"))),
        closed=bool(raw.get("closed")),
        icon_url=raw.get("icon") or None,
        event_slug=event_slug,
    )


async def fetch_markets(limit: int = 60, offset: int = 0) -> list[dict[str, Any]]:
    """Active, open markets by 24-hour volume. Raises; the caller owns fallback."""
    payload = await get_json(
        f"{settings.POLYMARKET_GAMMA_URL}{GAMMA_MARKETS}",
        params={
            "active": "true",
            "closed": "false",
            "archived": "false",
            "order": "volume24hr",
            "ascending": "false",
            "limit": limit,
            "offset": offset,
            # Not an optimisation — see the module docstring.
            "include_tag": "true",
        },
        timeout=METADATA_TIMEOUT,
    )
    return payload if isinstance(payload, list) else []


async def fetch_market_by_slug(slug: str) -> dict[str, Any] | None:
    """
    One market by its slug, or None when nothing matches.

    Gamma has no by-slug route, so this is the listing filtered server-side.
    None here becomes a 404 rather than an empty market: an unresolvable slug is
    a question we cannot answer, not a market with nothing in it.
    """
    payload = await get_json(
        f"{settings.POLYMARKET_GAMMA_URL}{GAMMA_MARKETS}",
        params={"slug": slug, "limit": 1, "include_tag": "true"},
        timeout=METADATA_TIMEOUT,
    )
    if isinstance(payload, list) and payload:
        return payload[0]
    return None
