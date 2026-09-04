"""
What the whole positioning board says, above four panels that each say one thing.

`/bist/konumlanma` draws crowding as a scatter, futures as four quadrants, the
52-week range as a histogram and sector heat as a treemap. Each panel is a
correct answer to its own question, and the question a reader actually arrives
with sits *between* them:

* whether the crowd is chasing strength or buying what has already fallen. The
  scatter knows which names are busy and the histogram knows where the board
  sits in its own year, and nothing on the page crosses the two — so the one
  reading that would name the behaviour is the one nobody can see.
* whether the crowding is a market-wide condition or four names in one sector.
  The treemap shows which sector is heaviest; it cannot show that the heaviest
  sector is half the board's whole score.
* whether published futures positioning agrees with either. Roughly forty names
  have contracts, so the quadrant chart is a sample of the board rather than a
  picture of it, and that distinction decides how much the panel is worth.

So this module aggregates, classifies in Python, and hands `services/ai_notes` a
finished set of facts to narrate — the contract `market_note` holds to, and for
the same reason: a local model asked to do arithmetic will do it confidently and
wrongly.

**Bucketing is load-bearing here, not tidiness.** The equity board refreshes
every two minutes and this board is derived from it, so fingerprinting a raw
crowding score or a raw count of names near their highs would retire the note on
every poll and leave a machine running a local model writing positioning
commentary forever. Every volatile reading is quantized, cohort sizes are
carried as bucketed shares rather than as counts that move by one all session,
and — the part that matters for correctness — the prompt is rendered from those
same bucketed values, so a cached note can never quote a figure that has since
moved.

The quantizers are redefined here rather than imported from `market_note`, which
is the choice `macro_regime` and `asset_brief_service` already made: they are
six one-line functions, and a shared module holding them would be a dependency
between three unrelated reads for no behaviour.

Nothing here raises. A note is a paragraph above a board that is already
complete, so every failure comes back as `unavailable` and the page keeps its
panels.
"""

import logging
import statistics
from typing import Any

from services.ai_notes import (
    REASON_INSUFFICIENT_DATA,
    NoteSpec,
    get_note,
    unavailable,
)
from services.bist.equity_service import EquityBoard, EquityDataUnavailable, fetch_equity_board
from services.bist.positioning_service import (
    MIN_FREE_FLOAT,
    MIN_RELATIVE_VOLUME,
    PositioningRow,
    build_positioning,
)
from services.bist.viop_service import ViopUnavailable, fetch_viop_board

logger = logging.getLogger(__name__)

UNKNOWN = "not available"

POSITIONING_SPEC = NoteSpec(
    kind="bist_positioning",
    prompt="notes/bist_positioning",
    # Same room the two market-wide reads get: this weaves four panels rather
    # than describing one instrument.
    max_tokens=560,
    max_chars=1400,
    temperature=0.25,
    max_age_seconds=4 * 3600,
)

# What this read cannot see, named to the reader and to the model rather than
# left implicit. The first entry is the page's own caveat: this board was
# specified as a fund-to-stock cross index and no public source carries the
# holdings it would need, so a paragraph about "who is positioned" that stayed
# silent about that would be claiming a completeness the data does not have.
NOT_MEASURED: tuple[str, ...] = (
    "fonların hangi hisseyi tuttuğu",
    "yabancı takas oranı",
    "açığa satış bakiyesi",
    "emir defteri derinliği",
)

# Below this the board is a handful of quotes, not a market to characterise.
MIN_EQUITIES = 50
# Below this the crowding ranking is a list, not a distribution to describe.
MIN_SCORED = 15

# How many names at the head of the ranking stand for "the crowd".
#
# Twenty rather than the top three: the stance below compares this cohort's
# median position in its own year against the board's, and a median over three
# names is one name with two neighbours. Three is what gets *named* in the
# prose; twenty is what gets measured.
CROWDED_HEAD = 20
NAMED_HEAD = 3

# Percentage points of 52-week range position separating the crowded head from
# the board before the difference is a behaviour rather than noise. Range
# position is bucketed to 5 points, so anything under two buckets would be a
# stance that flips on quantization alone.
RANGE_GAP_PCT = 12.0

STANCE_CHASING_STRENGTH = "chasing_strength"
STANCE_BOTTOM_FISHING = "bottom_fishing"
STANCE_DISPERSED = "dispersed"

