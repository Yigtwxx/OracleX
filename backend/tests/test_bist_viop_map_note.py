"""
The read above the VİOP margin map.

Everything the model is allowed to say is computed here, so this file tests the
computation and never the prose. What carries the weight:

* **The lean is by notional, from the bucketed share.** A field with more long
  cells than short cells is not long-heavy if the short cells are larger, and
  the label must come from the same figure the note quotes.
* **Distances are from the spot close, on the spot axis.** The whole page is a
  fold of three expiries onto one axis; a level quoted in contract terms would
  be a level nobody can find on the chart.
* **A thin or short book produces no facts.** The page declines to draw those,
  and a note narrating a field the page did not draw would be describing
  nothing.
* **`viop_map_values` derives from the facts and from nothing else.** That is
  the contract stopping a cached note from citing a figure that has since
  moved.
"""

import pytest

from services.bist import viop_map_note as m
from services.bist.takasbank_psr import PsrSnapshot, UnderlyingPsr
from services.bist.viop_bulletin import BulletinHistory, BulletinUnavailable, SsfRow
from services.bist.viop_margin_map import MarginCell, MarginMap, build_margin_map


def row(
    day: str,
    *,
    underlying: str = "THYAO",
    expiry: str = "0926",
    settlement: float = 300.0,
    previous: float | None = 298.0,
    weighted: float | None = None,
    open_interest: float = 100_000.0,
    oi_change: float = 1_000.0,
) -> SsfRow:
    return SsfRow(
        day=day,
        contract=f"F_{underlying}{expiry}",
        underlying=underlying,
        expiry=expiry,
        settlement=settlement,
        previous_settlement=previous,
        high=settlement * 1.01,
        low=settlement * 0.99,
        weighted_average=weighted or settlement,
        volume_try=1_000_000.0,
        contracts_traded=100.0,
        open_interest=open_interest,
        open_interest_change=oi_change,
        multiplier=100,
    )


def days(count: int) -> list[str]:
    """`count` consecutive ISO days, oldest first, inside one month."""
    return [f"2026-08-{index + 1:02d}" for index in range(count)]


def psr_snapshot(psr: float = 0.134) -> PsrSnapshot:
    return PsrSnapshot(
        rates={"THYAO": UnderlyingPsr("THYAO", psr, 30_000.0, 100)},
        as_of="20260901",
        run="1",
        created="20260901 20:00",
        source_file="TAKASEOD_20260901-001.zip",
        stored_at=0.0,
    )


def synthetic_map(
    *,
    cells: list[MarginCell],
    sessions: int = 20,
    thin: bool = False,
    price_min: float = 200.0,
    bin_size: float = 2.0,
    bins: int = 100,
) -> MarginMap:
    return MarginMap(
        underlying="THYAO",
        sessions=days(sessions),
        price_min=price_min,
        price_max=price_min + bin_size * bins,
        bin_size=bin_size,
        bins=bins,
        cells=cells,
        max_value=max((cell.long_try + cell.short_try for cell in cells), default=0.0),
        psr=0.134,
        thin=thin,
        open_interest=420_000.0,
        undirected_sessions=2,
        undirected_notional=3_000_000.0,
        basis_carried_sessions=0,
        dropped_sessions=0,
        contract_multiplier=100,
        expiries=["0926", "1226", "0327"],
    )


def cell(column: int, bin_index: int, long_try: float = 0.0, short_try: float = 0.0):
    return MarginCell(column=column, bin_index=bin_index, long_try=long_try, short_try=short_try)


# ── Classification ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("share", "expected"),
    [
        (None, m.STANCE_EMPTY),
        (60.0, m.STANCE_LONG_HEAVY),
        (75.0, m.STANCE_LONG_HEAVY),
        (40.0, m.STANCE_SHORT_HEAVY),
        (10.0, m.STANCE_SHORT_HEAVY),
        (55.0, m.STANCE_BALANCED),
        (45.0, m.STANCE_BALANCED),
    ],
)
def test_the_lean_has_a_deadband_and_an_empty_state(share, expected):
    assert m.classify_map_stance(share) == expected


def test_bucket_never_produces_negative_zero():
    assert str(m._bucket(-0.0001, 0.5)) == "0.0"


# ── Aggregation off a synthetic field ───────────────────────────────────────


def facts_for(board: MarginMap, spot: float = 300.0, rows: list[SsfRow] | None = None):
    closes = dict.fromkeys(board.sessions, spot)
    return m.facts_from_map(
        board,
        rows if rows is not None else [row(board.sessions[-1])],
        closes,
        sessions_requested=120,
        stale=False,
        psr_as_of="20260901",
        psr_run="1",
    )


