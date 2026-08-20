"""
The institutional flow note's aggregation.

This is the surface where getting the arithmetic wrong would be least visible and
most misleading — a note that says "institutions were net buyers" is believed,
and nothing on the page contradicts it. So the cases below are mostly about what
must *not* be counted: moves from other provider families, unpriced moves counted
as zero, and holders whose first filing means no change exists for them at all.

Conventions follow `test_ownership_refresh.py`: `Move` objects built from literal
data, private helpers called directly, nothing on the network.
"""

from datetime import date

import pytest

from models.ownership import Move, SourceRef
from services import ai_notes
from services.ownership import board, flow_note
from services.ownership.errors import BoardUnavailable


def _move(
    move_id: str,
    entity: str,
    symbol: str,
    kind: str,
    value: float | None,
    *,
    source_kind: str = "sec_13f",
    occurred: date = date(2026, 6, 30),
    reported: date | None = date(2026, 8, 14),
) -> Move:
    return Move(
        id=move_id,
        entity_id=entity.lower().replace(" ", "-"),
        entity_name=entity,
        category="institution",
        kind=kind,
        asset_label=symbol,
        asset_symbol=symbol,
        asset_class="equity",
        value_usd_delta=value,
        occurred_at=occurred,
        reported_at=reported,
        headline=f"{entity} {kind} {symbol}",
        source=SourceRef(kind=source_kind, label="13F Q2 2026", as_of=occurred),
    )


def _install(monkeypatch, moves: list[Move], payload: dict | None = None) -> None:
    monkeypatch.setattr(board, "get_moves", lambda **_kwargs: list(moves))
    monkeypatch.setattr(board, "stored_payload", lambda: payload or {})


def _quarter(monkeypatch, *, buys: int = 4, sells: int = 2) -> None:
    moves = [_move(f"b{i}", f"Fund {i}", "NVDA", "add", 10_000_000) for i in range(buys)]
    moves += [_move(f"s{i}", f"Fund {i}", "TSLA", "trim", 1_000_000) for i in range(sells)]
    _install(monkeypatch, moves)


def test_only_thirteen_f_moves_are_institutional_flow(monkeypatch):
    """
    `MoveKind` spans ten kinds across four provider families. A corporate treasury
    topping up its bitcoin is not an institution building a position, and letting
    one through would have the note say "institutions bought" about a row no
    institution filed.
    """
    _install(
        monkeypatch,
        [
            _move("a", "Fund A", "NVDA", "add", 5_000_000),
            _move("b", "Fund B", "NVDA", "add", 6_000_000),
            _move("c", "Fund C", "NVDA", "add", 7_000_000),
            _move(
                "t", "Strategy", "BTC", "increase", 900_000_000, source_kind="coingecko_treasury"
            ),
        ],
    )

    facts = flow_note.build_flow_facts()
    assert facts["buy_count"] == 3
    assert facts["other_activity_count"] == 1
    assert facts["gross_bought_usd"] == pytest.approx(18_000_000)


def test_an_unpriced_move_is_not_a_move_worth_nothing(monkeypatch):
    """
    A filing that did not carry a dollar value is missing data, not a zero. The
    totals become floors and have to be labelled as floors, or the note quietly
    understates the quarter.
    """
    _install(
        monkeypatch,
        [
            _move("a", "Fund A", "NVDA", "add", 5_000_000),
            _move("b", "Fund B", "AAPL", "add", None),
            _move("c", "Fund C", "MSFT", "add", 1_000_000),
        ],
    )

    facts = flow_note.build_flow_facts()
    assert facts["value_is_partial"] is True
    assert facts["unpriced_moves"] == 1
    assert facts["gross_bought_usd"] == pytest.approx(6_000_000)
    assert "floors" in flow_note.note_values(facts)["coverage"]


def test_disagreement_over_one_asset_is_surfaced(monkeypatch):
    """
    The one fact on this page that no table below it can show. Every panel there
    ranks moves by size, and none of them can say two holders took opposite sides
    of the same name in the same quarter.
    """
    _install(
        monkeypatch,
        [
            _move("a", "Fund A", "NVDA", "add", 5_000_000),
            _move("b", "Fund B", "NVDA", "trim", 3_000_000),
            _move("c", "Fund C", "MSFT", "add", 1_000_000),
        ],
    )

    facts = flow_note.build_flow_facts()
    assert [row["symbol"] for row in facts["contested"]] == ["NVDA"]
    assert facts["contested"][0]["buyers"] == ["Fund A"]
    assert facts["contested"][0]["sellers"] == ["Fund B"]


