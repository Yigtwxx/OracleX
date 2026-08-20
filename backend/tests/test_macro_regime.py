"""
The cross-asset regime read.

The point of this module is that the label is arithmetic, not opinion, so these
tests are about the arithmetic: which rows count toward breadth, what a missing
feed does to a vote, where each ladder rung starts, and — the one that keeps the
feature affordable — that a price tick which does not change the reading does not
change the fingerprint either.

Nothing here touches the network or the model. Boards are literal dicts, in the
style `test_macro_board_service.py` already uses.
"""

import pytest

from services import macro_regime
from services.macro_regime import build_regime, note_facts, ratio_change_pct

EQUITY_SYMBOLS = (
    "^GSPC",
    "^IXIC",
    "^DJI",
    "^FTSE",
    "^GDAXI",
    "^N225",
    "^HSI",
    "^STOXX50E",
    "^FCHI",
    "^AXJO",
    "XU100.IS",
)


def _index(symbol: str, change, status: str = "open") -> dict:
    return {
        "symbol": symbol,
        "name": symbol,
        "change_24h": change,
        "region": "US",
        "market_status": {"status": status, "label": status.title()},
    }


def _commodity(symbol: str, change) -> dict:
    return {"symbol": symbol, "name": symbol, "change_24h": change, "group": "metals"}


def _board(*, advancing: int = 8, dollar=-0.5, copper=0.9, gold=-0.3, status="open") -> dict:
    """A board with `advancing` of the eleven equity indices up on the day."""
    indices = [
        _index(symbol, 1.0 if i < advancing else -1.0, status)
        for i, symbol in enumerate(EQUITY_SYMBOLS)
    ]
    indices.append(_index(macro_regime.DOLLAR_SYMBOL, dollar, status))
    return {
        "indices": indices,
        "commodities": [
            _commodity(macro_regime.COPPER_SYMBOL, copper),
            _commodity(macro_regime.GOLD_SYMBOL, gold),
            _commodity(macro_regime.OIL_SYMBOL, 0.4),
        ],
        "as_of": "2026-08-18T09:00:00+00:00",
        "stale": False,
    }


def _signal(regime: dict, key: str):
    for component in regime["components"]:
        if component["key"] == key:
            return component["signal"]
    return None


def test_three_agreeing_components_read_risk_on():
    regime = build_regime(_board())
    assert regime["score"] == 3
    assert regime["label"] == "Risk-on"


def test_three_agreeing_components_read_risk_off():
    regime = build_regime(_board(advancing=3, dollar=0.5, copper=-0.9, gold=0.3))
    assert regime["score"] == -3
    assert regime["label"] == "Risk-off"


@pytest.mark.parametrize(
    "score,label",
    [
        (3, "Risk-on"),
        (2, "Risk-on"),
        (1, "Leaning risk-on"),
        (0, "Mixed"),
        (-1, "Leaning risk-off"),
        (-2, "Risk-off"),
        (-3, "Risk-off"),
    ],
)
def test_every_rung_of_the_ladder(score, label):
    assert macro_regime._label_for(score) == label


def test_the_dollar_index_is_not_counted_as_market_breadth():
    """
    `DX-Y.NYB` ships in the same feed as the equity benchmarks but is not one.
    Counting it would let a dollar rally read as breadth, which is close to the
    opposite of what a rising dollar means for risk appetite.
    """
    regime = build_regime(_board(advancing=11, dollar=-0.5))
    breadth = next(c for c in regime["components"] if c["key"] == "breadth")
    assert "11 of 11" in breadth["reading"]


def test_a_missing_feed_votes_nothing_and_is_named():
    """
    The snapshot convention: a feed that failed is reported, never silently
    treated as neutral, because "no data" and "no signal" are different claims.
    """
    board = _board()
    board["commodities"] = [_commodity(macro_regime.OIL_SYMBOL, 0.4)]

    regime = build_regime(board)
    assert "Copper vs gold" in regime["unavailable"]
    assert _signal(regime, "copper_gold") is None
    assert regime["score"] == 2, "The two surviving components still vote"


def test_two_missing_components_withhold_the_read():
    """One vote deciding a three-vote question is not a regime call."""
    board = _board()
    board["commodities"] = []
    board["indices"] = [_index(macro_regime.DOLLAR_SYMBOL, -0.5)]

    regime = build_regime(board)
    assert regime["label"] == macro_regime.LABEL_UNAVAILABLE


