"""
The VİOP end-of-day bulletin parser.

The fixture is a byte-for-byte slice of a real file, kept that way on purpose:
it carries the BOM the exchange ships and the one column header that arrives
with a leading space. Both are handled on read rather than being baked into a
constant, and a hand-written fixture would quietly stop testing either.

The rest of the file is about refusing to guess. A bulletin whose shape has
changed must produce nothing rather than rows whose numbers landed in the wrong
fields, and a holiday must be recorded as a fact about that date rather than
retried on every boot.
"""

import os
from dataclasses import replace

import pytest

from services.bist.viop_bulletin import (
    DEFAULT_CONTRACT_MULTIPLIER,
    BulletinHistory,
    _decimal,
    _multiplier,
    parse_bulletin,
)
from services.cache import bist_cache

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "viop_bulletin_sample.csv")


@pytest.fixture(autouse=True)
def _clean_cache():
    bist_cache.clear()
    yield
    bist_cache.clear()


@pytest.fixture
def payload() -> bytes:
    with open(FIXTURE, "rb") as handle:
        return handle.read()


class TestUpstreamShape:
    def test_the_fixture_still_carries_the_bom(self, payload):
        # If the fixture is ever regenerated without it, the BOM test below
        # would pass for the wrong reason.
        assert payload.startswith(b"\xef\xbb\xbf")

    def test_the_fixture_still_carries_the_leading_space(self, payload):
        # The exchange publishes `" AGIRLIKLI ORTALAMA FIYAT"`. The parser strips
        # headers so that a fix upstream does not break us; this pins that the
        # unfixed spelling is what it is actually being asked to survive.
        header = payload.decode("utf-8-sig").splitlines()[0]
        assert " AGIRLIKLI ORTALAMA FIYAT" in header

    def test_bom_does_not_reach_the_first_column_name(self, payload):
        rows = parse_bulletin(payload)
        assert rows, "the fixture should parse to something"
        assert all(row.day.startswith("2026-") for row in rows)


class TestSegmentAndSymbols:
    def test_only_single_stock_futures_survive(self, payload):
        rows = parse_bulletin(payload)
        # The fixture holds SSO/INF/CRF rows too; none of them is an equity
        # futures contract and none should reach the board.
        assert {row.contract[:2] for row in rows} == {"F_"}

    def test_the_equity_board_suffix_is_stripped(self, payload):
        rows = parse_bulletin(payload)
        assert "THYAO" in {row.underlying for row in rows}
        assert not any(row.underlying.endswith(".E") for row in rows)

    def test_every_expiry_of_a_name_is_kept(self, payload):
        thyao = [row for row in parse_bulletin(payload) if row.underlying == "THYAO"]
        # Three months are listed at a time, and the map folds all of them.
        assert len(thyao) == 3
        assert len({row.expiry for row in thyao}) == 3


class TestNumbers:
    def test_figures_are_dot_decimal(self):
        assert _decimal("18.39") == 18.39
        assert _decimal("476678454") == 476678454.0

    def test_a_turkish_formatted_number_is_refused(self):
        # Reading `1.234,56` with this parser would produce 1234 or 1.234 —
        # both plausible, both wrong. The file does not use that convention, so
        # meeting it means the format changed and the import should stop.
        assert _decimal("1.234,56") is None
        assert _decimal("18,39") is None

    def test_blanks_and_dashes_are_missing_not_zero(self):
        assert _decimal("") is None
        assert _decimal("-") is None
        assert _decimal(None) is None


class TestContractMultiplier:
    def test_derived_from_the_row(self, payload):
        rows = parse_bulletin(payload)
        assert {row.multiplier for row in rows} == {100}

    def test_a_thin_far_month_does_not_drift(self):
        # `F_GUBRF1026` on a real session derives 101.40 because the weighted
        # average is published to two places and the quantity is small. Rounding
        # that to the nearest integer would scale the underlying by one percent.
        assert _multiplier(32_633_500, 611, 526.71) == 100

    def test_a_restated_contract_size_is_believed(self):
        assert _multiplier(1000 * 250.0 * 7.0, 250.0, 7.0) == 1000

    def test_an_untraded_expiry_falls_back(self):
        assert _multiplier(0, 0, 0) == DEFAULT_CONTRACT_MULTIPLIER
        assert _multiplier(None, None, None) == DEFAULT_CONTRACT_MULTIPLIER


class TestRefusesToGuess:
    def test_a_reshaped_header_yields_nothing(self):
        assert parse_bulletin(b"A;B;C\n1;2;3\n") == []

    def test_a_missing_required_column_yields_nothing(self, payload):
        text = payload.decode("utf-8-sig")
        lines = text.splitlines()
        lines[0] = lines[0].replace("ACIK POZISYON DEGISIMI", "SOMETHING ELSE")
        assert parse_bulletin("\n".join(lines).encode("utf-8")) == []

    def test_an_empty_body_yields_nothing(self):
        assert parse_bulletin(b"") == []


class TestHistory:
    def _history(self, days: list[str]) -> BulletinHistory:
        """The fixture's one session, restamped onto several."""
        with open(FIXTURE, "rb") as handle:
            template = [row for row in parse_bulletin(handle.read()) if row.underlying == "THYAO"]
        rows = [replace(row, day=day) for day in days for row in template]
        return BulletinHistory(rows=rows, holidays=set(), stored_at=0.0)

    def test_sessions_are_sorted_and_unique(self):
        history = self._history(["2026-08-26", "2026-08-27", "2026-08-28"])
        assert history.sessions() == ["2026-08-26", "2026-08-27", "2026-08-28"]

    def test_for_underlying_filters(self):
        history = self._history(["2026-08-28"])
        assert history.for_underlying("THYAO")
        assert history.for_underlying("AKBNK") == []

    def test_an_empty_history_reads_as_stale(self):
        assert BulletinHistory(rows=[], holidays=set(), stored_at=0.0).stale() is True

    def test_an_old_newest_session_reads_as_stale(self):
        assert self._history(["2020-01-02"]).stale() is True
