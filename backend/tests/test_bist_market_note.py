"""
The market-wide reads behind the two BIST screener panels.

Everything the model is allowed to say is computed here, so this file tests the
computation and never the prose. Two properties carry most of the weight:

* **Bucketing.** A note whose fingerprint moved on every two-minute poll would
  never be served from cache and would run a local model continuously. The tests
  that assert an unchanged fingerprint across a small price move are the ones
  that keep that from silently regressing.
* **`note_values` derives from the facts and from nothing else.** That is the
  contract that stops a cached note from citing a figure that has since moved,
  and it is invisible in review — a builder that reached past its argument would
  look identical.
"""

import asyncio

import pytest

from services import ai_notes, analysis_jobs
from services.ai_notes import NoteSpec, _clean, fingerprint
from services.bist import market_note as m
from services.bist.equity_service import SectorStat
from services.bist.tefas_client import FundRow
from services.bist.tradingview_client import EquityRow


def row(
    ticker: str = "AAA",
    *,
    change_pct: float | None = 0.01,
    pe: float | None = 8.0,
    pb: float | None = 1.2,
    indices: tuple[str, ...] = ("XU100",),
    sector: str = "Finans",
) -> EquityRow:
    return EquityRow(
        ticker=ticker,
        symbol=f"BIST:{ticker}",
        name=ticker,
        price=100.0,
        change_pct=change_pct,
        change_abs=None,
        volume=None,
        traded_value=1_000.0,
        market_cap=1_000.0,
        pe=pe,
        pb=pb,
        ev_ebitda=None,
        free_float_pct=None,
        sector=sector,
        indices=indices,
    )


def fund(
    code: str = "AAA",
    *,
    umbrella: str = "Hisse Senedi Şemsiye Fonu",
    risk_value: int | None = 5,
    one_year: float | None = 0.50,
) -> FundRow:
    return FundRow(
        code=code,
        title=f"{code} Fonu",
        umbrella=umbrella,
        tradable=True,
        risk_value=risk_value,
        returns={"1y": one_year},
    )


def framed(pairs: dict[str, tuple[float | None, float | None]]) -> dict[str, dict[str, dict]]:
    """`{code: (nominal, real)}` in the shape `enrich_returns` produces."""
    return {
        code: {"1y": {"nominal": nominal, "real": real, "usd": None}}
        for code, (nominal, real) in pairs.items()
    }


# ── Quantization ─────────────────────────────────────────────────────────────


def test_bucket_snaps_to_the_step():
    assert m._bucket(1.23, 0.5) == 1.0
    assert m._bucket(1.30, 0.5) == 1.5
    assert m._bucket(None, 0.5) is None


def test_bucket_never_produces_negative_zero():
    """`-0.0` renders as "-0.0%" and the model quotes it verbatim."""
    value = m._bucket(-0.0001, 0.5)
    assert value == 0.0
    assert not str(value).startswith("-")


def test_pct_turns_a_fraction_into_percentage_points():
    assert m._pct(0.0123) == 1.2
    assert m._pct(None) is None
    assert m._pct("nonsense") is None


def test_percentile_returns_a_value_that_was_actually_in_the_set():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert m._percentile(values, 0.10) in values
    assert m._percentile(values, 0.90) in values
    assert m._percentile([], 0.5) is None


def test_a_timestamp_is_quantized_to_the_day_before_it_is_fingerprinted():
    """`MacroSnapshot.as_of` carries microseconds. Fingerprinting it raw would
    retire the note on every macro refresh, for a change nobody could see."""
    assert m._day("2026-08-28T11:08:49.967350+00:00") == "2026-08-28"
    assert m._day("2026-08-28") == "2026-08-28"
    assert m._day(None) is None
    assert m._day("") is None


# ── Equity stance ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("index_pct", "advancer_pct", "expected"),
    [
        (1.2, 40.0, m.STANCE_NARROW_RALLY),
        (1.2, 65.0, m.STANCE_BROAD_RALLY),
        (1.2, 50.0, m.STANCE_MIXED),
        (-1.2, 60.0, m.STANCE_NARROW_SELLOFF),
        (-1.2, 35.0, m.STANCE_BROAD_SELLOFF),
        (-1.2, 50.0, m.STANCE_MIXED),
    ],
)
def test_stance_reads_the_index_against_the_breadth(index_pct, advancer_pct, expected):
    assert m.classify_stance(index_pct, advancer_pct) == expected


