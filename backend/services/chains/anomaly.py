"""
What on the chain board is not normal right now.

The detector is the product here; the note that explains it is not. Every flag
below is found in Python and ships with a sentence written in Python, so the
board keeps saying "Ethereum fees are triple their usual midnight level" whether
or not a model is reachable. `DeviationBanner` already works this way on the
front end, and this is the same discipline one layer down.

Two independent sources of "usual", because they fail independently:

* **Coin Metrics dailies** — thirty days of active addresses, transaction counts
  and exchange flows for Bitcoin and Ethereum, already fetched by `flows.py`.
  Works on a cold start, survives a restart, and is unaffected by who happens to
  be browsing.
* **The local metric history** — fees and load against the same hour of day on
  previous days. Needs a warm-up and says so; see `history.py` for why the hour
  matching is not optional.

And several readings that need no baseline at all, because the number carries its
own meaning: a Bitcoin mempool backlog, a difficulty retarget, Solana's skipped
slot rate, and the fill trend across the ten blocks every row already carries.

Cadence is deliberately absent. `DeviationBanner` reports a chain running late,
and a second element on the same page saying the same thing in different words is
noise, not redundancy.
"""

import logging
import statistics
from typing import Any, Optional

from services.ai_notes import (
    REASON_NOTHING_FLAGGED,
    NoteSpec,
    get_note,
    unavailable,
)
from services.chains import flows, history
from services.chains.registry import BY_KEY

logger = logging.getLogger(__name__)

# The board shows at most this many. Three is what fits on one line above the
# grid, and a list long enough to scroll is a list nobody reads.
MAX_ANOMALIES = 3

SEVERITY_ORDER = {"high": 0, "notable": 1}

# --- thresholds, all in the units of the reading they judge -------------------

# Fees are heavy-tailed, so a spike has to clear both a robust dispersion test
# and a plain doubling. Either alone fires too often: MAD collapses to zero on a
# flat chain, and a doubling off a near-zero base is meaningless.
FEE_MAD_MULTIPLE = 3.0
FEE_RATIO = 2.0

# Percentage points of block space, against the same hour on other days.
LOAD_SURGE_POINTS = 25.0

# Ten blocks is a trend on Ethereum (~2 min) and noise on BSC (~4.5 s). Below a
# minute of span the two halves are the same instant with different jitter.
MIN_TREND_SPAN_SECONDS = 60
TREND_POINTS = 15.0
FILLING_FLOOR = 80.0
DRAINING_CEILING = 50.0

# Blocks' worth of backlog before a Bitcoin mempool is congested rather than busy.
BACKLOG_BLOCKS = 3
# The gap between the fee-contested backlog and the raw one is the signal: a
# large raw queue behind a small contested one is dust nobody is bidding for,
# which is the state most often misreported as congestion.
DUST_RATIO = 5
DUST_MIN_RAW_BLOCKS = 10

DIFFICULTY_PERCENT = 5.0
SKIPPED_SLOT_PERCENT = 5.0

# Coin Metrics names its assets by ticker; the board names its rows by chain.
# `flows.COVERED` maps the first to the ticker, this maps the ticker to the row.
FLOW_CHAIN = {"BTC": "bitcoin", "ETH": "ethereum"}

ACTIVITY_NOTABLE = 0.25
ACTIVITY_HIGH = 0.40
FLOW_RATIO = 2.0
FLOW_FLOOR_USD = 50_000_000

NOTE_SPEC = NoteSpec(
    kind="chain_anomaly",
    prompt="chains/anomaly",
    max_tokens=260,
    temperature=0.2,
    max_age_seconds=3600,
)


def _name(key: str) -> str:
    chain = BY_KEY.get(key)
    return chain.name if chain else key


def _round_to(value: float, grain: float) -> float:
    """Snap a figure to a coarse grain, so small drift is not a new fingerprint."""
    return round(value / grain) * grain