@pytest.mark.parametrize(
    "bought,sold,expected",
    [
        (10_000_000, 1_000_000, flow_note.TILT_NET_BUYING),
        (1_000_000, 10_000_000, flow_note.TILT_NET_SELLING),
        (10_000_000, 8_000_000, flow_note.TILT_BALANCED),
    ],
)
def test_the_quarter_is_only_called_when_it_leans(bought, sold, expected):
    """Below the band the holders disagreed, which is its own finding."""
    assert flow_note._tilt(bought, sold, moves=8, entities=4) == expected


def test_a_handful_of_filings_is_not_a_picture_of_institutional_flow():
    assert flow_note._tilt(9_000_000, 0, moves=2, entities=1) == flow_note.TILT_INSUFFICIENT
    assert flow_note._tilt(9_000_000, 0, moves=9, entities=2) == flow_note.TILT_INSUFFICIENT


def test_the_filing_gap_is_preserved_rather_than_collapsed(monkeypatch):
    """
    13F positions describe a quarter end and become public up to forty-five days
    later. Both dates reach the note, because a reader who takes this for current
    positioning has been misled.
    """
    _quarter(monkeypatch)
    facts = flow_note.build_flow_facts()

    assert facts["period"] == "2026-06-30"
    assert facts["filed_to"] == "2026-08-14"
    assert "2026-08-14" in flow_note.note_values(facts)["filed"]


def test_a_single_filing_date_is_not_rendered_as_a_range(monkeypatch):
    """
    13F filings cluster on the deadline, so one date is the common case. Rendered
    naively it reads "between 2026-08-14 and 2026-08-14", which looks like a bug
    rather than like a quarter everyone filed on the same day.
    """
    _quarter(monkeypatch)
    filed = flow_note.note_values(flow_note.build_flow_facts())["filed"]
    assert filed == "on 2026-08-14"


def test_holders_on_a_first_filing_are_named(monkeypatch):
    """
    A holder with one filing on record has no quarter-over-quarter change at all.
    Saying so is the difference between "they did nothing" and "we cannot see
    what they did".
    """
    _install(
        monkeypatch,
        [_move("a", "Fund A", "NVDA", "add", 5_000_000)],
        payload={
            "baselines": ["fund-b"],
            "board": {
                "entities": [{"id": "fund-a", "name": "Fund A"}, {"id": "fund-b", "name": "Fund B"}]
            },
        },
    )

    facts = flow_note.build_flow_facts()
    assert facts["baseline_entities"] == ["Fund B"]
    assert "single filing" in flow_note.note_values(facts)["coverage"]


def test_the_fingerprint_follows_the_filings(monkeypatch):
    """
    Move ids are deterministic hashes of the filing they came from, so they change
    when a new 13F lands and at no other time. That is what makes this note one
    generation a quarter rather than one a page load.
    """
    _quarter(monkeypatch)
    before = flow_note.build_flow_facts()

    _quarter(monkeypatch, buys=5)
    after = flow_note.build_flow_facts()

    assert before["move_ids"] != after["move_ids"]

    _quarter(monkeypatch)
    assert flow_note.build_flow_facts()["move_ids"] == before["move_ids"]


def test_no_board_is_not_an_empty_quarter(monkeypatch):
    def unavailable(**_kwargs):
        raise BoardUnavailable("No ownership board has been built yet")

    monkeypatch.setattr(board, "get_moves", unavailable)
    assert flow_note.build_flow_facts() is None


async def test_nothing_to_narrate_never_reaches_the_model(monkeypatch):
    from services import llm

    calls = []

    async def fail(*_args, **_kwargs):
        calls.append(1)
        return "should not happen"

    monkeypatch.setattr(llm, "generate", fail)
    _install(monkeypatch, [])

    note = await flow_note.flow_note(flow_note.build_flow_facts())
    assert note["status"] == ai_notes.STATUS_UNAVAILABLE
    assert note["reason"] == ai_notes.REASON_INSUFFICIENT_DATA
    assert not calls


def _placeholders(name: str) -> set:
    import re

    from services.prompts import load_prompt

    return set(re.findall(r"\{\{(\w+)\}\}", load_prompt(name)))


def test_the_prompt_asks_for_exactly_what_the_facts_supply(monkeypatch):
    """
    As in the macro and chains suites: the note names its template through a
    spec, so the placeholder contract `test_prompts.py` enforces elsewhere is
    asserted here, where the supplied keys are known.
    """
    _quarter(monkeypatch)
    supplied = set(flow_note.note_values(flow_note.build_flow_facts())) | {"rules"}
    assert _placeholders(flow_note.NOTE_SPEC.prompt) == supplied