def test_a_flat_index_has_no_direction_however_wide_the_breadth():
    """Inside the deadband the day has no direction, and a sign test would flip
    the read from one poll to the next on noise."""
    assert m.classify_stance(0.1, 95.0) == m.STANCE_MIXED
    assert m.classify_stance(-0.1, 5.0) == m.STANCE_MIXED


def test_stance_is_mixed_when_a_reading_is_missing():
    assert m.classify_stance(None, 70.0) == m.STANCE_MIXED
    assert m.classify_stance(2.0, None) == m.STANCE_MIXED


# ── Fund stance ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("beat_pct", "expected"),
    [
        (70.0, m.FUND_STANCE_BEATING),
        (60.0, m.FUND_STANCE_BEATING),
        (30.0, m.FUND_STANCE_LOSING),
        (40.0, m.FUND_STANCE_LOSING),
        (50.0, m.FUND_STANCE_SPLIT),
        (None, m.FUND_STANCE_SPLIT),
    ],
)
def test_fund_stance_reads_the_share_that_beat_inflation(beat_pct, expected):
    assert m.classify_fund_stance(beat_pct) == expected


# ── Valuation ────────────────────────────────────────────────────────────────


def test_valuation_uses_the_headline_index_rather_than_the_whole_board():
    """A micro-cap outside XU100 must not move the multiple a reader benchmarks
    the index against."""
    board = [row(f"A{i}", pe=10.0) for i in range(5)]
    board.append(row("JUNK", pe=900.0, indices=()))
    assert m._valuation(board)["median_pe"] == 10.0


def test_valuation_excludes_loss_making_companies():
    """A negative P/E is not a cheap company; it is a company with no E."""
    board = [row("A", pe=10.0), row("B", pe=12.0), row("C", pe=-40.0)]
    assert m._valuation(board)["median_pe"] == 11.0


def test_valuation_falls_back_to_the_board_when_no_constituent_is_flagged():
    board = [row("A", pe=10.0, indices=()), row("B", pe=12.0, indices=())]
    assert m._valuation(board)["median_pe"] == 11.0


# ── Sector entries ───────────────────────────────────────────────────────────


def test_sector_entry_quantizes_every_figure_it_carries():
    stat = SectorStat(
        sector="Finans",
        count=12,
        market_cap=1_000.0,
        weight=0.3123,
        change_pct=0.0123,
        advancers=7,
        decliners=5,
    )
    entry = m._sector_entry(stat)
    assert entry["change_pct"] == 1.0
    assert entry["weight_pct"] == 31.0
    assert entry["advancers"] == 7


# ── Leaders and laggards ─────────────────────────────────────────────────────


def test_a_thin_board_reports_no_laggards_rather_than_repeating_its_leaders():
    """ "Led by X, held back by X" is not a finding, and on a three-sector board
    a naive head/tail slice produces exactly that."""
    ranked = ["a", "b", "c"]
    assert m._tail(ranked, 3) == []


def test_laggards_are_worst_first():
    """`ranked` is sorted best to worst, so the tail has to be reversed — a
    reader scanning the lagging list expects the worst at the top of it."""
    ranked = ["best", "good", "bad", "worst"]
    assert m._tail(ranked, 2) == ["worst", "bad"]


def test_leaders_and_laggards_never_share_an_entry():
    ranked = list(range(10))
    leaders = ranked[:3]
    laggards = m._tail(ranked, 3)
    assert not set(leaders) & set(laggards)


# ── Umbrella and risk aggregation ────────────────────────────────────────────


def test_thin_categories_are_dropped_rather_than_ranked():
    """A "category" of two funds ranked first is one lucky manager wearing a
    category's name, and a reader would take it as a claim about a strategy."""
    funds = [fund(f"BIG{i}", umbrella="Hisse") for i in range(m.MIN_UMBRELLA_MEMBERS)]
    funds += [fund("TINY1", umbrella="Serbest"), fund("TINY2", umbrella="Serbest")]
    frames = framed({f.code: (0.5, 0.1) for f in funds})

    names = {entry["umbrella"] for entry in m._umbrella_stats(funds, frames)}
    assert names == {"Hisse"}


