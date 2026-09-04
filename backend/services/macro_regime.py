"""
The cross-asset regime read behind the macro board.

The board renders correct figures and says nothing about what they add up to.
This module answers that in one word — and computes the word in Python. The
model is handed the finished label and the readings that produced it, and writes
the sentence explaining them; it never scores, never classifies, and never sees a
number that has not already been rounded to the grain the label was decided on.

Three components, each voting -1, 0 or +1 through a deadband so a flat tape does
not flip the read every refresh:

* **Equity breadth** — how many of the benchmark indices are up on the day.
* **The dollar** — a falling dollar loosens global financial conditions.
* **Copper against gold** — the cleanest growth-versus-safety pair the board
  carries, and the one that most often disagrees with equities.

Crude is deliberately not scored. Oil rising is a growth signal when demand
drives it and a margin squeeze when supply does, and a component that can mean
either is noise dressed as evidence. It rides along as context.

**What this read does not contain**: interest rates, credit spreads and equity
volatility. None of them exist anywhere in this application, and their absence is
stated in the note rather than papered over — a regime call built from equities,
the dollar and two metals is a partial one, and saying so is cheaper than being
quietly wrong on the day rates are the whole story.
"""

import logging
from datetime import UTC, datetime
from typing import Any, Optional

from services.ai_notes import (
    REASON_INSUFFICIENT_DATA,
    NoteSpec,
    get_note,
    unavailable,
)

logger = logging.getLogger(__name__)

DOLLAR_SYMBOL = "DX-Y.NYB"
GOLD_SYMBOL = "GC=F"
COPPER_SYMBOL = "HG=F"
OIL_SYMBOL = "CL=F"

# Share of measured equity indices advancing. Wide deadband on purpose: a board
# that is 55% green is not telling anyone anything.
BREADTH_RISK_ON = 0.65
BREADTH_RISK_OFF = 0.35

# Below this many readable indices the breadth figure is a sample, not a breadth.
MIN_BREADTH_INDICES = 4

# Percentage points. The dollar moves less than equities, so its band is tighter.
DOLLAR_DEADBAND = 0.25
COPPER_GOLD_DEADBAND = 0.75

LABEL_UNAVAILABLE = "Unavailable"

# Score -> label. The score runs -3..+3; anything past ±2 is two of three
# components agreeing, which is as much conviction as three inputs can carry.
_LADDER = (
    (2, "Risk-on"),
    (1, "Leaning risk-on"),
    (0, "Mixed"),
    (-1, "Leaning risk-off"),
    (-2, "Risk-off"),
)

# Named so the note can disclose them, and constant so it cannot disclose
# something it was not actually missing.
NOT_MEASURED = ("interest rates", "credit spreads", "equity volatility")

NOTE_SPEC = NoteSpec(
    kind="macro_regime",
    prompt="macro/regime",
    max_tokens=200,
    temperature=0.2,
    max_age_seconds=6 * 3600,
)


def _row(rows: list[dict[str, Any]], symbol: str) -> Optional[dict[str, Any]]:
    for row in rows:
        if row.get("symbol") == symbol:
            return row
    return None


def _change(row: Optional[dict[str, Any]]) -> Optional[float]:
    if row is None:
        return None
    value = row.get("change_24h")
    return float(value) if isinstance(value, (int, float)) else None


def _zeroed(value: float) -> float:
    """
    Rounding turns a small negative into `-0.0`, which prints as "-0.0%".

    Harmless arithmetic and a bad sentence: the model quotes the reading
    verbatim, so a dollar index that barely moved was being described as having
    fallen by negative zero.
    """
    return 0.0 if value == 0 else value


def _component(key: str, label: str, signal: int, reading: str) -> dict[str, Any]:
    return {"key": key, "label": label, "signal": signal, "reading": reading}


