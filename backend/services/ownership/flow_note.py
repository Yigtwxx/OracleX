"""
What the tracked institutions did last quarter, in a sentence or four.

Everything here is aggregation. The deltas were computed when the filings were
parsed — `providers/sec_13f.py` compares two consecutive 13F-HR filings and emits
the `add`, `trim`, `new` and `exit` moves this module counts — and nothing is
recomputed. That is not only laziness: the generic snapshot diff explicitly skips
`sec_13f` (`snapshots.EVENT_SOURCE_KINDS`), so the provider is the only correct
source for these numbers, and a second opinion derived here would be a wrong one.

**Only 13F moves count.** `MoveKind` spans ten kinds across four provider
families, and a corporate treasury topping up its bitcoin is not an institution
building a position. Letting one through would let the note say "institutions
bought" about a row no institution filed. The excluded activity is reported as a
count so the omission is visible rather than silent.

Two things this adds that no table on the page shows. The first is the tilt —
whether the quarter was net buying or net selling — which needs the whole set to
compute and so cannot be read off any single row. The second is disagreement:
assets that some holders added and others trimmed in the same quarter. That is
the one fact on this page genuinely worth prose, because it is the only one that
is invisible in a list sorted by size.
"""

import logging
from typing import Any, Optional

from services.ai_notes import (
    REASON_INSUFFICIENT_DATA,
    NoteSpec,
    get_note,
    unavailable,
)
from services.ownership import board
from services.ownership.errors import OwnershipError

logger = logging.getLogger(__name__)

SOURCE_KIND = "sec_13f"

# The 13F subset of the move vocabulary. The other six kinds belong to treasury,
# on-chain and Form 4 rows and cannot appear on a 13F move.
BUY_KINDS = frozenset({"new", "add"})
SELL_KINDS = frozenset({"trim", "exit"})

# Moves to read before filtering. Every entity keeps at most 50 events, so this
# covers a full board of institutions without paging.
MOVE_SCAN_LIMIT = 400

TOP_MOVES = 5
TOP_CONSENSUS = 5

# Share of gross activity that has to lean one way before the quarter is called.
# Below it the holders disagreed, which is its own finding.
TILT_RATIO = 0.15

# Below this the sample is a few filings, not a picture of institutional flow.
MIN_MOVES = 5
MIN_ENTITIES = 3

TILT_NET_BUYING = "net_buying"
TILT_NET_SELLING = "net_selling"
TILT_BALANCED = "balanced"
TILT_INSUFFICIENT = "insufficient"

NOTE_SPEC = NoteSpec(
    kind="ownership_flow",
    prompt="ownership/flow",
    max_tokens=320,
    temperature=0.2,
    # 13F filings land quarterly, so a note that has not been invalidated by a new
    # filing is still current a fortnight later. The move ids in the fingerprint
    # are what actually retires it.
    max_age_seconds=14 * 24 * 3600,
)


def _symbol(move: Any) -> str:
    return (move.asset_symbol or move.asset_label or "").upper()


def _bucket(moves: list[Any]) -> dict[str, dict[str, Any]]:
    """Holders per asset, for one side of the quarter."""
    rows: dict[str, dict[str, Any]] = {}
    for move in moves:
        key = _symbol(move)
        row = rows.setdefault(
            key,
            {"symbol": key, "label": move.asset_label, "holders": [], "total_value_usd": 0.0},
        )
        if move.entity_name not in row["holders"]:
            row["holders"].append(move.entity_name)
        if move.value_usd_delta is not None:
            row["total_value_usd"] += abs(move.value_usd_delta)
    return rows