def test_umbrellas_are_ranked_on_the_real_median_not_the_nominal_one():
    """Ranking on lira printed is the question this realm exists to reframe."""
    loud = [fund(f"L{i}", umbrella="Loud") for i in range(5)]
    quiet = [fund(f"Q{i}", umbrella="Quiet") for i in range(5)]
    frames = framed({f.code: (0.80, -0.05) for f in loud} | {f.code: (0.60, 0.10) for f in quiet})

    ranked = m._umbrella_stats(loud + quiet, frames)
    assert [entry["umbrella"] for entry in ranked] == ["Quiet", "Loud"]


def test_risk_cohorts_report_each_grade_band_separately():
    funds = [fund("LOW", risk_value=2), fund("MID", risk_value=4), fund("HIGH", risk_value=7)]
    frames = framed({"LOW": (0.10, -0.20), "MID": (0.40, 0.05), "HIGH": (0.90, 0.35)})

    cohorts = {c["key"]: c for c in m._risk_cohorts(funds, frames)}
    assert set(cohorts) == {"low", "mid", "high"}
    assert cohorts["high"]["median_real_pct"] == 35.0
    assert cohorts["low"]["median_real_pct"] == -20.0


def test_risk_cohorts_omit_a_grade_nobody_on_the_board_carries():
    funds = [fund("A", risk_value=2), fund("B", risk_value=3)]
    frames = framed({"A": (0.1, 0.0), "B": (0.2, 0.05)})
    assert [c["key"] for c in m._risk_cohorts(funds, frames)] == ["low"]


def test_funds_without_a_risk_grade_are_skipped_rather_than_bucketed():
    funds = [fund("A", risk_value=None), fund("B", risk_value=2)]
    frames = framed({"A": (5.0, 5.0), "B": (0.2, 0.05)})
    cohorts = m._risk_cohorts(funds, frames)
    assert len(cohorts) == 1
    assert cohorts[0]["count"] == 1


# ── The refusal path ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_market_note_refuses_rather_than_narrating_nothing():
    """ "Nothing is happening" and "we cannot see what is happening" are
    different claims, and only the second is a missing note."""
    result = await m.market_note(None)
    assert result["status"] == "unavailable"
    assert result["reason"] == "insufficient_data"
    assert result["note"] is None


@pytest.mark.asyncio
async def test_funds_market_note_refuses_on_an_unreadable_board():
    result = await m.funds_market_note(None)
    assert result["status"] == "unavailable"
    assert result["reason"] == "insufficient_data"


# ── Rendering ────────────────────────────────────────────────────────────────


def sample_market_facts(**overrides) -> dict:
    facts = {
        "stance": m.STANCE_NARROW_RALLY,
        "as_of": "2026-08-28",
        "stale": False,
        "index": {
            "code": "XU100",
            "name": "BIST 100",
            "value": 11_000.0,
            "change_pct": 1.0,
            "ytd_pct": 24.0,
            "year_nominal_pct": 58.0,
            "year_real_pct": -3.0,
        },
        "breadth": {
            "advancers": 118,
            "decliners": 174,
            "unchanged": 20,
            "total": 312,
            "advancer_pct": 40.0,
        },
        "sentiment": {
            "score": 38.0,
            "label": "Korku",
            "measured": 300,
            "components": [
                {
                    "key": "breadth",
                    "label": "Piyasa genişliği",
                    "score": 30.0,
                    "reading": "118 yükselen / 174 düşen",
                }
            ],
        },
        "leaders": [
            {
                "sector": "Finans",
                "count": 12,
                "change_pct": 2.0,
                "weight_pct": 31.0,
                "advancers": 9,
                "decliners": 3,
            }
        ],
        "laggards": [
            {
                "sector": "Sanayi",
                "count": 40,
                "change_pct": -1.5,
                "weight_pct": 18.0,
                "advancers": 8,
                "decliners": 30,
            }
        ],
        "concentration": {
            "sector": "Finans",
            "sector_weight_pct": 31.0,
            "sector_change_pct": 2.0,
            "top_ticker": "THYAO",
            "top_turnover_pct": 12.0,
            "top5_turnover_pct": 34.0,
            "concentrated": True,
        },
        "valuation": {"median_pe": 8.4, "median_pb": 1.35, "measured": 100},
        "macro": {
            "inflation_pct": 33.0,
            "ppi_pct": 25.0,
            "policy_rate_pct": 39.0,
            "real_policy_rate_pct": 4.5,
            "unemployment_pct": 8.4,
            "gdp_pct": 3.2,
            "usdtry": 41.25,
            "as_of": "2026-08-01",
        },
        "viop": {"total": 1_200_000.0, "stale": False},
        "not_measured": ["oynaklık endeksi"],
    }
    facts.update(overrides)
    return facts


