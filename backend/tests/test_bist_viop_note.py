"""
The board-wide read above the VİOP page.

Everything the model is allowed to say is computed here, so this file tests the
computation and never the prose. Four properties carry most of the weight:

* **The expiry parser.** Two panels order contracts by time, and `31 Ağu 26`
  sorts alphabetically into a term structure that does not exist. A month
  abbreviation that stopped being recognised would not raise — it would quietly
  empty the curve.
* **Weight is not count.** The stance follows how much open interest moved, not
  how many contracts moved, because one index strip outweighs forty single-stock
  books. A regression to counting would be invisible on a calm day and wrong on
  every busy one.
* **Bucketing.** The board is cached for five minutes and the page polls it, so
  a fingerprint that moved on every refresh would run a local model forever.
* **`viop_values` derives from the facts and from nothing else.** That is the
  contract stopping a cached note from citing a figure that has since moved, and
  it is invisible in review — a builder reaching past its argument would look
  identical.
"""

import pytest

from services.bist import viop_note as v
from services.bist.viop_service import (
    KIND_CALL,
    KIND_FUTURE,
    KIND_PUT,
    ViopBoard,
    ViopContract,
    parse_expiry,
    parse_kind,
)


def contract(
    underlying: str = "AAA",
    *,
    expiry: str = "31 Ağu 26",
    open_interest: float | None = 10_000.0,
    open_interest_change: float | None = 500.0,
    change_pct: float | None = 0.01,
    settlement: float | None = 100.0,
    physical: bool = False,
    kind: str = KIND_FUTURE,
) -> ViopContract:
    return ViopContract(
        contract=f"{underlying} ({expiry}) Vadeli",
        underlying=underlying,
        expiry=expiry,
        physical=physical,
        last=100.0,
        change_pct=change_pct,
        high=None,
        low=None,
        open_interest=open_interest,
        open_interest_change=open_interest_change,
        settlement=settlement,
        previous_settlement=None,
        traded_at="18:10",
        expiry_date=parse_expiry(expiry),
        kind=kind,
    )


def strip(underlying: str, *months: tuple[str, float]) -> list[ViopContract]:
    """One underlying across several expiries, each with its own settlement."""
    return [
        contract(underlying, expiry=expiry, settlement=settlement) for expiry, settlement in months
    ]


# ── The expiry parser ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("31 Ağu 26", "2026-08-31"),
        ("30 Eki 26", "2026-10-30"),
        ("31 Ara 2026", "2026-12-31"),
        ("31 Ağustos 26", "2026-08-31"),
        ("29 Şub 24", "2024-02-29"),
    ],
)
def test_a_turkish_expiry_label_becomes_an_iso_day(raw, expected):
    assert parse_expiry(raw) == expected


def test_a_month_whose_byte_the_source_destroyed_is_still_read():
    """The broker double-encodes this cell and then replaces the byte its own
    decoder cannot read, so `Ş` arrives as `Å` plus a replacement character and
    nothing on this side can re-decode it. Stripped to ASCII the twelve months
    are still twelve distinct strings, which is what rescues USDTRY's February
    contract from falling off the term-structure curve."""
    assert parse_expiry("26 Å\ufffdub 27") == "2027-02-26"
    assert parse_expiry("31 A\ufffdu 26") == "2026-08-31"


def test_the_fold_never_reinterprets_a_label_that_was_already_readable():
    """The exact table runs first, so an ordinary row can never take the fuzzy
    path — which is the only thing keeping the fallback from being a licence to
    guess."""
    assert parse_expiry("31 May 26") == "2026-05-31"
    assert parse_expiry("31 Mar 26") == "2026-03-31"


@pytest.mark.parametrize("raw", ["31 Nis 26", "29 Şub 26", "30 Xyz 26", "202612", "", "   "])
def test_an_unreadable_expiry_is_none_rather_than_a_guess(raw):
    """A contract placed on the wrong month of a curve does not look like
    missing data — it looks like a market in backwardation."""
    assert parse_expiry(raw) is None


def test_expiries_order_by_date_and_not_alphabetically():
    """Ağustos before Eylül before Ekim is the calendar; `A`, `E`, `E` is the
    string, and sorting on the label puts October before September."""
    labels = ["30 Eki 26", "31 Ağu 26", "30 Eyl 26"]
    assert sorted(labels) != labels[::-1]
    assert sorted(parse_expiry(label) or "" for label in labels) == [
        "2026-08-31",
        "2026-09-30",
        "2026-10-30",
    ]


