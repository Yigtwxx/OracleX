"""
What the VİOP board says as a whole, above the panels that draw its rows.

The derivatives page publishes the one number this market does not make anyone
infer: open interest. Four panels draw it — a bar per underlying, a quadrant
scatter, a term-structure curve and the split across expiries — and each answers
its own question correctly. The question a reader arrives with sits between them:

* whether the day's move was positions being *opened* or *closed*. Price and
  open interest each have a column and a direction, and the pairing of the two
  is the whole read; neither column states it.
* whether "the VİOP book grew" is a statement about this market or about one
  contract. USDTRY and the index routinely carry most of the outstanding
  interest, so a board-wide growth figure can be one underlying wearing the
  market's name — the bar chart shows which is biggest, not that the biggest is
  most of the total.
* whether the curve agrees with the flow. In a high-rate currency the futures
  strip sits above spot as a matter of arithmetic, so contango is the resting
  state and says nothing; backwardation is the finding, and no panel can say
  which of the two it is looking at without knowing that.

So this module aggregates, classifies in Python, and hands `services/ai_notes` a
finished set of facts to narrate — the contract `market_note` and
`positioning_note` hold to, and for the same reason: a local model asked to do
arithmetic will do it confidently and wrongly.

**Bucketing is load-bearing here, not tidiness.** The board is cached for five
minutes and the page polls, so fingerprinting a raw open-interest total would
retire the note on every refresh and leave a machine writing derivatives
commentary forever. Every volatile reading is quantized, and — the part that
matters for correctness — the prompt is rendered from those same bucketed
values, so a cached note can never quote a figure that has since moved.

The quantizers are redefined here rather than imported from `positioning_note`,
which is the choice `market_note` and `macro_regime` already made: they are six
one-line functions, and a shared module holding them would be a dependency
between unrelated reads for no behaviour.

**Futures only.** The board is not one instrument. Roughly a fifth of its rows
are options, and a put on the same underlying and expiry settles at its premium
— 0.13 where the future settles at 13.16. Every read here is a futures read, so
the options are filtered out once in `build_viop_facts` and counted, rather than
being filtered in four places or, worse, in none: summed they add two unrelated
books into one open-interest total, and drawn on one axis they produce a term
structure in 99% backwardation.

Nothing here raises. A note is a paragraph above a board that is already
complete, so every failure comes back as `unavailable` and the page keeps its
panels.
"""

import logging
from typing import Any

from services.ai_notes import (
    REASON_INSUFFICIENT_DATA,
    NoteSpec,
    get_note,
    unavailable,
)
from services.bist.viop_service import (
    KIND_FUTURE,
    ViopContract,
    ViopUnavailable,
    fetch_viop_board,
    roll_by_underlying,
)

logger = logging.getLogger(__name__)

UNKNOWN = "not available"

VIOP_SPEC = NoteSpec(
    kind="bist_viop",
    prompt="notes/bist_viop",
    # The room the other board-wide reads get: this weaves four panels rather
    # than describing one instrument.
    max_tokens=520,
    max_chars=1300,
    temperature=0.25,
    max_age_seconds=4 * 3600,
)

# What this read does not cover, named to the reader and to the model rather
# than left implicit. The first two are the ones a derivatives reader will
# assume are there: the exchange publishes how many contracts are outstanding
# and never who holds them, and the options on this same board are set aside
# rather than folded in — see `build_viop_facts`.
NOT_MEASURED: tuple[str, ...] = (
    "pozisyonların hangi tarafta kimde olduğu",
    "opsiyon açık pozisyonu",
    "emir defteri derinliği",
    "teminat ve takas seviyeleri",
)

# Below this the board is a handful of quotes rather than a market to
# characterise. The exchange lists well over a hundred contracts on a normal
# day, so this only fires when the scrape came back half-parsed.
MIN_CONTRACTS = 12
# Open interest is the reason this note exists. Without enough contracts
# publishing it there is a price board here and nothing to say about positioning.
MIN_MEASURED = 6

