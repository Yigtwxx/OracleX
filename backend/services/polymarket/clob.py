"""
CLOB — what a market costs, and what it cost before.

The price history is the input to `moves.detect_sharp_moves`, which is what
turns "why does this market exist?" into a dated question a news search can
answer. Everything here is therefore in service of getting a clean, evenly
spaced series out of an upstream that will happily return duplicates.

One naming trap: the `market` query parameter on `/prices-history` takes a CLOB
**token id** — one per outcome, from Gamma's `clobTokenIds` — and not the
`conditionId` that the data API calls a market. Passing the condition id returns
an empty history rather than an error, which reads as "this market never moved".
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC
from typing import Any

from config import settings
from models.polymarket import PricePoint
from services.http_client import get_json
from services.polymarket.registry import (
    CLOB_PRICES_HISTORY,
    HISTORY_FIDELITY_MINUTES,
    HISTORY_TIMEOUT,
)

logger = logging.getLogger(__name__)


def parse_history(payload: Any) -> list[PricePoint]:
    """
    CLOB's `{"history": [{"t": epoch, "p": price}]}` as points.

    Malformed rows are skipped rather than defaulted. A point with no timestamp
    cannot be placed on the axis, and placing it at zero would put a spike at
    the epoch — a move detector's worst possible input.
    """
    rows = payload.get("history") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []

    points: list[PricePoint] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        stamp, price = row.get("t"), row.get("p")
        if stamp is None or price is None:
            continue
        try:
            points.append(
                PricePoint(
                    t=datetime.fromtimestamp(int(stamp), tz=UTC),
                    p=float(price),
                )
            )
        except (TypeError, ValueError, OSError, OverflowError):
            continue
    return points


async def fetch_history(
    token_id: str,
    *,
    interval: str = "max",
    fidelity_minutes: int = HISTORY_FIDELITY_MINUTES,
) -> list[PricePoint]:
    """Price history for one outcome token. Raises; the caller owns fallback."""
    payload = await get_json(
        f"{settings.POLYMARKET_CLOB_URL}{CLOB_PRICES_HISTORY}",
        params={"market": token_id, "interval": interval, "fidelity": fidelity_minutes},
        timeout=HISTORY_TIMEOUT,
    )
    return parse_history(payload)
