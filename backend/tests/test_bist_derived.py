"""
The boards derived from other boards: KAP parsing, VİOP parsing, the calendar
and the positioning ranking.

The two parsers carry the most weight. Both read somebody else's HTML, so the
question worth asking of each is not "does it work on the happy path" but "what
does it do when the shape changes" — and the answer has to be *nothing*, not a
half-parsed row of plausible numbers.
"""

from datetime import date

import pytest

from services.bist.calendar_service import build_calendar, group_by_day
from services.bist.kap_service import (
    RESTRICTION_PHRASES,
    Disclosure,
    filter_restrictions,
    is_restriction,
    parse_disclosure,
)
from services.bist.positioning_service import (
    MIN_FREE_FLOAT,
    build_positioning,
    futures_positioning,
    range_position,
)
from services.bist.tradingview_client import EquityRow
from services.bist.viop_service import ViopContract, _number, _repair_encoding, parse_board


def _equity(ticker, **kwargs) -> EquityRow:
    defaults: dict = {
        "ticker": ticker,
        "symbol": f"BIST:{ticker}",
        "name": f"{ticker} A.Ş.",
        "price": 100.0,
        "change_pct": 0.01,
        "change_abs": 1.0,
        "volume": 1000.0,
        "traded_value": 1000.0,
        "market_cap": 1_000.0,
        "pe": 10.0,
        "pb": 1.0,
        "ev_ebitda": 5.0,
        "free_float_pct": 0.4,
        "sector": "Finans",
        "indices": ("XU100",),
        "week52_high": 200.0,
        "week52_low": 50.0,
        "relative_volume": 1.5,
    }
    defaults.update(kwargs)
    return EquityRow(**defaults)


# ── KAP ────────────────────────────────────────────────────────────────────

_PAGE = (
    'junk before {"title":"Kredi Derecelendirmesi","mkkMemberOid":"x",'
    '"companyTitle":"JCR AVRASYA DERECELENDİRME A.Ş.","stockCode":"JCRAV",'
    '"relatedStocks":null,"disclosureClass":"DG","disclosureCategory":"ODA",'
    '"publishDate":"2026.08.27 15:06:10","disclosureIndex":1655377,'
    '"summary":"KREDİ DERECELENDİRME BİLDİRİMİ","isLate":false} junk after'
)


class TestKapParsing:
    def test_reads_a_disclosure_out_of_the_page(self):
        item = parse_disclosure(_PAGE, 1655377)
        assert item is not None
        assert item.ticker == "JCRAV"
        assert item.category == "ODA"
        assert item.category_label == "Özel durum açıklaması"
        assert item.published_at == "2026-08-27T15:06:10"
        assert item.url.endswith("/1655377")

    def test_handles_the_escaped_form_the_page_actually_ships(self):
        # The payload arrives inside a streamed script chunk with every quote
        # backslash-escaped.
        escaped = _PAGE.replace('"', '\\"')
        assert parse_disclosure(escaped, 1655377) is not None

    def test_declines_when_the_index_is_not_on_the_page(self):
        # The tape walks a range of integers; gaps in it are ordinary.
        assert parse_disclosure(_PAGE, 999) is None

    def test_declines_on_a_page_with_no_disclosure_fields(self):
        assert parse_disclosure('{"disclosureIndex":5}', 5) is None

    def test_an_unreadable_timestamp_is_none_rather_than_a_guess(self):
        broken = _PAGE.replace("2026.08.27 15:06:10", "not a date")
        item = parse_disclosure(broken, 1655377)
        assert item is not None and item.published_at is None

    def test_an_exchange_measure_takes_its_ticker_from_the_summary(self):
        # Borsa İstanbul files its own circuit breakers, so `stockCode` is empty
        # and the affected share is named only at the head of the summary.
        measure = (
            _PAGE.replace('"stockCode":"JCRAV"', '"stockCode":""')
            .replace(
                '"companyTitle":"JCR AVRASYA DERECELENDİRME A.Ş."',
                '"companyTitle":"BORSA İSTANBUL BISTECH DEVRE KESİCİ UYGULAMASI"',
            )
            .replace(
                '"summary":"KREDİ DERECELENDİRME BİLDİRİMİ"',
                '"summary":"SVGYO.E işlem sırasında Pay Bazında Devre Kesici '
                'Uygulaması devreye girmiştir"',
            )
        )
        item = parse_disclosure(measure, 1655377)
        assert item is not None and item.ticker == "SVGYO"

    def test_a_real_stock_code_wins_over_the_summary(self):
        shadowed = _PAGE.replace(
            '"summary":"KREDİ DERECELENDİRME BİLDİRİMİ"',
            '"summary":"SVGYO.E işlem sırasında"',
        )
        item = parse_disclosure(shadowed, 1655377)
        assert item is not None and item.ticker == "JCRAV"

    def test_a_ticker_mid_sentence_is_not_mistaken_for_the_filer(self):
        # Anchored at the start: a code inside the narrative belongs to the
        # story, not to the filing.
        narrative = _PAGE.replace('"stockCode":"JCRAV"', '"stockCode":""').replace(
            '"summary":"KREDİ DERECELENDİRME BİLDİRİMİ"',
            '"summary":"Şirketimiz THYAO.E paylarını satın almıştır"',
        )
        item = parse_disclosure(narrative, 1655377)
        assert item is not None and item.ticker == ""


