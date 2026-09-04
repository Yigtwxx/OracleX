"""
The grounded read behind the KAP tape's analysis button.

The prose is never tested; the two properties that would fail silently are:

* **Bucketing.** A filing never changes but the share beside it moves every two
  minutes, so a note fingerprinted on a live `change_pct` would be rewritten all
  afternoon for a document that is identical each time. The tests asserting an
  unchanged fingerprint across a small price move are what keep that from
  regressing back into a permanent cache entry that never hits.
* **`disclosure_values` derives from the facts and from nothing else.** That is
  the contract that stops a cached note from quoting a reading that has since
  moved, and a builder reaching past its argument would look identical in review.
"""

import pytest

from services.ai_notes import fingerprint
from services.bist import kap_note as k
from services.bist.kap_service import Disclosure
from services.bist.tradingview_client import EquityRow


def filing(**overrides) -> Disclosure:
    fields = {
        "index": 1655377,
        "title": "Pay Geri Alım İşlemleri",
        "company": "ÖRNEK HOLDİNG A.Ş.",
        "ticker": "ORNEK",
        "category": "ODA",
        "category_label": "Özel Durum Açıklaması",
        "published_at": "2026-08-27T15:06:10",
        "summary": "Şirketimiz 100.000 adet payı 42,50 TL ortalama fiyatla geri almıştır.",
        "is_late": False,
        "url": "https://www.kap.org.tr/tr/Bildirim/1655377",
    }
    fields.update(overrides)
    return Disclosure(**fields)


def share(**overrides) -> EquityRow:
    fields = {
        "ticker": "ORNEK",
        "symbol": "BIST:ORNEK",
        "name": "Örnek Holding",
        "price": 42.5,
        "change_pct": 0.032,
        "change_abs": 1.3,
        "volume": 1_000_000.0,
        "traded_value": 42_500_000.0,
        "market_cap": 80_000_000_000.0,
        "pe": 8.0,
        "pb": 1.2,
        "ev_ebitda": None,
        "free_float_pct": 30.0,
        "sector": "Holding ve Yatırım Şirketleri",
        "indices": ("XU100", "XU030"),
        "perf_1y": 0.41,
        "relative_volume": 2.6,
    }
    fields.update(overrides)
    return EquityRow(**fields)


# ── Bucketing ────────────────────────────────────────────────────────────────


def test_a_small_intraday_move_does_not_retire_the_note():
    """The whole cache design: an unchanged filing is an unchanged fingerprint."""
    before = k.disclosure_facts(filing(), share(change_pct=0.032))
    after = k.disclosure_facts(filing(), share(change_pct=0.034))
    assert fingerprint(k.NOTE_SPEC, before) == fingerprint(k.NOTE_SPEC, after)


def test_a_move_across_a_bucket_does_retire_it():
    quiet = k.disclosure_facts(filing(), share(change_pct=0.002))
    limit_up = k.disclosure_facts(filing(), share(change_pct=0.098))
    assert fingerprint(k.NOTE_SPEC, quiet) != fingerprint(k.NOTE_SPEC, limit_up)


def test_two_different_filings_are_two_different_notes():
    one = k.disclosure_facts(filing(index=1, title="Pay Geri Alım İşlemleri"))
    two = k.disclosure_facts(filing(index=2, title="Sermaye Artırımı"))
    assert fingerprint(k.NOTE_SPEC, one) != fingerprint(k.NOTE_SPEC, two)


def test_a_capitalisation_that_moved_within_its_band_is_the_same_note():
    """A band, not a figure — otherwise a day's rally rewrites yesterday's filing."""
    before = k.disclosure_facts(filing(), share(market_cap=80_000_000_000.0))
    after = k.disclosure_facts(filing(), share(market_cap=84_000_000_000.0))
    assert fingerprint(k.NOTE_SPEC, before) == fingerprint(k.NOTE_SPEC, after)


def test_a_flat_session_is_never_rendered_as_negative_zero():
    facts = k.disclosure_facts(filing(), share(change_pct=-0.0001))
    assert "-0%" not in k.disclosure_values(facts)["market"]


# ── The rendered blocks ──────────────────────────────────────────────────────


def test_values_fills_every_placeholder_the_prompt_declares():
    from services.prompts import load_prompt

    template = load_prompt("notes/kap_disclosure")
    values = k.disclosure_values(k.disclosure_facts(filing(), share()))
    for key in values:
        assert f"{{{{{key}}}}}" in template, f"{key} is rendered but never used"