TOP_UNDERLYINGS = 3
CURVE_UNDERLYINGS = 3
NAMED_MOVERS = 3

# Share of the day's open-interest movement one quadrant has to carry before it
# is the board's direction rather than the largest of four similar piles.
DOMINANCE_PCT = 40.0

# Above this share of all outstanding interest in one underlying, a board-wide
# figure is that underlying's figure and saying so is the finding.
CONCENTRATION_PCT = 50.0

# Below this spread between the front and back of a strip, the curve is flat.
# Two points on a strip that differ by a quarter of a percent are the same
# price quoted twice, and calling that contango would invent a term structure.
FLAT_SPREAD_PCT = 0.5

QUADRANTS: tuple[str, ...] = ("long_build", "short_build", "short_cover", "long_liquidation")

STANCE_MIXED = "mixed"

SHAPE_CONTANGO = "contango"
SHAPE_BACKWARDATION = "backwardation"
SHAPE_FLAT = "flat"


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
    """A cohort size as a bucketed share of the board."""
    if total <= 0:
        return None
    return _bucket(count / total * 100, step)


def _day(stamp: str | None) -> str | None:
    """An ISO stamp as a bare date — `as_of` carries microseconds."""
    return (stamp or "")[:10] or None


# ── Rendering helpers ────────────────────────────────────────────────────────


def _show_pct(value: float | None, sign: bool = True) -> str:
    if value is None:
        return UNKNOWN
    return f"{value:+.1f}%" if sign else f"{value:.1f}%"


def _show_num(value: float | None, digits: int = 1) -> str:
    return UNKNOWN if value is None else f"{value:,.{digits}f}"


def _bullet(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines) if lines else "- none"


# ── Classification ───────────────────────────────────────────────────────────


def quadrant_of(contract: ViopContract) -> str | None:
    """
    Which positioning quadrant a contract sits in, or None if it sits on an axis.

    Mirrors `viopQuadrantOf` in `frontend/lib/bist-viop.ts`, deliberately: the
    scatter and the paragraph above it must count the same contracts, and a
    second definition written a fortnight later is how they stop doing that.

    Exactly zero on either axis is the absence of a read rather than a weak one.
    Open interest that did not move says nothing about who opened what, and a
    contract that did not move in price says nothing about which side paid.
    """
    change = contract.open_interest_change
    price = contract.change_pct
    if change is None or price is None or change == 0 or price == 0:
        return None
    if change > 0:
        return "long_build" if price > 0 else "short_build"
    return "short_cover" if price > 0 else "long_liquidation"


def classify_viop_stance(weight_pct: dict[str, float | None]) -> str:
    """
    The board's direction: the quadrant carrying most of the day's flow.

    Weighted by how much open interest actually moved rather than by how many
    contracts moved, because the two disagree constantly on this board. Forty
    single-stock contracts opening a hundred lots each is a different day from
    the index strip opening fifty thousand, and a count treats the first as the
    larger event.

    `mixed` below the dominance floor, which is a real read: a session where new
    longs and closing shorts each carry a third of the movement has no direction
    to name, and picking the larger of two similar piles would state one.

    Classified from the *bucketed* shares so the label cannot flip on a rounding
    difference the note's own facts would not show.
    """
    best: str | None = None
    best_share = 0.0
    for quadrant in QUADRANTS:
        share = weight_pct.get(quadrant)
        if share is not None and share > best_share:
            best, best_share = quadrant, share
    if best is None or best_share < DOMINANCE_PCT:
        return STANCE_MIXED
    return best


def classify_curve(spread_pct: float | None) -> str:
    """
    Whether a strip prices later expiries above or below the near one.

    Deliberately not read as a sentiment signal here. Turkish rates make the
    cost of carry large, so an equity or currency strip in contango is the
    resting state and carries no information at all; the deadband and the
    explicit `flat` exist so the note can tell "the curve is doing the normal
    thing" apart from "the curve has inverted", which is the only one of the
    three worth a sentence.
    """
    if spread_pct is None:
        return SHAPE_FLAT
    if spread_pct >= FLAT_SPREAD_PCT:
        return SHAPE_CONTANGO
    if spread_pct <= -FLAT_SPREAD_PCT:
        return SHAPE_BACKWARDATION
    return SHAPE_FLAT


