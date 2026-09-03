"""
Where one underlying's VİOP book stands against its scan range, narrated.

The margin map draws a field: every level a cohort's initial margin was sized
to survive, session by session, with the levels price has already traded
through swept away. It is the one page on this realm whose whole claim rests on
a published parameter rather than a modelled one, and it is also the page
whose picture is hardest to read cold — a reader sees a streak of heat below
price and has to work out for themselves that it is the long side's band, that
it is four percent away, and that the newest sessions have been adding to it.

So this module reads the field the way `viop_note` reads the board: aggregate,
classify in Python, hand `services/ai_notes` a finished set of facts. Three
reads that the map cannot state on its own:

* which side the standing book leans to, by notional rather than by contract
  count — a long-heavy field is one whose bands sit below price, which is a
  different market from the same size sitting above it;
* how far the heaviest surviving level on each side is from the latest spot
  close, in the scan range's own units, since the band is the whole point;
* whether the newest session added to that book or to the other side.

**Per underlying, per window, per session.** Unlike the board-wide notes this
one carries its inputs in its fingerprint — the ticker, the window the reader
chose and the newest session day — so a note written about THYAO over six
months is never served for SASA over three. The bulletin publishes once, after
the close, so the fingerprint moves at most once a day and the store holds a
handful of names comfortably.

**What this must never say.** The band is where a position's initial margin
has absorbed the move it was sized for. It is not a margin call: Takasbank
publishes no maintenance rate for VİOP, so the trigger cannot be computed and
is not claimed — see `viop_margin_map` and `takasbank_psr`. And the exchange
publishes sizes, never sides, so "who is long" is not knowable from anything
here. Both are stated to the model as facts it must repeat rather than
constraints it might forget.

Nothing here raises. The map is complete without the paragraph, so every
failure comes back as `unavailable` and the page keeps its field.
"""

import logging
from typing import Any

from services.ai_notes import (
    REASON_INSUFFICIENT_DATA,
    NoteSpec,
    get_note,
    unavailable,
)
from services.bist.equity_service import fetch_candles
from services.bist.takasbank_psr import PsrUnavailable, fetch_psr
from services.bist.viop_bulletin import BulletinUnavailable, SsfRow, get_history
from services.bist.viop_margin_map import (
    SCAN_SCENARIOS,
    SIDE_LONG,
    SIDE_SHORT,
    MarginMap,
    build_margin_map,
    direction,
)

logger = logging.getLogger(__name__)

UNKNOWN = "not available"

VIOP_MAP_SPEC = NoteSpec(
    kind="bist_viop_map",
    prompt="notes/bist_viop_map",
    # One underlying rather than a board, so shorter than the VİOP note; longer
    # than a single-instrument brief because it has to say what a band is
    # before it can say where one sits.
    max_tokens=440,
    max_chars=1100,
    temperature=0.25,
    # The bulletin publishes once a day, after the close. Twelve hours keeps a
    # note written on the evening's file good through the next session, and
    # the fingerprint retires it the moment a new session lands anyway.
    max_age_seconds=12 * 3600,
)

# Named to the reader and to the model rather than left implicit. The first is
# the one every reader of a "liquidation map" will assume is drawn; the second
# is what every derivatives reader assumes the exchange knows.
NOT_MEASURED: tuple[str, ...] = (
    "sürdürme teminatı seviyesi — Takasbank VİOP için yayımlamıyor",
    "pozisyonların hangi tarafta kimde olduğu",
    "spot hacim profili",
    "opsiyon pozisyonları",
)

# A year of daily closes covers the longest window the map offers. Kept equal
# to the map route's own range so the note and the field convert basis from
# the same series.
SPOT_RANGE = "1y"

# Below this the field is a few columns and reads as noise.
MIN_SESSIONS = 10

# Share of the standing notional one side has to carry before the book leans.
# Sixty rather than fifty because the rungs weight both sides identically, so
# a 55/45 split is two similar piles rather than a lean.
HEAVY_SIDE_PCT = 60.0