def test_the_lean_follows_notional_rather_than_cell_count():
    """Three small long cells against one large short cell is a short-heavy
    field, whatever a count of the coloured squares says."""
    board = synthetic_map(
        cells=[
            cell(19, 40, long_try=1_000_000),
            cell(19, 41, long_try=1_000_000),
            cell(19, 42, long_try=1_000_000),
            cell(19, 60, short_try=9_000_000),
        ]
    )
    facts = facts_for(board)
    assert facts is not None
    assert facts["book"]["long_share_pct"] == 25.0
    assert facts["stance"] == m.STANCE_SHORT_HEAVY


def test_only_the_newest_column_is_the_standing_book():
    """Earlier columns are history the map draws as a streak; what stands is
    the last snapshot, and a level swept yesterday must not be counted."""
    board = synthetic_map(
        cells=[
            cell(5, 40, long_try=50_000_000),
            cell(19, 60, short_try=2_000_000),
        ]
    )
    facts = facts_for(board)
    assert facts["book"]["long_try"] == 0.0
    assert facts["stance"] == m.STANCE_SHORT_HEAVY


def test_levels_are_priced_on_the_spot_axis_and_measured_from_the_close():
    # bin 40 on a 200 + 2/bin grid is centred at 281; against a 300 close
    # that is 6.3% below, which the half-point bucket snaps to 6.5.
    board = synthetic_map(cells=[cell(19, 40, long_try=4_000_000)])
    facts = facts_for(board, spot=300.0)
    [level] = facts["levels"]["long"]
    assert level["price"] == 281.0
    assert level["distance_pct"] == -6.5
    assert facts["levels"]["short"] == []


def test_the_heaviest_levels_are_named_nearest_first():
    board = synthetic_map(
        cells=[
            cell(19, 20, long_try=9_000_000),  # far and heavy
            cell(19, 45, long_try=5_000_000),  # near and lighter
            cell(19, 47, long_try=1_000),  # near and negligible
        ]
    )
    facts = facts_for(board)
    named = facts["levels"]["long"]
    assert len(named) == m.LEVELS_PER_SIDE
    assert abs(named[0]["distance_pct"]) < abs(named[1]["distance_pct"])
    assert all(level["notional_try"] >= 5_000_000 for level in named)


def test_an_empty_field_is_a_stance_rather_than_a_missing_read():
    board = synthetic_map(cells=[])
    facts = facts_for(board)
    assert facts is not None
    assert facts["stance"] == m.STANCE_EMPTY
    assert facts["book"]["standing_try"] == 0.0


def test_a_thin_book_produces_no_facts():
    board = synthetic_map(cells=[cell(19, 40, long_try=1_000_000)], thin=True)
    assert facts_for(board) is None


def test_a_short_window_produces_no_facts():
    board = synthetic_map(cells=[cell(3, 40, long_try=1_000_000)], sessions=4)
    assert facts_for(board) is None


def test_no_spot_close_means_no_distances_and_no_facts():
    board = synthetic_map(cells=[cell(19, 40, long_try=1_000_000)])
    facts = m.facts_from_map(
        board, [], {}, sessions_requested=120, stale=False, psr_as_of="x", psr_run="1"
    )
    assert facts is None


def test_the_close_falls_back_to_the_last_session_that_has_one():
    """A basis-carried session has no close of its own; the field was drawn
    through the previous one and the distances should be measured from it."""
    board = synthetic_map(cells=[cell(19, 40, long_try=1_000_000)])
    closes = dict.fromkeys(board.sessions[:-1], 300.0)
    facts = m.facts_from_map(
        board,
        [row(board.sessions[-1])],
        closes,
        sessions_requested=120,
        stale=False,
        psr_as_of="x",
        psr_run="1",
    )
    assert facts["spot"]["close"] == 300.0


def test_the_band_carries_the_three_rungs_the_field_is_drawn_at():
    board = synthetic_map(cells=[cell(19, 40, long_try=1_000_000)])
    facts = facts_for(board)
    assert facts["band"]["psr_pct"] == 13.4
    assert facts["band"]["rungs_pct"] == [4.5, 8.9, 13.4]


# ── The newest session ───────────────────────────────────────────────────────