# ── Aggregation ──────────────────────────────────────────────────────────────


def _oi_ratio(contract: ViopContract) -> float | None:
    """
    A contract's open-interest change against *yesterday's* book.

    Dividing by today's total would already contain the move, understating a
    build and overstating a liquidation.
    """
    change = contract.open_interest_change
    if change is None or contract.open_interest is None:
        return None
    previous = contract.open_interest - change
    return change / previous if previous > 0 else None


def _quadrants(contracts: list[ViopContract]) -> dict[str, Any]:
    """The four positioning reads, by contract count and by weight of flow."""
    counts = dict.fromkeys(QUADRANTS, 0)
    weights = dict.fromkeys(QUADRANTS, 0.0)
    on_axis = 0

    for contract in contracts:
        quadrant = quadrant_of(contract)
        if quadrant is None:
            on_axis += 1
            continue
        counts[quadrant] += 1
        weights[quadrant] += abs(contract.open_interest_change or 0.0)

    total = sum(weights.values())
    weight_pct = {
        quadrant: (_bucket(weights[quadrant] / total * 100, 5.0) if total > 0 else None)
        for quadrant in QUADRANTS
    }

    # Which quadrant holds the most *contracts*, which is routinely not the one
    # holding the most flow. Computed here rather than left for the model to
    # notice, because the first thing a model does with two competing rankings
    # is pick the one with the larger integers: given 23 short-side contracts
    # against a long side carrying 65% of the movement, it wrote the board up as
    # short and contradicted the stance it had been told to explain.
    busiest = max(QUADRANTS, key=lambda quadrant: counts[quadrant])
    if counts[busiest] == 0 or sum(1 for q in QUADRANTS if counts[q] == counts[busiest]) > 1:
        busiest = None

    return {
        "counts": counts,
        "weight_pct": weight_pct,
        "on_axis": on_axis,
        "measured": sum(counts.values()),
        "busiest": busiest,
    }


def _concentration(contracts: list[ViopContract]) -> dict[str, Any]:
    """
    Where the outstanding interest actually sits.

    Built from `roll_by_underlying` rather than from the summary the endpoint
    serves, because that one flattens "no expiry published a figure" back to
    zero for payload-compatibility reasons of its own. Here the distinction
    matters: an underlying whose open-interest column was empty must not be
    ranked as a name nobody holds.
    """
    rolls = roll_by_underlying(contracts)
    measured = [roll for roll in rolls.values() if roll.open_interest is not None]
    total = sum(roll.open_interest or 0.0 for roll in measured)

    ranked = sorted(measured, key=lambda roll: roll.open_interest or 0.0, reverse=True)
    top = [
        {
            "underlying": roll.underlying,
            "open_interest": _bucket(roll.open_interest, 1000.0),
            "share_pct": _bucket((roll.open_interest or 0.0) / total * 100, 2.0) if total else None,
            "oi_change_pct": _pct_bucket(
                (
                    (roll.open_interest_change or 0.0)
                    / ((roll.open_interest or 0.0) - (roll.open_interest_change or 0.0))
                    if (roll.open_interest or 0.0) - (roll.open_interest_change or 0.0) > 0
                    else None
                ),
                1.0,
            ),
            "expiries": roll.contracts,
        }
        for roll in ranked[:TOP_UNDERLYINGS]
    ]

    top_share = top[0]["share_pct"] if top else None
    return {
        "top": top,
        "top_share_pct": top_share,
        "concentrated": top_share is not None and top_share >= CONCENTRATION_PCT,
    }


