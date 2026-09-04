"""
A grounded read of the Borsa İstanbul offering board.

Different from every other note in this realm in one way that governs the whole
module: the facts are built from **third-party free text**. Company names and
broker names arrive from a community-maintained website, and a note prompt is a
place where attacker-controlled text is read by a model. So `sanitize_label` is
applied to every string that comes from that source before it can reach the
facts block, only the ticker is trusted structurally, and the prompt is told in
writing that the names inside it are data. None of the three is sufficient
alone; together they are cheap.

The quantization has a second job here beyond cache stability. The board moves
every day — an offering opens, another lists — and a note fingerprinted on the
day would be rewritten nightly for a market that had not changed. Facts are
snapped to the month and returns to five or ten points, so the note is retired
when the picture moves rather than when the clock does.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from services.ai_notes import NoteSpec, get_note, unavailable

NOTE_SPEC = NoteSpec(
    kind="bist_ipo",
    prompt="notes/bist_ipo",
    max_tokens=320,
    temperature=0.2,
    max_age_seconds=24 * 3600,
    max_chars=1100,
)

UNKNOWN = "not available"

MIN_SAMPLE = 8
"""
Measured listings needed before the board says anything about the distribution.

Below this the median is one company's luck. The endpoint answers with null
facts rather than a note hedged into meaninglessness.
"""

MAX_COMPANY = 120
MAX_TICKER = 8

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_TICKER_RE = re.compile(r"^[A-Z]{3,6}$")


def sanitize_label(raw: Any, limit: int = MAX_COMPANY) -> str:
    """
    Third-party text, made inert before it reaches a prompt.

    Strips control characters and backticks, removes the `{{`/`}}` sequences the
    prompt renderer substitutes on, collapses whitespace and caps the length.
    The cap matters as much as the stripping: an unbounded name is an unbounded
    share of the context window, and the longest thing on a legitimate page is a
    company name of a few dozen characters.
    """
    text = _CONTROL_RE.sub(" ", str(raw or ""))
    text = text.replace("{{", "").replace("}}", "").replace("`", "")
    return " ".join(text.split())[:limit].strip()


def safe_ticker(raw: Any) -> Optional[str]:
    """The one field trusted structurally, and only after it proves the shape."""
    text = sanitize_label(raw, MAX_TICKER).upper()
    return text if _TICKER_RE.match(text) else None


def _zeroed(value: float) -> float:
    return 0.0 if value == 0 else value


def _bucket(value: Optional[float], step: float) -> Optional[float]:
    if value is None:
        return None
    try:
        return _zeroed(round(round(float(value) / step) * step, 4))
    except (TypeError, ValueError):
        return None


def _pct(value: Optional[float], step: float) -> Optional[float]:
    if value is None:
        return None
    try:
        return _bucket(float(value) * 100, step)
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


BUCKET_EDGES = (-0.5, -0.25, 0.0, 0.25, 0.5, 1.0)
BUCKET_LABELS = (
    "under -50%",
    "-50% to -25%",
    "-25% to 0%",
    "0% to +25%",
    "+25% to +50%",
    "+50% to +100%",
    "above +100%",
)


def bucket_counts(values: list[float]) -> dict[str, int]:
    counts = dict.fromkeys(BUCKET_LABELS, 0)
    for value in values:
        index = 0
        while index < len(BUCKET_EDGES) and value > BUCKET_EDGES[index]:
            index += 1
        counts[BUCKET_LABELS[index]] += 1
    return counts


def _returns(rows: list[dict[str, Any]], key: str) -> list[float]:
    return [
        row["performance"][key]
        for row in rows
        if row.get("performance") and row["performance"].get(key) is not None
    ]


# ── Facts ────────────────────────────────────────────────────────────────────


def ipo_facts(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Everything the note may speak about, quantized and made inert."""
    past = payload.get("past") or []
    upcoming = payload.get("upcoming") or []
    coverage = payload.get("coverage") or {}
    measured = [row for row in past if row.get("performance")]

    if len(measured) < MIN_SAMPLE:
        return None

    nominal = _returns(measured, "nominal")
    real = _returns(measured, "real")

    best = max(measured, key=lambda row: row["performance"]["nominal"], default=None)
    worst = min(measured, key=lambda row: row["performance"]["nominal"], default=None)

    def extreme(row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if row is None:
            return None
        return {
            "ticker": safe_ticker(row.get("ticker")),
            "pct": _pct(row["performance"]["nominal"], 10.0),
            "months_listed": round((row["performance"].get("days_listed") or 0) / 30),
        }

    structures = [
        row["structure"]["capital_increase_share"]
        for row in past
        if row.get("structure") and row["structure"].get("capital_increase_share") is not None
    ]

    allocations = [row["results"]["groups"] for row in past if row.get("results")]

    def group_share(key: str) -> Optional[float]:
        shares = [
            group.get("share")
            for groups in allocations
            for group in groups
            if group.get("key") == key and group.get("share") is not None
        ]
        return _median(shares) if shares else None

    foreign = [
        sum(
            group.get("share") or 0
            for group in groups
            if str(group.get("key", "")).startswith("foreign")
        )
        for groups in allocations
    ]

    inflation = payload.get("inflation") or {}

    return {
        "window_months": (payload.get("window") or {}).get("months_back"),
        # The month, not the day. A note fingerprinted on the date would be
        # rewritten nightly for a market that had not moved.
        "as_of_month": str(payload.get("as_of", ""))[:7] or None,
        "upcoming_count": len(upcoming),
        "undated_count": coverage.get("undated"),
        "listed_in_window": len(past),
        "measured": len(measured),
        "unmeasured": len(past) - len(measured),
        "median_nominal_pct": _pct(_median(nominal), 5.0),
        "median_real_pct": _pct(_median(real), 5.0),
        "positive_share_pct": _pct(
            sum(1 for value in nominal if value > 0) / len(nominal) if nominal else None, 10.0
        ),
        "real_positive_share_pct": _pct(
            sum(1 for value in real if value > 0) / len(real) if real else None, 10.0
        ),
        "best": extreme(best),
        "worst": extreme(worst),
        "buckets": bucket_counts(nominal),
        "inflation_available": bool(inflation.get("available")),
        "inflation_reason": inflation.get("reason"),
        "structure_mix": {
            "capital_increase_share_pct": _pct(_median(structures), 10.0),
            "sample": len(structures),
        },
        "allocation_mix": {
            "domestic_retail_pct": _pct(group_share("domestic_retail"), 5.0),
            "domestic_institutional_pct": _pct(group_share("domestic_institutional"), 5.0),
            "foreign_pct": _pct(_median(foreign), 5.0),
            "sample": len(allocations),
        },
        "next_up": [
            {
                # The company name is the one piece of third-party free text the
                # note is allowed to repeat, because it has to be able to say
                # what is coming. Broker, method and proceeds labels never enter
                # the prompt at all — they are display-only.
                "company": sanitize_label(row.get("company")),
                "ticker": safe_ticker(row.get("ticker")),
                "start_month": (row.get("offer_dates") or {}).get("start", "")[:7] or None,
                "price_low": _bucket((row.get("price") or {}).get("low"), 0.5),
                "price_high": _bucket((row.get("price") or {}).get("high"), 0.5),
                "market": sanitize_label(row.get("market"), 40) or None,
            }
            for row in upcoming[:3]
        ],
        "source_updated_month": str(payload.get("source_updated_at") or "")[:7] or None,
        "detail_pages_failed": coverage.get("detail_pages_failed"),
    }


# ── Rendering ────────────────────────────────────────────────────────────────


def _show_pct(value: Optional[float], *, signed: bool = True) -> str:
    if value is None:
        return UNKNOWN
    return f"{value:+.0f}%" if signed else f"{value:.0f}%"


def ipo_values(facts: dict[str, Any]) -> dict[str, str]:
    """The prompt's blocks, rendered from `facts` and from nothing else."""
    window = [
        f"- Window: the last {facts.get('window_months')} months of listings, "
        f"as of {facts.get('as_of_month') or UNKNOWN}.",
        f"- Listed in this window: {facts.get('listed_in_window')}",
        f"- Upcoming or in the book: {facts.get('upcoming_count')}, of which "
        f"{facts.get('undated_count')} have no announced date yet.",
        f"- Calendar last updated by the source: {facts.get('source_updated_month') or UNKNOWN}",
    ]

    returns = [
        "Measured against the struck offering price, using our own current "
        "prices — not the calendar's.",
        f"- Median return since listing, nominal: {_show_pct(facts.get('median_nominal_pct'))}",
    ]
    if facts.get("inflation_available"):
        returns.append(
            f"- The same median with inflation stripped out: "
            f"{_show_pct(facts.get('median_real_pct'))}"
        )
        returns.append(
            f"- Share that made money in lira: "
            f"{_show_pct(facts.get('positive_share_pct'), signed=False)}; "
            f"in purchasing power: "
            f"{_show_pct(facts.get('real_positive_share_pct'), signed=False)}"
        )
    else:
        returns.append(
            "- No inflation series is available, so every figure here is nominal "
            "only. Say so plainly and do not describe any of them as real."
        )
        returns.append(
            f"- Share that made money in lira: "
            f"{_show_pct(facts.get('positive_share_pct'), signed=False)}"
        )

    best, worst = facts.get("best"), facts.get("worst")
    if best:
        returns.append(
            f"- Best: {best.get('ticker') or UNKNOWN} at {_show_pct(best.get('pct'))} "
            f"after about {best.get('months_listed')} months"
        )
    if worst:
        returns.append(
            f"- Worst: {worst.get('ticker') or UNKNOWN} at {_show_pct(worst.get('pct'))} "
            f"after about {worst.get('months_listed')} months"
        )

    buckets = facts.get("buckets") or {}
    distribution = [f"- {label}: {count}" for label, count in buckets.items()]
    distribution.append(
        f"Based on {facts.get('measured')} measured listings. "
        f"{facts.get('unmeasured')} more listed in this window and could not be "
        "measured — a price band that never struck, a missing listing date, or "
        "no scanner row. They are excluded from every figure above."
    )

    mix = facts.get("structure_mix") or {}
    allocation = facts.get("allocation_mix") or {}
    structure = [
        f"- Median share of the offering that was new capital rather than "
        f"existing shareholders selling: "
        f"{_show_pct(mix.get('capital_increase_share_pct'), signed=False)} "
        f"(across {mix.get('sample')} offerings)",
        f"- Median allocation to domestic retail investors: "
        f"{_show_pct(allocation.get('domestic_retail_pct'), signed=False)}; "
        f"domestic institutions: "
        f"{_show_pct(allocation.get('domestic_institutional_pct'), signed=False)}; "
        f"foreign: {_show_pct(allocation.get('foreign_pct'), signed=False)} "
        f"(across {allocation.get('sample')} offerings)",
    ]

    next_up = facts.get("next_up") or []
    if not next_up:
        pipeline = "Nothing is scheduled inside the board's forward window."
    else:
        lines = []
        for entry in next_up:
            price = (
                f"{entry['price_low']}–{entry['price_high']} TRY"
                if entry.get("price_low") is not None
                and entry.get("price_high") is not None
                and entry["price_low"] != entry["price_high"]
                else (
                    f"{entry['price_low']} TRY" if entry.get("price_low") is not None else UNKNOWN
                )
            )
            lines.append(
                f"- {entry.get('company') or UNKNOWN} "
                f"({entry.get('ticker') or 'code not assigned yet'}), "
                f"book opens {entry.get('start_month') or 'date not announced'}, "
                f"at {price}, on the {entry.get('market') or UNKNOWN}"
            )
        pipeline = "\n".join(lines)

    coverage = [
        f"- Detail pages that could not be read this time: {facts.get('detail_pages_failed')}",
        "- The calendar is halkarz.com, a community-maintained site. It is not "
        "KAP, not the SPK and not Borsa İstanbul, and it carries no obligation "
        "to be complete or correct.",
    ]

    return {
        "window": "\n".join(window),
        "returns": "\n".join(returns),
        "distribution": "\n".join(distribution),
        "structure": "\n".join(structure),
        "pipeline": pipeline,
        "coverage": "\n".join(coverage),
    }


# ── Entry point ──────────────────────────────────────────────────────────────


async def note_for_ipos(payload: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
    facts = ipo_facts(payload)
    if facts is None:
        return unavailable("insufficient_sample")
    return await get_note(NOTE_SPEC, facts, ipo_values(facts), user_id)
