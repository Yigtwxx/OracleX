"""
Turns provider output into the board the grid and the detail pane render.

Two rules run through everything here, and both exist because this page's whole
claim is that its numbers are checkable:

An entity never disappears. A source that fails leaves the entity on the grid
carrying `stale` and a reason, because a card that vanishes during an outage
reads as "sold everything" — a claim we would be making on our own.

A total is only computed from the parts that actually have a value. If a
position's USD figure is unknown, it is excluded from the total *and* the entity
is marked incomplete, rather than being counted as zero. Weights follow the same
rule: a percentage against a denominator we do not fully know is a fabrication,
so `weight_pct` stays None whenever the total is unknown.
"""

import logging
import os
from datetime import UTC, date, datetime
from typing import Any

from models.ownership import (
    POOLED_SLICE_KEY,
    AllocationSlice,
    EntityDetail,
    EntitySummary,
    Move,
    OwnershipBoard,
    Position,
    SourceHealth,
    SourceRef,
)
from services.asset_registry import REGISTRY_DIR, read_json_cache, write_json_cache
from services.cache import ownership_cache
from services.ownership import registry
from services.ownership.errors import BoardUnavailable, EntityNotFound
from services.ownership.providers.base import EntityConfig, ProviderResult

logger = logging.getLogger(__name__)

BOARD_CACHE_KEY = "board"
BOARD_FILE = os.path.join(REGISTRY_DIR, "ownership_board.json")
# The board is rebuilt once a day. The TTL governs the memory cache only — a
# board is never discarded for being old, it is served with a stale marker.
BOARD_TTL_SECONDS = 26 * 60 * 60
# Past this, the daily rebuild has demonstrably not happened. Two hours of slack
# on a 24h cadence, so a job that runs late does not flap the badge.
BOARD_STALE_AFTER_SECONDS = 26 * 60 * 60
# How many moves the grid strip carries. The detail view fetches its own.
LATEST_MOVES_LIMIT = 12
# Holdings shown on a grid card before it stops being a summary.
TOP_POSITIONS_ON_CARD = 3
# Holdings the allocation bar names individually before the rest are pooled.
TOP_ALLOCATION_SLICES = 6


def _allocation(positions: list[Position]) -> list[AllocationSlice]:
    """
    Share of the entity's known value per holding, largest first.

    Per holding rather than per asset class: a bar drawn by class tells a
    twenty-nine-stock fund and a one-stock fund apart in no way at all, and it
    merges an ETH position into a BTC one because both are "crypto" — the one
    distinction a holder of both actually cares about.

    Built only from positions that have a value. A holding whose USD figure is
    unknown is absent from the bar rather than drawn at zero width, because a
    zero-width slice and an absent one look identical and only one is true.

    The tail past `TOP_ALLOCATION_SLICES` is pooled into a single segment. A bar
    of thirty slivers is a texture, not a reading, and each sliver would be
    below the width where it can be pointed at anyway.
    """
    totals: dict[str, float] = {}
    first_seen: dict[str, Position] = {}
    for position in positions:
        if position.value_usd is None or position.value_usd <= 0:
            continue
        totals[position.key] = totals.get(position.key, 0.0) + position.value_usd
        first_seen.setdefault(position.key, position)

    grand_total = sum(totals.values())
    if grand_total <= 0:
        return []

    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    head = ranked[:TOP_ALLOCATION_SLICES]
    tail = ranked[TOP_ALLOCATION_SLICES:]

    slices = [
        AllocationSlice(
            key=key,
            label=first_seen[key].label,
            symbol=first_seen[key].symbol,
            asset_class=first_seen[key].asset_class,
            value_usd=value,
            pct=value / grand_total * 100.0,
        )
        for key, value in head
    ]

    # Two share classes file under one issuer name, so Li Lu's book draws
    # "Alphabet Inc" beside "Alphabet Inc" at 23% and 22%. The ticker is the
    # only thing that tells them apart, and a legend that repeats itself reads
    # as a rendering bug rather than as two holdings.
    seen_labels: dict[str, int] = {}
    for entry in slices:
        seen_labels[entry.label] = seen_labels.get(entry.label, 0) + 1
    for entry in slices:
        if seen_labels[entry.label] > 1 and entry.symbol:
            entry.label = f"{entry.label} ({entry.symbol})"

    if tail:
        pooled = sum(value for _, value in tail)
        slices.append(
            AllocationSlice(
                key=POOLED_SLICE_KEY,
                label=f"{len(tail)} smaller holdings",
                asset_class="other",
                value_usd=pooled,
                pct=pooled / grand_total * 100.0,
            )
        )
    return slices


