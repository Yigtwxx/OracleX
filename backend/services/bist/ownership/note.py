"""
What the whole ownership board says, above eighty cards that each say one thing.

`/bist/ortaklik` lists every tracked holder with its stakes. Each card is a
correct answer to "what does this one own", and the question a reader arrives
with sits above them: how much of the index is the state, how much is family
holdings, how much is foreign strategic capital, and what that leaves to trade.
Nothing on the grid adds the cards up, so this module does, classifies the
result in Python, and hands `services/ai_notes` a finished set of facts to
narrate — the contract every note on this realm holds to, and for the same
reason: a local model asked to do arithmetic will do it confidently and wrongly.

**The facts are quantized to the day.** The board rebuilds once a day and the
market caps it is valued at come from that build, so a fingerprint over
day-rounded figures retires the note exactly once a day. Shares are rounded
to a point and lira totals to ten billion, which is coarser than anything the
prose would quote and fine enough that a real change still re-fires the note.

**The prompt is rendered from the facts and from nothing else.** A cached note
can then never quote a figure that has since moved — see `ai_notes.get_note`.
"""

from __future__ import annotations

import logging
import statistics
from collections import Counter
from typing import Any

from services.ai_notes import REASON_INSUFFICIENT_DATA, NoteSpec, get_note, unavailable
from services.bist.ownership import board as board_module
from services.bist.ownership import snapshots
from services.bist.ownership.errors import BistOwnershipError

logger = logging.getLogger(__name__)

OWNERSHIP_SPEC = NoteSpec(
    kind="bist_ownership",
    prompt="notes/bist_ownership",
    # The same room the other market-wide reads get: this weaves a category
    # split, a concentration reading and a change log rather than one card.
    max_tokens=560,
    max_chars=1400,
    temperature=0.25,
    max_age_seconds=8 * 3600,
)

# What this read cannot see, named to the reader and to the model rather than
# left implicit. The first is the structural one: there is no 13F, so a
# holder's stakes under 5% and anything outside the XU100 are invisible.
NOT_MEASURED: tuple[str, ...] = (
    "%5 altındaki paylar",
    "ortakların XU100 dışındaki varlıkları",
    "pay değişimlerinin gerçek işlem tarihi",
    "fon raporu okunamayan fonların pozisyonları",
)

# Below this coverage the split is a handful of cards, not an index to describe.
MIN_TICKERS_COVERED = 40

STANCE_STATE = "state_anchored"
STANCE_HOLDINGS = "family_holdings"
STANCE_FOREIGN = "foreign_strategic"
STANCE_DISPERSED = "dispersed"

# Under this share for the largest category, no single kind of owner
# characterises the index and the read is "dispersed".
DOMINANT_SHARE_PCT = 35.0

TOP_HOLDERS = 5
TOP_FOREIGN = 3
RECENT_MOVES = 5
RECENT_FILINGS = 4

# Turkish, because the note is written in Turkish and a local model handed an
# English category name translates it on the fly — "sovereign fund" came back
# as "süvari fon", which is a cavalry fund. The prompt names the categories
# the way the page does and the model has nothing to translate.
CATEGORY_LABEL = {
    "state": "kamu (Varlık Fonu, Hazine, kamu kurumları)",
    "holding": "yerli holdingler ve aile şirketleri",
    "foreign": "yabancı stratejik ortaklar",
    "fund": "TEFAS hisse fonları",
    "other": "vakıflar, kulüpler ve diğer kurumlar",
}


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def _bn(value: float | None) -> float | None:
    """Lira to billions, to the nearest ten billion — the day's coarse figure."""
    if value is None:
        return None
    return round(value / 1e9 / 10.0) * 10.0


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _show(value: float | None, suffix: str = "", digits: int = 1) -> str:
    return "not available" if value is None else f"{value:.{digits}f}{suffix}"


def _bullet(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) if lines else "- none"


def classify_stance(category_shares: dict[str, float]) -> str:
    """Which kind of owner characterises the index, from the valued split."""
    if not category_shares:
        return STANCE_DISPERSED
    top, share = max(category_shares.items(), key=lambda kv: kv[1])
    if share < DOMINANT_SHARE_PCT:
        return STANCE_DISPERSED
    if top == "state":
        return STANCE_STATE
    if top == "holding":
        return STANCE_HOLDINGS
    if top == "foreign":
        return STANCE_FOREIGN
    return STANCE_DISPERSED