# Mirrors `frontend/lib/bist-positioning.ts`. How far into its 52-week range a
# name has to be to count as sitting at an extreme.
NEAR_EXTREME_PCT = 10.0

OVERBOUGHT_RSI = 70.0
OVERSOLD_RSI = 30.0

# Volume this far above its own norm is unusual by anyone's reading, and the
# count of such names is what makes "crowded" a condition rather than a ratio.
HOT_RELATIVE_VOLUME = 2.0

TOP_SECTORS = 3
# A "sector" of two listings is a company, and its crowding is that company's.
MIN_SECTOR_MEMBERS = 3
# Above this share of the board's whole crowding score in one sector, the
# ranking is a sector's story wearing a market's name.
SECTOR_CONCENTRATION_PCT = 35.0

QUADRANTS: tuple[str, ...] = ("long_build", "short_build", "short_cover", "long_liquidation")
NAMED_BUILDS = 2


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
    """A fraction as rounded percentage points, or None."""
    if value is None:
        return None
    try:
        return _zeroed(round(float(value) * 100, digits))
    except (TypeError, ValueError):
        return None


def _pct_bucket(value: float | None, step: float) -> float | None:
    """A fraction as percentage points, snapped to `step`."""
    return _bucket(_pct(value, 4), step)


def _share_bucket(count: int, total: int, step: float = 2.0) -> float | None:
    """
    A cohort size as a bucketed share of the board.

    Cohorts are carried as shares rather than as counts on purpose. "Names near
    their 52-week high" moves by one or two on every two-minute poll, and a raw
    count in the fingerprint would regenerate this note all session for a change
    no reader could see. A share snapped to two points does not move until the
    board actually does.
    """
    if total <= 0:
        return None
    return _bucket(count / total * 100, step)