def test_too_few_readable_indices_is_not_a_breadth_reading():
    board = _board()
    board["indices"] = [_index(symbol, 1.0) for symbol in EQUITY_SYMBOLS[:3]]
    board["indices"].append(_index(macro_regime.DOLLAR_SYMBOL, -0.5))

    regime = build_regime(board)
    assert "Equity breadth" in regime["unavailable"]


def test_an_empty_board_reads_unavailable_rather_than_neutral():
    """The outage path: a 503 upstream must not render as a calm 'Mixed' tape."""
    regime = build_regime({})
    assert regime["label"] == macro_regime.LABEL_UNAVAILABLE
    assert len(regime["unavailable"]) == 3


def test_a_ratio_change_compounds_rather_than_subtracting():
    """
    Copper +0.9% against gold −0.3% moves the ratio 1.204%, not 1.2 points. The
    difference is small here and grows with the legs; the exact figure is free
    because the board publishes both.
    """
    assert ratio_change_pct(0.9, -0.3) == pytest.approx(1.2036108, rel=1e-6)


def test_a_flat_tape_does_not_flip_the_read():
    """Deadbands exist so a board that is 55% green says nothing, loudly."""
    regime = build_regime(_board(advancing=6, dollar=-0.1, copper=0.2, gold=0.1))
    assert regime["score"] == 0
    assert regime["label"] == "Mixed"


def test_a_tick_that_does_not_change_the_reading_does_not_change_the_fingerprint():
    """
    This is the test that keeps the feature affordable. The board refreshes every
    two minutes and every price is a live float, so fingerprinting raw figures
    would regenerate a note on a local model every two minutes and never hit the
    cache once. Facts are quantised to the grain each signal was decided on.
    """
    quiet = note_facts(build_regime(_board(dollar=-0.52)))
    still_quiet = note_facts(build_regime(_board(dollar=-0.54)))
    assert quiet == still_quiet

    moved = note_facts(build_regime(_board(dollar=-0.14)))
    assert moved != quiet


def test_an_index_flip_does_change_the_fingerprint():
    assert note_facts(build_regime(_board(advancing=8))) != note_facts(
        build_regime(_board(advancing=7))
    )


def test_breadth_across_closed_sessions_is_disclosed():
    """
    Tokyo's change was fixed at 06:00 UTC and New York's at 21:00. An advancing
    count taken across both is an average of different days wearing one label,
    and the reader cannot see that from the number.
    """
    regime = build_regime(_board(status="closed"))
    assert regime["session_caveat"]
    assert "last closes" in regime["session_caveat"]


def test_an_all_open_board_carries_no_session_caveat():
    assert build_regime(_board(status="open"))["session_caveat"] is None


def test_the_read_always_declares_what_it_cannot_see():
    """
    There is no VIX, no yield and no credit feed anywhere in this application. A
    "cross-asset" read that does not say so overclaims, so the disclosure is a
    constant rather than something the model is trusted to remember.
    """
    regime = build_regime(_board())
    assert regime["not_measured"] == list(macro_regime.NOT_MEASURED)
    assert any("volatility" in item for item in regime["not_measured"])


async def test_an_unavailable_read_never_reaches_the_model(monkeypatch):
    from services import llm

    calls = []

    async def fail(*_args, **_kwargs):
        calls.append(1)
        return "should not happen"

    monkeypatch.setattr(llm, "generate", fail)

    note = await macro_regime.regime_note(build_regime({}))
    assert note["status"] == "unavailable"
    assert not calls


def _placeholders(name: str) -> set:
    import re

    from services.prompts import load_prompt

    return set(re.findall(r"\{\{(\w+)\}\}", load_prompt(name)))


def test_the_prompt_asks_for_exactly_what_the_facts_supply():
    """
    `test_prompts.py` proves this for every template rendered from a literal
    name, but a note reaches `render_prompt` through its spec, so the check lands
    here — where the supplied keys are actually known. Both directions matter: a
    placeholder nobody fills ships `{{...}}` to the model verbatim, and a key no
    placeholder uses is a fact silently dropped from the prompt.
    """
    facts = note_facts(build_regime(_board()))
    supplied = set(macro_regime.note_values(facts)) | {"rules"}
    assert _placeholders(macro_regime.NOTE_SPEC.prompt) == supplied


def test_a_barely_moved_reading_is_not_reported_as_negative_zero():
    """
    Rounding a small decline gives `-0.0`, which prints as "-0.0%". The model
    quotes these readings verbatim, so this shipped as "the dollar index fell by
    negative zero percent" before it was caught.
    """
    regime = build_regime(_board(dollar=-0.04, copper=0.1, gold=0.1))
    readings = " ".join(c["reading"] for c in regime["components"])
    assert "-0.0" not in readings
    assert "+0.0%" in readings