# ── Futures against options ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [
        ("Vadeli", KIND_FUTURE),
        ("Vadeli FIZ.", KIND_FUTURE),
        ("Alim opsiyonu", KIND_CALL),
        ("Alım opsiyonu", KIND_CALL),
        ("Satim opsiyonu FIZ.", KIND_PUT),
        ("SATIM OPSİYONU", KIND_PUT),
    ],
)
def test_the_instrument_is_read_off_the_label(suffix, expected):
    """The page writes `Alim` with a plain `i` today and `Alım` is the correct
    spelling, so a rule keyed on either alone stops working the day the upstream
    fixes its own typography."""
    assert parse_kind(suffix) == expected


def test_an_unrecognised_suffix_is_a_future_rather_than_a_dropped_row():
    """A row dropped for an unknown label would take its open interest out of
    the board's totals silently, which is worse than calling a futures variant a
    future."""
    assert parse_kind("Vadeli Yeni") == KIND_FUTURE
    assert parse_kind("") == KIND_FUTURE


# ── Quantization ─────────────────────────────────────────────────────────────


def test_bucket_snaps_to_the_step():
    assert v._bucket(1.23, 0.5) == 1.0
    assert v._bucket(1.30, 0.5) == 1.5
    assert v._bucket(None, 0.5) is None


def test_bucket_never_produces_negative_zero():
    """ "-0.0%" is harmless arithmetic and a sentence claiming a book shrank by
    negative zero."""
    value = v._bucket(-0.0001, 0.5)
    assert value == 0.0
    assert f"{value:+.1f}" == "+0.0"


def test_a_timestamp_is_quantized_to_the_day_before_it_is_fingerprinted():
    assert v._day("2026-08-28T11:08:49.967350+00:00") == "2026-08-28"
    assert v._day(None) is None


# ── Quadrants ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("oi_change", "change_pct", "expected"),
    [
        (500.0, 0.02, "long_build"),
        (500.0, -0.02, "short_build"),
        (-500.0, 0.02, "short_cover"),
        (-500.0, -0.02, "long_liquidation"),
        (0.0, 0.02, None),
        (500.0, 0.0, None),
        (None, 0.02, None),
        (500.0, None, None),
    ],
)
def test_quadrant_matches_the_rule_the_scatter_draws(oi_change, change_pct, expected):
    """Mirrors `viopQuadrantOf` in `frontend/lib/bist-viop.ts`. A contract
    sitting on an axis has no read, and rounding it into the nearest quadrant
    would invent a direction the market did not express."""
    row = contract(open_interest_change=oi_change, change_pct=change_pct)
    assert v.quadrant_of(row) == expected


def test_the_stance_follows_the_flow_rather_than_the_headcount():
    """Forty single-stock contracts opening a hundred lots each is a different
    day from one index strip opening fifty thousand, and a count calls the first
    the larger event."""
    contracts = [
        contract(f"S{i}", open_interest_change=100.0, change_pct=-0.01) for i in range(40)
    ] + [contract("XU030", open_interest_change=50_000.0, change_pct=0.02)]

    quadrants = v._quadrants(contracts)
    assert quadrants["counts"]["short_build"] == 40
    assert quadrants["counts"]["long_build"] == 1
    assert v.classify_viop_stance(quadrants["weight_pct"]) == "long_build"


def test_a_board_with_no_direction_is_mixed_rather_than_the_largest_pile():
    """A session where three quadrants each carry a third has no direction to
    name, and picking the biggest of them would state one."""
    weights = {"long_build": 35.0, "short_build": 35.0, "short_cover": 30.0}
    assert v.classify_viop_stance(weights) == v.STANCE_MIXED
    assert v.classify_viop_stance({"long_build": v.DOMINANCE_PCT}) == "long_build"
    assert v.classify_viop_stance(dict.fromkeys(v.QUADRANTS, None)) == v.STANCE_MIXED


def test_contracts_on_an_axis_are_counted_rather_than_dropped():
    """They are the board saying nothing about who opened what, which is a
    reading — a note describing forty contracts it never saw is not."""
    quadrants = v._quadrants([contract(open_interest_change=0.0), contract()])
    assert quadrants["on_axis"] == 1
    assert quadrants["measured"] == 1


# ── Concentration ────────────────────────────────────────────────────────────


def test_one_underlying_carrying_the_book_is_the_finding():
    """USDTRY and the index routinely hold most of the outstanding interest, so
    a board-wide growth figure is largely one contract's."""
    contracts = [contract("USDTRY", open_interest=900_000.0)] + [
        contract(f"S{i}", open_interest=10_000.0) for i in range(5)
    ]
    concentration = v._concentration(contracts)

    assert concentration["top"][0]["underlying"] == "USDTRY"
    assert concentration["concentrated"] is True

    spread = v._concentration([contract(f"S{i}", open_interest=10_000.0) for i in range(5)])
    assert spread["concentrated"] is False


