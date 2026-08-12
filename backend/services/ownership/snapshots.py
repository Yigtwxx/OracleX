"""
The history behind the moves, and the diff that turns it into them.

Only two sources need this. A 13F and a Form 4 arrive as events already — the
filing *is* the record of what changed — and an on-chain transfer is a
transaction. Corporate treasuries and central bank reserves publish a level, not
a change, so the only way to know MicroStrategy bought 5,000 BTC is to have
written down what they held yesterday.

Everything that keeps this file from growing without bound lives here, and the
one that actually does the work is the change threshold: a quarterly filing does
not move for ninety days, and appending an identical observation every noon is
what would turn a 200 KB file into a 20 MB one. An observation is only recorded
when it differs materially from the last.

## Replacing this with a database

`load`, `append`/`diff_and_append` and `save` are the entire surface. Nothing
outside this module touches the file, so the day multiple backend instances need
to share history, these three grow a Supabase implementation and no caller
changes. That containment is the point of the module.
"""

import hashlib
import json
import logging
import os
from datetime import UTC, date, datetime
from typing import Any

from models.ownership import Move, Position, SourceRef
from services.asset_registry import REGISTRY_DIR, read_json_cache, write_json_cache
from services.ownership.providers.base import EntityConfig

logger = logging.getLogger(__name__)

SNAPSHOT_FILE = os.path.join(REGISTRY_DIR, "ownership_snapshots.json")
SCHEMA_VERSION = 1

# Observations kept per entity. Two are enough to diff; the rest are headroom
# for a future sparkline, and the ceiling is what stops the file creeping.
MAX_OBSERVATIONS = 8
# Source-supplied events (Form 4 lines, transfers) kept per entity, so they do
# not have to be re-fetched every day to stay on the board.
MAX_EVENTS = 50
# Relative change below which two quantities are the same reading. Five basis
# points: rounding in a filing, not a trade.
CHANGE_EPSILON = 0.0005
# Beyond this share of an entity's positions changing at once, the diff is more
# likely a parser regression than a portfolio. See `_is_implausible`.
IMPLAUSIBLE_TURNOVER = 0.6
# Below this many positions the turnover ratio says nothing. A corporate
# treasury holds one line; when it buys more bitcoin, 100% of its positions
# changed and that is simply what happened. Applying the ratio here would
# suppress every real move these entities will ever make.
MIN_POSITIONS_FOR_TURNOVER_GUARD = 5
# Escape valve, not a normal path.
MAX_FILE_BYTES = 2_000_000

# Sources that report changes themselves rather than only a level. A 13F names
# the quarter it covers and can be diffed against the previous filing at the
# source; a Form 4 and a chain transfer *are* events. Their positions are still
# recorded here so the history stays complete, but diffing them would publish
# every change twice — once from the filing, once from our own bookkeeping.
EVENT_SOURCE_KINDS = {"sec_13f", "sec_form4", "onchain"}

# How a level change is worded, per category. A pension fund "adds"; a treasury
# "increases". Same arithmetic, different vocabulary, because the reader of a
# 13F and the reader of a balance sheet are not being told the same kind of fact.
_LEVEL_KINDS: dict[str, dict[str, str]] = {
    "institution": {"open": "new", "close": "exit", "up": "add", "down": "trim"},
    "politician": {"open": "new", "close": "exit", "up": "add", "down": "trim"},
    "treasury": {"open": "new", "close": "exit", "up": "increase", "down": "decrease"},
    "central_bank": {"open": "new", "close": "exit", "up": "increase", "down": "decrease"},
    "onchain": {"open": "new", "close": "exit", "up": "transfer_in", "down": "transfer_out"},
}


# ── Store ───────────────────────────────────────────────────────────────────


def load() -> dict[str, Any]:
    """The whole history, or an empty shell when there is none yet."""
    payload = read_json_cache(SNAPSHOT_FILE)
    if not isinstance(payload, dict) or payload.get("version") != SCHEMA_VERSION:
        if payload is not None:
            logger.info("Ownership snapshots: unrecognised schema — starting a new history")
        return {"version": SCHEMA_VERSION, "entities": {}, "events": {}}
    payload.setdefault("entities", {})
    payload.setdefault("events", {})
    return payload


