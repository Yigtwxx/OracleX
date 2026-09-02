"""
Takasbank's scan-range file.

Two filters carry this whole module, and the fixture exists to hold them down.
The archive lists a portfolio per broker beside the ones per underlying, and a
rights-issue portfolio beside each main contract. Drop either filter and THYAO
reads 14.0 instead of 13.4 — a number that is wrong by half a percentage point,
looks entirely reasonable, and would move every band on the board.
"""

import os
import zipfile

import pytest

from services.bist.takasbank_psr import EOD_PATTERN, PsrUnavailable, parse_span
from services.cache import bist_cache

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "takasbank_span_sample.zip")


@pytest.fixture(autouse=True)
def _clean_cache():
    bist_cache.clear()
    yield
    bist_cache.clear()


@pytest.fixture
def payload() -> bytes:
    with open(FIXTURE, "rb") as handle:
        return handle.read()


class TestFilters:
    def test_the_rights_issue_portfolio_is_dropped(self, payload):
        snapshot = parse_span(payload)
        # `THYAO_C` is in the fixture and must not be what THYAO resolves to.
        assert "THYAO_C" not in snapshot.rates
        assert snapshot.get("THYAO") is not None

    def test_thyao_reads_its_own_scan_range(self, payload):
        # The number the whole feature hangs on. If a filter regresses this
        # becomes 14.0 and nothing else in the suite notices.
        assert snapshot_psr(payload, "THYAO") == pytest.approx(0.134)

    def test_a_cash_settled_portfolio_is_dropped(self, payload):
        snapshot = parse_span(payload)
        # Only physically settled single-stock futures belong on this board;
        # the fixture carries a cash-settled portfolio to prove it is excluded.
        assert all(code in {"THYAO", "AKBNK"} for code in snapshot.rates)

    def test_each_underlying_appears_once(self, payload):
        snapshot = parse_span(payload)
        assert len(snapshot.rates) == len(set(snapshot.rates))


class TestValues:
    def test_the_percentage_becomes_a_fraction(self, payload):
        # The file publishes 15.7; everything downstream multiplies a price by
        # it, so it is stored as 0.157 and converted exactly once.
        assert snapshot_psr(payload, "AKBNK") == pytest.approx(0.157)

    def test_the_clearing_house_contract_size_is_carried(self, payload):
        rate = parse_span(payload).get("AKBNK")
        # `cvf` is an independent read on the multiplier the bulletin derives
        # for itself, which is the only cross-check either side gets.
        assert rate.multiplier == 100

    def test_contract_value_agrees_with_the_scan_range(self, payload):
        rate = parse_span(payload).get("AKBNK")
        # 7326.00 × 15.7% is the initial margin the file's own risk array
        # carries, and that agreement is what says the field was read right.
        assert rate.contract_value == pytest.approx(7326.0)
        assert rate.contract_value * rate.psr == pytest.approx(1150.18, abs=0.02)


class TestProvenance:
    def test_the_snapshot_stamp_is_the_files_own(self, payload):
        snapshot = parse_span(payload)
        # Not when we fetched it. A parameter revised intraday is only
        # meaningful with the moment it was published attached.
        assert snapshot.as_of == "20260828"
        assert snapshot.run == "1"
        assert snapshot.created == "202608282128"

    def test_end_of_day_files_are_recognised(self):
        assert EOD_PATTERN.findall("TAKASEOD_-CCP__-BI-_____-260828-001.zip") == ["260828"]

    def test_intraday_files_are_not(self):
        # Nine to sixteen runs a day revise the parameter, so none of them is a
        # snapshot the map can be pinned to.
        assert EOD_PATTERN.findall("TAKASINT_-CCP__-BI-_____-260828-009.zip") == []


class TestRefusesToGuess:
    def test_an_archive_without_xml_raises(self, tmp_path):
        path = tmp_path / "empty.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("readme.txt", "nothing here")
        with pytest.raises(PsrUnavailable):
            parse_span(path.read_bytes())

    def test_an_archive_with_no_scan_ranges_raises(self, tmp_path):
        path = tmp_path / "bare.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("bare.xml", "<spanFile><fileFormat>4.00</fileFormat></spanFile>")
        with pytest.raises(PsrUnavailable):
            parse_span(path.read_bytes())


def snapshot_psr(payload: bytes, underlying: str) -> float:
    rate = parse_span(payload).get(underlying)
    assert rate is not None, f"{underlying} missing from the fixture"
    return rate.psr