def _flag(
    chain: str,
    kind: str,
    severity: str,
    text: str,
    phrase: str,
    *,
    magnitude: float,
    basis: str,
    window: Optional[str] = None,
) -> dict[str, Any]:
    """
    One detected condition, said twice on purpose.

    `text` is exact and live — the strip renders it, and it is right to the last
    block. `phrase` is the same condition with its figures snapped to a coarse
    grain, and it is the only version the model ever sees.

    The split exists because the two have different jobs. The board refreshes
    every ten seconds and its numbers move every time; fingerprinting the exact
    sentence would mean writing a fresh note every ten seconds on a local model,
    for a situation that had not changed at all. Coarse figures change when the
    situation does. And because the model is given only the coarse version, a
    cached note still cannot quote a figure that has moved — it never had the
    precise one to quote.

    `basis` says what the reading was measured against, because "fees are high"
    and "fees are high for a Tuesday at 03:00" are different claims and only one
    of them is supported.
    """
    return {
        "chain": chain,
        "chain_name": _name(chain),
        "kind": kind,
        "severity": severity,
        "text": text,
        "phrase": phrase,
        "basis": basis,
        "window": window,
        "magnitude": abs(magnitude),
    }


def _number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) else None


def _fee_flag(row: dict[str, Any], now: Optional[float]) -> Optional[dict[str, Any]]:
    key = row.get("key")
    fee = row.get("fee") or {}
    current = _number(fee.get("transfer_native"))
    if key is None or current is None:
        return None

    base = history.baseline(key, "fee_native", now=now)
    if base is None or base["median"] <= 0:
        return None

    median, mad = base["median"], base["mad"]
    ratio = current / median
    dispersed = mad > 0 and current > median + FEE_MAD_MULTIPLE * mad
    if not (dispersed and ratio >= FEE_RATIO):
        return None

    severity = "high" if ratio >= 2 * FEE_RATIO else "notable"
    window = (
        f"{base['samples']} readings across {base['days']} days at "
        f"{base['hour_utc']:02d}:00 UTC ±{base['band_hours']}h"
    )
    text = (
        f"{_name(key)} transfer fees are {ratio:.1f}x their usual level for this "
        f"hour of day ({current:.6g} against a median of {median:.6g})."
    )
    phrase = (
        f"{_name(key)}: transfer fees roughly {_round_to(ratio, 0.5):.1f}x their usual "
        f"level for this hour of day, against {base['days']} days of readings around "
        f"{base['hour_utc']:02d}:00 UTC"
    )
    return _flag(key, "fee", severity, text, phrase, magnitude=ratio, basis=window, window=window)


def _load_flag(row: dict[str, Any], now: Optional[float]) -> Optional[dict[str, Any]]:
    key = row.get("key")
    load = row.get("load") or {}
    current = _number(load.get("percent"))
    if key is None or current is None:
        return None

    base = history.baseline(key, "load_percent", now=now)
    if base is None:
        return None

    delta = current - base["median"]
    if delta < LOAD_SURGE_POINTS:
        return None

    window = (
        f"{base['samples']} readings across {base['days']} days at "
        f"{base['hour_utc']:02d}:00 UTC ±{base['band_hours']}h"
    )
    text = (
        f"{_name(key)} is running {delta:.0f} points fuller than usual for this "
        f"hour ({current:.0f}% against a median of {base['median']:.0f}%)."
    )
    phrase = (
        f"{_name(key)}: blocks about {_round_to(delta, 10):.0f} points fuller than usual "
        f"for this hour of day, against {base['days']} days of readings around "
        f"{base['hour_utc']:02d}:00 UTC"
    )
    return _flag(key, "load", "notable", text, phrase, magnitude=delta, basis=window, window=window)


