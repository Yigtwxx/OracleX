"""
Daily snapshots of every XU100 shareholder table, and the stake changes read
off them.

**Why snapshots and not a source.** Nothing public carries the history of a
Turkish company's shareholder table. İş Yatırım's card is today's table and
only today's; KAP's company page is the same; the filing that changes a stake
is a free-text PDF. So the only way to know *when* a holder entered, left, or
changed size is to have written the table down yesterday and compare. This
module writes it down.

**What a move means here.** A holder that appears in a ticker's table between
two snapshots is a `new` entry, one that disappears an `exit`, and a stake
that changes an `add` or a `trim`. The date on the move is the snapshot day
the change was *observed*, not the day it happened — the card lags the filing
by however long İş Yatırım takes to update it, and the module does not
pretend otherwise. The KAP filings on the same ticker (`board._ownership_moves`)
are the other half of the answer, and usually the earlier one.

**The baseline is honest.** Before the first snapshot nothing is known: a
holder present on day one has been there "since at least" that day, and the
page says so rather than showing the snapshot date as an entry date. A holder
first seen on a later day was genuinely absent the day before, and that is
the only kind of entry this module will claim.

Storage is one JSON file under the registry directory, per day, per ticker,
holder label → stake fraction. Days past the retention window are dropped on
write; the file is a few hundred kilobytes a year.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from services.asset_registry import REGISTRY_DIR, read_json_cache, write_json_cache
from services.cache import bist_cache

logger = logging.getLogger(__name__)

SNAPSHOT_FILE = os.path.join(REGISTRY_DIR, "bist_ownership_snapshots.json")
SNAPSHOT_CACHE_KEY = "bist_ownership:snapshots"
SNAPSHOT_VERSION = 1

# Two years of daily tables. Enough to answer "when did they come in" for
# anything a reader is likely to ask about; the file stays small.
RETENTION_DAYS = 730

# Below this a change is the card rounding, not a trade: the table prints two
# decimals of percent, so a hundredth of a point is its own noise floor.
MIN_STAKE_DELTA = 0.0002

# In-memory only; the file is the truth and every refresh rewrites it.
SNAPSHOT_TTL_SECONDS = 26 * 60 * 60

MoveKind = str  # "new" | "exit" | "add" | "trim"


@dataclass(frozen=True)
class StakeChange:
    ticker: str
    holder: str
    kind: MoveKind
    stake_before: float | None
    stake_after: float | None
    observed_at: str
    """The snapshot day the change was first seen, ISO date."""


@dataclass(frozen=True)
class HolderHistory:
    first_seen: str
    """Earliest snapshot day the holder appears in this ticker's table."""
    at_baseline: bool
    """True when `first_seen` is the earliest snapshot held — the holder was
    already there and the real entry date is unknown."""
    previous_stake: float | None
    """The stake on the snapshot before the latest one. None when there is
    only one snapshot, or the holder was absent from it."""


Tables = dict[str, dict[str, float]]
"""ticker → holder label → stake fraction, for one day."""


def _load() -> dict[str, Any]:
    cached = bist_cache.get(SNAPSHOT_CACHE_KEY)
    if cached is not None:
        return cached
    payload = read_json_cache(SNAPSHOT_FILE)
    if not isinstance(payload, dict) or payload.get("version") != SNAPSHOT_VERSION:
        payload = {"version": SNAPSHOT_VERSION, "days": {}}
    bist_cache.set(SNAPSHOT_CACHE_KEY, payload, SNAPSHOT_TTL_SECONDS)
    return payload


def _store(payload: dict[str, Any]) -> None:
    write_json_cache(SNAPSHOT_FILE, payload)
    bist_cache.set(SNAPSHOT_CACHE_KEY, payload, SNAPSHOT_TTL_SECONDS)


def days() -> list[str]:
    """Every snapshot day held, oldest first."""
    return sorted(_load().get("days", {}).keys())


def tables_for(day: str) -> Tables:
    return _load().get("days", {}).get(day, {})


def record(day: str, tickers: dict[str, Any]) -> None:
    """
    Write today's tables. A second refresh on the same day overwrites the
    first — the later card is the better one — and a card that failed today
    is left out rather than written as an empty table, because an empty table
    would read tomorrow as every holder having exited at once.
    """
    tables: Tables = {}
    for ticker, row in tickers.items():
        if not row.get("ok") or row.get("carried"):
            continue
        tables[ticker] = {
            h["label"]: float(h["stake_pct"])
            for h in row.get("holders", [])
            if h.get("stake_pct") is not None
        }
    if not tables:
        return

    payload = dict(_load())
    held = dict(payload.get("days", {}))
    held[day] = tables
    kept = sorted(held)[-RETENTION_DAYS:]
    payload["days"] = {d: held[d] for d in kept}
    payload["version"] = SNAPSHOT_VERSION
    _store(payload)
    logger.info("BIST ownership snapshot recorded for %s: %d tables", day, len(tables))


def changes_between(earlier: Tables, later: Tables, observed_at: str) -> list[StakeChange]:
    """
    Every holder that entered, left or changed size between two tables.

    Only tickers present in *both* are compared. A ticker missing from one
    side was not fetched that day, and comparing against nothing would report
    every holder as new or gone.
    """
    out: list[StakeChange] = []
    for ticker in sorted(set(earlier) & set(later)):
        before = earlier[ticker]
        after = later[ticker]
        for holder in sorted(set(before) | set(after)):
            b = before.get(holder)
            a = after.get(holder)
            if b is None and a is not None:
                out.append(StakeChange(ticker, holder, "new", None, a, observed_at))
            elif a is None and b is not None:
                out.append(StakeChange(ticker, holder, "exit", b, None, observed_at))
            elif a is not None and b is not None and abs(a - b) >= MIN_STAKE_DELTA:
                out.append(
                    StakeChange(ticker, holder, "add" if a > b else "trim", b, a, observed_at)
                )
    return out


def all_changes() -> list[StakeChange]:
    """Every change across the whole history, newest first."""
    held = days()
    out: list[StakeChange] = []
    for previous, current in zip(held, held[1:]):
        out.extend(changes_between(tables_for(previous), tables_for(current), current))
    return sorted(out, key=lambda c: c.observed_at, reverse=True)


def history_for(ticker: str, holder: str) -> HolderHistory | None:
    """
    When this holder was first seen in this ticker's table, and what its stake
    was the snapshot before the latest. None when never seen.
    """
    held = days()
    if not held:
        return None
    first_seen: str | None = None
    # Walk oldest to newest so `first_seen` is the earliest day, but reset on
    # a gap: a holder that exited and came back entered again on the later day.
    for day in held:
        table = tables_for(day).get(ticker)
        if table is None:
            continue
        if holder in table:
            if first_seen is None:
                first_seen = day
        else:
            first_seen = None
    if first_seen is None:
        return None

    previous_stake: float | None = None
    if len(held) >= 2:
        previous_stake = tables_for(held[-2]).get(ticker, {}).get(holder)

    return HolderHistory(
        first_seen=first_seen,
        at_baseline=first_seen == held[0],
        previous_stake=previous_stake,
    )


def baseline_day() -> str | None:
    """The oldest snapshot held — before it nothing is known."""
    held = days()
    return held[0] if held else None