def _movers(contracts: list[ViopContract]) -> list[dict[str, Any]]:
    """The contracts whose books moved most in proportional terms."""
    scored = [
        (contract, ratio)
        for contract in contracts
        if (ratio := _oi_ratio(contract)) is not None and quadrant_of(contract) is not None
    ]
    scored.sort(key=lambda pair: abs(pair[1]), reverse=True)

    return [
        {
            "underlying": contract.underlying,
            "expiry": contract.expiry,
            "quadrant": quadrant_of(contract),
            "oi_change_pct": _pct_bucket(ratio, 5.0),
            "change_pct": _pct_bucket(contract.change_pct, 0.5),
            "open_interest": _bucket(contract.open_interest, 1000.0),
        }
        for contract, ratio in scored[:NAMED_MOVERS]
    ]


def _curve_for(strip: list[ViopContract]) -> dict[str, Any] | None:
    """
    One underlying's term structure: the back of the strip against its front.

    Settlement rather than last, and that is not interchangeable. The far months
    on this board can go a whole session without a trade, so their last price is
    whenever someone last dealt; the settlement price is published for every
    contract every day, which is the only thing that makes two points on a curve
    comparable.
    """
    dated = [
        contract
        for contract in strip
        if contract.expiry_date is not None and contract.settlement is not None
    ]
    if len(dated) < 2:
        return None

    dated.sort(key=lambda contract: contract.expiry_date or "")
    front, back = dated[0], dated[-1]
    if not front.settlement:
        return None

    spread = _bucket(
        ((back.settlement or 0.0) - front.settlement) / front.settlement * 100,
        0.5,
    )
    return {
        "underlying": front.underlying,
        "shape": classify_curve(spread),
        "spread_pct": spread,
        "expiries": len(dated),
        "front": front.expiry_date,
        "back": back.expiry_date,
    }


def _curves(contracts: list[ViopContract], ranked: list[str]) -> list[dict[str, Any]]:
    """Term structure for the underlyings that carry the book, largest first."""
    strips: dict[str, list[ViopContract]] = {}
    for contract in contracts:
        strips.setdefault(contract.underlying, []).append(contract)

    curves = []
    for underlying in ranked[:CURVE_UNDERLYINGS]:
        curve = _curve_for(strips.get(underlying, []))
        if curve is not None:
            curves.append(curve)
    return curves


def _roll(contracts: list[ViopContract]) -> dict[str, Any]:
    """
    How much of the book still sits in the nearest expiry.

    The reading a table sorted by open interest cannot give: a front month
    holding almost all of the outstanding interest is a market that has not
    rolled yet, and the same board a fortnight later with the same total is a
    different set of positions.
    """
    dated = [
        contract
        for contract in contracts
        if contract.expiry_date is not None and contract.open_interest is not None
    ]
    if not dated:
        return {"front": None, "front_share_pct": None, "expiries": 0}

    front = min(contract.expiry_date or "" for contract in dated)
    total = sum(contract.open_interest or 0.0 for contract in dated)
    in_front = sum(
        contract.open_interest or 0.0 for contract in dated if contract.expiry_date == front
    )

    return {
        "front": front,
        "front_share_pct": _bucket(in_front / total * 100, 5.0) if total > 0 else None,
        "expiries": len({contract.expiry_date for contract in dated}),
    }