def test_the_filing_is_quoted_verbatim():
    values = k.disclosure_values(k.disclosure_facts(filing(), share()))
    assert "Pay Geri Alım İşlemleri" in values["filing"]
    assert "100.000 adet" in values["filing"]


def test_a_filing_with_no_ticker_forbids_characterising_a_share():
    """
    Borsa İstanbul files its own notices with no stock code.

    Left unstated, the model reaches for the session it usually gets and
    describes a share that does not exist behind the filing.
    """
    values = k.disclosure_values(k.disclosure_facts(filing(ticker="", company="BORSA İSTANBUL")))
    assert "No session reading was available" in values["market"]
    assert "Do not characterise the share" in values["market"]
    assert "not attributed to a listed share" in values["company"]


def test_an_unreachable_equity_board_reads_as_a_gap_not_a_flat_session():
    values = k.disclosure_values(k.disclosure_facts(filing(), None))
    assert "No session reading was available" in values["market"]
    assert "0%" not in values["market"]


def test_an_empty_summary_says_the_filing_cannot_be_sized():
    """A body in an attachment is a gap, not a filing with nothing in it."""
    values = k.disclosure_values(k.disclosure_facts(filing(summary=""), share()))
    assert "classified but not sized" in values["filing"]


def test_a_late_filing_is_named_as_late():
    values = k.disclosure_values(k.disclosure_facts(filing(is_late=True), share()))
    assert "late" in values["filing"]


def test_an_overlong_summary_is_bounded_before_it_reaches_the_prompt():
    values = k.disclosure_values(k.disclosure_facts(filing(summary="a " * 4000), share()))
    assert len(values["filing"]) < k.MAX_SUMMARY_CHARS + 600


def test_session_readings_are_stated_as_rounded():
    values = k.disclosure_values(k.disclosure_facts(filing(), share()))
    assert "rounded" in values["market"]
    assert "+3%" in values["market"]
    assert "2.5x" in values["market"]


@pytest.mark.parametrize(
    "market_cap,expected",
    [
        (80_000_000_000.0, "large"),
        (20_000_000_000.0, "mid"),
        (2_000_000_000.0, "small"),
        (None, None),
    ],
)
def test_size_bands(market_cap, expected):
    facts = k.disclosure_facts(filing(), share(market_cap=market_cap))
    assert facts["session"]["size"] == expected


# ── The route ────────────────────────────────────────────────────────────────


class TestKapNoteRoute:
    """
    The button's endpoint. Three behaviours the tape depends on.

    The equity lookup is the interesting one: it is enrichment, not a
    dependency, and an outage on the scanner must cost the note its session
    clause rather than costing the reader their answer.
    """

    def _client(self):
        from fastapi.testclient import TestClient

        from main import app

        return TestClient(app)

    def test_an_index_kap_does_not_serve_is_a_404(self, monkeypatch):
        async def _missing(index: int):
            return None

        monkeypatch.setattr("routers.bist.fetch_disclosure", _missing)
        assert self._client().get("/api/bist/kap/1/note").status_code == 404

    def test_the_filing_travels_back_with_the_note(self, monkeypatch):
        async def _one(index: int):
            return filing(index=index)

        async def _share(ticker: str):
            return share()

        async def _note(disclosure, equity=None, user_id=None):
            assert equity is not None, "the session should have been looked up"
            return {"status": "ready", "note": "Bir cümle.", "generated_at": None, "reason": None}

        monkeypatch.setattr("routers.bist.fetch_disclosure", _one)
        monkeypatch.setattr("routers.bist.fetch_equity", _share)
        monkeypatch.setattr("routers.bist.note_for_disclosure", _note)

        payload = self._client().get("/api/bist/kap/1655377/note").json()
        assert payload["disclosure"]["index"] == 1655377
        assert payload["note"]["note"] == "Bir cümle."

    def test_an_unreachable_equity_board_still_answers(self, monkeypatch):
        """A note without its session clause beats no note at all."""
        from services.bist.equity_service import EquityDataUnavailable

        async def _one(index: int):
            return filing(index=index)

        async def _down(ticker: str):
            raise EquityDataUnavailable("scanner is down")

        async def _note(disclosure, equity=None, user_id=None):
            assert equity is None
            return {"status": "generating", "note": None, "generated_at": None, "reason": None}

        monkeypatch.setattr("routers.bist.fetch_disclosure", _one)
        monkeypatch.setattr("routers.bist.fetch_equity", _down)
        monkeypatch.setattr("routers.bist.note_for_disclosure", _note)

        response = self._client().get("/api/bist/kap/1655377/note")
        assert response.status_code == 200
        assert response.json()["note"]["status"] == "generating"