def test_market_values_fills_every_placeholder_the_prompt_declares():
    from services.prompts import load_prompt

    template = load_prompt("notes/bist_market")
    values = m.market_values(sample_market_facts())
    for key in values:
        assert f"{{{{{key}}}}}" in template, f"{key} is rendered but never used"


def test_market_values_says_a_lira_gain_was_a_purchasing_power_loss():
    values = m.market_values(sample_market_facts())
    assert "gained in lira and lost in purchasing power" in values["index"]


def test_market_values_states_an_uncomputable_real_return_rather_than_skipping_it():
    facts = sample_market_facts()
    facts["index"] = {**facts["index"], "year_real_pct": None}
    values = m.market_values(facts)
    assert "not available" in values["index"]
    assert "purchasing-power terms" in values["index"]


def test_market_values_reports_unmeasured_sentiment_as_unmeasured_not_neutral():
    """A placeholder on a sentiment gauge is a reading someone would act on."""
    values = m.market_values(sample_market_facts(sentiment=None))
    assert "could not be computed" in values["sentiment"]
    assert "50" not in values["sentiment"]


def test_market_values_flags_concentrated_turnover():
    values = m.market_values(sample_market_facts())
    assert "concentrated" in values["concentration"]


def test_market_values_survives_a_missing_macro_print():
    values = m.market_values(sample_market_facts(macro=None, viop=None))
    assert "could not be read" in values["macro"]


def sample_fund_facts(**overrides) -> dict:
    facts = {
        "stance": m.FUND_STANCE_LOSING,
        "fund_type": "YAT",
        "fund_type_label": "Yatırım Fonları",
        "stale": False,
        "total": 1180,
        "tradable": 1100,
        "measured": 1150,
        "median_nominal_pct": 28.0,
        "median_real_pct": -4.0,
        "spread": {
            "p10_real_pct": -22.0,
            "p90_real_pct": 31.0,
            "width_pct": 53.0,
            "measured": 1150,
        },
        "inflation": {
            "beat_count": 380,
            "measured": 1150,
            "beat_pct": 35.0,
            "inflation_pct": 33.0,
            "nominal_gain_real_loss": 610,
            "nominal_gain_real_loss_measured": 1150,
            "example": {"code": "AFA", "nominal_pct": 31.0, "real_pct": -2.0},
        },
        "risk_free": {"rate_pct": 41.0, "source": "money_market_median", "beat_count": 300},
        "leaders": [
            {
                "umbrella": "Hisse Senedi Şemsiye Fonu",
                "count": 120,
                "median_nominal_pct": 55.0,
                "median_real_pct": 16.0,
            }
        ],
        "laggards": [
            {
                "umbrella": "Borçlanma Araçları Şemsiye Fonu",
                "count": 300,
                "median_nominal_pct": 22.0,
                "median_real_pct": -8.0,
            }
        ],
        "risk_cohorts": [
            {
                "key": "low",
                "label": "1–3",
                "count": 200,
                "median_nominal_pct": 20.0,
                "median_real_pct": -10.0,
            }
        ],
        "deflatable_windows": ["1y"],
    }
    facts.update(overrides)
    return facts


def test_funds_market_values_fills_every_placeholder_the_prompt_declares():
    from services.prompts import load_prompt

    template = load_prompt("notes/bist_funds_market")
    values = m.funds_market_values(sample_fund_facts())
    for key in values:
        assert f"{{{{{key}}}}}" in template, f"{key} is rendered but never used"


def test_funds_market_values_names_the_estimate_behind_the_risk_free_rate():
    """A Sharpe against an estimate is a different claim from one against the
    published policy rate, and the note must not blur them."""
    values = m.funds_market_values(sample_fund_facts())
    assert "money-market funds" in values["risk_free"]
    assert "rather than taken from the central bank" in values["risk_free"]


def test_funds_market_values_carries_the_nominal_gain_real_loss_example():
    values = m.funds_market_values(sample_fund_facts())
    assert "AFA" in values["inflation"]


def test_funds_market_values_says_when_no_window_could_be_deflated():
    values = m.funds_market_values(sample_fund_facts(deflatable_windows=[]))
    assert "nominal" in values["coverage"]
    assert "unavailable" in values["coverage"]


# ── The cache contract ───────────────────────────────────────────────────────