def test_an_unpublished_open_interest_column_is_not_a_name_nobody_holds():
    """`summarise` flattens the distinction back to zero for payload reasons of
    its own; ranking a silent contract as an empty one would state something the
    board never said."""
    contracts = [contract("AAA", open_interest=None), contract("BBB", open_interest=5_000.0)]
    top = v._concentration(contracts)["top"]
    assert [entry["underlying"] for entry in top] == ["BBB"]


# ── Term structure ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("spread", "expected"),
    [
        (4.0, v.SHAPE_CONTANGO),
        (-4.0, v.SHAPE_BACKWARDATION),
        (0.0, v.SHAPE_FLAT),
        (v.FLAT_SPREAD_PCT - 0.1, v.SHAPE_FLAT),
        (None, v.SHAPE_FLAT),
    ],
)
def test_a_curve_inside_the_deadband_is_flat_rather_than_a_term_structure(spread, expected):
    assert v.classify_curve(spread) == expected


def test_the_curve_reads_the_back_of_the_strip_against_its_front_by_date():
    """The point of parsing the expiry at all: on the label alone the October
    contract would sort ahead of the September one and invert the curve."""
    curve = v._curve_for(strip("XU030", ("30 Eki 26", 110.0), ("31 Ağu 26", 100.0)))

    assert curve["front"] == "2026-08-31"
    assert curve["back"] == "2026-10-30"
    assert curve["spread_pct"] == 10.0
    assert curve["shape"] == v.SHAPE_CONTANGO


def test_a_single_expiry_has_no_term_structure():
    assert v._curve_for(strip("AAA", ("31 Ağu 26", 100.0))) is None


def test_an_undated_strip_is_dropped_rather_than_ordered_by_label():
    assert v._curve_for(strip("AAA", ("202608", 100.0), ("202610", 110.0))) is None


# ── The roll ─────────────────────────────────────────────────────────────────


def test_the_roll_measures_what_is_still_in_the_nearest_expiry():
    """The same total a fortnight later with a small front share is a different
    set of positions at the same size."""
    contracts = [
        contract("AAA", expiry="31 Ağu 26", open_interest=7_500.0),
        contract("AAA", expiry="30 Eki 26", open_interest=2_500.0),
    ]
    roll = v._roll(contracts)

    assert roll["front"] == "2026-08-31"
    assert roll["front_share_pct"] == 75.0
    assert roll["expiries"] == 2


def test_an_undated_board_says_the_roll_is_unknown():
    assert v._roll([contract(expiry="202608")])["front"] is None


# ── The board ────────────────────────────────────────────────────────────────


@pytest.fixture
def upstream(monkeypatch):
    """A readable board: one large currency strip and a spread of stock books."""
    state = {
        "contracts": (
            strip("USDTRY", ("31 Ağu 26", 100.0), ("30 Eki 26", 104.0))
            + [contract(f"S{i}", open_interest=5_000.0) for i in range(14)]
        ),
        "stale": False,
    }

    async def viop_board():
        return ViopBoard(
            contracts=state["contracts"],
            as_of="2026-08-28T11:08:49.967350+00:00",
            stale=state["stale"],
        )

    monkeypatch.setattr(v, "fetch_viop_board", viop_board)
    return state


@pytest.mark.asyncio
async def test_a_board_too_thin_to_characterise_produces_no_facts(upstream):
    """This source is a scrape. Silence here is far more often a half-parsed
    page than a quiet session, and the two must not render the same."""
    upstream["contracts"] = [contract()]
    assert await v.build_viop_facts() is None


@pytest.mark.asyncio
async def test_a_price_board_without_open_interest_is_not_a_positioning_board(upstream):
    upstream["contracts"] = [
        contract(f"S{i}", open_interest=None, open_interest_change=None) for i in range(20)
    ]
    assert await v.build_viop_facts() is None


@pytest.mark.asyncio
async def test_a_viop_outage_produces_no_facts_rather_than_an_empty_board(upstream):
    from services.bist.viop_service import ViopUnavailable

    async def down():
        raise ViopUnavailable("scrape failed")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(v, "fetch_viop_board", down)
    try:
        assert await v.build_viop_facts() is None
    finally:
        monkeypatch.undo()


