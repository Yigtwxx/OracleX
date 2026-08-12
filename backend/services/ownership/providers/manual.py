"""
Figures copied by hand out of a published report.

This provider exists because the interesting part of "what does Berkshire hold"
is not in any API. A 13F lists US-listed long equity and nothing else — no cash,
no gold, no bonds, no foreign listings. The $300bn+ cash pile that everyone
actually means when they ask is a line in a 10-Q, and the only way onto this
board is for a person to read it and type it in.

That makes this the one place where a wrong number cannot be blamed on an
upstream, so two rules are enforced rather than encouraged:

A row without a `source_url` and an `as_of` is rejected outright. A hand-typed
figure with no filing behind it is indistinguishable from an invented one, and
the whole page rests on every number being checkable.

A row retires itself. Hand-maintained data does not get corrected when it goes
out of date, it just quietly keeps being displayed — so a figure past
`STALE_AFTER_MONTHS` is marked, and past `EXPIRE_AFTER_MONTHS` it stops being
served at all and the cell goes back to saying Unknown. Silence is the honest
end state for maintenance nobody did.
"""

import logging
import os
from datetime import UTC, date, datetime
from typing import Any

from models.ownership import Position, SourceRef
from services.asset_registry import REGISTRY_DIR, read_json_cache
from services.ownership.providers.base import EntityConfig, ProviderResult

logger = logging.getLogger(__name__)

KIND = "manual"

# Owned here rather than in registry.py: that module imports providers.base, so
# reaching back into it for a path would close an import cycle.
MANUAL_POSITIONS_FILE = os.path.join(REGISTRY_DIR, "ownership_manual_positions.json")

VALID_ASSET_CLASSES = {
    "equity",
    "crypto",
    "cash",
    "gold",
    "fx_reserve",
    "bond",
    "fund",
    "other",
}

# Past this the figure is shown but visibly aged.
STALE_AFTER_MONTHS = 18
# Past this it is withheld. An unmaintained number is worse than no number,
# because it still looks like a measurement.
EXPIRE_AFTER_MONTHS = 36


def _months_since(when: date) -> float:
    return (date.today() - when).days / 30.44


def _parse_date(raw: Any) -> date | None:
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _coerce(raw: Any, retrieved_at: datetime) -> tuple[str, Position] | None:
    """One manual row into (group, Position), or None if it cannot be trusted."""
    if not isinstance(raw, dict):
        return None

    group = raw.get("group")
    key = raw.get("key")
    label = raw.get("label")
    asset_class = raw.get("asset_class")

    if not isinstance(group, str) or not group:
        logger.warning("Manual positions: row without a group — skipped")
        return None
    if not isinstance(key, str) or not key or not isinstance(label, str) or not label:
        logger.warning("Manual positions: %s row missing key/label — skipped", group)
        return None
    if asset_class not in VALID_ASSET_CLASSES:
        logger.warning(
            "Manual positions: %s/%s has unknown asset_class %r — skipped", group, key, asset_class
        )
        return None

    source_url = raw.get("source_url")
    as_of = _parse_date(raw.get("as_of"))
    if not isinstance(source_url, str) or not source_url.startswith("http"):
        logger.warning(
            "Manual positions: %s/%s has no source_url — skipped. A hand-entered "
            "figure without a citation cannot be told apart from an invented one.",
            group,
            key,
        )
        return None
    if as_of is None:
        logger.warning("Manual positions: %s/%s has no valid as_of date — skipped", group, key)
        return None

    age_months = _months_since(as_of)
    if age_months > EXPIRE_AFTER_MONTHS:
        logger.info(
            "Manual positions: %s/%s is %.0f months old — withheld, the cell reverts to Unknown",
            group,
            key,
            age_months,
        )
        return None

    quantity = raw.get("quantity")
    value_usd = raw.get("value_usd")
    note = raw.get("note")
    if age_months > STALE_AFTER_MONTHS:
        aged = f"Last reported {as_of.year}."
        note = f"{note} {aged}".strip() if note else aged

    position = Position(
        key=key,
        label=label,
        symbol=raw.get("symbol"),
        asset_class=asset_class,  # type: ignore[arg-type]
        quantity=float(quantity) if isinstance(quantity, (int, float)) else None,
        quantity_unit=raw.get("quantity_unit"),
        value_usd=float(value_usd) if isinstance(value_usd, (int, float)) else None,
        # The company published this exact figure. We did not compute it.
        value_basis="reported" if isinstance(value_usd, (int, float)) else "unknown",
        source=SourceRef(
            kind=KIND,
            label=str(raw.get("source_label") or "Company filing"),
            url=source_url,
            as_of=as_of,
            retrieved_at=retrieved_at,
            manual=True,
        ),
        note=note,
    )
    return group, position


def load_groups() -> dict[str, list[Position]]:
    """Every valid manual position, bucketed by the group an entity claims."""
    payload = read_json_cache(MANUAL_POSITIONS_FILE)
    if not isinstance(payload, dict):
        return {}

    rows = payload.get("positions")
    if not isinstance(rows, list):
        logger.warning("Manual positions: %s has no positions array", MANUAL_POSITIONS_FILE)
        return {}

    retrieved_at = datetime.now(UTC)
    groups: dict[str, list[Position]] = {}
    for raw in rows:
        parsed = _coerce(raw, retrieved_at)
        if parsed is None:
            continue
        group, position = parsed
        groups.setdefault(group, []).append(position)
    return groups


class ManualProvider:
    """Hand-maintained rows for things no API publishes."""

    kind: str = KIND
    # Local file read; nothing to wait on.
    timeout: float = 5.0

    async def fetch(self, entity: EntityConfig) -> ProviderResult:
        config = entity.sources.get(KIND)
        if not config:
            return ProviderResult.skipped(KIND)

        group = config.get("group")
        if not isinstance(group, str) or not group:
            return ProviderResult.failed(KIND, "registry entry needs a `group`")

        positions = load_groups().get(group, [])
        if not positions:
            # Every row was rejected, expired, or the group is empty. Not an
            # outage — but the detail view should be able to say so.
            return ProviderResult(
                kind=KIND,
                ok=True,
                error=f"no valid manual rows for group {group!r}",
            )

        return ProviderResult(
            kind=KIND,
            ok=True,
            positions=positions,
            as_of=datetime.now(UTC),
        )