def test_an_unchanged_read_keeps_its_fingerprint():
    """The whole design rests on this: identical facts reuse the note."""
    first = fingerprint(m.MARKET_SPEC, sample_market_facts())
    second = fingerprint(m.MARKET_SPEC, sample_market_facts())
    assert first == second


def test_a_changed_reading_retires_the_note():
    facts = sample_market_facts()
    moved = sample_market_facts()
    moved["breadth"] = {**moved["breadth"], "advancer_pct": 65.0}
    assert fingerprint(m.MARKET_SPEC, facts) != fingerprint(m.MARKET_SPEC, moved)


def test_bucketing_holds_the_fingerprint_across_a_move_inside_one_step():
    """Without this the note regenerates on every two-minute poll and a local
    model writes market commentary continuously."""
    quiet = m._pct_bucket(0.0121, 0.5)
    quieter = m._pct_bucket(0.0124, 0.5)
    assert quiet == quieter


# ── The raised ceiling ───────────────────────────────────────────────────────


def test_market_notes_are_allowed_more_room_than_a_single_instrument_note():
    assert m.MARKET_SPEC.max_chars > NoteSpec(kind="x", prompt="y").max_chars
    assert m.FUNDS_MARKET_SPEC.max_chars == m.MARKET_SPEC.max_chars


def test_a_long_note_is_cut_at_a_sentence_end_rather_than_mid_clause():
    text = ("Bu bir cümledir. " * 20).strip()
    cleaned = _clean(text, 100)
    assert len(cleaned) <= 100
    assert cleaned.endswith(".")


def test_a_note_with_no_sentence_break_still_gets_trimmed():
    """A model that answers in one very long sentence must not lose the note to
    a search for a full stop that is not there."""
    cleaned = _clean("kelime " * 200, 100)
    assert 0 < len(cleaned) <= 100


def test_a_short_note_is_returned_whole():
    assert _clean("Kısa bir not.", 900) == "Kısa bir not."


# ── End to end, with the provider stubbed ────────────────────────────────────
#
# The prompts are real here. `render_prompt` substitutes by plain string
# replacement and does not raise on a placeholder nobody filled, so a prompt that
# had drifted from its builder would ship a literal `{{macro}}` to the model and
# nothing would complain. These tests read the rendered text back off the stub
# and assert there is none left, which is the check `test_prompts.py` cannot make
# for values assembled at runtime.


class _Stub:
    """A stand-in provider that records the prompt it was handed."""

    def __init__(self):
        self.calls = 0
        self.prompt = ""
        self.reply = "Piyasa genişliği endeksin kapanışını doğrulamıyor."

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
async def test_the_equity_prompt_renders_with_no_placeholder_left_behind(model):
    first = await m.market_note(sample_market_facts())
    assert first["status"] == "generating", "the request must not wait for the model"
    await _settle()

    assert model.calls == 1
    assert "{{" not in model.prompt, f"unfilled placeholder in the rendered prompt: {model.prompt}"
    # The shared constraints are appended by the engine, not by the builder.
    assert "No advice and no forecasts" in model.prompt


@pytest.mark.asyncio
async def test_the_fund_prompt_renders_with_no_placeholder_left_behind(model):
    await m.funds_market_note(sample_fund_facts())
    await _settle()

    assert model.calls == 1
    assert "{{" not in model.prompt, f"unfilled placeholder in the rendered prompt: {model.prompt}"


@pytest.mark.asyncio
async def test_the_prompt_carries_the_computed_stance_for_the_model_to_explain(model):
    await m.market_note(sample_market_facts())
    await _settle()
    assert "narrow rally" in model.prompt


@pytest.mark.asyncio
async def test_an_unchanged_read_is_written_once_and_then_served_from_cache(model):
    """The property that keeps a local model from writing commentary forever."""
    await m.market_note(sample_market_facts())
    await _settle()
    assert model.calls == 1

    second = await m.market_note(sample_market_facts())
    assert second["status"] == "ready"
    assert second["note"] == model.reply
    assert model.calls == 1, "identical facts must not run the model a second time"


@pytest.mark.asyncio
async def test_a_dead_provider_costs_the_paragraph_and_nothing_else(model):
    model.reply = ""
    result = await m.market_note(sample_market_facts())
    await _settle()

    settled = await m.market_note(sample_market_facts())
    assert result["status"] == "generating"
    assert settled["status"] == "unavailable"
    assert settled["reason"] == "provider_unavailable"
