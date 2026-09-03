"""
The ownership note's facts, and the prompt rendered from them.

What is pinned: the stance is decided by the valued split and nothing else, a
missing or thin board is `None` and not a quiet index, the per-company
readings come from the stored tables so untracked holders count, and every
placeholder the prompt names is rendered from the facts alone.
"""

from __future__ import annotations

import pytest

from models.bist_ownership import (
    EntitySummary,
    Move,
    OwnershipBoard,
    StakeMove,
)
from services.bist.ownership import board as board_module
from services.bist.ownership import note, snapshots
from services.bist.ownership.errors import BoardUnavailable
from services.cache import bist_cache


@pytest.fixture(autouse=True)
def _clean():
    bist_cache.clear()
    yield
    bist_cache.clear()


def _entity(entity_id: str, category: str, value: float | None, positions: int = 1):
    return EntitySummary(
        id=entity_id,
        name=entity_id.upper(),
        category=category,  # type: ignore[arg-type]
        total_value_try=value,
        positions_count=positions,
        has_data=value is not None,
    )


def _board(**overrides) -> OwnershipBoard:
    base = {
        "entities": [
            _entity("tvf", "state", 900e9, 5),
            _entity("koc", "holding", 300e9, 4),
            _entity("sabanci", "holding", 200e9, 3),
            _entity("bbva", "foreign", 400e9, 1),
            _entity("fund-a", "fund", 3e9, 20),
            _entity("fund-b", "fund", None, 0),
            _entity("vakif", "other", None, 0),
        ],
        "latest_moves": [
            Move(
                id="kap-1",
                ticker="THYAO",
                company="THY",
                event="icsel_islem",
                event_label="İçeriden pay işlemi",
                headline="THYAO · Pay Alım Satım Bildirimi",
                published_at="2026-09-01T10:00:00+03:00",
                url="https://www.kap.org.tr/tr/Bildirim/1",
                score=6,
                band="medium",
            )
        ],
        "latest_stake_moves": [
            StakeMove(
                id="stake-1",
                ticker="THYAO",
                company="THY",
                holder="Türkiye Varlık Fonu",
                entity_id="tvf",
                kind="add",
                stake_before=0.45,
                stake_after=0.4912,
                delta_pct=0.0412,
                observed_at="2026-09-03",
            )
        ],
        "tracking_since": "2026-09-02",
        "tickers_covered": 100,
        "tickers_total": 100,
        "as_of": "2026-09-03T06:00:00+00:00",
        "stale": False,
    }
    base.update(overrides)
    return OwnershipBoard(**base)


PAYLOAD = {
    "tickers": {
        "THYAO": {
            "ok": True,
            "holders": [{"label": "Türkiye Varlık Fonu", "stake_pct": 0.4912}],
            "free_float_pct": 0.50,
            "foreign_ratio_pct": 0.22,
        },
        "HALKB": {
            "ok": True,
            "holders": [{"label": "Türkiye Varlık Fonu", "stake_pct": 0.9149}],
            "free_float_pct": 0.08,
            "foreign_ratio_pct": 0.01,
        },
        "KRDMD": {"ok": True, "holders": [], "free_float_pct": 0.93, "foreign_ratio_pct": 0.25},
        "KCHOL": {
            "ok": True,
            "holders": [
                {"label": "Untracked Family Co", "stake_pct": 0.4375},
                {"label": "Vehbi Koç Vakfı", "stake_pct": 0.0729},
            ],
            "free_float_pct": 0.26,
            "foreign_ratio_pct": 0.53,
        },
        "FAILED": {"ok": False, "holders": []},
    }
}


@pytest.fixture
def stubbed(monkeypatch):
    async def get_board():
        return _board()

    monkeypatch.setattr(board_module, "get_board", get_board)
    monkeypatch.setattr(board_module, "stored_payload", lambda: PAYLOAD)
    monkeypatch.setattr(snapshots, "all_changes", lambda: [object(), object()])
    monkeypatch.setattr(snapshots, "days", lambda: ["2026-09-02", "2026-09-03"])
    return monkeypatch


class TestStance:
    def test_the_largest_category_decides_when_it_dominates(self):
        assert note.classify_stance({"state": 50.0, "holding": 30.0}) == "state_anchored"
        assert note.classify_stance({"holding": 49.0, "state": 34.0}) == "family_holdings"
        assert note.classify_stance({"foreign": 40.0, "holding": 35.0}) == "foreign_strategic"

    def test_no_dominant_kind_is_dispersed(self):
        assert (
            note.classify_stance({"state": 30.0, "holding": 30.0, "foreign": 30.0}) == "dispersed"
        )
        assert note.classify_stance({}) == "dispersed"
        # A dominant "other" or "fund" is not a stance this board names.
        assert note.classify_stance({"other": 60.0}) == "dispersed"


