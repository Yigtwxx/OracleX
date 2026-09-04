"""
halkarz.com into structured offerings.

The source has no contract and no versioning, so the whole module is written to
fail visibly rather than quietly: an unparseable field is None and gets counted,
never guessed. These tests pin that. The ones that matter most are the negative
cases — a date that must not become today, a band that must not become a
midpoint, a row with no BIST code that must not be dropped.

The fixtures are live captures: the index trimmed to seven offerings plus one
deliberately malformed article, a completed offering carrying all three optional
blocks, and an upcoming one carrying none of them.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from services.bist import halkarz_client as hz

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index_rows() -> list[hz.IndexRow]:
    return hz.parse_index(fixture("halkarz_index.html"))


@pytest.fixture(scope="module")
def completed() -> hz.DetailFields:
    return hz.parse_detail(fixture("halkarz_detail_intet.html"))


@pytest.fixture(scope="module")
def upcoming() -> hz.DetailFields:
    return hz.parse_detail(fixture("halkarz_detail_upcoming.html"))


class TestTurkishDate:
    def test_a_two_day_window(self):
        parsed = hz.parse_turkish_date("26-27 Ağustos 2026")
        assert parsed == hz.DateRange(date(2026, 8, 26), date(2026, 8, 27))

    def test_a_three_day_window(self):
        parsed = hz.parse_turkish_date("24-25-26 Ağustos 2026")
        assert parsed == hz.DateRange(date(2026, 8, 24), date(2026, 8, 26))

    def test_a_range_across_two_months_takes_the_earlier_month_for_its_start(self):
        parsed = hz.parse_turkish_date("31 Ağustos - 1 Eylül 2026")
        assert parsed == hz.DateRange(date(2026, 8, 31), date(2026, 9, 1))

    def test_a_single_day(self):
        parsed = hz.parse_turkish_date("1 Eylül 2026")
        assert parsed == hz.DateRange(date(2026, 9, 1), date(2026, 9, 1))

    @pytest.mark.parametrize("month,number", list(hz.TR_MONTHS.items()))
    def test_every_turkish_month_resolves(self, month, number):
        # Capitals included, because the site is inconsistent about them and
        # Turkish uppercasing is not the ASCII one.
        for spelling in (month, month.upper(), month.capitalize()):
            parsed = hz.parse_turkish_date(f"3 {spelling} 2026")
            assert parsed is not None and parsed.start.month == number

    def test_the_site_marker_for_no_announced_date(self):
        assert hz.parse_turkish_date("Hazırlanıyor...") is None
        assert hz.parse_turkish_date("Hazırlanıyor…") is None

    def test_a_date_without_a_year_is_never_completed(self):
        # Assuming the current year would file a 2019 offering as upcoming.
        assert hz.parse_turkish_date("26-27 Ağustos") is None

    def test_a_reversed_range_is_rejected_rather_than_swapped(self):
        assert hz.parse_turkish_date("5 Eylül - 1 Ağustos 2026") is None

    def test_an_impossible_day_is_rejected(self):
        assert hz.parse_turkish_date("31 Şubat 2026") is None

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            None,
            "2026",
            "Yakında",
            "Foo Bar 2026",
            "--",
            "%%%",
            "2026-08-26",
            "x" * 5000,
            "1 " * 800 + "Ağustos 2026",
        ],
    )
    def test_never_raises_on_junk(self, raw):
        # The whole document is third-party text; a parser that raises takes the
        # board down with it.
        hz.parse_turkish_date(raw)


class TestNumbers:
    def test_lot_counts_treat_the_dot_as_a_thousands_separator(self):
        # `float("40.000")` is 40.0 and does not raise, which is how a
        # forty-million-lot offering silently becomes forty.
        assert hz.parse_lots("40.000.000 Lot") == 40_000_000
        assert hz.parse_lots("39.997.279 Lot") == 39_997_279
        assert hz.parse_lots("2.777") == 2777
        assert hz.parse_lots("38") == 38

    @pytest.mark.parametrize("raw", ["", None, "Lot", "—"])
    def test_unreadable_lots_are_none(self, raw):
        assert hz.parse_lots(raw) is None

    def test_a_single_price(self):
        assert hz.parse_try_amount("53,60 TL") == hz.Money(53.6, 53.6, False)

    def test_a_price_band_is_flagged_and_not_averaged(self):
        # A midpoint is a specific number nobody offered at, and a return
        # measured against it would look measured and be invented.
        assert hz.parse_try_amount("12,00 - 14,50 TL") == hz.Money(12.0, 14.5, True)

    def test_an_en_dash_band(self):
        assert hz.parse_try_amount("12,00 – 14,50 TL") == hz.Money(12.0, 14.5, True)

    def test_a_price_with_a_thousands_separator(self):
        assert hz.parse_try_amount("1.250,00 TL") == hz.Money(1250.0, 1250.0, False)

    @pytest.mark.parametrize("raw", ["", None, "TL", "belli değil"])
    def test_unreadable_price_is_none(self, raw):
        assert hz.parse_try_amount(raw) is None

    def test_percentages_in_both_orders(self):
        assert hz.parse_percent("%24,99") == pytest.approx(0.2499)
        assert hz.parse_percent("24,99%") == pytest.approx(0.2499)
        assert hz.parse_percent("%100") == pytest.approx(1.0)

    @pytest.mark.parametrize("raw", ["", None, "—", "yok"])
    def test_unreadable_percentage_is_none(self, raw):
        assert hz.parse_percent(raw) is None

    def test_timestamp(self):
        assert hz.parse_timestamp("03.09.2026 17:01") == "2026-09-03T17:01"
        assert hz.parse_timestamp("32.09.2026 17:01") is None
        assert hz.parse_timestamp("dün") is None


class TestTicker:
    @pytest.mark.parametrize("raw,expected", [("INTET", "INTET"), (" thyao ", "THYAO")])
    def test_accepts_a_bist_code(self, raw, expected):
        assert hz.normalise_ticker(raw) == expected

    @pytest.mark.parametrize("raw", ["", None, "not-a-ticker", "A", "TOOLONGCODE", "AB1"])
    def test_rejects_anything_else(self, raw):
        # The only field trusted structurally, so the gate is a regex rather
        # than a strip.
        assert hz.normalise_ticker(raw) is None


class TestClean:
    def test_caps_length_and_collapses_whitespace(self):
        assert hz.clean("  a\n\n  b  ", 20) == "a b"
        assert len(hz.clean("x" * 10_000, hz.MAX_COMPANY)) == hz.MAX_COMPANY

    def test_strips_control_characters(self):
        assert "\x00" not in (hz.clean("a\x00b", 20) or "")

    def test_empty_becomes_none(self):
        assert hz.clean("   ", 20) is None
        assert hz.clean(None, 20) is None


class TestIndex:
    def test_reads_every_well_formed_article(self, index_rows):
        assert len(index_rows) == 7

    def test_keeps_a_row_whose_bist_code_is_not_assigned_yet(self, index_rows):
        # The code arrives only when the exchange admits the share, so dropping
        # these would delete exactly the upcoming offerings the calendar is for.
        unassigned = [row for row in index_rows if row.ticker is None]
        assert len(unassigned) == 1
        assert unassigned[0].company
        assert unassigned[0].slug

    def test_carries_the_new_badge(self, index_rows):
        assert index_rows[0].is_new is True
        assert any(row.is_new is False for row in index_rows)

    def test_skips_a_malformed_article_without_losing_the_others(self, index_rows):
        # The fixture carries an eighth article with no heading at all.
        assert all(row.company for row in index_rows)

    def test_derives_slug_and_url_from_the_link(self, index_rows):
        row = next(row for row in index_rows if row.ticker == "INTET")
        assert row.slug == "intetra-teknoloji-ve-bilisim-hizmetleri-a-s"
        assert row.url == f"{hz.BASE}/{row.slug}/"

    def test_carries_the_raw_date_untouched_for_the_caller_to_parse(self, index_rows):
        assert index_rows[0].offer_dates_raw == "Hazırlanıyor..."


class TestSlug:
    @pytest.mark.parametrize(
        "href,expected",
        [
            ("https://halkarz.com/abc-a-s/", "abc-a-s"),
            ("https://halkarz.com/abc-a-s", "abc-a-s"),
            ("https://halkarz.com/", None),
            ("/relative/", None),
            ("", None),
            (None, None),
        ],
    )
    def test_slug_from_href(self, href, expected):
        assert hz.slug_from_href(href) == expected


class TestCompletedDetail:
    def test_reads_every_label_pair(self, completed):
        assert completed.ticker == "INTET"
        assert completed.offer_dates_raw == "26-27 Ağustos 2026"
        assert completed.price_raw == "53,60 TL"
        assert completed.lots_raw == "40.000.000 Lot"
        assert completed.free_float_lots_raw == "39.997.279 Lot"
        assert completed.free_float_pct_raw == "%24,99"
        assert completed.broker.startswith("Bulls Yatırım")
        assert completed.method == "Eşit Dağıtım"
        assert completed.market == "Yıldız Pazar"

    def test_the_listing_date_is_read(self, completed):
        # The field that makes a post-offering return computable at all, so it
        # gets its own assertion rather than riding along with the others.
        assert completed.listing_date_raw == "1 Eylül 2026"
        parsed = hz.parse_turkish_date(completed.listing_date_raw)
        assert parsed is not None and parsed.start == date(2026, 9, 1)

    def test_freshness_is_the_sites_own_stamp(self, completed):
        assert completed.updated_at == "2026-09-03T17:01"

    def test_allocation_groups_are_normalised_but_keep_their_labels(self, completed):
        keys = [group.key for group in completed.results.groups]
        assert keys == ["domestic_retail", "domestic_institutional", "foreign_retail"]
        assert completed.results.groups[0].label == "Yurt İçi Bireysel"
        assert completed.results.groups[0].lots == 39_905_887

    def test_the_total_row_is_a_denominator_not_a_group(self, completed):
        assert all(group.key != "total" for group in completed.results.groups)
        assert completed.results.total_lots == 40_000_000
        assert completed.results.total_investors == 653_433

    def test_the_companys_own_financial_table_is_not_read_as_an_allocation(self, completed):
        # The page carries other four-column tables; a row-shape match alone
        # happily reads "Brüt Kâr" as an investor group.
        labels = [group.label for group in completed.results.groups]
        assert not any("Kâr" in label or "Hasılat" in label for label in labels)

    def test_offer_structure_and_its_citation(self, completed):
        assert completed.structure.capital_increase_lots == 30_000_000
        assert completed.structure.share_sale_lots == 10_000_000
        assert completed.structure.capital_increase_share == pytest.approx(0.75)
        assert completed.structure.spk_bulletin == "2026/52"

    def test_use_of_proceeds_keeps_document_order_and_stops_at_its_own_citation(self, completed):
        lines = completed.use_of_proceeds
        assert len(lines) == 2
        assert lines[0].share == pytest.approx(0.35)
        assert lines[1].share == pytest.approx(0.65)
        assert sum(line.share for line in lines) == pytest.approx(1.0)
        assert completed.proceeds_source == "İzahname, sayfa 319"


class TestUpcomingDetail:
    def test_every_optional_block_is_absent_and_the_parse_still_succeeds(self, upcoming):
        # The assertion that stops an empty chart frame: an offering that has
        # not happened yet has no results, no listing date and no BIST code, and
        # none of that is an error.
        assert upcoming.results is None
        assert upcoming.use_of_proceeds is None
        assert upcoming.listing_date_raw is None
        assert upcoming.ticker is None

    def test_what_is_published_is_still_read(self, upcoming):
        assert upcoming.price_raw == "25,52 TL"
        assert upcoming.broker.startswith("Tacirler")
        assert upcoming.market == "Yıldız Pazar"
        assert upcoming.structure is not None

    def test_the_undated_marker_survives_to_the_caller(self, upcoming):
        assert upcoming.offer_dates_raw == "Hazırlanıyor..."
        assert hz.parse_turkish_date(upcoming.offer_dates_raw) is None


class TestRobustness:
    @pytest.mark.parametrize(
        "html", ["", "<html></html>", "<article class='index-list'></article>"]
    )
    def test_index_of_junk_is_empty_rather_than_an_exception(self, html):
        assert hz.parse_index(html) == []

    @pytest.mark.parametrize("html", ["", "<html></html>", "<p>Halka Arz Tarihi :</p>"])
    def test_detail_of_junk_is_empty_rather_than_an_exception(self, html):
        parsed = hz.parse_detail(html)
        assert parsed.ticker is None
        assert parsed.results is None

    def test_a_missing_label_costs_one_field_not_the_page(self):
        # Fields are keyed on their own label text, not on DOM position, so a
        # layout change should be survivable one field at a time.
        html = "<div><p>Bist Kodu :</p><p>ABCDE</p><p>Pazar :</p><p>Ana Pazar</p></div>"
        parsed = hz.parse_detail(html)
        assert parsed.ticker == "ABCDE"
        assert parsed.market == "Ana Pazar"
        assert parsed.broker is None

    def test_free_text_is_capped_at_parse_time(self):
        html = f"<div><p>Aracı Kurum :</p><p>{'x' * 5000}</p></div>"
        assert len(hz.parse_detail(html).broker) == hz.MAX_BROKER