def _disclosure(title: str, summary: str = "") -> Disclosure:
    return Disclosure(
        index=1,
        title=title,
        company="X",
        ticker="X",
        category="ODA",
        category_label="Özel durum açıklaması",
        published_at=None,
        summary=summary,
        is_late=False,
        url="",
    )


class TestRestrictions:
    def test_recognises_every_phrase_it_claims_to(self):
        for phrase in RESTRICTION_PHRASES:
            assert is_restriction(_disclosure(f"{phrase} Bildirimi"))

    def test_matches_case_insensitively(self):
        assert is_restriction(_disclosure("PAY BAZINDA DEVRE KESİCİ BİLDİRİMİ"))

    def test_reads_the_summary_as_well_as_the_title(self):
        assert is_restriction(_disclosure("Borsa Duyurusu", "Brüt Takas uygulanacaktır"))

    def test_leaves_ordinary_company_news_alone(self):
        assert not is_restriction(_disclosure("Kredi Derecelendirmesi"))
        assert not is_restriction(_disclosure("Finansal Rapor"))

    def test_filters_a_list(self):
        rows = [_disclosure("Devre Kesici"), _disclosure("Kar Payı Dağıtımı")]
        assert len(filter_restrictions(rows)) == 1


# ── VİOP ───────────────────────────────────────────────────────────────────

_VIOP_ROW = (
    "<tr>"
    "<td>THYAO (31 AÄŸu 26) Vadeli FIZ.</td><td>%-0,92</td><td>1.234,56</td>"
    "<td>1.240,00</td><td>1.200,00</td><td>2.786.465</td><td>42.647,00</td>"
    "<td>12,84</td><td>12,99</td><td>14:54:32</td>"
    "</tr>"
)


class TestViopParsing:
    def test_reads_a_contract_row(self):
        contracts = parse_board(_VIOP_ROW)
        assert len(contracts) == 1
        c = contracts[0]
        assert c.underlying == "THYAO"
        assert c.physical is True
        assert c.open_interest == pytest.approx(2_786_465)
        assert c.open_interest_change == pytest.approx(42_647)

    def test_repairs_the_mojibake_month(self):
        # The page is UTF-8 decoded as cp1252 upstream, so `Ağu` arrives as
        # `AÄŸu`. `Ÿ` is not in latin-1, which is why the repair has to try
        # cp1252 first — the first version tried latin-1 only and silently
        # did nothing.
        assert parse_board(_VIOP_ROW)[0].expiry == "31 Ağu 26"
        assert _repair_encoding("31 AÄŸu 26") == "31 Ağu 26"

    def test_leaves_clean_text_alone(self):
        assert _repair_encoding("31 Eyl 26") == "31 Eyl 26"

    def test_turkish_number_format(self):
        # `1.234,56` is one thousand two hundred; a plain float() reads 1.234.
        assert _number("1.234,56") == pytest.approx(1234.56)
        assert _number("%-0,92") == pytest.approx(-0.92)
        assert _number("-") is None
        assert _number("") is None

    def test_skips_a_row_with_the_wrong_shape(self):
        # A scrape that starts guessing produces a board of plausible wrong
        # numbers, which is worse than an empty one.
        short = "<tr><td>THYAO (31 Ağu 26) Vadeli</td><td>%1,0</td></tr>"
        assert parse_board(short) == []

    def test_skips_a_row_whose_label_is_not_a_contract(self):
        header = (
            "<tr><td>Toplam</td><td>1</td><td>2</td><td>3</td><td>4</td>"
            "<td>5</td><td>6</td><td>7</td><td>8</td><td>9</td></tr>"
        )
        assert parse_board(header) == []