def test_the_session_is_read_by_the_rule_the_field_places_cohorts():
    latest = "2026-08-20"
    rows = [
        # Open interest up on a rising settlement: long, 1000 × 100 × 310.
        row(latest, expiry="0926", settlement=310.0, previous=300.0, oi_change=1_000),
        # Up on a falling settlement: short.
        row(latest, expiry="1226", settlement=320.0, previous=325.0, oi_change=500),
        # Up on an unchanged settlement: neither side.
        row(latest, expiry="0327", settlement=330.0, previous=330.0, oi_change=200),
    ]
    board = synthetic_map(cells=[cell(19, 40, long_try=1_000_000)])
    facts = facts_for(board, rows=rows)
    session = facts["session"]
    assert session["opened_long_try"] == 31_000_000.0
    assert session["opened_short_try"] == 16_000_000.0
    assert session["undirected_try"] == 6_500_000.0
    assert session["closed_try"] == 0.0
    assert session["oi_change"] == 1_700.0
    # The front month is the one that expires first — `0926`, not `0327`,
    # which sorts first as text and expires six months later.
    assert session["front_settlement_change_pct"] == 3.5


@pytest.mark.parametrize(
    ("labels", "front"),
    [
        (["1226", "0327", "0926"], "0926"),
        (["0327", "0627"], "0327"),
        (["202612", "202703"], "202612"),
    ],
)
def test_the_front_month_is_the_earliest_expiry_rather_than_the_smallest_label(labels, front):
    assert min(labels, key=m.expiry_key) == front


def test_closing_open_interest_places_nothing_but_is_counted():
    latest = "2026-08-20"
    rows = [row(latest, settlement=310.0, previous=300.0, oi_change=-2_000)]
    board = synthetic_map(cells=[cell(19, 40, long_try=1_000_000)])
    session = facts_for(board, rows=rows)["session"]
    assert session["opened_long_try"] == 0.0
    assert session["closed_try"] == 62_000_000.0


def test_a_session_whose_rows_are_missing_is_said_to_be():
    board = synthetic_map(cells=[cell(19, 40, long_try=1_000_000)])
    facts = facts_for(board, rows=[])
    assert facts["session"] is None
    assert "could not be read" in m.viop_map_values(facts)["session"]


# ── The upstreams ────────────────────────────────────────────────────────────


@pytest.fixture
def upstream(monkeypatch):
    """A readable book: twenty sessions of one contract, each opening longs."""
    state = {
        "rows": [
            row(day, settlement=300.0 + index, previous=299.0 + index, open_interest=400_000.0)
            for index, day in enumerate(days(20))
        ],
        "psr": psr_snapshot(),
        "closes": {day: 300.0 + index for index, day in enumerate(days(20))},
        "bulletin_error": None,
        "psr_error": None,
    }

    async def history():
        if state["bulletin_error"]:
            raise state["bulletin_error"]
        return BulletinHistory(rows=state["rows"], holidays=set(), stored_at=0.0)

    async def psr():
        if state["psr_error"]:
            raise state["psr_error"]
        return state["psr"]

    async def candles(ticker, *, range_="1y", interval="1d"):
        return [{"date": day, "close": close} for day, close in state["closes"].items()]

    monkeypatch.setattr(m, "get_history", history)
    monkeypatch.setattr(m, "fetch_psr", psr)
    monkeypatch.setattr(m, "fetch_candles", candles)
    return state


@pytest.mark.asyncio
async def test_the_facts_describe_the_field_the_page_draws(upstream):
    facts = await m.build_viop_map_facts("thyao", 120)
    assert facts is not None
    assert facts["ticker"] == "THYAO"
    assert facts["as_of"] == days(20)[-1]
    assert facts["window"]["covered"] == 20
    assert facts["stance"] == m.STANCE_LONG_HEAVY
    # The same builder the route uses, so the fold and the sweep agree.
    board = build_margin_map(
        upstream["rows"], upstream["psr"], upstream["closes"], underlying="THYAO"
    )
    assert facts["book"]["open_interest"] == m._bucket(board.open_interest, 1000.0)


@pytest.mark.asyncio
async def test_an_unknown_underlying_produces_no_facts_rather_than_an_error(upstream):
    assert await m.build_viop_map_facts("NOPE", 120) is None
    assert await m.build_viop_map_facts("   ", 120) is None


@pytest.mark.asyncio
async def test_a_bulletin_outage_produces_no_facts(upstream):
    upstream["bulletin_error"] = BulletinUnavailable("archive down")
    assert await m.build_viop_map_facts("THYAO", 120) is None


@pytest.mark.asyncio
async def test_a_missing_scan_range_produces_no_facts(upstream):
    """The band is a published number and there is no version of this note
    that substitutes one."""
    upstream["psr"] = PsrSnapshot(
        rates={}, as_of="x", run="1", created="x", source_file="x", stored_at=0.0
    )
    assert await m.build_viop_map_facts("THYAO", 120) is None


