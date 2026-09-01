"""
The market-wide read above the Konumlanma board.

Everything the model is allowed to say is computed here, so this file tests the
computation and never the prose. Three properties carry most of the weight:

* **Bucketing.** The equity board refreshes every two minutes and this board is
  derived from it, so a fingerprint that moved on every poll would run a local
  model continuously. The tests asserting an unchanged fingerprint across a small
  price move are what keep that from silently regressing.
* **`positioning_values` derives from the facts and from nothing else.** That is
  the contract stopping a cached note from citing a figure that has since moved,
  and it is invisible in review — a builder reaching past its argument would look
  identical.
* **The quadrant rule matches the frontend's.** The paragraph and the chart under
  it must count the same names; two definitions written a fortnight apart are how
  they stop doing that.
"""

import asyncio

import pytest

from services import ai_notes, analysis_jobs
from services.bist import positioning_note as p
from services.bist.equity_service import EquityBoard
from services.bist.positioning_service import PositioningRow
from services.bist.tradingview_client import EquityRow
from services.bist.viop_service import ViopBoard, ViopContract


def row(
    ticker: str = "AAA",
    *,
    price: float = 100.0,
    change_pct: float | None = 0.01,
    free_float_pct: float | None = 0.30,
    relative_volume: float | None = 1.5,
    week52_low: float | None = 50.0,
    week52_high: float | None = 150.0,
    rsi: float | None = 55.0,
    sector: str = "Finans",
) -> EquityRow:
    return EquityRow(
        ticker=ticker,
        symbol=f"BIST:{ticker}",
        name=ticker,
        price=price,
        change_pct=change_pct,
        change_abs=None,
        volume=None,
        traded_value=1_000.0,
        market_cap=1_000.0,
        pe=8.0,
        pb=1.2,
        ev_ebitda=None,
        free_float_pct=free_float_pct,
        sector=sector,
        week52_high=week52_high,
        week52_low=week52_low,
        rsi=rsi,
        relative_volume=relative_volume,
    )


def positioned(
    ticker: str = "AAA",
    *,
    crowding: float | None = 10.0,
    free_float_pct: float | None = 0.30,
    relative_volume: float | None = 1.5,
    range_position: float | None = 0.5,
    change_pct: float | None = 0.01,
    open_interest: float | None = None,
    open_interest_change: float | None = None,
    sector: str = "Finans",
) -> PositioningRow:
    return PositioningRow(
        ticker=ticker,
        symbol=f"BIST:{ticker}",
        name=ticker,
        sector=sector,
        price=100.0,
        change_pct=change_pct,
        market_cap=1_000.0,
        free_float_pct=free_float_pct,
        relative_volume=relative_volume,
        range_position=range_position,
        beta=1.0,
        rsi=55.0,
        open_interest=open_interest,
        open_interest_change=open_interest_change,
        crowding=crowding,
    )


def contract(
    underlying: str = "AAA",
    *,
    open_interest: float | None = 10_000.0,
    open_interest_change: float | None = 500.0,
) -> ViopContract:
    return ViopContract(
        contract=f"F_{underlying}",
        underlying=underlying,
        expiry="202612",
        physical=False,
        last=100.0,
        change_pct=0.01,
        high=None,
        low=None,
        open_interest=open_interest,
        open_interest_change=open_interest_change,
        settlement=None,
        previous_settlement=None,
        traded_at="2026-08-28",
    )


# ── Quantization ─────────────────────────────────────────────────────────────


def test_bucket_snaps_to_the_step():
    assert p._bucket(1.23, 0.5) == 1.0
    assert p._bucket(1.30, 0.5) == 1.5
    assert p._bucket(None, 0.5) is None


def test_bucket_never_produces_negative_zero():
    """ "-0.0%" is harmless arithmetic and a sentence claiming a board fell by
    negative zero."""
    value = p._bucket(-0.0001, 0.5)
    assert value == 0.0
    assert f"{value:+.1f}" == "+0.0"


def test_a_cohort_is_carried_as_a_bucketed_share_not_as_a_count():
    """A count of names near their highs moves by one on every poll, and a raw
    count in the fingerprint would rewrite the note all session for a change no
    reader could see."""
    assert p._share_bucket(23, 500) == 4.0
    assert p._share_bucket(24, 500) == 4.0
    assert p._share_bucket(0, 0) is None


def test_a_timestamp_is_quantized_to_the_day_before_it_is_fingerprinted():
    assert p._day("2026-08-28T11:08:49.967350+00:00") == "2026-08-28"
    assert p._day(None) is None