def _known_total(positions: list[Position]) -> tuple[float | None, bool]:
    """
    Sum of the positions that have a value, and whether any lacked one.

    Returns (None, True) when nothing is priced: an entity whose every figure is
    unknown has an unknown total, not a total of zero.
    """
    priced = [p.value_usd for p in positions if p.value_usd is not None]
    has_unpriced = len(priced) != len(positions)
    if not priced:
        return None, True
    return sum(priced), has_unpriced


def _apply_weights(positions: list[Position], total: float | None) -> None:
    """Fill in `weight_pct` where the denominator is actually known."""
    if total is None or total <= 0:
        return
    for position in positions:
        if position.value_usd is not None:
            position.weight_pct = position.value_usd / total * 100.0


def _dominant_source_label(positions: list[Position]) -> str | None:
    """The badge on the card: the label carrying the most value."""
    if not positions:
        return None
    weight: dict[str, float] = {}
    for position in positions:
        label = position.source.label
        weight[label] = weight.get(label, 0.0) + (position.value_usd or 0.0)
    # Ties and all-unknown values fall back to the first label seen, which is
    # stable because positions arrive in provider order.
    return (
        max(weight, key=lambda label: weight[label])
        if any(weight.values())
        else (positions[0].source.label)
    )


def _earliest_as_of(positions: list[Position]) -> date | None:
    """
    The oldest `as_of` among the positions — the honest age of the card.

    Oldest rather than newest on purpose: a card summarising a Q3 filing and a
    live price is only as current as the Q3 filing.
    """
    dates = [p.source.as_of for p in positions if p.source.as_of is not None]
    return min(dates) if dates else None


def build_entity_summary(
    entity: EntityConfig,
    results: list[ProviderResult],
) -> tuple[EntitySummary, list[Position]]:
    """One card plus the positions behind it."""
    positions = [p for r in results if r.ok for p in r.positions]
    # Some sources report only events. A Form 4 says what an insider traded, not
    # what they hold, so an entity built on one legitimately has no positions —
    # that is a different state from a source having failed, and the card must
    # not wear a stale badge for it.
    reported_moves = [m for r in results if r.ok for m in r.moves]

    issues: list[str] = []
    for result in results:
        if not result.ok and result.error:
            issues.append(f"{result.kind}: {result.error}")
        elif result.ok and result.error:
            # A provider that partly succeeded still reports what it missed.
            issues.append(f"{result.kind}: {result.error}")

    total, has_unpriced = _known_total(positions)
    if has_unpriced and positions:
        issues.append("Some positions have no published USD value and are excluded from the total.")

    _apply_weights(positions, total)

    # Largest first, with the unpriced ones last rather than sorted as zero —
    # an unknown value is not a small one.
    ranked = sorted(positions, key=lambda p: (p.value_usd is None, -(p.value_usd or 0.0)))

    summary = EntitySummary(
        id=entity.id,
        name=entity.name,
        subtitle=entity.subtitle,
        category=entity.category,  # type: ignore[arg-type]
        country=entity.country,
        total_value_usd=total,
        positions_count=len(positions),
        allocation=_allocation(positions),
        top_positions=ranked[:TOP_POSITIONS_ON_CARD],
        source_label=_dominant_source_label(positions),
        last_move=None,
        as_of=_earliest_as_of(positions)
        or (max(m.occurred_at for m in reported_moves) if reported_moves else None),
        # Stale means the sources could not be reached, not that they had
        # nothing to say. An insider who simply did not trade this quarter is a
        # real answer, and flagging it would cry outage over a quiet period.
        stale=bool(results) and not any(r.ok for r in results),
        issues=issues,
        has_data=bool(positions) or bool(reported_moves),
        coverage_note=entity.coverage_note,
    )
    return summary, positions


def _source_health(
    resolved: dict[str, list[ProviderResult]],
    built_at: datetime,
) -> list[SourceHealth]:
    """Per-provider outcome, for the line under the board."""
    tally: dict[str, dict[str, Any]] = {}
    for results in resolved.values():
        for result in results:
            entry = tally.setdefault(
                result.kind,
                {"ok": 0, "failed": 0, "message": None},
            )
            if result.ok:
                # Counted on the provider answering, not on it having something
                # to say. A Form 4 source never returns positions and an insider
                # can go a quarter without trading; scoring those as failures
                # would report an outage that is not happening.
                entry["ok"] += 1
            else:
                entry["failed"] += 1
                entry["message"] = entry["message"] or result.error

    return [
        SourceHealth(
            kind=kind,  # type: ignore[arg-type]
            # A source is healthy when it answered for at least one entity.
            # Every entity failing is an outage; one failing is a bad key.
            ok=entry["ok"] > 0,
            entities_covered=entry["ok"],
            as_of=built_at,
            message=entry["message"] if entry["ok"] == 0 else None,
        )
        for kind, entry in sorted(tally.items())
    ]