async def build_viop_facts() -> dict[str, Any] | None:
    """
    The whole VİOP board as a quantized set of readings, or None.

    None means the board could not be read or came back too thin to describe,
    which the caller must not render as a quiet session. "Nothing is happening"
    and "we cannot see what is happening" are different claims, and this
    particular board is a scrape — the second is the likelier one.
    """
    try:
        board = await fetch_viop_board()
    except ViopUnavailable as e:
        logger.info("VİOP board unavailable for its own note: %s", e)
        return None

    # Futures only, and this is not a simplification.
    #
    # Roughly a fifth of the board is options, and `ISCTR (30 Eyl 26) Satim
    # opsiyonu` settles at 0.13 against the future's 13.16 because one figure is
    # a premium and the other is a price. Summed, they add two unrelated books
    # into one open-interest total; placed on one axis they produce a term
    # structure in 99% backwardation. The reads below — the curve, the roll, the
    # quadrants — are all futures reads, so the filter belongs here rather than
    # in each of them, and the count of what was set aside is carried into the
    # facts so the note can say what it did not look at.
    options = [c for c in board.contracts if c.kind != KIND_FUTURE]
    contracts = [c for c in board.contracts if c.kind == KIND_FUTURE]
    if len(contracts) < MIN_CONTRACTS:
        return None

    measured = [contract for contract in contracts if contract.open_interest is not None]
    if len(measured) < MIN_MEASURED:
        return None

    total = sum(contract.open_interest or 0.0 for contract in measured)
    change = sum(contract.open_interest_change or 0.0 for contract in contracts)
    # Growth against yesterday's book, for the reason `_oi_ratio` records.
    previous = total - change
    growth = change / previous if previous > 0 else None

    concentration = _concentration(contracts)
    quadrants = _quadrants(contracts)
    ranked = [entry["underlying"] for entry in concentration["top"]]

    return {
        "stance": classify_viop_stance(quadrants["weight_pct"]),
        "as_of": _day(board.as_of),
        "stale": board.stale,
        "board": {
            "contracts": len(contracts),
            "underlyings": len({contract.underlying for contract in contracts}),
            "measured": len(measured),
            "silent": len(contracts) - len(measured),
            "undated": sum(1 for contract in contracts if contract.expiry_date is None),
            "total_open_interest": _bucket(total, 1000.0),
            "open_interest_change": _bucket(change, 500.0),
            "growth_pct": _pct_bucket(growth, 0.5),
            "physical_pct": _share_bucket(
                sum(1 for contract in contracts if contract.physical), len(contracts), 5.0
            ),
            "options_set_aside": len(options),
        },
        "concentration": concentration,
        "quadrants": quadrants,
        "movers": _movers(contracts),
        "curves": _curves(contracts, ranked),
        "roll": _roll(contracts),
        "not_measured": list(NOT_MEASURED),
    }


# ── Prompt rendering ─────────────────────────────────────────────────────────

_QUADRANT_GLOSS: dict[str, str] = {
    "long_build": "open interest rose with price — new money long",
    "short_build": "open interest rose as price fell — new money short",
    "short_cover": "open interest fell as price rose — shorts closing",
    "long_liquidation": "open interest and price fell together — longs leaving",
}

_SHAPE_GLOSS: dict[str, str] = {
    SHAPE_CONTANGO: "later expiries priced above the front month",
    SHAPE_BACKWARDATION: "later expiries priced below the front month",
    SHAPE_FLAT: "no meaningful spread between the front and back of the strip",
}