# ── Stance ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("head_pct", "board_pct", "expected"),
    [
        (80.0, 50.0, p.STANCE_CHASING_STRENGTH),
        (20.0, 50.0, p.STANCE_BOTTOM_FISHING),
        (55.0, 50.0, p.STANCE_DISPERSED),
        (50.0, 50.0, p.STANCE_DISPERSED),
        (None, 50.0, p.STANCE_DISPERSED),
    ],
)
def test_stance_reads_the_crowd_against_the_board(head_pct, board_pct, expected):
    assert p.classify_positioning_stance(head_pct, board_pct) == expected


def test_a_gap_inside_the_deadband_is_not_a_behaviour():
    """Range position is bucketed to five points, so a stance that flipped on a
    smaller gap would be flipping on quantization alone."""
    assert p.classify_positioning_stance(50.0 + p.RANGE_GAP_PCT - 1, 50.0) == p.STANCE_DISPERSED
    assert p.classify_positioning_stance(50.0 + p.RANGE_GAP_PCT, 50.0) == p.STANCE_CHASING_STRENGTH


# ── Futures quadrants ────────────────────────────────────────────────────────


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
    ],
)
def test_quadrant_matches_the_rule_the_chart_draws(oi_change, change_pct, expected):
    """Mirrors `quadrantOf` in `frontend/lib/bist-positioning.ts`. A name sitting
    on an axis has no read, and rounding it into the nearest quadrant would
    invent a direction the market did not express."""
    contract_row = positioned(open_interest_change=oi_change, change_pct=change_pct)
    assert p.quadrant_of(contract_row) == expected


def test_a_tie_has_no_dominant_quadrant():
    """ "The board is leaning long" said about a two-two split is a claim the
    counts do not support."""
    assert p._dominant({"long_build": 3, "short_build": 3}) is None
    assert p._dominant({"long_build": 4, "short_build": 3}) == "long_build"
    assert p._dominant(dict.fromkeys(p.QUADRANTS, 0)) is None


# ── Sector aggregation ───────────────────────────────────────────────────────


def test_thin_sectors_are_dropped_rather_than_ranked():
    """A tile built from one busy name puts that name's story under a sector's
    label — the reading a treemap makes easiest to misread."""
    rows = [positioned(f"BIG{i}", sector="Finans") for i in range(p.MIN_SECTOR_MEMBERS)]
    rows.append(positioned("SOLO", sector="Turizm", crowding=900.0))

    assert {entry["sector"] for entry in p._sectors(rows)} == {"Finans"}


def test_sector_shares_are_of_the_boards_whole_crowding():
    heavy = [positioned(f"H{i}", sector="Finans", crowding=30.0) for i in range(3)]
    light = [positioned(f"L{i}", sector="Sanayi", crowding=10.0) for i in range(3)]

    entries = {entry["sector"]: entry for entry in p._sectors(heavy + light)}
    assert entries["Finans"]["share_pct"] == 76.0
    assert entries["Sanayi"]["share_pct"] == 24.0


# ── Futures aggregation ──────────────────────────────────────────────────────


def test_open_interest_growth_is_measured_against_yesterdays_book():
    """Dividing by today's total would already contain the move, understating a
    build and overstating a liquidation."""
    rows = [positioned("AAA", open_interest=11_000.0, open_interest_change=1_000.0)]
    futures = p._futures(rows, has_data=True)
    assert futures["growth_pct"] == 10.0


def test_futures_are_dropped_rather_than_guessed_when_viop_is_down():
    assert p._futures([positioned()], has_data=False) is None


def test_names_without_futures_do_not_enter_the_futures_block():
    assert p._futures([positioned(open_interest=None)], has_data=True) is None


# ── The board ────────────────────────────────────────────────────────────────


def board(
    equities: list[EquityRow], as_of: str = "2026-08-28T11:08:49.967350+00:00"
) -> EquityBoard:
    return EquityBoard(equities=equities, indices=[], stale=False, as_of=as_of)


@pytest.fixture
def upstream(monkeypatch):
    """A readable board of a hundred names, half of them near their highs."""
    state = {
        "equities": [
            row(
                f"A{i}",
                price=145.0 if i < 50 else 55.0,
                relative_volume=3.0 if i < 20 else 1.2,
                free_float_pct=0.10 if i < 20 else 0.40,
            )
            for i in range(100)
        ],
        "contracts": [contract("A0"), contract("A1", open_interest_change=-200.0)],
    }

    async def equity_board():
        return board(state["equities"])

    async def viop_board():
        return ViopBoard(contracts=state["contracts"], as_of="2026-08-28", stale=False)

    monkeypatch.setattr(p, "fetch_equity_board", equity_board)
    monkeypatch.setattr(p, "fetch_viop_board", viop_board)
    return state