class TestFacts:
    async def test_split_and_concentration_come_from_the_board(self, stubbed):
        facts = await note.build_ownership_facts()

        assert facts is not None
        assert facts["stance"] == "state_anchored"
        categories = {c["category"]: c for c in facts["total"]["categories"]}
        assert categories["state"]["share_pct"] == 50.0  # 900 of 1803
        assert categories["foreign"]["share_pct"] == 22.0
        assert "other" not in categories, "an entity with no value is not part of the split"
        assert facts["total"]["valued_try_bn"] == 1800.0
        assert [h["name"] for h in facts["holders"]["top"][:2]] == ["TVF", "BBVA"]
        assert facts["holders"]["top3_share_pct"] == 89.0
        assert facts["funds"] == {"tracked": 2, "readable": 1}

    async def test_company_readings_count_untracked_holders_and_skip_failed_cards(self, stubbed):
        facts = await note.build_ownership_facts()

        assert facts is not None
        companies = facts["companies"]
        assert companies["with_named_holder"] == 3
        assert companies["without_named_holder"] == 1, "KRDMD, not the failed card"
        assert companies["majority_held"] == 1, "HALKB only; KCHOL's 43.75% is not a majority"
        # Named stakes: 49.12, 91.49, 51.04 → median 51.
        assert companies["median_named_stake_pct"] == 51.0
        assert companies["foreign_high"][0] == {"ticker": "KCHOL", "pct": 53.0}
        assert companies["foreign_low"][0] == {"ticker": "HALKB", "pct": 1.0}

    async def test_moves_are_counted_and_the_recent_ones_named(self, stubbed):
        facts = await note.build_ownership_facts()

        assert facts is not None
        assert facts["moves"]["stake_total"] == 2
        assert facts["moves"]["stake_kinds"] == {"add": 1}
        assert facts["moves"]["recent_stakes"][0]["after_pct"] == 49.1
        assert facts["moves"]["filing_kinds"] == {"İçeriden pay işlemi": 1}
        assert facts["coverage"]["tracking_days"] == 2

    async def test_a_missing_board_is_none_not_a_quiet_index(self, stubbed):
        async def missing():
            raise BoardUnavailable("not built")

        stubbed.setattr(board_module, "get_board", missing)

        assert await note.build_ownership_facts() is None

    async def test_a_thin_board_is_none(self, stubbed):
        async def thin():
            return _board(tickers_covered=10)

        stubbed.setattr(board_module, "get_board", thin)

        assert await note.build_ownership_facts() is None


class TestValues:
    async def test_every_placeholder_is_rendered_from_the_facts(self, stubbed):
        facts = await note.build_ownership_facts()
        assert facts is not None

        values = note.ownership_values(facts)

        assert set(values) == {
            "stance",
            "coverage",
            "categories",
            "holders",
            "companies",
            "moves",
            "filings",
            "not_measured",
        }
        assert values["stance"] == "state anchored"
        assert "1800 bn TRY" in values["coverage"]
        assert "50% of the valued total" in values["categories"]
        assert "TVF (kamu" in values["holders"]
        assert "Türkiye Varlık Fonu in THYAO — add, 45.0% → 49.1%" in values["moves"]
        assert "İçeriden pay işlemi 1" in values["filings"]
        assert "%5 altındaki paylar" in values["not_measured"]

    def test_no_moves_yet_is_said_out_loud(self):
        facts = {
            "stance": "dispersed",
            "coverage": {
                "universe": "XU100",
                "tickers_covered": 100,
                "tickers_total": 100,
                "entities": 1,
                "entities_with_data": 1,
                "as_of": "2026-09-02",
                "tracking_since": "2026-09-02",
                "tracking_days": 1,
            },
            "total": {"valued_try_bn": 10.0, "categories": []},
            "holders": {"top": [], "top3_share_pct": None},
            "companies": {
                "with_named_holder": 0,
                "without_named_holder": 0,
                "majority_held": 0,
                "median_named_stake_pct": None,
                "median_free_float_pct": None,
                "median_foreign_ratio_pct": None,
                "foreign_high": [],
                "foreign_low": [],
            },
            "moves": {
                "stake_total": 0,
                "stake_kinds": {},
                "recent_stakes": [],
                "filing_kinds": {},
                "recent_filings": [],
            },
            "funds": {"tracked": 0, "readable": 0},
            "not_measured": list(note.NOT_MEASURED),
            "stale": True,
        }

        values = note.ownership_values(facts)

        assert "recording began on 2026-09-02" in values["moves"]
        assert "older than a day" in values["coverage"]
        assert "not available" in values["companies"]


async def test_the_note_declines_without_facts():
    result = await note.ownership_note(None)

    assert result["status"] == "unavailable"
    assert result["reason"] == "insufficient_data"