# ── Calendar ───────────────────────────────────────────────────────────────


class TestCalendar:
    def test_includes_events_inside_the_window(self):
        rows = [_equity("A", next_earnings="2026-09-10", ex_dividend_date="2026-09-01")]
        events = build_calendar(rows, today=date(2026, 8, 27))
        assert {e.kind for e in events} == {"earnings", "dividend"}

    def test_excludes_events_past_the_horizon(self):
        rows = [_equity("A", next_earnings="2027-06-01")]
        assert build_calendar(rows, days_ahead=30, today=date(2026, 8, 27)) == []

    def test_keeps_a_results_date_that_just_passed(self):
        # "Did they report yet" is the same question as "when do they report",
        # asked a day later.
        rows = [_equity("A", next_earnings="2026-08-20")]
        events = build_calendar(rows, days_back=14, today=date(2026, 8, 27))
        assert len(events) == 1

    def test_orders_by_day_then_by_size(self):
        rows = [
            _equity("SMALL", market_cap=10.0, next_earnings="2026-09-01"),
            _equity("BIG", market_cap=900.0, next_earnings="2026-09-01"),
            _equity("LATER", market_cap=500.0, next_earnings="2026-09-05"),
        ]
        events = build_calendar(rows, today=date(2026, 8, 27))
        assert [e.ticker for e in events] == ["BIG", "SMALL", "LATER"]

    def test_dividend_events_carry_the_amount_and_earnings_do_not(self):
        rows = [
            _equity(
                "A",
                ex_dividend_date="2026-09-01",
                dividend_amount=1.5,
                next_earnings="2026-09-02",
                dividend_yield=0.1,
            )
        ]
        events = build_calendar(rows, today=date(2026, 8, 27))
        dividend = next(e for e in events if e.kind == "dividend")
        earnings = next(e for e in events if e.kind == "earnings")
        assert dividend.amount == 1.5 and dividend.yield_pct == 0.1
        assert earnings.amount is None and earnings.yield_pct is None

    def test_kind_filter(self):
        rows = [_equity("A", next_earnings="2026-09-01", ex_dividend_date="2026-09-02")]
        only = build_calendar(rows, kinds=frozenset({"dividend"}), today=date(2026, 8, 27))
        assert [e.kind for e in only] == ["dividend"]

    def test_group_by_day_buckets_and_counts(self):
        rows = [
            _equity("A", next_earnings="2026-09-01"),
            _equity("B", next_earnings="2026-09-01"),
            _equity("C", next_earnings="2026-09-03"),
        ]
        days = group_by_day(build_calendar(rows, today=date(2026, 8, 27)))
        assert [d["day"] for d in days] == ["2026-09-01", "2026-09-03"]
        assert days[0]["count"] == 2


# ── Positioning ────────────────────────────────────────────────────────────