@pytest.mark.asyncio
async def test_a_board_too_thin_to_characterise_produces_no_facts(monkeypatch):
    """ "Nothing is happening" and "we cannot see what is happening" are
    different claims, and only the second is a missing note."""

    async def thin():
        return board([row("A")])

    monkeypatch.setattr(p, "fetch_equity_board", thin)
    assert await p.build_positioning_facts() is None


@pytest.mark.asyncio
async def test_the_facts_read_the_crowd_against_the_whole_board(upstream):
    facts = await p.build_positioning_facts()

    # The busiest twenty are the ones priced at their highs, so the crowd sits
    # above the board — the read no panel on the page can produce.
    assert facts["stance"] == p.STANCE_CHASING_STRENGTH
    assert facts["crowd"]["median_range_pct"] > facts["crowd"]["board_median_range_pct"]
    assert facts["board"]["total"] == 100


@pytest.mark.asyncio
async def test_the_unscored_are_split_by_why_they_carry_no_score(upstream):
    """Both floors are deliberate refusals rather than gaps, and a reader told
    only that a hundred names are unscored would read it as missing data."""
    upstream["equities"] = (
        [row(f"T{i}", free_float_pct=0.01) for i in range(60)]
        + [row(f"Q{i}", relative_volume=0.4) for i in range(60)]
        + [row(f"OK{i}") for i in range(20)]
    )
    facts = await p.build_positioning_facts()

    assert facts["board"]["unscored_tight_float"] == 60
    assert facts["board"]["unscored_quiet"] == 60
    assert facts["board"]["scored"] == 20


@pytest.mark.asyncio
async def test_a_viop_outage_costs_a_fact_and_names_itself(upstream):
    upstream["contracts"] = []
    facts = await p.build_positioning_facts()

    assert facts["futures"] is None
    assert "VİOP açık pozisyonu" in facts["not_measured"]


@pytest.mark.asyncio
async def test_the_fund_holdings_caveat_is_carried_into_the_facts(upstream):
    """The page's whole premise. A paragraph about "who is positioned" that
    stayed silent about it would claim a completeness the data does not have."""
    facts = await p.build_positioning_facts()
    assert "fonların hangi hisseyi tuttuğu" in facts["not_measured"]


@pytest.mark.asyncio
async def test_a_small_price_move_does_not_retire_the_note(upstream):
    """The property that keeps a local model from writing commentary forever."""
    from services.ai_notes import fingerprint

    before = await p.build_positioning_facts()
    upstream["equities"] = [
        row(
            f"A{i}",
            price=(145.3 if i < 50 else 55.2),
            change_pct=0.0102,
            relative_volume=3.02 if i < 20 else 1.21,
            free_float_pct=0.10 if i < 20 else 0.40,
        )
        for i in range(100)
    ]
    after = await p.build_positioning_facts()

    assert fingerprint(p.POSITIONING_SPEC, before) == fingerprint(p.POSITIONING_SPEC, after)


# ── The refusal path ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_note_refuses_rather_than_narrating_nothing():
    result = await p.positioning_note(None)
    assert result["status"] == "unavailable"
    assert result["reason"] == "insufficient_data"
    assert result["note"] is None


# ── Rendering ────────────────────────────────────────────────────────────────


def sample_facts(**overrides) -> dict:
    facts = {
        "stance": p.STANCE_CHASING_STRENGTH,
        "as_of": "2026-08-28",
        "stale": False,
        "board": {
            "total": 512,
            "scored": 96,
            "scored_pct": 18.0,
            "unscored_tight_float": 22,
            "unscored_quiet": 380,
            "median_free_float_pct": 32.0,
            "median_relative_volume": 0.75,
            "hot_pct": 8.0,
            "min_free_float_pct": 5.0,
            "min_relative_volume": 1.0,
        },
        "crowd": {
            "cohort": 20,
            "median_crowding": 25.0,
            "median_free_float_pct": 12.0,
            "median_relative_volume": 3.0,
            "median_range_pct": 80.0,
            "board_median_range_pct": 55.0,
            "range_gap_pct": 25.0,
            "names": [
                {
                    "ticker": "SASA",
                    "sector": "Kimya",
                    "crowding": 45.0,
                    "free_float_pct": 8.0,
                    "relative_volume": 3.5,
                    "change_pct": 6.0,
                    "range_pct": 90.0,
                    "rsi": 75.0,
                }
            ],
        },
        "range": {
            "measured": 500,
            "median_pct": 55.0,
            "near_high_pct": 12.0,
            "near_low_pct": 6.0,
            "near_extreme_pct": 10.0,
            "median_rsi": 55.0,
            "near_high_median_rsi": 65.0,
            "overbought_pct": 10.0,
            "oversold_pct": 4.0,
        },
        "sectors": [
            {
                "sector": "Kimya",
                "count": 12,
                "share_pct": 40.0,
                "median_relative_volume": 2.5,
                "median_range_pct": 80.0,
            }
        ],
        "sector_concentrated": True,
        "futures": {
            "covered": 38,
            "total_open_interest": 1_200_000.0,
            "growth_pct": 3.5,
            "quadrants": {
                "long_build": 14,
                "short_build": 8,
                "short_cover": 9,
                "long_liquidation": 7,
            },
            "dominant": "long_build",
            "movers": [
                {
                    "ticker": "THYAO",
                    "quadrant": "long_build",
                    "oi_change_pct": 15.0,
                    "change_pct": 2.0,
                }
            ],
        },
        "not_measured": ["fonların hangi hisseyi tuttuğu"],
    }
    facts.update(overrides)
    return facts