def _num(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    try:
        return _zeroed(round(float(value), digits))
    except (TypeError, ValueError):
        return None


def _day(stamp: str | None) -> str | None:
    """An ISO stamp as a bare date — `as_of` carries microseconds."""
    return (stamp or "")[:10] or None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


# ── Rendering helpers ────────────────────────────────────────────────────────


def _show_pct(value: float | None, sign: bool = True) -> str:
    if value is None:
        return UNKNOWN
    return f"{value:+.1f}%" if sign else f"{value:.1f}%"


def _show_num(value: float | None, digits: int = 1) -> str:
    return UNKNOWN if value is None else f"{value:.{digits}f}"


def _bullet(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) if lines else "- none"


# ── Classification ───────────────────────────────────────────────────────────


def classify_positioning_stance(
    head_range_pct: float | None,
    board_range_pct: float | None,
) -> str:
    """
    Whether the busiest names sit higher or lower in their own year than the board.

    This is the one reading the four panels cannot produce between them. The
    scatter knows which names are busy and the histogram knows where the board
    sits in its range; crossing them is what separates a market buying what is
    already working from one buying what has already fallen, and the two look
    identical in every column on the page.

    `dispersed` when the gap is inside the deadband — unusual volume that is not
    aligned with the range at all, which is a real read and not a failure to
    classify.
    """
    if head_range_pct is None or board_range_pct is None:
        return STANCE_DISPERSED

    gap = head_range_pct - board_range_pct
    if gap >= RANGE_GAP_PCT:
        return STANCE_CHASING_STRENGTH
    if gap <= -RANGE_GAP_PCT:
        return STANCE_BOTTOM_FISHING
    return STANCE_DISPERSED


def quadrant_of(row: PositioningRow) -> str | None:
    """
    Which futures quadrant a name sits in, or None if it sits on an axis.

    Mirrors `quadrantOf` in `frontend/lib/bist-positioning.ts`, deliberately: the
    panel and the paragraph above it must count the same names, and a second
    definition written a fortnight later is how they stop doing that. Exactly
    zero on either axis is the absence of a read rather than a weak one — open
    interest that did not move says nothing about who opened what.
    """
    change = row.open_interest_change
    price = row.change_pct
    if change is None or price is None or change == 0 or price == 0:
        return None
    if change > 0:
        return "long_build" if price > 0 else "short_build"
    return "short_cover" if price > 0 else "long_liquidation"


def _dominant(counts: dict[str, int]) -> str | None:
    """The quadrant with the strictly highest count, or None when nothing wins."""
    best: str | None = None
    best_count = 0
    tied = False
    for key, count in counts.items():
        if count > best_count:
            best, best_count, tied = key, count, False
        elif count == best_count and count > 0:
            tied = True
    return None if tied or best_count == 0 else best


# ── Aggregation ──────────────────────────────────────────────────────────────


def _name_entry(row: PositioningRow) -> dict[str, Any]:
    """One named example, quantized exactly as the aggregates around it are."""
    return {
        "ticker": row.ticker,
        "sector": row.sector,
        # Step 5 on a score that runs from about 5 to 100: a crowding figure
        # that moved by a point is the same reading, and rewriting the note for
        # it is the failure this module's whole quantization exists to avoid.
        "crowding": _bucket(row.crowding, 5.0),
        "free_float_pct": _pct_bucket(row.free_float_pct, 2.0),
        "relative_volume": _bucket(row.relative_volume, 0.5),
        "change_pct": _pct_bucket(row.change_pct, 1.0),
        "range_pct": _pct_bucket(row.range_position, 10.0),
        "rsi": _bucket(row.rsi, 5.0),
    }


def _sector_entry(sector: str, rows: list[PositioningRow], total_crowding: float) -> dict[str, Any]:
    scores = [row.crowding for row in rows if row.crowding is not None]
    volumes = [row.relative_volume for row in rows if row.relative_volume is not None]
    ranges = [row.range_position for row in rows if row.range_position is not None]
    summed = sum(scores)
    return {
        "sector": sector,
        "count": len(scores),
        "share_pct": _bucket(summed / total_crowding * 100, 2.0) if total_crowding > 0 else None,
        "median_relative_volume": _bucket(_median(volumes), 0.25),
        "median_range_pct": _pct_bucket(_median(ranges), 10.0),
    }


def _sectors(scored: list[PositioningRow]) -> list[dict[str, Any]]:
    """
    Crowding gathered by sector, heaviest first.

    Only scored rows contribute, and only sectors with enough of them to be a
    sector. A tile built from one busy name would put that name's story on the
    page under a sector's label, which is the reading a treemap makes easiest to
    misread and the one this paragraph should not repeat.
    """
    buckets: dict[str, list[PositioningRow]] = {}
    for row in scored:
        buckets.setdefault(row.sector or "Diğer", []).append(row)

    total = sum(row.crowding or 0.0 for row in scored)
    entries = [
        _sector_entry(sector, rows, total)
        for sector, rows in buckets.items()
        if len(rows) >= MIN_SECTOR_MEMBERS
    ]
    entries.sort(key=lambda entry: entry["share_pct"] or 0.0, reverse=True)
    return entries


def _futures(rows: list[PositioningRow], has_data: bool) -> dict[str, Any] | None:
    """
    Published positioning, or None when VİOP could not be read.

    Optional on purpose, as it is in `market_note`: this comes from a scraped
    page that is down more often than the rest of the realm, and a failure
    should drop the fact and add the reading to `not_measured` rather than cost
    the paragraph.
    """
    if not has_data:
        return None

    with_futures = [row for row in rows if row.open_interest]
    if not with_futures:
        return None

    counts = dict.fromkeys(QUADRANTS, 0)
    for row in with_futures:
        quadrant = quadrant_of(row)
        if quadrant:
            counts[quadrant] += 1

    open_interest = sum(row.open_interest or 0.0 for row in with_futures)
    change = sum(row.open_interest_change or 0.0 for row in with_futures)
    # Growth against yesterday's book. Dividing by today's total would already
    # contain the move, understating a build and overstating a liquidation.
    previous = open_interest - change
    growth = change / previous if previous > 0 else None

    def _ratio(row: PositioningRow) -> float | None:
        before = (row.open_interest or 0.0) - (row.open_interest_change or 0.0)
        return (row.open_interest_change or 0.0) / before if before > 0 else None

    builds = [row for row in with_futures if quadrant_of(row) and _ratio(row) is not None]
    builds.sort(key=lambda row: abs(_ratio(row) or 0.0), reverse=True)

    return {
        "covered": len(with_futures),
        # A thousand lots: the total is a large integer that moves by a handful
        # of contracts constantly.
        "total_open_interest": _bucket(open_interest, 1000.0),
        "growth_pct": _pct_bucket(growth, 0.5),
        "quadrants": counts,
        "dominant": _dominant(counts),
        "movers": [
            {
                "ticker": row.ticker,
                "quadrant": quadrant_of(row),
                "oi_change_pct": _pct_bucket(_ratio(row), 5.0),
                "change_pct": _pct_bucket(row.change_pct, 1.0),
            }
            for row in builds[:NAMED_BUILDS]
        ],
    }


async def build_positioning_facts() -> dict[str, Any] | None:
    """
    The whole positioning board as a quantized set of readings, or None.

    Computed across every listing rather than the page the caller asked for. The
    endpoint beside this ranks by crowding and takes a `limit`, so its rows are a
    *biased* sample by construction — "the board is sitting at the top of its
    year" answered over the hundred busiest names is not a narrower answer, it is
    a wrong one.

    None means the board could not be read or is too thin to characterise, which
    the caller must not render as a quiet market. "Nothing is happening" and "we
    cannot see what is happening" are different claims.
    """
    try:
        board: EquityBoard = await fetch_equity_board()
    except EquityDataUnavailable as e:
        logger.info("Equity board unavailable for the positioning note: %s", e)
        return None

    if len(board.equities) < MIN_EQUITIES:
        return None

    contracts = []
    try:
        contracts = (await fetch_viop_board()).contracts
    except ViopUnavailable as e:
        logger.info("VİOP unavailable for the positioning note: %s", e)

    rows = build_positioning(board.equities, contracts)
    scored = [row for row in rows if row.crowding is not None]
    if len(scored) < MIN_SCORED:
        return None

    head = scored[:CROWDED_HEAD]

    positions = [row.range_position for row in rows if row.range_position is not None]
    head_positions = [row.range_position for row in head if row.range_position is not None]
    board_range = _pct_bucket(_median(positions), 5.0)
    head_range = _pct_bucket(_median(head_positions), 5.0)

    near_high = sum(1 for value in positions if value * 100 >= 100 - NEAR_EXTREME_PCT)
    near_low = sum(1 for value in positions if value * 100 <= NEAR_EXTREME_PCT)

    rsis = [row.rsi for row in rows if row.rsi is not None]
    high_rsis = [
        row.rsi
        for row in rows
        if row.rsi is not None
        and row.range_position is not None
        and row.range_position * 100 >= 100 - NEAR_EXTREME_PCT
    ]

    floats = [row.free_float_pct for row in rows if row.free_float_pct is not None]
    head_floats = [row.free_float_pct for row in head if row.free_float_pct is not None]
    volumes = [row.relative_volume for row in rows if row.relative_volume is not None]
    head_volumes = [row.relative_volume for row in head if row.relative_volume is not None]
    hot = sum(1 for value in volumes if value >= HOT_RELATIVE_VOLUME)

    # Why the rest of the board carries no score, split by cause. Both are
    # deliberate refusals rather than gaps — see `positioning_service._crowding`
    # — and a reader told only that "260 names are unscored" would reasonably
    # read it as missing data.
    tight = sum(
        1
        for row in rows
        if row.crowding is None
        and row.free_float_pct is not None
        and row.free_float_pct < MIN_FREE_FLOAT
    )
    quiet = sum(
        1
        for row in rows
        if row.crowding is None
        and row.relative_volume is not None
        and row.relative_volume < MIN_RELATIVE_VOLUME
    )

    sectors = _sectors(scored)
    futures = _futures(rows, bool(contracts))

    not_measured = list(NOT_MEASURED)
    if futures is None:
        not_measured.append("VİOP açık pozisyonu")

    top_share = sectors[0]["share_pct"] if sectors else None

    return {
        "stance": classify_positioning_stance(head_range, board_range),
        "as_of": _day(board.as_of),
        "stale": board.stale,
        "board": {
            "total": len(rows),
            "scored": len(scored),
            "scored_pct": _share_bucket(len(scored), len(rows)),
            "unscored_tight_float": tight,
            "unscored_quiet": quiet,
            "median_free_float_pct": _pct_bucket(_median(floats), 2.0),
            "median_relative_volume": _bucket(_median(volumes), 0.25),
            "hot_pct": _share_bucket(hot, len(volumes)),
            "min_free_float_pct": _pct(MIN_FREE_FLOAT),
            "min_relative_volume": MIN_RELATIVE_VOLUME,
        },
        "crowd": {
            "cohort": len(head),
            "median_crowding": _bucket(_median([row.crowding for row in head]), 5.0),
            "median_free_float_pct": _pct_bucket(_median(head_floats), 2.0),
            "median_relative_volume": _bucket(_median(head_volumes), 0.25),
            "median_range_pct": head_range,
            "board_median_range_pct": board_range,
            "range_gap_pct": (
                _bucket(head_range - board_range, 1.0)
                if head_range is not None and board_range is not None
                else None
            ),
            "names": [_name_entry(row) for row in head[:NAMED_HEAD]],
        },
        "range": {
            "measured": len(positions),
            "median_pct": board_range,
            "near_high_pct": _share_bucket(near_high, len(positions)),
            "near_low_pct": _share_bucket(near_low, len(positions)),
            "near_extreme_pct": NEAR_EXTREME_PCT,
            "median_rsi": _bucket(_median(rsis), 5.0),
            "near_high_median_rsi": _bucket(_median(high_rsis), 5.0),
            "overbought_pct": _share_bucket(
                sum(1 for value in rsis if value >= OVERBOUGHT_RSI), len(rsis)
            ),
            "oversold_pct": _share_bucket(
                sum(1 for value in rsis if value <= OVERSOLD_RSI), len(rsis)
            ),
        },
        "sectors": sectors[:TOP_SECTORS],
        "sector_concentrated": top_share is not None and top_share >= SECTOR_CONCENTRATION_PCT,
        "futures": futures,
        "not_measured": not_measured,
    }


# ── Prompt rendering ─────────────────────────────────────────────────────────


def positioning_values(facts: dict[str, Any]) -> dict[str, str]:
    """Render the prompt's placeholders from the facts, and from nothing else."""
    board = facts["board"]
    crowd = facts["crowd"]
    span = facts["range"]
    futures = facts["futures"]

    board_lines = [
        f"- Listings on the board: {board['total']}",
        f"- Listings carrying a crowding score: {board['scored']} "
        f"({_show_pct(board['scored_pct'], sign=False)} of the board)",
        f"- Unscored because their free float is under "
        f"{_show_pct(board['min_free_float_pct'], sign=False)} and dividing by it would "
        f"produce a score for a share nobody can trade: {board['unscored_tight_float']}",
        f"- Unscored because volume is not elevated at all "
        f"(under {_show_num(board['min_relative_volume'], 1)}× its own ten-day norm): "
        f"{board['unscored_quiet']}",
        f"- Median free float across the board: "
        f"{_show_pct(board['median_free_float_pct'], sign=False)}",
        f"- Median relative volume across the board: "
        f"{_show_num(board['median_relative_volume'], 2)}×",
        f"- Share of listings trading at twice their own norm or more: "
        f"{_show_pct(board['hot_pct'], sign=False)}",
    ]

    crowd_lines = [
        f"- The crowded cohort is the {crowd['cohort']} highest-scoring names",
        f"- Their median crowding score: {_show_num(crowd['median_crowding'], 0)} "
        "(relative volume divided by free float — a sorting aid, not a verdict)",
        f"- Their median free float: {_show_pct(crowd['median_free_float_pct'], sign=False)}, "
        f"against {_show_pct(board['median_free_float_pct'], sign=False)} for the board",
        f"- Their median relative volume: {_show_num(crowd['median_relative_volume'], 2)}×, "
        f"against {_show_num(board['median_relative_volume'], 2)}× for the board",
    ]
    if crowd["median_range_pct"] is None or crowd["board_median_range_pct"] is None:
        crowd_lines.append(
            "- Where they sit in their own 52-week range could not be measured, so "
            "whether the crowd is chasing strength or buying weakness is unknown "
            "rather than balanced"
        )
    else:
        crowd_lines.append(
            f"- Their median position in their own 52-week range: "
            f"{_show_pct(crowd['median_range_pct'], sign=False)} of the way from the "
            f"low to the high, against "
            f"{_show_pct(crowd['board_median_range_pct'], sign=False)} for the board "
            f"— a gap of {_show_pct(crowd['range_gap_pct'])} points"
        )

    def _name_line(entry: dict[str, Any]) -> str:
        return (
            f"{entry['ticker']} ({entry['sector']}): crowding "
            f"{_show_num(entry['crowding'], 0)}, free float "
            f"{_show_pct(entry['free_float_pct'], sign=False)}, volume "
            f"{_show_num(entry['relative_volume'], 1)}× its norm, today "
            f"{_show_pct(entry['change_pct'])}, sitting "
            f"{_show_pct(entry['range_pct'], sign=False)} up its 52-week range"
        )

    range_lines = [
        f"- Listings with a measurable 52-week range: {span['measured']}",
        f"- Median position in that range across the board: "
        f"{_show_pct(span['median_pct'], sign=False)}",
        f"- Sitting within {_show_pct(span['near_extreme_pct'], sign=False)} of their "
        f"52-week high: {_show_pct(span['near_high_pct'], sign=False)} of measured listings",
        f"- Within the same distance of their 52-week low: "
        f"{_show_pct(span['near_low_pct'], sign=False)}",
        f"- Median 14-day RSI across the board: {_show_num(span['median_rsi'], 0)}",
        f"- Median RSI of the names near their highs: "
        f"{_show_num(span['near_high_median_rsi'], 0)} "
        "(a cohort at its highs whose RSI has fallen back is a market that has "
        "stopped buying something it has not yet sold)",
        f"- Overbought, RSI {OVERBOUGHT_RSI:.0f} or above: "
        f"{_show_pct(span['overbought_pct'], sign=False)} of measured listings; "
        f"oversold, RSI {OVERSOLD_RSI:.0f} or below: "
        f"{_show_pct(span['oversold_pct'], sign=False)}",
    ]

    def _sector_line(entry: dict[str, Any]) -> str:
        return (
            f"{entry['sector']}: {_show_pct(entry['share_pct'], sign=False)} of the "
            f"board's total crowding across {entry['count']} scored names, median "
            f"volume {_show_num(entry['median_relative_volume'], 2)}×, median range "
            f"position {_show_pct(entry['median_range_pct'], sign=False)}"
        )

    sector_lines = [_sector_line(entry) for entry in facts["sectors"]]
    if facts["sector_concentrated"]:
        sector_lines.append(
            "Note: one sector carries an unusually large share of the board's whole "
            "crowding score, so the ranking is describing that sector rather than "
            "the market"
        )

    if futures is None:
        futures_lines = [
            "- VİOP could not be read, so the one place in this market where "
            "positioning is published rather than inferred is missing from this note"
        ]
    else:
        quadrants = futures["quadrants"]
        futures_lines = [
            f"- Underlyings with listed futures: {futures['covered']} "
            "— a sample of the board, not a picture of it",
            f"- Total open interest: {_show_num(futures['total_open_interest'], 0)} contracts",
            f"- Change against yesterday's book: {_show_pct(futures['growth_pct'])}",
            f"- Open interest rose with price (new money long): {quadrants['long_build']} names",
            f"- Open interest rose as price fell (new money short): "
            f"{quadrants['short_build']} names",
            f"- Open interest fell as price rose (shorts closing): "
            f"{quadrants['short_cover']} names",
            f"- Open interest and price fell together (longs leaving): "
            f"{quadrants['long_liquidation']} names",
        ]
        if futures["dominant"]:
            futures_lines.append(
                f"- The quadrant holding the most names: {futures['dominant'].replace('_', ' ')}"
            )
        else:
            futures_lines.append(
                "- No quadrant holds the most names outright, so futures positioning "
                "has no dominant direction today"
            )
        for mover in futures["movers"]:
            futures_lines.append(
                f"- {mover['ticker']}: open interest "
                f"{_show_pct(mover['oi_change_pct'])} against yesterday while the share "
                f"moved {_show_pct(mover['change_pct'])} — {mover['quadrant'].replace('_', ' ')}"
            )

    return {
        "stance": facts["stance"].replace("_", " "),
        "board": "\n".join(board_lines),
        "crowd": "\n".join(crowd_lines),
        "names": _bullet([_name_line(entry) for entry in crowd["names"]]),
        "range": "\n".join(range_lines),
        "sectors": _bullet(sector_lines),
        "futures": "\n".join(futures_lines),
        "not_measured": ", ".join(facts["not_measured"]),
    }


async def positioning_note(
    facts: dict[str, Any] | None, user_id: str | None = None
) -> dict[str, Any]:
    """The note for this board, or `unavailable` when there is nothing to read."""
    if not facts:
        return unavailable(REASON_INSUFFICIENT_DATA)
    return await get_note(POSITIONING_SPEC, facts, positioning_values(facts), user_id)