class TestPositioning:
    def test_range_position_places_the_price_in_its_year(self):
        assert range_position(_equity("A", price=50.0)) == pytest.approx(0.0)
        assert range_position(_equity("A", price=200.0)) == pytest.approx(1.0)
        assert range_position(_equity("A", price=125.0)) == pytest.approx(0.5)

    def test_range_position_is_none_without_a_range(self):
        assert range_position(_equity("A", week52_high=None)) is None
        assert range_position(_equity("A", week52_high=50.0, week52_low=50.0)) is None

    def test_crowding_ignores_a_float_too_small_to_trade(self):
        # A bank with a 0.4% float scored 391 in the first version and outranked
        # every genuinely busy name on the board.
        shell = build_positioning([_equity("SHELL", free_float_pct=0.004, relative_volume=0.5)])
        assert shell[0].crowding is None

    def test_crowding_ignores_volume_that_is_not_elevated(self):
        quiet = build_positioning([_equity("QUIET", free_float_pct=0.5, relative_volume=0.4)])
        assert quiet[0].crowding is None

    def test_crowding_ranks_a_tight_float_with_heavy_volume_first(self):
        rows = build_positioning(
            [
                _equity("LOOSE", free_float_pct=0.9, relative_volume=2.0),
                _equity("TIGHT", free_float_pct=MIN_FREE_FLOAT + 0.01, relative_volume=3.0),
            ]
        )
        assert rows[0].ticker == "TIGHT"

    def test_unscored_rows_sort_outside_the_ranking(self):
        rows = build_positioning(
            [
                _equity("NOSCORE", free_float_pct=None, relative_volume=None),
                _equity("SCORED", free_float_pct=0.5, relative_volume=2.0),
            ]
        )
        assert [r.ticker for r in rows] == ["SCORED", "NOSCORE"]

    def test_open_interest_sums_across_expiries(self):
        contracts = [
            ViopContract(
                "THYAO 1", "THYAO", "Ağu", True, 1.0, 0.0, 1.0, 1.0, 100.0, 10.0, 1.0, 1.0, ""
            ),
            ViopContract(
                "THYAO 2", "THYAO", "Eyl", True, 1.0, 0.0, 1.0, 1.0, 250.0, -30.0, 1.0, 1.0, ""
            ),
        ]
        rows = build_positioning([_equity("THYAO")], contracts)
        assert rows[0].open_interest == pytest.approx(350.0)
        assert rows[0].open_interest_change == pytest.approx(-20.0)

    def test_a_stock_without_futures_has_no_open_interest(self):
        rows = build_positioning([_equity("NOFUT")], [])
        assert rows[0].open_interest is None

    def test_futures_view_ranks_by_absolute_change(self):
        contracts = [
            ViopContract("A", "A", "Ağu", True, 1.0, 0.0, 1.0, 1.0, 100.0, 5.0, 1.0, 1.0, ""),
            ViopContract("B", "B", "Ağu", True, 1.0, 0.0, 1.0, 1.0, 100.0, -80.0, 1.0, 1.0, ""),
        ]
        rows = build_positioning([_equity("A"), _equity("B")], contracts)
        # A large unwind is as interesting as a large build.
        assert [r.ticker for r in futures_positioning(rows)] == ["B", "A"]


# ── Turkish folding ────────────────────────────────────────────────────────


class TestTurkishFold:
    def test_dotted_capital_folds_to_a_plain_i(self):
        from services.bist.text import fold

        # The whole reason this module exists: `str.casefold` leaves a combining
        # dot behind and the two strings stop comparing equal.
        assert fold("KESİCİ") == fold("Kesici") == "kesici"
        assert "KESİCİ".casefold() != "Kesici".casefold()

    def test_dotless_capital_folds_to_a_dotless_i(self):
        from services.bist.text import fold

        assert fold("ISI") == "ısı"

    def test_other_turkish_letters_still_fold(self):
        from services.bist.text import fold

        assert fold("ÇAĞRI ŞÜKRÜ ÖZ") == "çağrı şükrü öz"

    def test_contains_survives_mixed_case_turkish(self):
        from services.bist.text import contains

        assert contains("TÜRKİYE İŞ BANKASI", "iş bankası")
        assert contains("Türkiye İş Bankası", "İŞ BANKASI")
        assert not contains("GARANTİ BANKASI", "akbank")