async def build_ownership_facts() -> dict[str, Any] | None:
    """
    The whole board as a quantized set of readings, or None.

    None means the board has not been built or covers too little of the index
    to characterise, which the caller must not render as "nobody holds
    anything". "Nothing to say" and "cannot see" are different claims.
    """
    try:
        board = await board_module.get_board()
    except BistOwnershipError as e:
        logger.info("BIST ownership board unavailable for the note: %s", e)
        return None
    if board.tickers_covered < MIN_TICKERS_COVERED:
        return None

    payload = board_module.stored_payload() or {}
    tickers = payload.get("tickers") or {}

    valued = [e for e in board.entities if e.total_value_try]
    total = sum(e.total_value_try or 0.0 for e in valued)
    by_category: dict[str, float] = {}
    entities_by_category: Counter[str] = Counter()
    for entity in valued:
        by_category[entity.category] = by_category.get(entity.category, 0.0) + (
            entity.total_value_try or 0.0
        )
        entities_by_category[entity.category] += 1
    shares = {
        category: (value / total * 100.0 if total else 0.0)
        for category, value in by_category.items()
    }

    ranked = sorted(valued, key=lambda e: -(e.total_value_try or 0.0))
    top3 = sum(e.total_value_try or 0.0 for e in ranked[:3])

    # Per-company concentration, from the stored tables rather than the cards,
    # so untracked holders count towards it too.
    named_stakes: list[float] = []
    free_floats: list[float] = []
    foreign: list[tuple[str, float]] = []
    without_holder = 0
    majority_held = 0
    for ticker, row in tickers.items():
        if not row.get("ok"):
            continue
        stakes = [h["stake_pct"] for h in row.get("holders") or [] if h.get("stake_pct")]
        if stakes:
            named_stakes.append(sum(stakes) * 100.0)
            if max(stakes) > 0.5:
                majority_held += 1
        else:
            without_holder += 1
        if row.get("free_float_pct") is not None:
            free_floats.append(row["free_float_pct"] * 100.0)
        if row.get("foreign_ratio_pct") is not None:
            foreign.append((ticker, row["foreign_ratio_pct"] * 100.0))
    foreign.sort(key=lambda item: -item[1])

    stake_kinds = Counter(m.kind for m in board.latest_stake_moves)
    all_stake_changes = snapshots.all_changes()
    filing_kinds = Counter(m.event_label for m in board.latest_moves)

    funds = [e for e in board.entities if e.category == "fund"]
    funds_readable = sum(1 for e in funds if e.has_data)

    return {
        # Part of the fingerprint on purpose: bumping it retires every cached
        # note when the prompt or its labels change, which the facts alone
        # would not notice.
        "prompt_revision": 2,
        "stance": classify_stance(shares),
        "coverage": {
            "universe": board.universe,
            "tickers_covered": board.tickers_covered,
            "tickers_total": board.tickers_total,
            "entities": len(board.entities),
            "entities_with_data": sum(1 for e in board.entities if e.has_data),
            "as_of": (board.as_of or "")[:10] or None,
            "tracking_since": board.tracking_since,
            "tracking_days": len(snapshots.days()),
        },
        "total": {
            "valued_try_bn": _bn(total),
            "categories": [
                {
                    "category": category,
                    "share_pct": _round(share, 0),
                    "entities": entities_by_category[category],
                }
                for category, share in sorted(shares.items(), key=lambda kv: -kv[1])
            ],
        },
        "holders": {
            "top": [
                {
                    "name": e.name,
                    "category": e.category,
                    "value_try_bn": _bn(e.total_value_try),
                    "positions": e.positions_count,
                    "share_pct": _round(
                        (e.total_value_try or 0.0) / total * 100.0 if total else 0.0, 0
                    ),
                }
                for e in ranked[:TOP_HOLDERS]
            ],
            "top3_share_pct": _round(top3 / total * 100.0 if total else 0.0, 0),
        },
        "companies": {
            "with_named_holder": len(named_stakes),
            "without_named_holder": without_holder,
            "majority_held": majority_held,
            "median_named_stake_pct": _round(_median(named_stakes), 0),
            "median_free_float_pct": _round(_median(free_floats), 0),
            "median_foreign_ratio_pct": _round(_median([f for _, f in foreign]), 0),
            "foreign_high": [{"ticker": t, "pct": _round(f, 0)} for t, f in foreign[:TOP_FOREIGN]],
            "foreign_low": [
                {"ticker": t, "pct": _round(f, 0)} for t, f in foreign[-TOP_FOREIGN:][::-1]
            ],
        },
        "moves": {
            "stake_total": len(all_stake_changes),
            "stake_kinds": dict(sorted(stake_kinds.items())),
            "recent_stakes": [
                {
                    "ticker": m.ticker,
                    "holder": m.holder,
                    "kind": m.kind,
                    "before_pct": _round((m.stake_before or 0.0) * 100.0, 1)
                    if m.stake_before is not None
                    else None,
                    "after_pct": _round((m.stake_after or 0.0) * 100.0, 1)
                    if m.stake_after is not None
                    else None,
                    "observed_at": m.observed_at,
                }
                for m in board.latest_stake_moves[:RECENT_MOVES]
            ],
            "filing_kinds": dict(sorted(filing_kinds.items())),
            "recent_filings": [
                {"ticker": m.ticker, "event": m.event_label, "day": (m.published_at or "")[:10]}
                for m in board.latest_moves[:RECENT_FILINGS]
            ],
        },
        "funds": {"tracked": len(funds), "readable": funds_readable},
        "not_measured": list(NOT_MEASURED),
        "stale": board.stale,
    }


