"""
The commentator step, at the places it could quietly lie.

Pinned here: the model never chooses the company (aliases match first); an
invented quote is dropped; a call is graded on the close after the video and
against the index; a lucky single call does not read as 100%; and a speaker
without a record moves nothing.
"""

from datetime import date

from services.bist.radar import voices as v
from services.bist.tradingview_client import EquityRow


def _row(ticker: str, name: str) -> EquityRow:
    return EquityRow(
        ticker=ticker,
        symbol=f"BIST:{ticker}",
        name=name,
        price=100.0,
        change_pct=0.0,
        change_abs=0.0,
        volume=1.0,
        traded_value=1.0,
        market_cap=1.0,
        pe=None,
        pb=None,
        ev_ebitda=None,
        free_float_pct=None,
        sector="",
        indices=("XU100",),
    )


class TestAliases:
    def test_generic_openers_are_not_aliases_on_their_own(self):
        aliases = v.aliases_for([_row("THYAO", "TÜRK HAVA YOLLARI A.O.")], {"THYAO": ["THY"]})
        assert "THYAO" in aliases["THYAO"]
        assert "THY" in aliases["THYAO"]
        assert "TÜRK" not in aliases["THYAO"]

    def test_distinctive_first_word_becomes_an_alias(self):
        aliases = v.aliases_for([_row("ASELS", "ASELSAN ELEKTRONİK SANAYİ VE TİCARET A.Ş.")], {})
        assert "ASELSAN" in aliases["ASELS"]


class TestMentions:
    def test_spoken_name_is_matched_turkish_folded_on_word_boundaries(self):
        segments = [
            {"start": 0.0, "text": "Bugün TÜPRAŞ'a bakalım"},
            {"start": 5.0, "text": "tüpraş güçlü duruyor"},
            {"start": 9.0, "text": "başka bir şey"},
        ]
        found = v.find_mentions(segments, {"TUPRS": ["Tüpraş"], "THYAO": ["THY"]})
        assert found == {"TUPRS": [0, 1]}

    def test_a_short_alias_does_not_match_inside_another_word(self):
        segments = [{"start": 0.0, "text": "bu bir sathy değil"}]
        assert v.find_mentions(segments, {"THYAO": ["THY"]}) == {}

    def test_passages_merge_overlapping_windows(self):
        segments = [{"start": float(i * 10), "text": f"s{i}"} for i in range(30)]
        text = v.passages(segments, [5, 6])
        assert text.count("[") == 1
        assert "s0" in text and "s11" in text and "s20" not in text


class TestStanceParsing:
    def test_valid_json_is_accepted_and_horizon_kept(self):
        raw = '{"stance": "bullish", "horizon_days": 7, "target": 320, "quote": "yükselir bence"}'
        parsed = v.parse_stance(raw, "dedi ki yükselir bence")
        assert parsed == {
            "stance": "bullish",
            "horizon_days": 7,
            "target": 320.0,
            "quote": "yükselir bence",
        }

    def test_an_invented_quote_is_dropped_not_shown(self):
        raw = '{"stance": "bearish", "horizon_days": null, "target": null, "quote": "kesin düşer"}'
        assert v.parse_stance(raw, "hiç alakasız metin")["quote"] == ""

    def test_an_unknown_stance_is_refused(self):
        assert v.parse_stance('{"stance": "maybe"}', "x") is None
        assert v.parse_stance("not json", "x") is None

    def test_json_inside_prose_is_still_read(self):
        raw = 'Here you go: {"stance": "neutral", "horizon_days": null, "target": null, "quote": ""} done'
        assert v.parse_stance(raw, "")["stance"] == "neutral"


def _call(stance: str = "bullish", said_at: str = "2026-08-01", horizon: int = 7, **kw) -> v.Call:
    base = {
        "key": "vid:TEST",
        "voice_id": "a",
        "voice_name": "A",
        "video_id": "vid",
        "video_title": "t",
        "url": "u",
        "ticker": "TEST",
        "stance": stance,
        "horizon_days": horizon,
        "target": None,
        "quote": "",
        "said_at": said_at,
    }
    base.update(kw)
    return v.Call(**base)