def viop_values(facts: dict[str, Any]) -> dict[str, str]:
    """Render the prompt's placeholders from the facts, and from nothing else."""
    board = facts["board"]
    concentration = facts["concentration"]
    quadrants = facts["quadrants"]
    roll = facts["roll"]

    board_lines = [
        f"- Contracts on the board: {board['contracts']} across {board['underlyings']} underlyings",
        f"- Contracts publishing an open-interest figure: {board['measured']}; "
        f"publishing none: {board['silent']} "
        "(an empty column is an unread figure, not a position of zero)",
        f"- Total open interest: {_show_num(board['total_open_interest'], 0)} contracts",
        f"- Change against yesterday's book: "
        f"{_show_num(board['open_interest_change'], 0)} contracts, "
        f"{_show_pct(board['growth_pct'])}",
        f"- Share of contracts that settle physically rather than in cash: "
        f"{_show_pct(board['physical_pct'], sign=False)}",
    ]
    if board["options_set_aside"]:
        board_lines.append(
            f"- Option contracts on the same board, excluded from every figure above and "
            f"below: {board['options_set_aside']} "
            "(a premium and a price are not comparable, and summing their open interest "
            "would add two unrelated books together)"
        )
    if board["undated"]:
        board_lines.append(
            f"- Contracts whose expiry label could not be read, and which are therefore "
            f"absent from the curve and the roll figures below: {board['undated']}"
        )

    concentration_lines = [
        f"{entry['underlying']}: {_show_num(entry['open_interest'], 0)} contracts, "
        f"{_show_pct(entry['share_pct'], sign=False)} of all outstanding interest, "
        f"across {entry['expiries']} expiries, open interest "
        f"{_show_pct(entry['oi_change_pct'])} against yesterday"
        for entry in concentration["top"]
    ]
    if concentration["concentrated"]:
        concentration_lines.append(
            "Note: one underlying carries most of the board's entire open interest, "
            "so a board-wide figure is largely that one contract's figure"
        )

    counts = quadrants["counts"]
    weight = quadrants["weight_pct"]
    quadrant_lines = [
        f"- {_QUADRANT_GLOSS[quadrant]}: {counts[quadrant]} contracts, carrying "
        f"{_show_pct(weight[quadrant], sign=False)} of the day's open-interest movement"
        for quadrant in QUADRANTS
    ]
    quadrant_lines.append(
        f"- Contracts sitting on an axis — open interest or price did not move at all, "
        f"so they name no one: {quadrants['on_axis']}"
    )

    busiest = quadrants.get("busiest")
    stance = facts["stance"]
    if busiest is None:
        quadrant_lines.append(
            "- No quadrant holds the most contracts outright, so the headcount has no "
            "leader to compare the stance against"
        )
    elif busiest != stance:
        quadrant_lines.append(
            f"- **The headcount and the flow disagree.** The most contracts sit in "
            f"{busiest.replace('_', ' ')} ({counts[busiest]} of them), but "
            f"{stance.replace('_', ' ')} carries "
            f"{_show_pct(weight[stance], sign=False)} of the open interest that actually "
            "moved, and the stance follows the flow. Many small books moving one way "
            "while one large book moves the other is a real session and the reading is "
            "the second one — say both, and do not describe the board as though the "
            "headcount won."
        )
    else:
        quadrant_lines.append(
            f"- The headcount and the flow agree: {busiest.replace('_', ' ')} holds both "
            "the most contracts and the most movement"
        )

    mover_lines = [
        f"{mover['underlying']} {mover['expiry']}: open interest "
        f"{_show_pct(mover['oi_change_pct'])} against yesterday on a book of "
        f"{_show_num(mover['open_interest'], 0)} contracts, while the price moved "
        f"{_show_pct(mover['change_pct'])} — {_QUADRANT_GLOSS[mover['quadrant']]}"
        for mover in facts["movers"]
    ]

    curve_lines = [
        f"{curve['underlying']}: {curve['shape']} — {_SHAPE_GLOSS[curve['shape']]}; "
        f"the back of the strip ({curve['back']}) settles "
        f"{_show_pct(curve['spread_pct'])} against the front ({curve['front']}), "
        f"across {curve['expiries']} dated expiries"
        for curve in facts["curves"]
    ]

    if roll["front"] is None:
        roll_lines = [
            "- No expiry could be dated, so how much of the book still sits in the "
            "front month is unknown"
        ]
    else:
        roll_lines = [
            f"- Nearest expiry: {roll['front']}, one of {roll['expiries']} dated expiries "
            "on the board",
            f"- Share of all dated open interest still sitting in that nearest expiry: "
            f"{_show_pct(roll['front_share_pct'], sign=False)}",
        ]

    return {
        "stance": facts["stance"].replace("_", " "),
        "board": "\n".join(board_lines),
        "concentration": _bullet(concentration_lines),
        "quadrants": "\n".join(quadrant_lines),
        "movers": _bullet(mover_lines),
        "curves": _bullet(curve_lines),
        "roll": "\n".join(roll_lines),
        "not_measured": ", ".join(facts["not_measured"]),
    }


async def viop_note(facts: dict[str, Any] | None, user_id: str | None = None) -> dict[str, Any]:
    """The note for this board, or `unavailable` when there is nothing to read."""
    if not facts:
        return unavailable(REASON_INSUFFICIENT_DATA)
    return await get_note(VIOP_SPEC, facts, viop_values(facts), user_id)