def ownership_values(facts: dict[str, Any]) -> dict[str, str]:
    """Render the prompt's placeholders from the facts, and from nothing else."""
    coverage = facts["coverage"]
    total = facts["total"]
    holders = facts["holders"]
    companies = facts["companies"]
    moves = facts["moves"]
    funds = facts["funds"]

    coverage_lines = [
        f"- Universe: {coverage['universe']}, shareholder tables read for "
        f"{coverage['tickers_covered']} of {coverage['tickers_total']} companies "
        f"(as of {coverage['as_of'] or 'not available'})",
        f"- Tracked holders: {coverage['entities']}, of which "
        f"{coverage['entities_with_data']} hold at least one stake above 5%",
        f"- Fund reports readable: {funds['readable']} of {funds['tracked']} tracked funds",
        f"- Daily table snapshots held: {coverage['tracking_days']} "
        f"(since {coverage['tracking_since'] or 'not available'})",
        f"- Everything valued at the day's market cap: "
        f"{_show(total['valued_try_bn'], ' bn TRY', 0)} in total",
    ]
    if facts.get("stale"):
        coverage_lines.append("- The board is older than a day; figures are the last good build")

    category_lines = [
        f"- {CATEGORY_LABEL.get(c['category'], c['category'])}: "
        f"{_show(c['share_pct'], '%', 0)} of the valued total across {c['entities']} holders"
        for c in total["categories"]
    ]
    category_lines.append(
        f"- The three largest holders together: {_show(holders['top3_share_pct'], '%', 0)}"
    )

    holder_lines = [
        f"{h['name']} ({CATEGORY_LABEL.get(h['category'], h['category'])}): "
        f"{_show(h['value_try_bn'], ' bn TRY', 0)} across {h['positions']} stakes, "
        f"{_show(h['share_pct'], '%', 0)} of the valued total"
        for h in holders["top"]
    ]

    company_lines = [
        f"- Companies with at least one holder above 5%: {companies['with_named_holder']}; "
        f"with none (genuinely dispersed capital): {companies['without_named_holder']}",
        f"- Companies where one holder owns more than half: {companies['majority_held']}",
        f"- Median share of capital held by named holders: "
        f"{_show(companies['median_named_stake_pct'], '%', 0)}",
        f"- Median free float: {_show(companies['median_free_float_pct'], '%', 0)}",
        f"- Median foreign share of the free float: "
        f"{_show(companies['median_foreign_ratio_pct'], '%', 0)}",
        "- Highest foreign share: "
        + (
            ", ".join(f"{f['ticker']} {_show(f['pct'], '%', 0)}" for f in companies["foreign_high"])
            or "not available"
        ),
        "- Lowest foreign share: "
        + (
            ", ".join(f"{f['ticker']} {_show(f['pct'], '%', 0)}" for f in companies["foreign_low"])
            or "not available"
        ),
    ]

    kinds = moves["stake_kinds"]
    move_lines = [
        f"- Stake changes seen on the daily table, all time: {moves['stake_total']} "
        f"(recent strip: " + (", ".join(f"{k} {v}" for k, v in kinds.items()) or "none") + ")",
    ]
    for m in moves["recent_stakes"]:
        move_lines.append(
            f"- {m['observed_at']}: {m['holder']} in {m['ticker']} — {m['kind']}, "
            f"{_show(m['before_pct'], '%')} → {_show(m['after_pct'], '%')}"
        )
    if not moves["recent_stakes"]:
        move_lines.append(
            "- No stake change observed yet; recording began on "
            f"{coverage['tracking_since'] or 'not available'} and earlier entries are unknown"
        )

    filing_lines = [
        "- Ownership-shaped KAP filings on the tape: "
        + (", ".join(f"{k} {v}" for k, v in moves["filing_kinds"].items()) or "none")
    ]
    for f in moves["recent_filings"]:
        filing_lines.append(f"- {f['day']}: {f['ticker']} — {f['event']}")

    return {
        "stance": facts["stance"].replace("_", " "),
        "coverage": "\n".join(coverage_lines),
        "categories": "\n".join(category_lines),
        "holders": _bullet(holder_lines),
        "companies": "\n".join(company_lines),
        "moves": "\n".join(move_lines),
        "filings": "\n".join(filing_lines),
        "not_measured": ", ".join(facts["not_measured"]),
    }


async def ownership_note(
    facts: dict[str, Any] | None, user_id: str | None = None
) -> dict[str, Any]:
    """The note for this board, or `unavailable` when there is nothing to read."""
    if not facts:
        return unavailable(REASON_INSUFFICIENT_DATA)
    return await get_note(OWNERSHIP_SPEC, facts, ownership_values(facts), user_id)