def _rank(rows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = [{**row, "holder_count": len(row["holders"])} for row in rows.values()]
    ranked.sort(key=lambda row: (-row["holder_count"], -row["total_value_usd"]))
    return ranked[:TOP_CONSENSUS]


def _tilt(gross_bought: float, gross_sold: float, moves: int, entities: int) -> str:
    if moves < MIN_MOVES or entities < MIN_ENTITIES:
        return TILT_INSUFFICIENT

    gross = gross_bought + gross_sold
    if gross <= 0:
        return TILT_INSUFFICIENT

    ratio = (gross_bought - gross_sold) / gross
    if ratio >= TILT_RATIO:
        return TILT_NET_BUYING
    if ratio <= -TILT_RATIO:
        return TILT_NET_SELLING
    return TILT_BALANCED


def build_flow_facts() -> Optional[dict[str, Any]]:
    """
    Last quarter's institutional flow, or None when there is nothing to narrate.

    None covers both real cases — no board has been built, and every tracked
    holder is on its first filing so no quarter-over-quarter change exists — and
    the caller must not turn either into an empty-looking result. "Nobody traded"
    and "we cannot see what anybody did" are different claims.
    """
    try:
        scanned = board.get_moves(limit=MOVE_SCAN_LIMIT)
        payload = board.stored_payload() or {}
    except OwnershipError as e:
        logger.info("Ownership flow note unavailable: %s", e)
        return None

    moves = [move for move in scanned if move.source.kind == SOURCE_KIND]
    if not moves:
        return None

    other_activity = len(scanned) - len(moves)
    buys = [move for move in moves if move.kind in BUY_KINDS]
    sells = [move for move in moves if move.kind in SELL_KINDS]

    # Summing filed values is legitimate here and nowhere else on this page: every
    # 13F figure is as-filed at the same quarter end, so it is one basis. Do not
    # extend this sum across providers — a treasury holding marked at today's spot
    # and a 13F position marked at a quarter end are not addable.
    unpriced = [move for move in moves if move.value_usd_delta is None]
    gross_bought = sum(abs(m.value_usd_delta) for m in buys if m.value_usd_delta is not None)
    gross_sold = sum(abs(m.value_usd_delta) for m in sells if m.value_usd_delta is not None)

    entities = {move.entity_id for move in moves}
    bought_rows, sold_rows = _bucket(buys), _bucket(sells)
    contested = [
        {
            "symbol": symbol,
            "buyers": bought_rows[symbol]["holders"],
            "sellers": sold_rows[symbol]["holders"],
        }
        for symbol in sorted(set(bought_rows) & set(sold_rows))
    ]

    reported = [move.reported_at for move in moves if move.reported_at]
    baselines = set(payload.get("baselines") or [])
    summaries = (payload.get("board") or {}).get("entities") or []
    baseline_names = sorted(
        entry.get("name", entry.get("id", ""))
        for entry in summaries
        if entry.get("id") in baselines
    )

    ranked = sorted(
        moves, key=lambda m: abs(m.value_usd_delta) if m.value_usd_delta is not None else -1.0
    )
    largest = list(reversed(ranked))[: TOP_MOVES * 2]

    return {
        "quarter": moves[0].source.label,
        "period": str(max(move.occurred_at for move in moves)),
        "filed_from": str(min(reported)) if reported else None,
        "filed_to": str(max(reported)) if reported else None,
        "tilt": _tilt(gross_bought, gross_sold, len(moves), len(entities)),
        "gross_bought_usd": round(gross_bought, 2),
        "gross_sold_usd": round(gross_sold, 2),
        "net_usd": round(gross_bought - gross_sold, 2),
        "buy_count": len(buys),
        "sell_count": len(sells),
        "entities_reporting": len(entities),
        "entities_tracked": len(summaries) or len(entities),
        "unpriced_moves": len(unpriced),
        "value_is_partial": bool(unpriced),
        "other_activity_count": other_activity,
        "headlines": [move.headline for move in largest],
        "consensus_bought": _rank(bought_rows),
        "consensus_sold": _rank(sold_rows),
        "contested": contested,
        "baseline_entities": baseline_names,
        # The fingerprint anchor. These ids are deterministic hashes of the filing
        # they came from, so they change when a new 13F lands and at no other
        # time — which is why this note is generated once a quarter and served
        # from cache in between.
        "move_ids": sorted(move.id for move in moves),
    }


def _bullet(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) if lines else "- none"


def _usd(value: Optional[float]) -> str:
    """Whole dollars with separators. Never a bare 0 for a missing figure."""
    return f"${value:,.0f}" if isinstance(value, (int, float)) else "unknown"


def note_values(facts: dict[str, Any]) -> dict[str, str]:
    """Render the prompt's placeholders from the facts, and from nothing else."""
    consensus = [
        f"{row['symbol']}: {row['holder_count']} holder(s) added — {', '.join(row['holders'])}"
        for row in facts["consensus_bought"]
    ] + [
        f"{row['symbol']}: {row['holder_count']} holder(s) trimmed or exited — "
        f"{', '.join(row['holders'])}"
        for row in facts["consensus_sold"]
    ]

    contested = [
        f"{row['symbol']}: added by {', '.join(row['buyers'])}; "
        f"trimmed or exited by {', '.join(row['sellers'])}"
        for row in facts["contested"]
    ]

    coverage = [
        f"{facts['entities_reporting']} of {facts['entities_tracked']} tracked holders "
        "filed a comparable quarter."
    ]
    if facts["baseline_entities"]:
        coverage.append(
            f"{len(facts['baseline_entities'])} holder(s) have a single filing on record, "
            "so no quarter-over-quarter change exists for them: "
            + ", ".join(facts["baseline_entities"])
        )
    if facts["value_is_partial"]:
        coverage.append(
            f"{facts['unpriced_moves']} move(s) carry no dollar value, so the totals "
            "below are floors rather than totals."
        )
    if facts["other_activity_count"]:
        coverage.append(
            f"{facts['other_activity_count']} move(s) from treasury, on-chain and "
            "insider sources are excluded — this is 13F activity only."
        )

    first, last = facts["filed_from"], facts["filed_to"]
    if not first or not last:
        filed = "on dates the filings did not record"
    elif first == last:
        # "between the 14th and the 14th" is what a naive range renders, and it
        # reads as a bug rather than as a quarter whose filings all landed on the
        # deadline — which is exactly what usually happens.
        filed = f"on {first}"
    else:
        filed = f"between {first} and {last}"

    return {
        "quarter": facts["quarter"],
        "period": facts["period"],
        "filed": filed,
        "tilt": facts["tilt"].replace("_", " "),
        "totals": (
            f"{_usd(facts['gross_bought_usd'])} added across {facts['buy_count']} move(s); "
            f"{_usd(facts['gross_sold_usd'])} trimmed or exited across "
            f"{facts['sell_count']} move(s); net {_usd(facts['net_usd'])}"
        ),
        "headlines": _bullet(facts["headlines"]),
        "consensus": _bullet(consensus),
        "contested": _bullet(contested),
        "coverage": _bullet(coverage),
    }


async def flow_note(facts: Optional[dict[str, Any]]) -> dict[str, Any]:
    """The note for this quarter's filings, or `unavailable` when there are none."""
    if not facts:
        return unavailable(REASON_INSUFFICIENT_DATA)
    return await get_note(NOTE_SPEC, facts, note_values(facts))