@pytest.mark.asyncio
async def test_the_window_is_the_newest_sessions_requested(upstream):
    facts = await m.build_viop_map_facts("THYAO", 30)
    assert facts["window"]["requested"] == 30
    assert facts["window"]["covered"] == 20


@pytest.mark.asyncio
async def test_the_note_refuses_rather_than_narrating_nothing():
    note = await m.viop_map_note(None)
    assert note["status"] == "unavailable"
    assert note["reason"] == "insufficient_data"


# ── Prompt rendering ─────────────────────────────────────────────────────────


def sample_facts(**overrides) -> dict:
    facts = {
        "stance": m.STANCE_LONG_HEAVY,
        "ticker": "THYAO",
        "as_of": "2026-08-31",
        "stale": False,
        "window": {
            "requested": 120,
            "covered": 118,
            "undirected_sessions": 6,
            "undirected_try": 34_000_000.0,
            "basis_carried_sessions": 2,
            "dropped_sessions": 1,
        },
        "band": {"psr_pct": 13.4, "rungs_pct": [4.5, 8.9, 13.4], "as_of": "20260901", "run": "1"},
        "book": {
            "open_interest": 421_000.0,
            "expiries": 3,
            "standing_try": 26_000_000_000.0,
            "long_try": 17_000_000_000.0,
            "short_try": 9_000_000_000.0,
            "long_share_pct": 65.0,
        },
        "spot": {"close": 302.25},
        "levels": {
            "long": [{"price": 285.64, "distance_pct": -5.5, "notional_try": 1_477_500_000.0}],
            "short": [{"price": 356.81, "distance_pct": 18.0, "notional_try": 1_906_000_000.0}],
        },
        "session": {
            "day": "2026-08-31",
            "opened_long_try": 0.0,
            "opened_short_try": 1_226_000_000.0,
            "undirected_try": 0.0,
            "closed_try": 937_500_000.0,
            "oi_change": 8_500.0,
            "front_settlement_change_pct": -1.5,
        },
        "not_measured": list(m.NOT_MEASURED),
    }
    facts.update(overrides)
    return facts


def test_values_fill_every_placeholder_the_prompt_declares():
    from services.prompts import load_prompt

    template = load_prompt("notes/bist_viop_map")
    values = m.viop_map_values(sample_facts())
    for key in values:
        assert f"{{{{{key}}}}}" in template, f"{key} is rendered but never used"
    for key in ("ticker", "stance", "band", "window", "book", "levels", "session", "not_measured"):
        assert key in values


def test_the_band_is_named_as_not_a_margin_call():
    band = m.viop_map_values(sample_facts())["band"]
    assert "NOT a margin call" in band
    assert "13.4%" in band
    assert "4.5%, 8.9%, 13.4%" in band


def test_levels_quote_price_distance_and_notional_in_the_legend_unit():
    levels = m.viop_map_values(sample_facts())["levels"]
    assert "285.64" in levels
    assert "-5.5%" in levels
    assert "1,477.5M TRY" in levels
    assert "SHORT side, nearest short band: 356.81" in levels


def test_the_short_share_is_stated_rather_than_left_to_arithmetic():
    """The model given only the long share wrote a 45% long book up as
    long-dominated; the complement on the same line is what stops that."""
    book = m.viop_map_values(sample_facts())["book"]
    assert "Long side's share of what stands: 65.0%; short side's share: 35.0%" in book


def test_two_levels_on_one_side_are_ranked_in_words():
    facts = sample_facts()
    facts["levels"]["long"] = [
        {"price": 285.64, "distance_pct": -5.5, "notional_try": 1_477_500_000.0},
        {"price": 268.78, "distance_pct": -11.0, "notional_try": 1_159_000_000.0},
    ]
    levels = m.viop_map_values(facts)["levels"]
    assert "LONG side, nearest long band: 285.64" in levels
    assert "LONG side, next long band: 268.78" in levels


def test_partial_windows_are_named_only_when_partial():
    full = m.viop_map_values(
        sample_facts(
            window={
                "requested": 120,
                "covered": 120,
                "undirected_sessions": 0,
                "undirected_try": 0.0,
                "basis_carried_sessions": 0,
                "dropped_sessions": 0,
            }
        )
    )["window"]
    assert "carried-forward" not in full
    assert "dropped" not in full

    partial = m.viop_map_values(sample_facts())["window"]
    assert "carried-forward basis" in partial
    assert "dropped for want of any basis: 1" in partial


def test_the_stance_carries_its_gloss():
    assert "below the spot price" in m.viop_map_values(sample_facts())["stance"]
    empty = m.viop_map_values(sample_facts(stance=m.STANCE_EMPTY))["stance"]
    assert "traded through" in empty
