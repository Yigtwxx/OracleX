"""
The rebuild that fills the Ownership board.

Partial failure is the normal case here, not the exception: several independent
public sources, and on any given day one of them is rate-limiting or has renamed
a field. So this function has no path that returns nothing — every stage
degrades to what is already stored and records why in the report.

Providers are contracted never to raise, but a contract is not an enforcement:
one bad `float()` inside a parser would otherwise take down the refresh for
every entity at once. Hence the timeout and the catch around each call.

Concurrency is kept low on purpose. Several providers share a single upstream
rate limit — every 13F entity is the same SEC host, every treasury entity reads
the same CoinGecko table — so running all entities at once would spend a budget
that is deliberately paced.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from models.ownership import Move, Position, SourceHealth
from services.ownership import board as board_module
from services.ownership import registry, snapshots
from services.ownership.providers import PROVIDERS
from services.ownership.providers.base import EntityConfig, ProviderResult

logger = logging.getLogger(__name__)

# Per (entity, provider). Past this the provider counts as unavailable.
PROVIDER_TIMEOUT_SECONDS = 30.0
# Entities fetched at once.
ENTITY_CONCURRENCY = 4

# The sources worth asking again before tomorrow.
#
# A 13F is a quarterly document and a hand-typed balance-sheet line changes when
# someone edits it, so re-reading either during the day learns nothing and
# spends a rate limit. These three do move: a coin price reprices a treasury
# every minute, a wallet balance changes when the wallet is used, and a Form 4
# lands within two business days of the trade it reports.
LIVE_KINDS = frozenset({"coingecko_treasury", "onchain", "sec_form4"})


@dataclass(slots=True)
class RefreshReport:
    """What the last rebuild managed to do. Logged, and returned to admin."""

    entities_total: int = 0
    entities_ok: int = 0
    moves_new: int = 0
    sources_failed: int = 0
    health: list[SourceHealth] = field(default_factory=list)


async def _run_provider(kind: str, entity: EntityConfig) -> ProviderResult:
    """Call one provider for one entity, converting every failure into a value."""
    provider = PROVIDERS.get(kind)
    if provider is None:
        # A registry row can name a source whose provider has not shipped yet.
        # That is how a later phase's entities can be committed early.
        logger.debug("%s: no provider registered for %r — skipped", entity.id, kind)
        return ProviderResult.skipped(kind)  # type: ignore[arg-type]

    timeout = getattr(provider, "timeout", PROVIDER_TIMEOUT_SECONDS)
    try:
        return await asyncio.wait_for(provider.fetch(entity), timeout=timeout)
    except TimeoutError:
        return ProviderResult.failed(kind, f"timed out after {timeout:.0f}s")  # type: ignore[arg-type]
    except Exception as e:
        logger.exception("%s/%s provider raised", entity.id, kind)
        return ProviderResult.failed(kind, str(e))  # type: ignore[arg-type]


async def _fetch_entity(
    entity: EntityConfig, only_kinds: frozenset[str] | None = None
) -> list[ProviderResult]:
    """Every provider this entity is configured for, in parallel."""
    kinds = [k for k in entity.sources if only_kinds is None or k in only_kinds]
    if not kinds:
        return []
    return list(await asyncio.gather(*(_run_provider(kind, entity) for kind in kinds)))


def _carried_results(stored: list[dict[str, Any]], skipped_kinds: set[str]) -> list[ProviderResult]:
    """
    The last run's positions for the sources this run did not ask.

    A partial refresh has to hand the board every position it had, not only the
    ones it just re-read: rebuilding Strategy from the coin table alone would
    drop its cash line, and the snapshot diff would read that as the cash having
    been spent. Carried positions keep their original source and `as_of`, so the
    badge still dates them to the filing they came from rather than to now.
    """
    by_kind: dict[str, list[Position]] = {}
    for raw in stored:
        try:
            position = Position.model_validate(raw)
        except Exception:  # noqa: BLE001
            continue
        kind = position.source.kind
        if kind in skipped_kinds:
            by_kind.setdefault(kind, []).append(position)

    return [
        ProviderResult(kind=kind, ok=True, positions=positions)  # type: ignore[arg-type]
        for kind, positions in by_kind.items()
    ]


def _carry_failed(
    results: list[ProviderResult], stored: list[dict[str, Any]]
) -> tuple[list[ProviderResult], bool]:
    """
    Replace a failed source's silence with what it last said, and say so.

    A provider that 429s returns no positions, and an entity rebuilt without
    them loses its total — a treasury whose coin table was rate-limited for
    ninety seconds renders as "Unknown". That reads as "we do not know what this
    company holds", when what happened is that one request failed and we knew a
    minute ago.

    So the previous positions are carried, the entity is marked stale, and the
    reason goes in its issue list. The figures keep their original `as_of`, so
    the badge dates them to the reading they came from rather than to now: the
    card says "these are Tuesday's numbers", which is true, instead of "we have
    no numbers", which is not.
    """
    by_kind: dict[str, list[Position]] = {}
    failed_kinds = {r.kind for r in results if not r.ok}
    if not failed_kinds:
        return results, False

    for raw in stored:
        try:
            position = Position.model_validate(raw)
        except Exception:  # noqa: BLE001
            continue
        if position.source.kind in failed_kinds:
            by_kind.setdefault(position.source.kind, []).append(position)

    if not by_kind:
        return results, False

    repaired: list[ProviderResult] = []
    for result in results:
        carried = by_kind.get(result.kind) if not result.ok else None
        if not carried:
            repaired.append(result)
            continue
        repaired.append(
            ProviderResult(
                kind=result.kind,
                ok=True,
                positions=carried,
                # Kept as an issue rather than dropped: the card is showing an
                # older reading and has to be able to say why.
                error=f"{result.kind} unavailable ({result.error}) — showing the last reading",
            )
        )
    return repaired, True


def _carry_health(board: Any, stored: dict[str, Any], asked_kinds: frozenset[str]) -> None:
    """
    Restore the stored verdict for the sources this run did not ask.

    The line under the board reports which sources answered. A partial run only
    asked some of them, and the ones it skipped are carried as positions — so
    recomputing their health here would report an outcome for a request that
    never happened, and date it to now.
    """
    previous = {
        entry.get("kind"): entry for entry in (stored.get("board") or {}).get("sources", [])
    }
    restored: list[SourceHealth] = []
    for entry in board.sources:
        if entry.kind in asked_kinds:
            restored.append(entry)
            continue
        stored_entry = previous.get(entry.kind)
        if stored_entry is None:
            continue
        try:
            restored.append(SourceHealth.model_validate(stored_entry))
        except Exception:  # noqa: BLE001
            restored.append(entry)
    board.sources = restored


async def refresh_ownership(only_kinds: frozenset[str] | None = None) -> RefreshReport:
    """
    Rebuild the board, optionally from a subset of its sources.

    `only_kinds` is what makes an intraday run affordable. Asking every source
    again would re-download a quarterly filing that has not changed and spend a
    rate limit shared with nothing else; asking only the live ones reprices what
    moves. Positions from the sources that were not asked are carried forward
    from the stored board unchanged, so a partial run is a narrower reading of
    the same board rather than a smaller board.

    Never raises. When it cannot improve on what is stored it leaves the stored
    board in place, so the page keeps rendering yesterday's figures with a stale
    badge rather than falling to a 503.
    """
    started = datetime.now(UTC)
    entities = registry.load_entities()
    report = RefreshReport(entities_total=len(entities))

    if not entities:
        logger.warning("Ownership refresh: registry is empty — nothing to build")
        return report

    # Read on every run, not only the partial ones: a full run also needs
    # somewhere to fall back to when one of its sources fails.
    stored = board_module.stored_payload()
    if only_kinds is not None and stored is None:
        # Nothing to carry forward means a partial run would publish a board
        # made of one source. The first build has to be the full one.
        logger.info("Ownership refresh: no stored board to extend — running every source")
        only_kinds = None

    semaphore = asyncio.Semaphore(ENTITY_CONCURRENCY)

    async def _one(entity: EntityConfig) -> tuple[EntityConfig, list[ProviderResult]]:
        async with semaphore:
            return entity, await _fetch_entity(entity, only_kinds)

    gathered = await asyncio.gather(*(_one(entity) for entity in entities), return_exceptions=True)

    resolved: dict[str, list[ProviderResult]] = {}
    stale_ids: set[str] = set()
    stored_positions = (stored or {}).get("positions", {})

    for item in gathered:
        if isinstance(item, BaseException):
            logger.exception("Ownership entity task failed", exc_info=item)
            continue
        entity, results = item
        # Counted on what was actually fetched, before anything is carried: a
        # board rebuilt entirely from its own last copy has covered nothing, and
        # the guard below is what keeps that from being stored as a fresh run.
        if any(r.ok and (r.positions or r.moves) for r in results):
            report.entities_ok += 1

        if only_kinds is not None and stored is not None:
            skipped = {k for k in entity.sources if k not in only_kinds}
            results = results + _carried_results(stored_positions.get(entity.id, []), skipped)

        results, carried = _carry_failed(results, stored_positions.get(entity.id, []))
        if carried:
            stale_ids.add(entity.id)
        resolved[entity.id] = results

    if report.entities_ok == 0:
        # Every source failed. Overwriting a good board with an empty one would
        # turn an outage into the claim that nobody holds anything.
        logger.warning("Ownership refresh: no entity produced data — keeping the stored board")
        return report

    # History and deltas. Ordered after the fetch so a diff is never computed
    # against a half-filled entity: a source that timed out would otherwise read
    # as the holder having sold everything it reports through that source.
    history = snapshots.load()
    derived: list[Move] = []
    baseline_ids: set[str] = set()

    for entity in entities:
        results = resolved.get(entity.id, [])
        positions = [p for r in results if r.ok for p in r.positions]

        # Events a source hands us outright — Form 4 lines, chain transfers —
        # bypass the level diff entirely; they are already changes. Collected
        # before the positions check, because a Form 4 entity has no positions
        # at all and skipping it here would drop every trade it reported.
        derived.extend(m for r in results if r.ok for m in r.moves)

        if not positions:
            continue

        if not snapshots.has_baseline(history, entity.id):
            baseline_ids.add(entity.id)

        derived.extend(snapshots.diff_and_append(history, entity, positions, started))

    report.moves_new = len(snapshots.record_events(history, derived))
    snapshots.save(history)

    board, positions_by_entity = board_module.build_board(
        entities,
        resolved,
        started,
        moves=snapshots.stored_moves(history),
        baseline_ids=baseline_ids,
        stale_ids=stale_ids,
    )
    if only_kinds is not None and stored is not None:
        # A source that was not asked has no news. Recomputing its health from
        # the carried positions would stamp it "ok, as of now", which is this
        # run vouching for a request it never made.
        _carry_health(board, stored, only_kinds)
    board_module.store_board(
        board,
        positions_by_entity,
        moves=snapshots.stored_moves(history),
        baseline_ids=baseline_ids,
    )

    report.health = board.sources
    report.sources_failed = sum(1 for s in board.sources if not s.ok)
    return report


async def ensure_board(max_age_seconds: float = 36 * 60 * 60) -> None:
    """
    Build the board at boot if there is none, or if the stored one has aged out.

    Called from the startup warm-up rather than from a request: the sources
    behind this board are rate-limited hard enough that a page load must never
    be what triggers a fetch.
    """
    age = board_module.board_age_seconds()
    if age is not None and age < max_age_seconds:
        return
    logger.info(
        "Ownership board %s — building at startup",
        "missing" if age is None else f"{age / 3600:.1f}h old",
    )
    await refresh_ownership()