def save(history: dict[str, Any]) -> None:
    """Persist the history, pruning first and hard-trimming if it is oversized."""
    _prune(history)

    encoded = json.dumps(history)
    if len(encoded) > MAX_FILE_BYTES:
        logger.warning(
            "Ownership snapshots at %d bytes — trimming to the two most recent observations",
            len(encoded),
        )
        _prune(history, max_observations=2)

    write_json_cache(SNAPSHOT_FILE, history)


def _prune(history: dict[str, Any], max_observations: int = MAX_OBSERVATIONS) -> None:
    for record in history.get("entities", {}).values():
        observations = record.get("observations", [])
        if len(observations) > max_observations:
            record["observations"] = observations[-max_observations:]
    for entity_id, events in list(history.get("events", {}).items()):
        if len(events) > MAX_EVENTS:
            history["events"][entity_id] = events[-MAX_EVENTS:]


# ── Observations ────────────────────────────────────────────────────────────


def _encode(positions: list[Position]) -> dict[str, dict[str, Any]]:
    """Positions in the compact shape the file stores."""
    return {
        p.key: {
            "q": p.quantity,
            "v": p.value_usd,
            "u": p.quantity_unit,
            "c": p.asset_class,
            "l": p.label,
            "s": p.symbol,
            # Which provider produced this line. Needed to tell a holder opening
            # a position apart from us switching a source on — see `_backfilled`.
            "k": p.source.kind,
        }
        for p in positions
    }


def _source_kinds(encoded: dict[str, dict[str, Any]]) -> set[str]:
    return {row.get("k") for row in encoded.values() if row.get("k")}


def _backfilled(
    encoded: dict[str, Any],
    previous_kinds: set[str],
) -> bool:
    """
    Whether a newly-seen key is us gaining a source rather than them buying.

    When a manual cash row is added to the registry, or a new provider ships,
    every line it brings is new *to us* — but Tesla did not acquire $15bn of
    cash the morning someone typed it into a JSON file. Announcing that would be
    a plain falsehood, and the kind this whole feature exists to avoid.

    The test is whether the source itself is new to this entity. A key arriving
    from a provider that was already reporting yesterday is a real position
    being opened; a key arriving from a provider we had never run before is a
    backfill, recorded silently so that tomorrow's change against it is real.
    """
    kind = encoded.get("k")
    return bool(kind) and kind not in previous_kinds


def _materially_differs(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    """
    Whether `current` is a new reading rather than the same one again.

    Quantity first, value only as a fallback: a treasury's dollar figure moves
    with the coin price every single day while the holding itself sits still, so
    diffing on value would record an "observation" every noon and defeat the
    ceiling this check exists to protect.
    """
    if set(previous) != set(current):
        return True

    for key, now in current.items():
        before = previous[key]
        if not _same_number(before.get("q"), now.get("q")):
            return True
        if before.get("q") is None and now.get("q") is None:
            if not _same_number(before.get("v"), now.get("v")):
                return True
    return False


def _same_number(a: float | None, b: float | None) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if a == 0:
        return b == 0
    return abs(b - a) / abs(a) <= CHANGE_EPSILON


def _latest(history: dict[str, Any], entity_id: str) -> dict[str, Any] | None:
    observations = history.get("entities", {}).get(entity_id, {}).get("observations", [])
    return observations[-1] if observations else None


def has_baseline(history: dict[str, Any], entity_id: str) -> bool:
    """Whether we have ever recorded this entity — deltas need a prior reading."""
    return _latest(history, entity_id) is not None


# ── Diff ────────────────────────────────────────────────────────────────────


def _move_id(entity_id: str, key: str, kind: str, occurred_at: date, delta: float) -> str:
    """
    Deterministic, so the same event cannot be published twice.

    A 13F sits unchanged for a quarter and the daily job re-derives the same
    move from it every morning. Hashing the event's own identity means the
    ninetieth derivation collides with the first instead of stacking up.
    """
    raw = f"{entity_id}|{key}|{kind}|{occurred_at.isoformat()}|{delta:.6g}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _headline(
    entity_name: str, kind: str, label: str, delta_qty: float | None, unit: str | None
) -> str:
    verb = {
        "new": "opened a position in",
        "exit": "exited",
        "add": "added to",
        "trim": "trimmed",
        "increase": "increased",
        "decrease": "reduced",
        "transfer_in": "received",
        "transfer_out": "sent out",
    }.get(kind, "changed")

    if delta_qty is None:
        return f"{entity_name} {verb} {label}"
    magnitude = abs(delta_qty)
    formatted = f"{magnitude:,.0f}" if magnitude >= 1000 else f"{magnitude:,.4g}"
    return f"{entity_name} {verb} {label} — {formatted}{f' {unit}' if unit else ''}"