@pytest.mark.asyncio
async def test_options_are_set_aside_and_counted_rather_than_summed_in(upstream):
    """A put on the same underlying and expiry settles at its premium — 0.13
    where the future settles at 13.16. Summed they add two unrelated books into
    one total; drawn on one axis they invert the curve."""
    upstream["contracts"] = upstream["contracts"] + [
        contract("USDTRY", expiry="30 Eki 26", settlement=0.13, kind=KIND_PUT),
        contract("USDTRY", expiry="30 Eki 26", settlement=0.09, kind=KIND_CALL),
    ]
    facts = await v.build_viop_facts()

    assert facts["board"]["options_set_aside"] == 2
    # The curve is the reading an option would wreck outright.
    assert facts["curves"][0]["shape"] == v.SHAPE_CONTANGO
    assert facts["curves"][0]["spread_pct"] == 4.0


@pytest.mark.asyncio
async def test_a_board_that_is_all_options_has_no_futures_read(upstream):
    upstream["contracts"] = [contract(f"S{i}", kind=KIND_PUT) for i in range(20)]
    assert await v.build_viop_facts() is None


@pytest.mark.asyncio
async def test_the_facts_carry_the_board_the_panels_draw(upstream):
    facts = await v.build_viop_facts()

    assert facts["as_of"] == "2026-08-28"
    assert facts["board"]["contracts"] == 16
    assert facts["board"]["underlyings"] == 15
    assert facts["curves"][0]["shape"] == v.SHAPE_CONTANGO
    assert facts["roll"]["front"] == "2026-08-31"


@pytest.mark.asyncio
async def test_growth_is_measured_against_yesterdays_book(upstream):
    """Dividing by today's total would already contain the move, understating a
    build and overstating a liquidation."""
    upstream["contracts"] = [
        contract(f"S{i}", open_interest=11_000.0, open_interest_change=1_000.0) for i in range(20)
    ]
    facts = await v.build_viop_facts()
    assert facts["board"]["growth_pct"] == 10.0


@pytest.mark.asyncio
async def test_silent_contracts_are_counted_apart_from_measured_ones(upstream):
    upstream["contracts"] = [contract(f"S{i}") for i in range(14)] + [
        contract(f"Q{i}", open_interest=None) for i in range(4)
    ]
    facts = await v.build_viop_facts()

    assert facts["board"]["measured"] == 14
    assert facts["board"]["silent"] == 4


@pytest.mark.asyncio
async def test_a_small_move_does_not_retire_the_note(upstream):
    """The property that keeps a local model from writing derivatives commentary
    forever — the board is cached for five minutes and the page polls it."""
    from services.ai_notes import fingerprint

    before = await v.build_viop_facts()
    upstream["contracts"] = strip("USDTRY", ("31 Ağu 26", 100.2), ("30 Eki 26", 104.1)) + [
        contract(f"S{i}", open_interest=5_010.0, open_interest_change=503.0, change_pct=0.0102)
        for i in range(14)
    ]
    after = await v.build_viop_facts()

    assert fingerprint(v.VIOP_SPEC, before) == fingerprint(v.VIOP_SPEC, after)


# ── The refusal path ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_note_refuses_rather_than_narrating_nothing():
    result = await v.viop_note(None)
    assert result["status"] == "unavailable"
    assert result["reason"] == "insufficient_data"
    assert result["note"] is None


# ── Rendering ────────────────────────────────────────────────────────────────


def sample_facts(**overrides) -> dict:
    facts = {
        "stance": "long_build",
        "as_of": "2026-08-28",
        "stale": False,
        "board": {
            "contracts": 148,
            "underlyings": 42,
            "measured": 130,
            "silent": 18,
            "undated": 0,
            "total_open_interest": 1_842_000.0,
            "open_interest_change": 36_000.0,
            "growth_pct": 2.0,
            "physical_pct": 25.0,
            "options_set_aside": 10,
        },
        "concentration": {
            "top": [
                {
                    "underlying": "USDTRY",
                    "open_interest": 1_100_000.0,
                    "share_pct": 60.0,
                    "oi_change_pct": 3.0,
                    "expiries": 6,
                },
                {
                    "underlying": "XU030",
                    "open_interest": 420_000.0,
                    "share_pct": 22.0,
                    "oi_change_pct": -1.0,
                    "expiries": 3,
                },
            ],
            "top_share_pct": 60.0,
            "concentrated": True,
        },
        "quadrants": {
            "counts": {
                "long_build": 40,
                "short_build": 22,
                "short_cover": 18,
                "long_liquidation": 30,
            },
            "weight_pct": {
                "long_build": 55.0,
                "short_build": 15.0,
                "short_cover": 10.0,
                "long_liquidation": 20.0,
            },
            "on_axis": 38,
            "measured": 110,
            "busiest": "long_build",
        },
        "movers": [
            {
                "underlying": "THYAO",
                "expiry": "31 Eki 26",
                "quadrant": "long_build",
                "oi_change_pct": 25.0,
                "change_pct": 2.5,
                "open_interest": 18_000.0,
            }
        ],
        "curves": [
            {
                "underlying": "USDTRY",
                "shape": v.SHAPE_CONTANGO,
                "spread_pct": 12.0,
                "expiries": 6,
                "front": "2026-08-31",
                "back": "2027-02-26",
            }
        ],
        "roll": {"front": "2026-08-31", "front_share_pct": 65.0, "expiries": 7},
        "not_measured": list(v.NOT_MEASURED),
    }
    facts.update(overrides)
    return facts