def build_board(
    entities: list[EntityConfig],
    resolved: dict[str, list[ProviderResult]],
    built_at: datetime,
    moves: list[Move] | None = None,
    baseline_ids: set[str] | None = None,
    stale_ids: set[str] | None = None,
) -> tuple[OwnershipBoard, dict[str, list[Position]]]:
    """
    Assemble the grid payload and the per-entity position lists behind it.

    `stale_ids` are entities whose figures came out of the last reading because
    a source failed this time. They are marked here rather than inferred from
    the positions, because a carried position is indistinguishable from a fresh
    one by the time it arrives — only the caller that did the carrying knows.
    """
    summaries: list[EntitySummary] = []
    positions_by_entity: dict[str, list[Position]] = {}
    all_moves = moves or []
    baselines = baseline_ids or set()

    newest_by_entity: dict[str, Move] = {}
    for move in all_moves:
        current = newest_by_entity.get(move.entity_id)
        if current is None or _move_sort_key(move) > _move_sort_key(current):
            newest_by_entity[move.entity_id] = move

    for entity in entities:
        summary, positions = build_entity_summary(entity, resolved.get(entity.id, []))
        if stale_ids and entity.id in stale_ids:
            summary.stale = True
        # An entity at its baseline has no last move *by fact*, which the detail
        # view words differently from "nothing happened".
        if entity.id not in baselines:
            summary.last_move = newest_by_entity.get(entity.id)
        summaries.append(summary)
        positions_by_entity[entity.id] = positions

    counts: dict[str, int] = {}
    for summary in summaries:
        counts[summary.category] = counts.get(summary.category, 0) + 1

    # Sorted on when it became public, not when it happened: a filing disclosed
    # today is today's news even though the trade is a quarter old.
    latest = sorted(all_moves, key=_move_sort_key, reverse=True)[:LATEST_MOVES_LIMIT]

    board = OwnershipBoard(
        entities=summaries,
        latest_moves=latest,
        category_counts=counts,
        sources=_source_health(resolved, built_at),
        as_of=built_at,
        last_refresh_at=built_at,
        stale=False,
    )
    return board, positions_by_entity


def _move_sort_key(move: Move) -> date:
    return move.reported_at or move.occurred_at


# ── Persistence ─────────────────────────────────────────────────────────────
# The board lives in three places, checked in this order: memory, disk, nothing.
# Disk is what makes a cold start on a rate-limited morning render the previous
# day's board instead of a 503.


def store_board(
    board: OwnershipBoard,
    positions_by_entity: dict[str, list[Position]],
    moves: list[Move] | None = None,
    baseline_ids: set[str] | None = None,
) -> None:
    """
    Cache the board and persist it so a restart does not start from nothing.

    Moves and positions ride along in the same file rather than being re-derived
    from the snapshot history on read: the detail endpoint has to answer without
    touching the diff machinery, or a read path would depend on write-path state.
    """
    moves_by_entity: dict[str, list[dict[str, Any]]] = {}
    for move in moves or []:
        moves_by_entity.setdefault(move.entity_id, []).append(move.model_dump(mode="json"))

    payload = {
        "board": board.model_dump(mode="json"),
        "positions": {
            entity_id: [p.model_dump(mode="json") for p in positions]
            for entity_id, positions in positions_by_entity.items()
        },
        "moves": moves_by_entity,
        "baselines": sorted(baseline_ids or set()),
    }
    ownership_cache.set(BOARD_CACHE_KEY, payload, BOARD_TTL_SECONDS)
    write_json_cache(BOARD_FILE, payload)


def _load_payload() -> dict[str, Any] | None:
    """The stored board, from memory or disk. Age is decided separately."""
    cached = ownership_cache.get(BOARD_CACHE_KEY)
    if cached is not None:
        return cached

    fallback = ownership_cache.get_with_fallback(BOARD_CACHE_KEY)
    if fallback is not None:
        return fallback

    on_disk = read_json_cache(BOARD_FILE)
    if isinstance(on_disk, dict) and on_disk.get("board"):
        # Re-seed memory so the next reader does not touch the disk again.
        ownership_cache.set(BOARD_CACHE_KEY, on_disk, BOARD_TTL_SECONDS)
        return on_disk

    return None


def stored_payload() -> dict[str, Any] | None:
    """
    The stored board with its positions and moves, or None if nothing is stored.

    Public because a partial refresh has to read what it is extending: it asks
    only the live sources and carries every other position forward from here.
    """
    return _load_payload()