def _is_implausible(
    previous_keys: set[str],
    current_keys: set[str],
    move_count: int,
) -> bool:
    """
    Whether this diff looks like a parser regression rather than a portfolio.

    If position keys shift under us — a 13F parser moving from CUSIP to ticker,
    say — every holding reads as an exit plus a new position, and the board
    would announce that Berkshire liquidated and rebuilt itself overnight.
    Publishing that is worse than publishing nothing.

    Two signals, and the size floor matters as much as either. A one-line
    corporate treasury that buys more bitcoin has changed 100% of its positions,
    which is not suspicious, it is the entire event — an unguarded ratio would
    suppress every move those entities ever make. So the ratio only speaks for
    portfolios large enough for it to mean something, and the sharper signal is
    a key set that shares nothing at all with the previous one: real portfolios
    do not turn over completely between two readings.
    """
    if len(previous_keys) < MIN_POSITIONS_FOR_TURNOVER_GUARD:
        return False
    if not (previous_keys & current_keys):
        return True
    if not current_keys:
        return False
    return move_count / len(current_keys) > IMPLAUSIBLE_TURNOVER


def diff_and_append(
    history: dict[str, Any],
    entity: EntityConfig,
    positions: list[Position],
    captured_at: datetime,
) -> list[Move]:
    """
    Compare against the last reading, record this one, return what changed.

    Returns an empty list on the first ever observation. That is a real answer,
    not a failure: with no baseline there is no change to report, and inventing
    deltas against zero would announce that every holder just bought everything
    they own.
    """
    entities = history.setdefault("entities", {})
    record = entities.setdefault(entity.id, {"observations": []})

    current = _encode(positions)
    previous_observation = _latest(history, entity.id)
    observed_on = captured_at.date()

    if previous_observation is None:
        record["observations"].append(
            {
                "as_of": observed_on.isoformat(),
                "captured_at": captured_at.isoformat(),
                "positions": current,
            }
        )
        logger.info("Ownership: baseline captured for %s (%d positions)", entity.id, len(current))
        return []

    previous = previous_observation.get("positions", {})
    if not _materially_differs(previous, current):
        return []

    kinds = _LEVEL_KINDS.get(entity.category, _LEVEL_KINDS["institution"])
    source = _representative_source(positions)
    previous_kinds = _source_kinds(previous)
    moves: list[Move] = []

    for key in set(previous) | set(current):
        before = previous.get(key)
        after = current.get(key)

        # This line's provider publishes its own events. Recorded above, never
        # diffed here, or the same trade lands on the board twice.
        if (after or before or {}).get("k") in EVENT_SOURCE_KINDS:
            continue

        if before is None and after is not None:
            if _backfilled(after, previous_kinds):
                # A source we had not run before. Record the level, say nothing.
                continue
            move = _build_move(
                entity,
                kinds["open"],
                key,
                after,
                after.get("q"),
                after.get("v"),
                observed_on,
                source,
            )
        elif after is None and before is not None:
            # The mirror of a backfill: a provider that stopped reporting — a
            # manual group deleted, a source disabled — is our change, not a
            # disposal. Only a key vanishing from a source still running is one.
            if _backfilled(before, _source_kinds(current)):
                continue
            move = _build_move(
                entity,
                kinds["close"],
                key,
                before,
                _negate(before.get("q")),
                _negate(before.get("v")),
                observed_on,
                source,
            )
        elif before is not None and after is not None:
            if _same_number(before.get("q"), after.get("q")):
                continue
            qty_delta = _delta(before.get("q"), after.get("q"))
            if qty_delta is None or qty_delta == 0:
                continue
            kind = kinds["up"] if qty_delta > 0 else kinds["down"]
            move = _build_move(
                entity,
                kind,
                key,
                after,
                qty_delta,
                _delta(before.get("v"), after.get("v")),
                observed_on,
                source,
            )
        else:
            continue

        if move is not None:
            moves.append(move)

    if _is_implausible(set(previous), set(current), len(moves)):
        logger.warning(
            "Ownership: %s produced %d moves across %d positions — suppressing and re-baselining",
            entity.id,
            len(moves),
            len(current),
        )
        record["observations"].append(
            {
                "as_of": observed_on.isoformat(),
                "captured_at": captured_at.isoformat(),
                "positions": current,
                "suppressed": "implausible turnover",
            }
        )
        return []

    record["observations"].append(
        {
            "as_of": observed_on.isoformat(),
            "captured_at": captured_at.isoformat(),
            "positions": current,
        }
    )
    return moves