# Levels named per side. The field has thousands of cells; the reader needs the
# one that matters and the one behind it.
LEVELS_PER_SIDE = 2

STANCE_LONG_HEAVY = "long_heavy"
STANCE_SHORT_HEAVY = "short_heavy"
STANCE_BALANCED = "balanced"
STANCE_EMPTY = "empty"

SIDE_NAME = {SIDE_LONG: "long", SIDE_SHORT: "short"}


# ── Quantization ─────────────────────────────────────────────────────────────


def _zeroed(value: float) -> float:
    """Rounding turns a small negative into `-0.0`, which renders as "-0.0%"."""
    return 0.0 if value == 0 else value


def _bucket(value: float | None, step: float) -> float | None:
    """Snap to a multiple of `step`. The whole cache design rests on this."""
    if value is None:
        return None
    return _zeroed(round(round(value / step) * step, 4))


def _pct(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    try:
        return _zeroed(round(float(value) * 100, digits))
    except (TypeError, ValueError):
        return None


def _pct_bucket(value: float | None, step: float) -> float | None:
    """A fraction as percentage points, snapped to `step`."""
    return _bucket(_pct(value, 4), step)


def _share_bucket(part: float, total: float, step: float = 5.0) -> float | None:
    if total <= 0:
        return None
    return _bucket(part / total * 100, step)


# ── Rendering helpers ────────────────────────────────────────────────────────


def _show_pct(value: float | None, sign: bool = True) -> str:
    if value is None:
        return UNKNOWN
    return f"{value:+.1f}%" if sign else f"{value:.1f}%"


def _show_try(value: float | None) -> str:
    """A lira notional in millions, which is the unit the legend uses."""
    if value is None:
        return UNKNOWN
    return f"{value / 1_000_000:,.1f}M TRY"


def _show_price(value: float | None) -> str:
    return UNKNOWN if value is None else f"{value:,.2f}"


def _bullet(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) if lines else "- none"


# ── Classification ───────────────────────────────────────────────────────────


def classify_map_stance(long_share_pct: float | None) -> str:
    """
    Which side the standing book leans to, from the *bucketed* share.

    Classified from the same figure the note is rendered from, so the label
    cannot flip on a rounding difference the facts would not show.
    """
    if long_share_pct is None:
        return STANCE_EMPTY
    if long_share_pct >= HEAVY_SIDE_PCT:
        return STANCE_LONG_HEAVY
    if long_share_pct <= 100.0 - HEAVY_SIDE_PCT:
        return STANCE_SHORT_HEAVY
    return STANCE_BALANCED


# ── Aggregation ──────────────────────────────────────────────────────────────


def _standing(board: MarginMap) -> dict[int, tuple[float, float]]:
    """The newest column of the field: what stands on each bin, by side."""
    last = max((cell.column for cell in board.cells), default=None)
    if last is None:
        return {}
    return {
        cell.bin_index: (cell.long_try, cell.short_try)
        for cell in board.cells
        if cell.column == last
    }


def _bin_price(board: MarginMap, bin_index: int) -> float:
    return board.price_min + (bin_index + 0.5) * board.bin_size


def _levels(board: MarginMap, standing: dict[int, tuple[float, float]], spot: float, side: int):
    """The heaviest surviving levels on one side, nearest-first among the top."""
    ranked = sorted(
        ((bin_index, pair[side]) for bin_index, pair in standing.items() if pair[side] > 0),
        key=lambda item: item[1],
        reverse=True,
    )[:LEVELS_PER_SIDE]
    levels = [
        {
            "price": round(_bin_price(board, bin_index), 2),
            "distance_pct": _pct_bucket((_bin_price(board, bin_index) - spot) / spot, 0.5),
            "notional_try": _bucket(notional, 500_000.0),
        }
        for bin_index, notional in ranked
    ]
    levels.sort(key=lambda level: abs(level["distance_pct"] or 0.0))
    return levels


def _latest_session(rows: list[SsfRow]) -> dict[str, Any]:
    """
    What the newest session added, by the same rule the field places cohorts.

    Computed from the bulletin rows rather than read back off the map, because
    the map keeps only what survives sweeping and the question here is what
    was *opened* — a cohort placed and swept the same day is still a cohort
    that was opened.
    """
    opened = {SIDE_LONG: 0.0, SIDE_SHORT: 0.0}
    undirected = 0.0
    closed = 0.0
    for row in rows:
        entry = row.weighted_average or row.settlement
        notional = row.open_interest_change * row.multiplier * entry
        side = direction(row.open_interest_change, row.settlement, row.previous_settlement)
        if side is not None:
            opened[side] += notional
        elif row.open_interest_change > 0:
            undirected += notional
        elif row.open_interest_change < 0:
            closed += -notional

    front = min(rows, key=lambda row: expiry_key(row.expiry))
    settlement_change = (
        (front.settlement - front.previous_settlement) / front.previous_settlement
        if front.previous_settlement
        else None
    )
    return {
        "day": rows[0].day,
        "opened_long_try": _bucket(opened[SIDE_LONG], 500_000.0),
        "opened_short_try": _bucket(opened[SIDE_SHORT], 500_000.0),
        "undirected_try": _bucket(undirected, 500_000.0),
        "closed_try": _bucket(closed, 500_000.0),
        "oi_change": _bucket(sum(row.open_interest_change for row in rows), 100.0),
        "front_settlement_change_pct": _pct_bucket(settlement_change, 0.5),
    }


def expiry_key(expiry: str) -> tuple[str, str]:
    """
    A bulletin expiry label in sortable order.

    The bulletin writes `MMYY`, and `0327` sorts before `0926` as text even
    though March 2027 comes after September 2026. Year first, then month, so the
    front month is the one that expires first rather than the one whose label
    starts with the smaller digit.
    """
    label = expiry.strip()
    if len(label) == 4 and label.isdigit():
        return (label[2:], label[:2])
    return (label, "")


def _spot_close(spot_closes: dict[str, float], sessions: list[str]) -> float | None:
    """The newest session's close, or the last one the series has before it."""
    for day in reversed(sessions):
        close = spot_closes.get(day)
        if close and close > 0:
            return close
    return None


def facts_from_map(
    board: MarginMap,
    rows: list[SsfRow],
    spot_closes: dict[str, float],
    *,
    sessions_requested: int,
    stale: bool,
    psr_as_of: str,
    psr_run: str,
) -> dict[str, Any] | None:
    """
    The field as a quantized set of readings, or None.

    Split from `build_viop_map_facts` so the aggregation can be tested against
    a synthetic map without three upstreams in the way.
    """
    if board.thin or len(board.sessions) < MIN_SESSIONS:
        return None

    spot = _spot_close(spot_closes, board.sessions)
    if spot is None:
        # Every distance below is measured from here; without it the note
        # would be describing bands at unknown range.
        return None

    standing = _standing(board)
    long_try = sum(pair[SIDE_LONG] for pair in standing.values())
    short_try = sum(pair[SIDE_SHORT] for pair in standing.values())
    long_share = _share_bucket(long_try, long_try + short_try)

    latest = board.sessions[-1]
    latest_rows = [row for row in rows if row.day == latest]

    return {
        "stance": classify_map_stance(long_share),
        "ticker": board.underlying,
        "as_of": latest,
        "stale": stale,
        "window": {
            "requested": sessions_requested,
            "covered": len(board.sessions),
            "undirected_sessions": board.undirected_sessions,
            "undirected_try": _bucket(board.undirected_notional, 500_000.0),
            "basis_carried_sessions": board.basis_carried_sessions,
            "dropped_sessions": board.dropped_sessions,
        },
        "band": {
            "psr_pct": _bucket(board.psr * 100, 0.1),
            "rungs_pct": [
                _bucket(board.psr * fraction * 100, 0.1) for fraction, _ in SCAN_SCENARIOS
            ],
            "as_of": psr_as_of,
            "run": psr_run,
        },
        "book": {
            "open_interest": _bucket(board.open_interest, 1000.0),
            "expiries": len(board.expiries),
            "standing_try": _bucket(long_try + short_try, 1_000_000.0),
            "long_try": _bucket(long_try, 500_000.0),
            "short_try": _bucket(short_try, 500_000.0),
            "long_share_pct": long_share,
        },
        "spot": {"close": round(spot, 2)},
        "levels": {
            "long": _levels(board, standing, spot, SIDE_LONG),
            "short": _levels(board, standing, spot, SIDE_SHORT),
        },
        "session": _latest_session(latest_rows) if latest_rows else None,
        "not_measured": list(NOT_MEASURED),
    }


async def build_viop_map_facts(ticker: str, sessions: int) -> dict[str, Any] | None:
    """
    One underlying's field as facts, or None.

    None means the book could not be built or is too thin to describe, which the
    caller must not render as an empty field. The same three upstreams the map
    route reads, in the same order, so the note never describes a field the page
    could not draw.
    """
    wanted = ticker.strip().upper()
    if not wanted:
        return None

    try:
        history = await get_history()
    except BulletinUnavailable as e:
        logger.info("VİOP bulletin unavailable for the %s map note: %s", wanted, e)
        return None

    rows = history.for_underlying(wanted)
    if not rows:
        return None

    held = sorted({row.day for row in rows})
    window = set(held[-sessions:])
    rows = [row for row in rows if row.day in window]

    try:
        psr_snapshot = await fetch_psr()
    except PsrUnavailable as e:
        logger.info("Takasbank scan range unavailable for the %s map note: %s", wanted, e)
        return None

    candles = await fetch_candles(wanted, range_=SPOT_RANGE)
    spot_closes = {
        candle["date"]: candle["close"] for candle in candles if candle.get("close") is not None
    }

    board = build_margin_map(rows, psr_snapshot, spot_closes, underlying=wanted)
    if board is None:
        return None

    return facts_from_map(
        board,
        rows,
        spot_closes,
        sessions_requested=sessions,
        stale=history.stale(),
        psr_as_of=psr_snapshot.as_of,
        psr_run=psr_snapshot.run,
    )


# ── Prompt rendering ─────────────────────────────────────────────────────────

_STANCE_GLOSS: dict[str, str] = {
    STANCE_LONG_HEAVY: "most of the standing notional is on the long side, so its bands sit "
    "below the spot price",
    STANCE_SHORT_HEAVY: "most of the standing notional is on the short side, so its bands sit "
    "above the spot price",
    STANCE_BALANCED: "the two sides stand at similar size, so neither set of bands dominates",
    STANCE_EMPTY: "nothing stands on the field — every level placed in the window has been "
    "traded through",
}


def _level_lines(levels: list[dict[str, Any]], side: str) -> list[str]:
    """
    One line per level, the side stated twice and the rank stated once.

    The local model given "Long band at 285" and "Short band at 356" on
    adjacent lines wrote the long band up as the short one, and given two long
    levels nearest-first quoted the farther as the nearest. Naming the side in
    capitals and the rank in words is cheaper than a longer instruction.
    """
    ranks = ("nearest", "next")
    return [
        f"{side.upper()} side, {ranks[index] if index < len(ranks) else 'further'} "
        f"{side} band: {_show_price(level['price'])}, "
        f"{_show_pct(level['distance_pct'])} from the latest spot close, "
        f"carrying {_show_try(level['notional_try'])}"
        for index, level in enumerate(levels)
    ]


def viop_map_values(facts: dict[str, Any]) -> dict[str, str]:
    """Render the prompt's placeholders from the facts, and from nothing else."""
    window = facts["window"]
    band = facts["band"]
    book = facts["book"]
    levels = facts["levels"]
    session = facts["session"]

    band_lines = [
        f"- Takasbank price scan range for {facts['ticker']}: "
        f"{_show_pct(band['psr_pct'], sign=False)} "
        f"(file dated {band['as_of']}, run {band['run']})",
        "- Where the clearing house stresses a position, as fractions of that range: "
        + ", ".join(_show_pct(rung, sign=False) for rung in band["rungs_pct"])
        + " — each session leaves one mark per rung on each side",
        "- A band is the move a position's initial margin was sized to absorb. "
        "It is NOT a margin call level: no maintenance margin rate is published "
        "for VİOP, so the price at which a call actually triggers is unknown",
    ]

    window_lines = [
        f"- Sessions in the window: {window['covered']} of {window['requested']} requested; "
        f"newest session {facts['as_of']}",
        f"- Sessions whose settlement did not move, placing nothing: "
        f"{window['undirected_sessions']}, "
        f"{_show_try(window['undirected_try'])} of opened notional left undirected",
    ]
    if window["basis_carried_sessions"]:
        window_lines.append(
            f"- Sessions converted with a carried-forward basis because the spot close was "
            f"missing: {window['basis_carried_sessions']}"
        )
    if window["dropped_sessions"]:
        window_lines.append(
            f"- Sessions dropped for want of any basis: {window['dropped_sessions']}"
        )

    book_lines = [
        f"- Open interest on the newest session: {book['open_interest']:,.0f} contracts "
        f"across {book['expiries']} expiries, all folded onto one spot axis",
        f"- Notional still standing on the field after sweeping: "
        f"{_show_try(book['standing_try'])} — long {_show_try(book['long_try'])}, "
        f"short {_show_try(book['short_try'])}",
        f"- Long side's share of what stands: {_show_pct(book['long_share_pct'], sign=False)}; "
        f"short side's share: "
        f"{_show_pct(100.0 - book['long_share_pct'] if book['long_share_pct'] is not None else None, sign=False)}",
        f"- Latest spot close every distance below is measured from: "
        f"{_show_price(facts['spot']['close'])}",
    ]

    level_lines = _level_lines(levels["long"], "long") + _level_lines(levels["short"], "short")

    if session is None:
        session_lines = ["- The newest session's rows could not be read"]
    else:
        session_lines = [
            f"- Newest session {session['day']}: open interest "
            f"{session['oi_change']:+,.0f} contracts, front-month settlement "
            f"{_show_pct(session['front_settlement_change_pct'])}",
            f"- Opened long (open interest up on a rising settlement): "
            f"{_show_try(session['opened_long_try'])}",
            f"- Opened short (open interest up on a falling settlement): "
            f"{_show_try(session['opened_short_try'])}",
            f"- Opened on an unchanged settlement, so placed on neither side: "
            f"{_show_try(session['undirected_try'])}",
            f"- Closed (open interest down, which places nothing): "
            f"{_show_try(session['closed_try'])}",
        ]

    return {
        "ticker": facts["ticker"],
        "stance": f"{facts['stance'].replace('_', ' ')} — {_STANCE_GLOSS[facts['stance']]}",
        "band": "\n".join(band_lines),
        "window": "\n".join(window_lines),
        "book": "\n".join(book_lines),
        "levels": _bullet(level_lines),
        "session": "\n".join(session_lines),
        "not_measured": ", ".join(facts["not_measured"]),
    }


async def viop_map_note(facts: dict[str, Any] | None) -> dict[str, Any]:
    """The note for this field, or `unavailable` when there is nothing to read."""
    if not facts:
        return unavailable(REASON_INSUFFICIENT_DATA)
    return await get_note(VIOP_MAP_SPEC, facts, viop_map_values(facts))