def _fill_trend(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """
    Whether the last blocks are filling or draining.

    Needs no stored history — `blocks[]` is already a ten-point series — but it
    does need the series to span enough time to be one. Ten Arbitrum blocks are
    two and a half seconds apart end to end; calling the difference between their
    halves a trend would be reading jitter.
    """
    key = row.get("key")
    span = _number(row.get("cadence_span_seconds"))
    blocks = row.get("blocks") or []
    if key is None or span is None or span < MIN_TREND_SPAN_SECONDS or len(blocks) < 6:
        return None

    half = len(blocks) // 2
    # Newest first, so the head of the list is the recent half.
    recent = [_number(b.get("fill_percent")) for b in blocks[:half]]
    earlier = [_number(b.get("fill_percent")) for b in blocks[half:]]
    recent = [value for value in recent if value is not None]
    earlier = [value for value in earlier if value is not None]
    if len(recent) < 2 or len(earlier) < 2:
        return None

    new_mean, old_mean = statistics.fmean(recent), statistics.fmean(earlier)
    delta = new_mean - old_mean
    window = f"the last {len(blocks)} blocks, spanning {span:.0f}s"
    coarse = f"the last {len(blocks)} blocks, spanning about {_round_to(span, 10):.0f}s"

    if delta >= TREND_POINTS and new_mean >= FILLING_FLOOR:
        text = (
            f"{_name(key)} blocks are filling: {old_mean:.0f}% to {new_mean:.0f}% "
            f"full across {window}."
        )
        phrase = f"{_name(key)}: blocks filling across {coarse}"
        return _flag(
            key, "filling", "notable", text, phrase, magnitude=delta, basis=window, window=window
        )

    if delta <= -TREND_POINTS and new_mean <= DRAINING_CEILING:
        text = (
            f"{_name(key)} blocks are draining: {old_mean:.0f}% to {new_mean:.0f}% "
            f"full across {window}."
        )
        phrase = f"{_name(key)}: blocks draining across {coarse}"
        return _flag(
            key, "draining", "notable", text, phrase, magnitude=delta, basis=window, window=window
        )
    return None


def _mempool_flag(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    key = row.get("key")
    mempool = row.get("mempool") or {}
    backlog = _number(mempool.get("backlog_blocks"))
    raw = _number(mempool.get("raw_backlog_blocks"))
    if key is None or backlog is None:
        return None

    if raw is not None and raw >= DUST_MIN_RAW_BLOCKS and raw >= DUST_RATIO * max(backlog, 0.1):
        text = (
            f"{_name(key)}'s mempool holds {raw:.0f} blocks of transactions but only "
            f"{backlog:.0f} at a fee anyone is competing at — a dust queue rather "
            "than congestion."
        )
        phrase = (
            f"{_name(key)}: a queue of roughly {_round_to(raw, 10):.0f} blocks that almost "
            "nobody is bidding to clear — a dust queue rather than congestion"
        )
        return _flag(
            key, "dust_queue", "notable", text, phrase, magnitude=raw, basis="current mempool"
        )

    if backlog >= BACKLOG_BLOCKS:
        threshold = mempool.get("contested_fee_threshold_sat_vb")
        priced = f", clearing above {threshold} sat/vB" if threshold else ""
        text = f"{_name(key)}'s mempool is {backlog:.0f} blocks deep at contested fees{priced}."
        phrase = (
            f"{_name(key)}: roughly {_round_to(backlog, 2):.0f} blocks of backlog at "
            "fees people are actively competing at"
        )
        return _flag(
            key, "congested", "notable", text, phrase, magnitude=backlog, basis="current mempool"
        )
    return None


def _difficulty_flag(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    key = row.get("key")
    economics = row.get("economics") or {}
    change = _number(economics.get("difficulty_change_percent"))
    if key is None or change is None or abs(change) < DIFFICULTY_PERCENT:
        return None

    direction = "up" if change > 0 else "down"
    text = (
        f"{_name(key)} difficulty is heading {direction} {abs(change):.1f}% at the next retarget."
    )
    phrase = (
        f"{_name(key)}: difficulty heading {direction} roughly "
        f"{_round_to(abs(change), 1):.0f}% at the next retarget"
    )
    return _flag(
        key,
        "difficulty",
        "notable",
        text,
        phrase,
        magnitude=change,
        basis="the pending retarget estimate",
    )


def _skipped_slots(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    key = row.get("key")
    throughput = row.get("throughput") or {}
    skipped = _number(throughput.get("skipped_slot_percent"))
    if key is None or skipped is None or skipped < SKIPPED_SLOT_PERCENT:
        return None

    text = f"{_name(key)} is skipping {skipped:.1f}% of its scheduled slots."
    phrase = (
        f"{_name(key)}: skipping roughly {_round_to(skipped, 1):.0f}% of its scheduled "
        "slots this epoch"
    )
    return _flag(
        key, "skipped_slots", "notable", text, phrase, magnitude=skipped, basis="the current epoch"
    )


def _activity_flags(symbol: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Daily activity and exchange flow against their own thirty-day history.

    Deliberately not called a z-score. The distribution is not normal and the
    sample is thirty points; a deviation from the median is what the data
    supports, and the sample size travels with the flag so it can be stated.
    """
    found: list[dict[str, Any]] = []
    key = FLOW_CHAIN.get(symbol, symbol.lower())

    for metric, label in (
        ("active_addresses", "active addresses"),
        ("transactions", "transactions"),
    ):
        values = [row[metric] for row in rows if isinstance(row.get(metric), (int, float))]
        if len(values) < flows.MIN_BASELINE_DAYS + 1:
            continue

        current, prior = values[-1], values[:-1]
        median = statistics.median(prior)
        if median <= 0:
            continue

        deviation = (current - median) / median
        if abs(deviation) < ACTIVITY_NOTABLE:
            continue

        severity = "high" if abs(deviation) >= ACTIVITY_HIGH else "notable"
        direction = "above" if deviation > 0 else "below"
        window = f"the median of the prior {len(prior)} days"
        text = (
            f"{_name(key)} {label} at {current:,.0f} are {abs(deviation):.0%} {direction} {window}."
        )
        phrase = (
            f"{_name(key)}: daily {label} roughly {_round_to(abs(deviation), 0.05):.0%} "
            f"{direction} {window}"
        )
        found.append(
            _flag(
                key,
                f"activity_{metric}",
                severity,
                text,
                phrase,
                magnitude=deviation,
                basis=window,
            )
        )

    flow_values = [
        row["net_flow_usd"] for row in rows if isinstance(row.get("net_flow_usd"), (int, float))
    ]
    if len(flow_values) >= flows.MIN_BASELINE_DAYS + 1:
        current, prior = flow_values[-1], flow_values[:-1]
        typical = statistics.median([abs(value) for value in prior])
        if abs(current) >= FLOW_FLOOR_USD and typical > 0 and abs(current) >= FLOW_RATIO * typical:
            # `flows.py` fixes the subtraction order: positive is value moving on
            # to exchanges, which is the direction usually read as supply for sale.
            direction = "on to" if current > 0 else "off"
            window = f"the median of the prior {len(prior)} days"
            text = (
                f"{_name(key)} saw ${abs(current):,.0f} move {direction} exchanges, "
                f"against a typical day of ${typical:,.0f}."
            )
            phrase = (
                f"{_name(key)}: an unusually large day of value moving {direction} "
                f"exchanges, several times {window}"
            )
            found.append(
                _flag(
                    key, "exchange_flow", "notable", text, phrase, magnitude=current, basis=window
                )
            )
    return found


def detect(board: dict[str, Any], *, now: Optional[float] = None) -> dict[str, Any]:
    """
    Everything unusual on this board, with what each reading was measured against.

    Chains that could not be judged are listed rather than passed over: a chain
    with no baseline yet and a chain that is behaving normally look identical in
    an empty result, and only one of them is reassuring.
    """
    rows = board.get("chains") or []
    anomalies: list[dict[str, Any]] = []
    checked: list[str] = []
    not_checkable: dict[str, str] = {}

    for row in rows:
        key = row.get("key")
        if not key:
            continue
        if row.get("error"):
            not_checkable[key] = "unreachable on this refresh — the row is blank, not idle"
            continue

        checked.append(key)
        for detector in (_fee_flag, _load_flag):
            found = detector(row, now)
            if found:
                anomalies.append(found)
        for snapshot_detector in (_fill_trend, _mempool_flag, _difficulty_flag, _skipped_slots):
            found = snapshot_detector(row)
            if found:
                anomalies.append(found)

    series = flows.recent_series()
    for symbol, daily in series.items():
        anomalies.extend(_activity_flags(symbol, daily))

    anomalies.sort(key=lambda flag: (SEVERITY_ORDER.get(flag["severity"], 9), -flag["magnitude"]))
    kept = anomalies[:MAX_ANOMALIES]

    return {
        "anomalies": kept,
        "suppressed": max(0, len(anomalies) - len(kept)),
        "checked": checked,
        "not_checkable": not_checkable,
        "coverage": _coverage_note(checked, series),
        "as_of": board.get("as_of"),
        "stale": bool(board.get("stale")),
    }


def _coverage_note(checked: list[str], series: dict[str, list[dict[str, Any]]]) -> str:
    """One sentence on how much of the board could actually be judged."""
    warm = [key for key in checked if history.baseline(key, "fee_native") is not None]
    daily = ", ".join(sorted(series)) if series else "no assets"

    # Two baselines, named separately. Folding them into one sentence was the
    # first version, and the model read "the history is still filling" as
    # applying to the daily figures too — which are thirty days deep and were
    # never the thin half.
    fees = (
        f"Fee and load baselines: none yet for any of the {len(checked)} chains checked"
        if not warm
        else f"Fee and load baselines: ready for {', '.join(_name(key) for key in warm)}, "
        f"still filling for the other {len(checked) - len(warm)} chains"
    )
    return (
        f"{fees} — those compare a reading against the same hour of day on previous "
        f"days. Separately, daily exchange and activity history is a full thirty days "
        f"deep and covers {daily}."
    )


def _bullet(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) if lines else "- none"


def note_facts(detection: dict[str, Any]) -> dict[str, Any]:
    """
    The fingerprint: which conditions are flagged, not how far each has moved.

    A fee spike that lasts an hour is one note, not the three hundred and sixty
    the board's ten-second refresh would otherwise ask for. The severity is in
    the key because a condition getting worse is worth re-describing; a decimal
    place moving is not.
    """
    return {
        "flags": sorted(
            f"{flag['chain']}:{flag['kind']}:{flag['severity']}" for flag in detection["anomalies"]
        ),
        # The coarse phrasing, never `text`. `text` carries figures that move on
        # every ten-second refresh, and fingerprinting those would mean a fresh
        # note every ten seconds for a situation that had not changed.
        "phrases": sorted(flag["phrase"] for flag in detection["anomalies"]),
        "not_checkable": detection["not_checkable"],
        "coverage": detection["coverage"],
        "stale": detection["stale"],
    }


def note_values(facts: dict[str, Any]) -> dict[str, str]:
    detected = list(facts["phrases"])
    gaps = [f"{_name(key)}: {reason}" for key, reason in sorted(facts["not_checkable"].items())]
    return {
        "detected": _bullet(detected),
        "not_checkable": _bullet(gaps),
        "coverage": facts["coverage"],
        "staleness": (
            "These readings are replayed from cache and may be up to two minutes old."
            if facts["stale"]
            else "These readings are current."
        ),
    }


async def anomaly_note(detection: dict[str, Any]) -> dict[str, Any]:
    """The note explaining the flags, or `unavailable` when there are none."""
    if not detection["anomalies"]:
        return unavailable(REASON_NOTHING_FLAGGED)

    facts = note_facts(detection)
    return await get_note(NOTE_SPEC, facts, note_values(facts))
