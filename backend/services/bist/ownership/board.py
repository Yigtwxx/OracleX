"""
Building, storing and reading the BIST ownership board.

**One fetch a day, one file, every view derived from it.** The board is a
hundred İş Yatırım cards and ten KAP fund reports, fetched sequentially with a
pause between them and written to one JSON file under the registry directory.
Nothing on a request path fetches: `get_board`, `get_entity` and
`get_asset_owners` are pivots over the stored payload, and the only upstream a
read touches is the KAP tape already held in memory for `/bist/kap`. That is
what lets the company page carry its ownership panel without the panel being a
liability when İş Yatırım is slow.

**The stored payload is per ticker, not per entity.** İş Yatırım answers
"who holds THYAO", and that is what is written down. Entities are computed on
read by matching every stored row against the registry's aliases, so a fixed
alias takes effect on the next request rather than after the next nightly run —
the same reasoning `_disclosure` in the router gives for classifying KAP rows
on read.

**Two kinds of value, never mixed silently.** A shareholder position is a
percentage of capital marked at the equity board's market cap
(`value_basis="marked"`); a fund position is the lira figure the fund itself
filed (`"reported"`). A company the board cannot price keeps its percentage and
gets no value, and an entity's total is the sum of what could be valued with
the card saying so.

**Moves are the KAP tape, not stake deltas.** A stake changes when a 5% holder
files, and the filing is on the tape before the card updates. So "moves" here
are the ownership-shaped filings — insider trades, block sales, tender offers,
capital actions — read from the tape at request time. Comparing two daily
snapshots of the card would be a second, slower signal and is deliberately not
built until there are two snapshots to compare.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from models.bist_ownership import (
    OWNERSHIP_EVENTS,
    POOLED_SLICE_KEY,
    AllocationSlice,
    AssetOwners,
    EntityDetail,
    EntitySummary,
    FundHolder,
    Holder,
    Move,
    OwnershipBoard,
    Position,
    SourceHealth,
    SourceRef,
    StakeMove,
)
from services.asset_registry import REGISTRY_DIR, read_json_cache, write_json_cache
from services.bist import holdings_service
from services.bist.equity_service import EquityDataUnavailable, fetch_equity_board
from services.bist.kap_materiality import classify
from services.bist.kap_service import KapUnavailable, fetch_tape
from services.bist.ownership import registry, snapshots
from services.bist.ownership.errors import BoardUnavailable, EntityNotFound, TickerNotCovered
from services.bist.ownership.isyatirim_client import (
    SOURCE_LABEL,
    IsYatirimUnavailable,
    fetch_company_card,
)
from services.cache import bist_cache

logger = logging.getLogger(__name__)

BOARD_FILE = os.path.join(REGISTRY_DIR, "bist_ownership_board.json")
BOARD_CACHE_KEY = "bist_ownership:board"
MOVES_CACHE_KEY = "bist_ownership:moves"

UNIVERSE = "XU100"
PAYLOAD_VERSION = 1

# The memory cache only. A board is never discarded for age; it is served
# with `stale` set, and the two-hour slack keeps a late nightly run from
# flapping the flag.
BOARD_TTL_SECONDS = 26 * 60 * 60
BOARD_STALE_AFTER_SECONDS = 26 * 60 * 60

# Between cards. Each card is over a megabyte and takes a few seconds on its
# own, so the walk is around seven minutes for the index; the pause is not
# what makes it slow, it is what keeps a hundred requests from arriving as a
# burst at a SharePoint host that would otherwise notice.
REQUEST_SPACING_SECONDS = 0.5

# The tape window the moves are read from. `BUFFER_LIMIT` in `kap_service` is
# the most it can hold anyway.
TAPE_WINDOW = 600
MOVES_TTL_SECONDS = 60

LATEST_MOVES_LIMIT = 12
TOP_POSITIONS_ON_CARD = 3
TOP_ALLOCATION_SLICES = 6

_refresh_lock: asyncio.Lock | None = None


def _lock() -> asyncio.Lock:
    # Created lazily so the lock binds to the loop that first uses it — module
    # import happens before uvicorn's loop exists, and tests run several.
    global _refresh_lock
    if _refresh_lock is None:
        _refresh_lock = asyncio.Lock()
    return _refresh_lock


@dataclass
class RefreshReport:
    tickers_total: int = 0
    tickers_ok: int = 0
    tickers_failed: int = 0
    tickers_carried: int = 0
    funds_total: int = 0
    funds_ok: int = 0
    funds_failed: int = 0
    duration_seconds: float = 0.0


# ── Storage ──────────────────────────────────────────────────────────────


def _load_payload() -> dict[str, Any] | None:
    cached = bist_cache.get(BOARD_CACHE_KEY)
    if cached is not None:
        return cached
    payload = read_json_cache(BOARD_FILE)
    if not isinstance(payload, dict) or payload.get("version") != PAYLOAD_VERSION:
        return None
    bist_cache.set(BOARD_CACHE_KEY, payload, BOARD_TTL_SECONDS)
    return payload


def stored_payload() -> dict[str, Any] | None:
    """The stored board as written, for readers that need the per-ticker tables."""
    return _load_payload()


def store_payload(payload: dict[str, Any]) -> None:
    write_json_cache(BOARD_FILE, payload)
    bist_cache.set(BOARD_CACHE_KEY, payload, BOARD_TTL_SECONDS)
    bist_cache.invalidate(MOVES_CACHE_KEY)


def board_age_seconds() -> float | None:
    payload = _load_payload()
    if payload is None:
        return None
    stamp = payload.get("last_refresh_at")
    if not isinstance(stamp, str):
        return None
    try:
        refreshed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return (datetime.now(UTC) - refreshed).total_seconds()


def _is_stale(payload: dict[str, Any]) -> bool:
    age = board_age_seconds()
    return age is None or age > BOARD_STALE_AFTER_SECONDS


# ── Refresh ──────────────────────────────────────────────────────────────


def _fund_as_of(year: int, period: int) -> str:
    return f"{year:04d}-{period:02d}"


def _fraction(percent: float | None) -> float | None:
    return None if percent is None else percent / 100.0


async def refresh_board(*, spacing: float = REQUEST_SPACING_SECONDS) -> RefreshReport:
    """
    Fetch every XU100 card and every registry fund's report, and store them.

    Serialised: the admin button and the boot warm-up must not run two walks
    over the same host at once. A ticker whose card fails keeps its previous
    row, marked `carried`, so a bad afternoon at İş Yatırım does not empty a
    company's page — the reader sees yesterday's table and is told so.
    """
    async with _lock():
        started = time.monotonic()
        report = RefreshReport()

        try:
            equity_board = await fetch_equity_board()
        except EquityDataUnavailable as e:
            raise BoardUnavailable(f"equity board unavailable, cannot value stakes: {e}") from e

        members = [row for row in equity_board.equities if UNIVERSE in row.indices]
        if not members:
            raise BoardUnavailable(f"equity board lists no {UNIVERSE} members")

        previous = _load_payload() or {}
        previous_tickers: dict[str, Any] = previous.get("tickers") or {}

        market_caps = {
            row.ticker: row.market_cap for row in equity_board.equities if row.market_cap
        }
        names = {row.ticker: row.name for row in equity_board.equities}

        tickers: dict[str, Any] = {}
        report.tickers_total = len(members)
        for index, row in enumerate(sorted(members, key=lambda r: r.ticker)):
            try:
                card = await fetch_company_card(row.ticker)
            except IsYatirimUnavailable as e:
                logger.warning("BIST ownership: %s card failed: %s", row.ticker, e)
                carried = previous_tickers.get(row.ticker)
                if carried and carried.get("ok"):
                    tickers[row.ticker] = {**carried, "carried": True, "error": str(e)}
                    report.tickers_carried += 1
                else:
                    tickers[row.ticker] = {
                        "ticker": row.ticker,
                        "name": row.name,
                        "ok": False,
                        "carried": False,
                        "error": str(e),
                        "holders": [],
                    }
                report.tickers_failed += 1
            else:
                tickers[row.ticker] = {
                    "ticker": row.ticker,
                    "name": row.name,
                    "market_cap": row.market_cap or card.market_cap_try,
                    # Fractions from here on. The equity row already is one;
                    # the card prints percent.
                    "free_float_pct": row.free_float_pct
                    if row.free_float_pct is not None
                    else _fraction(card.free_float_pct),
                    "foreign_ratio_pct": _fraction(card.foreign_ratio_pct),
                    "other_pct": _fraction(card.other_pct),
                    "holders": [
                        {"label": s.name, "stake_pct": s.pct / 100.0} for s in card.shareholders
                    ],
                    "url": card.url,
                    "retrieved_at": card.retrieved_at,
                    "ok": True,
                    "carried": False,
                    "error": None,
                }
                report.tickers_ok += 1
            if index < len(members) - 1:
                await asyncio.sleep(spacing)

        funds: dict[str, Any] = {}
        for entity in registry.load_entities():
            code = entity.fund_code
            if not code:
                continue
            report.funds_total += 1
            outcome = await holdings_service.fetch_fund_holdings(code, entity.fund_type)
            book = outcome.holdings
            if book is None:
                report.funds_failed += 1
                funds[entity.id] = {
                    "code": code,
                    "ok": False,
                    "reason": outcome.reason,
                    "stale": outcome.stale,
                    "holdings": [],
                }
                continue
            report.funds_ok += 1
            funds[entity.id] = {
                "code": code,
                "ok": True,
                "reason": None,
                "stale": outcome.stale,
                "as_of": _fund_as_of(book.year, book.period),
                "published": book.published.isoformat() if book.published else None,
                "url": book.disclosure_url,
                "total_value": book.total_value,
                "holdings": [
                    {
                        "ticker": h.ticker,
                        "label": h.label,
                        "value": h.value,
                        "weight": h.weight,
                    }
                    for h in book.holdings
                ],
                "retrieved_at": datetime.now(UTC).isoformat(),
            }

        now = datetime.now(UTC).isoformat()
        payload = {
            "version": PAYLOAD_VERSION,
            "universe": UNIVERSE,
            "as_of": now,
            "last_refresh_at": now,
            "tickers": tickers,
            "funds": funds,
            "market_caps": market_caps,
            "names": names,
        }
        store_payload(payload)
        # Written after the board so a crash between the two leaves a board
        # without a snapshot rather than a snapshot without a board.
        snapshots.record(now[:10], tickers)
        report.duration_seconds = time.monotonic() - started
        logger.info(
            "BIST ownership board rebuilt: %d/%d cards (%d carried), %d/%d funds, %.0fs",
            report.tickers_ok,
            report.tickers_total,
            report.tickers_carried,
            report.funds_ok,
            report.funds_total,
            report.duration_seconds,
        )
        return report


async def ensure_board(max_age_seconds: float = 36 * 60 * 60) -> None:
    """Build at boot if there is no board or the stored one has aged out."""
    age = board_age_seconds()
    if age is not None and age < max_age_seconds:
        return
    logger.info(
        "BIST ownership board %s — building at startup",
        "missing" if age is None else f"{age / 3600:.1f}h old",
    )
    await refresh_board()


# ── Moves (read-time, from the KAP tape) ─────────────────────────────────


def _move(row: Any) -> Move | None:
    materiality = classify(row.title, row.summary, row.category)
    if materiality.event not in OWNERSHIP_EVENTS:
        return None
    company = row.company or row.ticker
    return Move(
        id=f"kap-{row.index}",
        ticker=row.ticker,
        company=company,
        event=materiality.event,
        event_label=materiality.label,
        headline=f"{row.ticker} · {row.title}" if row.ticker else row.title,
        published_at=row.published_at,
        url=row.url,
        score=materiality.score,
        band=materiality.band,
    )


async def _ownership_moves() -> list[Move]:
    cached = bist_cache.get(MOVES_CACHE_KEY)
    if cached is not None:
        return cached
    try:
        rows = await fetch_tape(TAPE_WINDOW, categories=frozenset())
    except KapUnavailable as e:
        logger.info("BIST ownership: KAP tape unavailable, no moves: %s", e)
        return []
    moves = [m for m in (_move(row) for row in rows) if m is not None]
    bist_cache.set(MOVES_CACHE_KEY, moves, MOVES_TTL_SECONDS)
    return moves


# ── Derivation ───────────────────────────────────────────────────────────


def _source_for_ticker(row: dict[str, Any]) -> SourceRef:
    retrieved = row.get("retrieved_at")
    return SourceRef(
        kind="isyatirim_shareholders",
        label=SOURCE_LABEL,
        url=row.get("url"),
        as_of=retrieved[:10] if isinstance(retrieved, str) else None,
        retrieved_at=retrieved,
    )


def _source_for_fund(fund: dict[str, Any]) -> SourceRef:
    return SourceRef(
        kind="kap_fund_report",
        label="KAP portföy raporu",
        url=fund.get("url"),
        as_of=fund.get("as_of"),
        retrieved_at=fund.get("retrieved_at"),
    )


def _marked(stake: float | None, market_cap: float | None) -> float | None:
    if stake is None or not market_cap:
        return None
    return market_cap * stake


def _history_fields(ticker: str, holder: str, stake: float | None) -> dict[str, Any]:
    """
    What the snapshots say about one holder of one company.

    `at_baseline` defaults to True when there is no history at all: with no
    snapshot, the entry date is unknown, which is exactly what the flag means.
    """
    history = snapshots.history_for(ticker, holder)
    if history is None:
        return {"since": None, "at_baseline": True, "previous_stake_pct": None, "delta_pct": None}
    delta = (
        stake - history.previous_stake
        if stake is not None and history.previous_stake is not None
        else None
    )
    if delta is not None and abs(delta) < snapshots.MIN_STAKE_DELTA:
        delta = 0.0
    return {
        "since": history.first_seen,
        "at_baseline": history.at_baseline,
        "previous_stake_pct": history.previous_stake,
        "delta_pct": delta,
    }


def _shareholder_positions(
    entity_id: str, payload: dict[str, Any], index: registry.AliasIndex
) -> list[Position]:
    positions: list[Position] = []
    for ticker, row in (payload.get("tickers") or {}).items():
        for holder in row.get("holders") or []:
            if index.match(holder["label"]) != entity_id:
                continue
            stake = holder.get("stake_pct")
            market_cap = row.get("market_cap")
            value = _marked(stake, market_cap)
            positions.append(
                Position(
                    ticker=ticker,
                    name=row.get("name") or ticker,
                    stake_pct=stake,
                    value_try=value,
                    value_basis="marked" if value is not None else "unknown",
                    source=_source_for_ticker(row),
                    note=("Dünkü tablo; bugünkü kart alınamadı" if row.get("carried") else None),
                    **_history_fields(ticker, holder["label"], stake),
                )
            )
    return positions


def _stake_moves(payload: dict[str, Any], index: registry.AliasIndex) -> list[StakeMove]:
    """Every entry, exit and resize the snapshots have seen, newest first."""
    names = payload.get("names") or {}
    tickers = payload.get("tickers") or {}
    out: list[StakeMove] = []
    for change in snapshots.all_changes():
        row = tickers.get(change.ticker) or {}
        delta = (
            (change.stake_after or 0.0) - (change.stake_before or 0.0)
            if change.kind in ("add", "trim")
            else None
        )
        out.append(
            StakeMove(
                id=f"stake-{change.observed_at}-{change.ticker}-{change.holder}",
                ticker=change.ticker,
                company=row.get("name") or names.get(change.ticker) or change.ticker,
                holder=change.holder,
                entity_id=index.match(change.holder),
                kind=change.kind,  # type: ignore[arg-type]
                stake_before=change.stake_before,
                stake_after=change.stake_after,
                delta_pct=delta,
                observed_at=change.observed_at,
            )
        )
    return out


def _fund_positions(entity_id: str, payload: dict[str, Any]) -> list[Position]:
    fund = (payload.get("funds") or {}).get(entity_id)
    if not fund or not fund.get("ok"):
        return []
    market_caps = payload.get("market_caps") or {}
    names = payload.get("names") or {}
    source = _source_for_fund(fund)
    positions: list[Position] = []
    for holding in fund.get("holdings") or []:
        ticker = holding["ticker"]
        value = holding.get("value")
        market_cap = market_caps.get(ticker)
        stake = (value / market_cap) if value and market_cap else None
        positions.append(
            Position(
                ticker=ticker,
                name=names.get(ticker) or holding.get("label") or ticker,
                stake_pct=stake,
                value_try=value,
                value_basis="reported" if value is not None else "unknown",
                source=source,
                note=None,
            )
        )
    return positions


def _weighted(positions: list[Position]) -> tuple[list[Position], float | None]:
    known = [p.value_try for p in positions if p.value_try is not None]
    total = sum(known) if known else None
    weighted: list[Position] = []
    for position in sorted(positions, key=lambda p: -(p.value_try or 0.0)):
        weight = position.value_try / total if total and position.value_try is not None else None
        weighted.append(position.model_copy(update={"weight_pct": weight}))
    return weighted, total


def _allocation(positions: list[Position], total: float | None) -> list[AllocationSlice]:
    if not total:
        return []
    valued = [p for p in positions if p.value_try]
    head = valued[:TOP_ALLOCATION_SLICES]
    tail = valued[TOP_ALLOCATION_SLICES:]
    slices = [
        AllocationSlice(
            key=p.ticker,
            label=p.name,
            ticker=p.ticker,
            value_try=p.value_try or 0.0,
            pct=(p.value_try or 0.0) / total,
        )
        for p in head
    ]
    pooled = sum(p.value_try or 0.0 for p in tail)
    if pooled > 0:
        slices.append(
            AllocationSlice(
                key=POOLED_SLICE_KEY,
                label=f"Diğer {len(tail)} pozisyon",
                ticker=None,
                value_try=pooled,
                pct=pooled / total,
            )
        )
    return slices


def _entity_issues(entity: registry.EntityConfig, payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if entity.fund_code:
        fund = (payload.get("funds") or {}).get(entity.id) or {}
        if not fund.get("ok"):
            reason = fund.get("reason") or holdings_service.REASON_UNAVAILABLE
            issues.append(
                {
                    holdings_service.REASON_NO_REPORT: "Fonun KAP'ta okunabilir bir portföy raporu yok.",
                    holdings_service.REASON_UNREADABLE: "Fonun portföy raporu bu ayrıştırıcı tarafından okunamadı.",
                    holdings_service.REASON_NOT_LISTED: "Fon KAP'ın aktif fon listesinde değil.",
                    holdings_service.REASON_NO_EQUITY: "Fonun son raporunda hisse pozisyonu yok.",
                }.get(reason, "KAP'a ulaşılamadı; fonun kitabı alınamadı.")
            )
        elif fund.get("stale"):
            issues.append("Fonun kitabı önceki bir çalışmadan taşındı.")
    if entity.tracks_shareholders:
        carried = sum(1 for row in (payload.get("tickers") or {}).values() if row.get("carried"))
        if carried:
            issues.append(f"{carried} şirketin kartı bugün alınamadı; dünkü tablo gösteriliyor.")
    return issues


def _summarise(
    entity: registry.EntityConfig,
    positions: list[Position],
    moves: list[Move],
    payload: dict[str, Any],
    stale: bool,
) -> tuple[EntitySummary, list[Position]]:
    weighted, total = _weighted(positions)
    tickers = {p.ticker for p in weighted}
    own_moves = [m for m in moves if m.ticker in tickers]
    return (
        EntitySummary(
            id=entity.id,
            name=entity.name,
            subtitle=entity.subtitle,
            category=entity.category,  # type: ignore[arg-type]
            total_value_try=total,
            positions_count=len(weighted),
            allocation=_allocation(weighted, total),
            top_positions=weighted[:TOP_POSITIONS_ON_CARD],
            last_move=own_moves[0] if own_moves else None,
            as_of=payload.get("as_of"),
            stale=stale,
            issues=_entity_issues(entity, payload),
            has_data=bool(weighted),
            coverage_note=entity.coverage_note,
        ),
        weighted,
    )


def _positions_for(
    entity: registry.EntityConfig, payload: dict[str, Any], index: registry.AliasIndex
) -> list[Position]:
    positions: list[Position] = []
    if entity.tracks_shareholders:
        positions.extend(_shareholder_positions(entity.id, payload, index))
    if entity.fund_code:
        positions.extend(_fund_positions(entity.id, payload))
    return positions


def _source_health(
    payload: dict[str, Any], entities: list[registry.EntityConfig]
) -> list[SourceHealth]:
    tickers = payload.get("tickers") or {}
    ok_cards = sum(1 for row in tickers.values() if row.get("ok") and not row.get("carried"))
    carried = sum(1 for row in tickers.values() if row.get("carried"))
    failed = len(tickers) - ok_cards - carried
    funds = payload.get("funds") or {}
    funds_ok = sum(1 for f in funds.values() if f.get("ok"))
    return [
        SourceHealth(
            kind="isyatirim_shareholders",
            ok=ok_cards > 0 and failed == 0 and carried == 0,
            entities_covered=sum(1 for e in entities if e.tracks_shareholders),
            tickers_covered=ok_cards + carried,
            as_of=payload.get("as_of"),
            message=(
                None
                if failed == 0 and carried == 0
                else f"{failed} kart alınamadı, {carried} kart dünden taşındı"
            ),
        ),
        SourceHealth(
            kind="kap_fund_report",
            ok=funds_ok == len(funds) and bool(funds),
            entities_covered=funds_ok,
            tickers_covered=len(
                {h["ticker"] for f in funds.values() for h in f.get("holdings", [])}
            ),
            as_of=max((f.get("as_of") or "" for f in funds.values()), default=None) or None,
            message=None if funds_ok == len(funds) else f"{len(funds) - funds_ok} fonun kitabı yok",
        ),
    ]


def _require_payload() -> dict[str, Any]:
    payload = _load_payload()
    if payload is None:
        raise BoardUnavailable("BIST ownership board has not been built yet")
    return payload


# ── Public reads ─────────────────────────────────────────────────────────


async def get_board() -> OwnershipBoard:
    payload = _require_payload()
    entities = registry.load_entities()
    index = registry.AliasIndex(entities)
    moves = await _ownership_moves()
    stale = _is_stale(payload)
    covered = {t for t, row in (payload.get("tickers") or {}).items() if row.get("ok")}
    universe_moves = [m for m in moves if m.ticker in covered]

    summaries: list[EntitySummary] = []
    counts: dict[str, int] = {}
    for entity in entities:
        summary, _ = _summarise(
            entity, _positions_for(entity, payload, index), universe_moves, payload, stale
        )
        summaries.append(summary)
        counts[entity.category] = counts.get(entity.category, 0) + 1

    stake_moves = [m for m in _stake_moves(payload, index) if m.ticker in covered]
    return OwnershipBoard(
        entities=summaries,
        latest_moves=universe_moves[:LATEST_MOVES_LIMIT],
        latest_stake_moves=stake_moves[:LATEST_MOVES_LIMIT],
        tracking_since=snapshots.baseline_day(),
        category_counts=counts,
        sources=_source_health(payload, entities),
        universe=payload.get("universe") or UNIVERSE,
        tickers_covered=len(covered),
        tickers_total=len(payload.get("tickers") or {}),
        as_of=payload.get("as_of"),
        last_refresh_at=payload.get("last_refresh_at"),
        stale=stale,
    )


async def get_entity(entity_id: str) -> EntityDetail:
    payload = _require_payload()
    entities = registry.load_entities()
    entity = next((e for e in entities if e.id == entity_id), None)
    if entity is None:
        raise EntityNotFound(f"unknown entity {entity_id!r}")
    index = registry.AliasIndex(entities)
    moves = await _ownership_moves()
    summary, positions = _summarise(
        entity, _positions_for(entity, payload, index), moves, payload, _is_stale(payload)
    )
    tickers = {p.ticker for p in positions}
    seen: dict[str, SourceRef] = {}
    for position in positions:
        seen.setdefault(position.source.kind, position.source)
    return EntityDetail(
        entity=summary,
        positions=positions,
        moves=[m for m in moves if m.ticker in tickers],
        stake_moves=[m for m in _stake_moves(payload, index) if m.entity_id == entity.id],
        sources=list(seen.values()),
        tracking_since=snapshots.baseline_day(),
    )


async def get_moves(limit: int = LATEST_MOVES_LIMIT, ticker: str | None = None) -> list[Move]:
    moves = await _ownership_moves()
    if ticker:
        wanted = ticker.strip().upper().rsplit(":", 1)[-1]
        moves = [m for m in moves if m.ticker == wanted]
    return moves[:limit]


async def get_asset_owners(ticker: str) -> AssetOwners:
    payload = _require_payload()
    code = ticker.strip().upper().rsplit(":", 1)[-1]
    row = (payload.get("tickers") or {}).get(code)
    if row is None:
        raise TickerNotCovered(f"{code} is not in the {UNIVERSE} universe this board covers")
    if not row.get("ok"):
        raise BoardUnavailable(f"{code}: {row.get('error') or 'card unavailable'}")

    entities = registry.load_entities()
    index = registry.AliasIndex(entities)
    market_cap = row.get("market_cap")
    holders = []
    for holder in row.get("holders") or []:
        entity_id = index.match(holder["label"])
        holders.append(
            Holder(
                label=holder["label"],
                stake_pct=holder["stake_pct"],
                value_try=_marked(holder.get("stake_pct"), market_cap),
                entity_id=entity_id,
                tracked=entity_id is not None,
                **_history_fields(code, holder["label"], holder.get("stake_pct")),
            )
        )
    holders.sort(key=lambda h: -h.stake_pct)

    funds: list[FundHolder] = []
    for entity in entities:
        fund = (payload.get("funds") or {}).get(entity.id)
        if not fund or not fund.get("ok"):
            continue
        for holding in fund.get("holdings") or []:
            if holding["ticker"] != code:
                continue
            value = holding.get("value")
            funds.append(
                FundHolder(
                    entity_id=entity.id,
                    name=entity.name,
                    code=fund["code"],
                    weight_in_fund_pct=holding.get("weight"),
                    value_try=value,
                    stake_pct=(value / market_cap) if value and market_cap else None,
                    as_of=fund.get("as_of"),
                    url=fund.get("url"),
                )
            )
    funds.sort(key=lambda f: -(f.value_try or 0.0))

    moves = await get_moves(limit=20, ticker=code)
    return AssetOwners(
        ticker=code,
        name=row.get("name") or code,
        market_cap=market_cap,
        free_float_pct=row.get("free_float_pct"),
        foreign_ratio_pct=row.get("foreign_ratio_pct"),
        holders=holders,
        funds=funds,
        moves=moves,
        stake_moves=[m for m in _stake_moves(payload, index) if m.ticker == code],
        tracking_since=snapshots.baseline_day(),
        as_of=row.get("retrieved_at") or payload.get("as_of"),
        stale=_is_stale(payload) or bool(row.get("carried")),
        source_url=row.get("url"),
    )