def _negate(value: float | None) -> float | None:
    return None if value is None else -value


def _delta(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return after - before


def _representative_source(positions: list[Position]) -> SourceRef:
    """
    The source a derived move is attributed to.

    A move computed from two observations has no filing of its own, so it
    inherits the source of the positions it was derived from rather than
    inventing one.
    """
    if positions:
        return positions[0].source
    return SourceRef(
        kind="manual", label="Derived from stored history", retrieved_at=datetime.now(UTC)
    )


def _build_move(
    entity: EntityConfig,
    kind: str,
    key: str,
    encoded: dict[str, Any],
    qty_delta: float | None,
    value_delta: float | None,
    occurred_at: date,
    source: SourceRef,
) -> Move | None:
    # Neither a quantity nor a value means we know something changed but not by
    # how much, and "it moved, amount unknown" is not publishable.
    if qty_delta is None and value_delta is None:
        return None

    label = encoded.get("l") or key
    unit = encoded.get("u")
    return Move(
        id=_move_id(
            entity.id,
            key,
            kind,
            occurred_at,
            qty_delta if qty_delta is not None else (value_delta or 0.0),
        ),
        entity_id=entity.id,
        entity_name=entity.name,
        category=entity.category,  # type: ignore[arg-type]
        kind=kind,  # type: ignore[arg-type]
        asset_label=label,
        asset_symbol=encoded.get("s"),
        asset_class=encoded.get("c", "other"),  # type: ignore[arg-type]
        quantity_delta=qty_delta,
        value_usd_delta=value_delta,
        pct_delta=None,
        occurred_at=occurred_at,
        reported_at=occurred_at,
        headline=_headline(entity.name, kind, label, qty_delta, unit),
        source=source,
    )


# ── Source-supplied events ──────────────────────────────────────────────────


def record_events(history: dict[str, Any], moves: list[Move]) -> list[Move]:
    """
    Merge moves into the per-entity event log, dropping ones already stored.

    Deduplication is on the deterministic move id, which is what lets a provider
    hand us the same last-30-days window every day without the board growing a
    duplicate row each time.
    """
    events = history.setdefault("events", {})
    fresh: list[Move] = []

    for move in moves:
        bucket = events.setdefault(move.entity_id, [])
        if any(stored.get("id") == move.id for stored in bucket):
            continue
        bucket.append(move.model_dump(mode="json"))
        fresh.append(move)

    return fresh


def stored_moves(history: dict[str, Any], entity_id: str | None = None) -> list[Move]:
    """Every remembered move, newest first."""
    events = history.get("events", {})
    buckets = [events.get(entity_id, [])] if entity_id else list(events.values())

    moves: list[Move] = []
    for bucket in buckets:
        for raw in bucket:
            try:
                moves.append(Move.model_validate(raw))
            except Exception:
                logger.debug("Ownership: dropping unreadable stored move")

    moves.sort(key=lambda m: m.reported_at or m.occurred_at, reverse=True)
    return moves