def _is_stale(board: OwnershipBoard) -> bool:
    """
    Whether this board is older than a daily rebuild should ever leave it.

    Read off the board's own `last_refresh_at` rather than off whether the cache
    happened to hold it. Cache presence answers a different question: the first
    request after a restart loads from disk and re-seeds memory, so every
    request after that one would look fresh no matter how old the file was — a
    week-old board would quietly present as current, which is exactly the claim
    this page must never make.
    """
    if board.last_refresh_at is None:
        return True
    built = board.last_refresh_at
    if built.tzinfo is None:
        built = built.replace(tzinfo=UTC)
    return (datetime.now(UTC) - built).total_seconds() > BOARD_STALE_AFTER_SECONDS


def get_board() -> OwnershipBoard:
    """
    The board as last built.

    Raises `BoardUnavailable` when there is nothing anywhere. It never returns
    an empty board: an empty grid is the claim that nobody holds anything.
    """
    payload = _load_payload()
    if payload is None:
        raise BoardUnavailable("No ownership board has been built yet")

    board = OwnershipBoard.model_validate(payload["board"])
    board.stale = _is_stale(board)
    _apply_logos(board.entities)
    return board


def _apply_logos(entities: list[EntitySummary]) -> None:
    """
    Stamp each summary with its registry icon on the way out.

    Applied on read rather than on build so a stored board — which may be a day
    old, or a week during an outage — still carries today's icons. A logo is
    curated metadata; making it wait for the next refresh would mean a wrong
    mark stayed wrong for as long as the numbers took to rebuild.
    """
    logos = registry.entity_logo_urls()
    for entity in entities:
        entity.logo_url = logos.get(entity.id)


def get_entity_detail(entity_id: str) -> EntityDetail:
    """
    One entity, fully expanded.

    A registered entity with no data answers 200 with `has_data=false` rather
    than 404 — it exists, we just could not fill it. Only an unknown id is a 404.
    """
    entity = registry.load_entity(entity_id)
    if entity is None:
        raise EntityNotFound(f"No tracked entity with id {entity_id!r}")

    payload = _load_payload()
    if payload is None:
        raise BoardUnavailable("No ownership board has been built yet")

    board = OwnershipBoard.model_validate(payload["board"])
    summary = next((e for e in board.entities if e.id == entity_id), None)
    if summary is None:
        # Registered after the last refresh: real, just not built yet.
        summary = EntitySummary(
            id=entity.id,
            name=entity.name,
            subtitle=entity.subtitle,
            category=entity.category,  # type: ignore[arg-type]
            country=entity.country,
            has_data=False,
            stale=True,
            issues=["Not yet included in a refresh."],
            coverage_note=entity.coverage_note,
        )

    # Same reason as the board: read from the registry, not from the snapshot.
    summary.logo_url = registry.entity_logo_url(entity)

    raw_positions = payload.get("positions", {}).get(entity_id, [])
    positions = [Position.model_validate(p) for p in raw_positions]
    positions.sort(key=lambda p: (p.value_usd is None, -(p.value_usd or 0.0)))

    seen: set[tuple[str, str]] = set()
    sources: list[SourceRef] = []
    for position in positions:
        marker = (position.source.kind, position.source.label)
        if marker not in seen:
            seen.add(marker)
            sources.append(position.source)

    raw_moves = payload.get("moves", {}).get(entity_id, [])
    moves = [Move.model_validate(m) for m in raw_moves]
    moves.sort(key=_move_sort_key, reverse=True)

    return EntityDetail(
        entity=summary,
        positions=positions,
        moves=moves,
        sources=sources,
        # Only ever observed once: the positions are real, the deltas are not
        # computable, and "no moves" would read as "nothing happened" when what
        # is true is "we have nothing to compare against yet".
        moves_baseline=entity_id in set(payload.get("baselines", [])),
    )


def get_moves(
    limit: int = 30,
    category: str | None = None,
    entity_id: str | None = None,
) -> list[Move]:
    """
    The move feed, newest first.

    An empty list here is a real answer — a quiet week genuinely has no moves —
    which is why this is the one part of the board allowed to say "nothing"
    with an empty collection rather than a 503.
    """
    payload = _load_payload()
    if payload is None:
        raise BoardUnavailable("No ownership board has been built yet")

    buckets = payload.get("moves", {})
    raw = buckets.get(entity_id, []) if entity_id else [m for b in buckets.values() for m in b]

    moves = [Move.model_validate(m) for m in raw]
    if category:
        moves = [m for m in moves if m.category == category]
    moves.sort(key=_move_sort_key, reverse=True)
    return moves[:limit]


def board_age_seconds() -> float | None:
    """How long ago the stored board was written, or None if there is none."""
    if ownership_cache.get_fallback_age(BOARD_CACHE_KEY) is not None:
        return ownership_cache.get_fallback_age(BOARD_CACHE_KEY)
    try:
        return datetime.now(UTC).timestamp() - os.path.getmtime(BOARD_FILE)
    except OSError:
        return None