def test_values_fill_every_placeholder_the_prompt_declares():
    from services.prompts import load_prompt

    template = load_prompt("notes/bist_positioning")
    values = p.positioning_values(sample_facts())
    for key in values:
        assert f"{{{{{key}}}}}" in template, f"{key} is rendered but never used"


def test_the_unscored_are_explained_rather_than_counted():
    values = p.positioning_values(sample_facts())
    assert "nobody can trade" in values["board"]
    assert "not elevated" in values["board"]


def test_the_crowd_is_always_stated_against_the_board():
    """Half the note's value is the comparison; a cohort median on its own is a
    figure the reader cannot place."""
    values = p.positioning_values(sample_facts())
    assert "against 32.0%" in values["crowd"]
    assert "for the board" in values["crowd"]


def test_an_unmeasurable_range_is_stated_rather_than_read_as_balanced():
    facts = sample_facts()
    facts["crowd"] = {**facts["crowd"], "median_range_pct": None, "range_gap_pct": None}
    values = p.positioning_values(facts)
    assert "unknown" in values["crowd"]


def test_a_concentrated_board_says_so():
    """One sector carrying most of the board's crowding means the ranking is
    that sector's story, which is the finding rather than a caveat on it."""
    concentrated = p.positioning_values(sample_facts())
    assert "one sector carries" in concentrated["sectors"]

    spread = p.positioning_values(sample_facts(sector_concentrated=False))
    assert "one sector carries" not in spread["sectors"]


def test_a_futures_outage_is_named_rather_than_left_out():
    values = p.positioning_values(sample_facts(futures=None))
    assert "could not be read" in values["futures"]


def test_the_futures_block_says_it_is_a_sample():
    """Forty underlyings against several hundred listings. A paragraph that read
    the quadrants as the market would be overstating what was measured."""
    values = p.positioning_values(sample_facts())
    assert "not a picture of it" in values["futures"]


# ── End to end, with the provider stubbed ────────────────────────────────────


class _Stub:
    def __init__(self):
        self.calls = 0
        self.prompt = ""
        self.reply = "Kalabalıklaşma yıllık zirvesine yakın isimlerde toplanıyor."

    async def generate(self, prompt, **_kwargs):
        self.calls += 1
        self.prompt = prompt
        return self.reply


@pytest.fixture
def model(tmp_path, monkeypatch):
    from services import llm

    monkeypatch.setattr(ai_notes, "STORE_FILE", str(tmp_path / "ai_notes.json"))
    ai_notes.reset_state()
    analysis_jobs._jobs.clear()

    stub = _Stub()
    monkeypatch.setattr(llm, "generate", stub.generate)
    yield stub

    ai_notes.reset_state()
    analysis_jobs._jobs.clear()


async def _settle():
    tasks = [job.task for job in analysis_jobs._jobs.values() if job.task]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_the_prompt_renders_with_no_placeholder_left_behind(model):
    first = await p.positioning_note(sample_facts())
    assert first["status"] == "generating", "the request must not wait for the model"
    await _settle()

    assert model.calls == 1
    assert "{{" not in model.prompt, f"unfilled placeholder in the rendered prompt: {model.prompt}"
    assert "No advice and no forecasts" in model.prompt


@pytest.mark.asyncio
async def test_the_prompt_carries_the_computed_stance_for_the_model_to_explain(model):
    await p.positioning_note(sample_facts())
    await _settle()
    assert "chasing strength" in model.prompt


@pytest.mark.asyncio
async def test_an_unchanged_read_is_written_once_and_then_served_from_cache(model):
    await p.positioning_note(sample_facts())
    await _settle()
    assert model.calls == 1

    second = await p.positioning_note(sample_facts())
    assert second["status"] == "ready"
    assert model.calls == 1, "identical facts must not run the model a second time"