def _breadth(indices: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """
    Advancing share of the equity indices.

    The dollar index is filed under the same feed as the equity benchmarks but is
    not one of them; counting it would let a dollar rally read as market breadth,
    which is close to the opposite of what it means.

    Quantized by construction: "7 of 11" is a pair of integers that changes only
    when an index actually flips, so the fingerprint is stable without rounding
    anything away.
    """
    equities = [row for row in indices if row.get("symbol") != DOLLAR_SYMBOL]
    measured = [row for row in equities if _change(row) is not None]
    if len(measured) < MIN_BREADTH_INDICES:
        return None

    advancing = sum(1 for row in measured if (_change(row) or 0.0) > 0)
    total = len(measured)
    share = advancing / total

    signal = 1 if share >= BREADTH_RISK_ON else -1 if share <= BREADTH_RISK_OFF else 0
    reading = f"{advancing} of {total} equity indices advancing ({share:.0%})"
    return _component("breadth", "Equity breadth", signal, reading)


def _dollar(indices: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """
    The dollar's move, to a tenth of a percent.

    Rounded before the signal is taken rather than after, so the label and the
    sentence explaining it can never be computed from different numbers.
    """
    change = _change(_row(indices, DOLLAR_SYMBOL))
    if change is None:
        return None

    rounded = _zeroed(round(change, 1))
    signal = 1 if rounded <= -DOLLAR_DEADBAND else -1 if rounded >= DOLLAR_DEADBAND else 0
    reading = f"Dollar index {rounded:+.1f}% on the day"
    return _component("dollar", "Dollar", signal, reading)


def ratio_change_pct(numerator_pct: float, denominator_pct: float) -> Optional[float]:
    """
    How much a ratio moved, given how each leg moved.

    Subtracting the two percentages is the obvious thing and is wrong: a ratio is
    a quotient, so its change compounds. Copper +0.9% against gold −0.3% is not a
    1.2-point move but a 1.204% one, and the gap widens as the legs get larger.
    The board already publishes both legs, so the exact figure is free.

    Returns None when the denominator fell by a full 100%, which cannot happen on
    a futures board but must not divide by zero if it ever does.
    """
    denominator = 1.0 + denominator_pct / 100.0
    if denominator == 0:
        return None
    return ((1.0 + numerator_pct / 100.0) / denominator - 1.0) * 100.0


def _copper_gold(commodities: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """
    The copper/gold ratio's move, to a quarter of a percent.

    The cleanest growth-versus-safety pair the board carries: copper is bid on
    industrial demand and gold on the wish to own nothing that can default, so
    the ratio rises when the market wants growth and falls when it wants cover.
    Its *level* is uninterpretable here — nothing in this application holds a
    historical baseline for it — but its change is exact arithmetic on two
    published legs, which is the only form of it worth scoring.
    """
    copper = _change(_row(commodities, COPPER_SYMBOL))
    gold = _change(_row(commodities, GOLD_SYMBOL))
    if copper is None or gold is None:
        return None

    exact = ratio_change_pct(copper, gold)
    if exact is None:
        return None

    move = _zeroed(round(exact * 4) / 4)
    signal = 1 if move >= COPPER_GOLD_DEADBAND else -1 if move <= -COPPER_GOLD_DEADBAND else 0
    reading = f"Copper/gold ratio {move:+.2f}% on the day"
    return _component("copper_gold", "Copper vs gold", signal, reading)


def _session_caveat(indices: list[dict[str, Any]]) -> Optional[str]:
    """
    Whether the breadth count is comparing like with like.

    It usually is not. Tokyo's "change on the day" was fixed when it closed at
    06:00 UTC and New York's when it closed at 21:00, so an advancing count taken
    across both is an average of different days wearing one label. Every index row
    already carries `market_status`, so the size of the problem is knowable — and
    a reader told "7 of 11 advancing" without it has been given a cleaner number
    than the data supports.
    """
    equities = [row for row in indices if row.get("symbol") != DOLLAR_SYMBOL]
    measured = [row for row in equities if _change(row) is not None]
    if not measured:
        return None

    live = sum(1 for row in measured if (row.get("market_status") or {}).get("status") == "open")
    if live == len(measured):
        return None
    if live == 0:
        return (
            f"All {len(measured)} index readings are last closes, taken across "
            "different time zones rather than at one moment."
        )
    return (
        f"{live} of the {len(measured)} index readings come from a session trading "
        "now; the rest are last closes from other time zones."
    )


def _oil_context(commodities: list[dict[str, Any]]) -> Optional[str]:
    change = _change(_row(commodities, OIL_SYMBOL))
    if change is None:
        return None
    return f"WTI crude {_zeroed(round(change, 1)):+.1f}% on the day"


def _label_for(score: int) -> str:
    for threshold, label in _LADDER:
        if score >= threshold:
            return label
    return _LADDER[-1][1]


def build_regime(board: dict[str, Any]) -> dict[str, Any]:
    """
    Score the board and name the regime. Deterministic — no model involved.

    A component whose inputs are missing scores nothing and is named in
    `unavailable`, following the snapshot convention: a feed that failed is
    reported, never silently treated as neutral. Two missing components leave one
    vote deciding a three-vote question, so the read is withheld entirely rather
    than published at a third of its intended evidence.
    """
    indices = board.get("indices") or []
    commodities = board.get("commodities") or []

    builders = (
        ("breadth", "Equity breadth", lambda: _breadth(indices)),
        ("dollar", "Dollar", lambda: _dollar(indices)),
        ("copper_gold", "Copper vs gold", lambda: _copper_gold(commodities)),
    )

    components: list[dict[str, Any]] = []
    missing: list[str] = []
    for _key, label, build in builders:
        component = build()
        if component is None:
            missing.append(label)
        else:
            components.append(component)

    score = sum(component["signal"] for component in components)
    label = LABEL_UNAVAILABLE if len(missing) >= 2 else _label_for(score)

    context: list[str] = []
    oil = _oil_context(commodities)
    if oil:
        context.append(oil)

    return {
        "label": label,
        "score": score,
        "components": components,
        "unavailable": missing,
        "not_measured": list(NOT_MEASURED),
        "session_caveat": _session_caveat(indices),
        "context": context,
        "stale": bool(board.get("stale")),
        "as_of": board.get("as_of") or datetime.now(UTC).isoformat(timespec="seconds"),
    }


def note_facts(regime: dict[str, Any]) -> dict[str, Any]:
    """
    The fingerprint input: everything the note is allowed to say, and nothing else.

    Every reading here is already rounded to the grain its signal was decided on,
    so a note cached under this fingerprint cannot cite a figure that has since
    moved. The date is included because a note written this morning should not
    still be explaining this morning's tape tomorrow.
    """
    return {
        "label": regime["label"],
        "score": regime["score"],
        "components": [
            {"key": c["key"], "signal": c["signal"], "reading": c["reading"]}
            for c in regime["components"]
        ],
        "unavailable": regime["unavailable"],
        "session_caveat": regime["session_caveat"],
        "context": regime["context"],
        "stale": regime["stale"],
        "date": (regime.get("as_of") or "")[:10],
    }


def _bullet(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) if lines else "- none"


def note_values(facts: dict[str, Any]) -> dict[str, str]:
    """Render the prompt's placeholders from the facts, and from nothing else."""
    directions = {1: "risk-on", -1: "risk-off", 0: "neutral"}
    scored = [f"{c['reading']} — votes {directions[c['signal']]}" for c in facts["components"]]

    missing = facts["unavailable"]
    context = list(facts["context"])
    if facts.get("session_caveat"):
        context.append(facts["session_caveat"])

    return {
        "label": facts["label"],
        "score": str(facts["score"]),
        "components": _bullet(scored),
        "context": _bullet(context),
        "unavailable": ", ".join(missing) if missing else "none",
        "not_measured": ", ".join(NOT_MEASURED),
        "staleness": (
            "The board is being replayed from cache and may be up to half an hour old."
            if facts["stale"]
            else "The board is current."
        ),
    }


async def regime_note(regime: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
    """The note for this regime read, or `unavailable` when there is nothing to say."""
    if regime["label"] == LABEL_UNAVAILABLE or not regime["components"]:
        return unavailable(REASON_INSUFFICIENT_DATA)

    facts = note_facts(regime)
    return await get_note(NOTE_SPEC, facts, note_values(facts), user_id)