def _candles(closes: dict[str, float]) -> list[dict]:
    return [
        {"date": d, "close": c, "high": c * 1.01, "low": c * 0.99, "open": c, "volume": 1}
        for d, c in sorted(closes.items())
    ]


class TestGrading:
    STOCK = _candles(
        {
            "2026-08-01": 100.0,
            "2026-08-03": 100.0,
            "2026-08-05": 103.0,
            "2026-08-10": 108.0,
            "2026-08-12": 109.0,
        }
    )
    INDEX = _candles(
        {"2026-08-01": 1000.0, "2026-08-03": 1000.0, "2026-08-05": 1000.0, "2026-08-10": 1020.0}
    )

    def test_entry_is_the_close_after_the_video_and_the_index_is_subtracted(self):
        outcome = v.grade(_call(), self.STOCK, self.INDEX, today=date(2026, 8, 20))
        assert outcome["entry_date"] == "2026-08-03"
        assert outcome["exit_date"] == "2026-08-10"
        assert outcome["return"] == 0.08
        assert outcome["index_return"] == 0.02
        assert outcome["result"] == "hit"

    def test_a_bearish_call_on_a_rising_name_is_a_miss(self):
        outcome = v.grade(_call("bearish"), self.STOCK, self.INDEX, today=date(2026, 8, 20))
        assert outcome["result"] == "miss"

    def test_a_move_inside_the_noise_floor_is_flat(self):
        flat = _candles({"2026-08-01": 100.0, "2026-08-03": 100.0, "2026-08-10": 100.5})
        outcome = v.grade(_call(), flat, [], today=date(2026, 8, 20))
        assert outcome["result"] == "flat"

    def test_an_immature_call_stays_open(self):
        assert v.grade(_call(), self.STOCK, self.INDEX, today=date(2026, 8, 6)) is None

    def test_neutral_is_never_graded(self):
        assert v.grade(_call("neutral"), self.STOCK, self.INDEX, today=date(2026, 8, 20)) is None


class TestAccuracy:
    def test_one_lucky_call_does_not_read_as_certainty(self):
        calls = {"k": _call(outcome={"result": "hit"})}
        acc = v.accuracy_for(calls, "a")
        assert acc.raw == 1.0
        assert acc.shrunk == 0.6

    def test_pending_and_flat_are_counted_apart(self):
        calls = {
            "1": _call(outcome={"result": "hit"}),
            "2": _call(outcome={"result": "flat"}),
            "3": _call(),
        }
        acc = v.accuracy_for(calls, "a")
        assert (acc.hits, acc.flats, acc.pending, acc.n) == (1, 1, 1, 1)


class TestAdjustment:
    def _entry(self, stance: str, n: int, shrunk: float) -> dict:
        return {"voice_name": "A", "stance": stance, "accuracy": {"n": n, "shrunk": shrunk}}

    def test_a_speaker_without_a_record_moves_nothing(self):
        assert v.adjustment_for([self._entry("bullish", 3, 0.9)]) is None
        assert v.adjustment_for([self._entry("bullish", 20, 0.5)]) is None

    def test_a_proven_speaker_adds_or_subtracts_three(self):
        assert v.adjustment_for([self._entry("bullish", 12, 0.7)]).points == 3
        assert v.adjustment_for([self._entry("bearish", 12, 0.7)]).points == -3

    def test_opposing_proven_speakers_cancel(self):
        both = [self._entry("bullish", 12, 0.7), self._entry("bearish", 12, 0.7)]
        assert v.adjustment_for(both) is None


def test_registry_seed_loads():
    voices, aliases = v.load_registry()
    assert len(voices) >= 2
    assert all(voice.channel_id.startswith("UC") for voice in voices)
    assert "THY" in aliases["THYAO"]


async def test_no_candidates_is_a_checked_step_with_nothing_to_read():
    _out, report = await v.voices_for([], [])
    assert report.checked is True
    assert report.videos == 0
