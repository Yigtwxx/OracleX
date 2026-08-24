"""
Data API — who is holding this market, and who has been trading it.

Concentration is the reading this exists for. A price of 0.62 set by four
hundred wallets and a price of 0.62 set by one whale who bought the book are the
same number and different facts, and the holder table is the only place that
difference shows up.

**Names are opt-in.** Every holder and trade carries a `pseudonym`, a `name` and
a `displayUsernamePublic` flag, and when that flag is false the `name` field is
simply the wallet address repeated. Rendering it as a display name would present
an address as though its owner had chosen to be identified. The flag is
honoured here rather than in the UI, so no consumer can get it wrong.

`/holders` and `/trades` both key on `conditionId`, not on the CLOB token id
that `clob.fetch_history` wants. The two identifiers are not interchangeable and
neither upstream errors when given the other.
"""

from __future__ import annotations

import logging
from typing import Any

from config import settings
from models.polymarket import Holder
from services.http_client import get_json
from services.polymarket.registry import (
    DATA_HOLDERS,
    DATA_TRADES,
    HOLDERS_TIMEOUT,
    TRADES_TIMEOUT,
)

logger = logging.getLogger(__name__)

#: The upstream caps this at 20 per outcome and ignores anything larger.
HOLDERS_LIMIT = 20


def _display_name(row: dict[str, Any]) -> str | None:
    """A name only when its owner chose to publish one. See module docstring."""
    if not row.get("displayUsernamePublic"):
        return None
    name = (row.get("name") or row.get("pseudonym") or "").strip()
    wallet = (row.get("proxyWallet") or "").strip()
    # Some rows set the flag but leave `name` as the address anyway.
    if not name or name.lower() == wallet.lower():
        return None
    return name


def parse_holders(payload: Any, outcome_labels: list[str]) -> list[Holder]:
    """
    Flatten the per-token holder lists into one table.

    `outcomeIndex` is mapped back to the outcome's label so a reader can see
    which side a wallet is on; an index alone is meaningless once the rows from
    both tokens sit in the same list.
    """
    if not isinstance(payload, list):
        return []

    holders: list[Holder] = []
    for group in payload:
        if not isinstance(group, dict):
            continue
        for row in group.get("holders") or []:
            if not isinstance(row, dict):
                continue
            wallet = (row.get("proxyWallet") or "").strip()
            if not wallet:
                continue
            index = row.get("outcomeIndex")
            label = (
                outcome_labels[index]
                if isinstance(index, int) and 0 <= index < len(outcome_labels)
                else None
            )
            try:
                shares = float(row.get("amount")) if row.get("amount") is not None else None
            except (TypeError, ValueError):
                shares = None
            holders.append(
                Holder(
                    wallet=wallet,
                    display_name=_display_name(row),
                    outcome_label=label,
                    shares=shares,
                )
            )

    holders.sort(key=lambda h: h.shares or 0.0, reverse=True)
    return holders


async def fetch_holders(condition_id: str, outcome_labels: list[str]) -> list[Holder]:
    """Top holders per outcome. Raises; the caller owns fallback."""
    payload = await get_json(
        f"{settings.POLYMARKET_DATA_URL}{DATA_HOLDERS}",
        params={"market": condition_id, "limit": HOLDERS_LIMIT},
        timeout=HOLDERS_TIMEOUT,
    )
    return parse_holders(payload, outcome_labels)


async def fetch_trades(condition_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """
    Recent trades, newest first.

    Returned raw. The only consumer is the activity-hour histogram, which needs
    `timestamp` and `size` and nothing else, and a typed model here would be
    four fields of ceremony around a list this module does not interpret.
    """
    payload = await get_json(
        f"{settings.POLYMARKET_DATA_URL}{DATA_TRADES}",
        params={"market": condition_id, "limit": limit, "takerOnly": "true"},
        timeout=TRADES_TIMEOUT,
    )
    return payload if isinstance(payload, list) else []