def test_values_fill_every_placeholder_the_prompt_declares():
    from services.prompts import load_prompt

    template = load_prompt("notes/bist_viop")
    values = v.viop_values(sample_facts())
    for key in values:
        assert f"{{{{{key}}}}}" in template, f"{key} is rendered but never used"


def test_every_quadrant_carries_both_its_count_and_its_weight():
    """The two disagree constantly on this board, and the disagreement is the
    finding — a block carrying only counts would hide it."""
    values = v.viop_values(sample_facts())
    assert "40 contracts" in values["quadrants"]
    assert "55.0% of the day's open-interest movement" in values["quadrants"]


def test_the_headcount_and_the_flow_are_compared_in_python():
    """The first thing a model does with two competing rankings is pick the one
    with the larger integers. Given 26 short-side contracts against a long side
    carrying 55% of the movement, it wrote the board up as short and
    contradicted the stance it had been told to explain."""
    facts = sample_facts()
    facts["quadrants"] = {**facts["quadrants"], "busiest": "long_liquidation"}
    values = v.viop_values(facts)

    assert "headcount and the flow disagree" in values["quadrants"]
    assert "the stance follows the flow" in values["quadrants"]


def test_an_agreeing_board_says_that_instead_of_a_warning():
    values = v.viop_values(sample_facts())
    assert "headcount and the flow agree" in values["quadrants"]


def test_a_tied_headcount_has_no_leader_to_compare_against():
    facts = sample_facts()
    facts["quadrants"] = {**facts["quadrants"], "busiest": None}
    assert "no leader to compare" in v.viop_values(facts)["quadrants"]


def test_the_busiest_quadrant_is_a_strict_winner_or_nothing():
    """ "The board is leaning long" said about a two-two split is a claim the
    counts do not support."""
    tied = [
        contract("A", open_interest_change=500.0, change_pct=0.01),
        contract("B", open_interest_change=500.0, change_pct=-0.01),
    ]
    assert v._quadrants(tied)["busiest"] is None
    assert v._quadrants([contract()])["busiest"] == "long_build"


def test_a_concentrated_book_says_so():
    concentrated = v.viop_values(sample_facts())
    assert "one underlying carries most" in concentrated["concentration"]

    facts = sample_facts()
    facts["concentration"] = {**facts["concentration"], "concentrated": False}
    assert "one underlying carries most" not in v.viop_values(facts)["concentration"]


def test_an_empty_open_interest_column_is_described_as_unread():
    """Rendering it as a position of zero is the one reading the facts must not
    let the model take."""
    values = v.viop_values(sample_facts())
    assert "not a position of zero" in values["board"]


def test_set_aside_options_are_named_only_when_there_are_some():
    """A note silent about them would present a futures-only total as the whole
    board's."""
    values = v.viop_values(sample_facts())
    assert "Option contracts on the same board" in values["board"]

    facts = sample_facts()
    facts["board"] = {**facts["board"], "options_set_aside": 0}
    assert "Option contracts on the same board" not in v.viop_values(facts)["board"]


def test_undated_contracts_are_named_only_when_there_are_some():
    facts = sample_facts()
    facts["board"] = {**facts["board"], "undated": 6}
    assert "could not be read" in v.viop_values(facts)["board"]
    assert "could not be read" not in v.viop_values(sample_facts())["board"]


def test_an_undated_board_states_the_roll_is_unknown_rather_than_omitting_it():
    facts = sample_facts()
    facts["roll"] = {"front": None, "front_share_pct": None, "expiries": 0}
    assert "unknown" in v.viop_values(facts)["roll"]


def test_a_board_with_no_curve_renders_an_explicit_nothing():
    """`_bullet` answering "- none" is what keeps the placeholder from
    collapsing into an empty section the model reads as an omission."""
    assert v.viop_values(sample_facts(curves=[]))["curves"] == "- none"
