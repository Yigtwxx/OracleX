"""
Reading equity positions out of a KAP portfolio report.

Every fixture here is a reduced copy of a real filing, and each one pins a
mistake this parser actually made against it:

* the wide layout's repo contract number, an eight-digit integer that is larger
  than a pledged position and was read as one;
* the two decimal locales, which appear in the same corpus and once in the same
  file;
* the glyph-substituted fonts, where `HİSSE SENETLERİ` extracts as
  `HĠSSE SENETLERĠ` and made every report from those houses unrecognisable;
* the `(ALIŞLAR)` / `(SATIŞLAR)` transaction registers further down the same
  document, which list the same tickers again and doubled a fund's book.

Pure text in, holdings out. Nothing here touches the network or a PDF.
"""

import pytest

from services.bist.fund_holdings import parse_equity_holdings

LETTERED = """
3- FON PORTFÖY DEĞERİ TABLOSU
                    İhraççı                       Nominal Değeri     Rayiç Değeri        %

 A) HİSSE SENETLERİ
    IEYHO           IŞIKLAR ENERJİ VE YAPI A.Ş.    81.775.746,00   13.697.437.455,00  41,32%
    ISKPL           IŞIK PLASTİK SANAYİ A.Ş.      136.662.351,00    1.087.832.313,96   3,28%
    TOPLAM:                                       219.073.097,00   14.847.087.018,96
 B) VARANTLAR
 C) DEVLET TAHVİLİ VE BONOLAR
    TRT12          HAZİNE                          10.000.000,00    9.500.000.000,00  28,66%
"""

WIDE = """
III-FON PORTFÖY DEĞERİ TABLOSU
 MENKUL KIYMET  DÖVİZ İHRAÇCI  NOMİNAL DEĞER  BİRİM ALIŞ  REPO TEMİNAT  GÜNLÜK BR  TOPLAM DEĞER   %

HİSSE SENETLERİ
Hisse Türk
AKSEN     TL   AKSA        30.944.626,00   102,781389   80100511   94,150000   2.913.436.537,90   6,60   5,21
ALKLC     TL   ALTINKILIÇ   1.165.000,00   255,087014               396,500000    461.922.500,00   1,05   0,83
ALKLC     TL   ALTINKILIÇ    -222.500,00   255,087014   80100511   396,500000    -88.221.250,00  -0,20  -0,16
TÜREV
VIOP Nakit Teminatı                                                                558.816,67  100,00   0,23
"""

US_LOCALE = """
3- FON PORTFÖY DEĞERİ TABLOSU
 A) HİSSE SENETLERİ
    ALBRK        ALBARAKA TÜRK KATILIM BANK      320,805.00     2,543,983.65   3.81%
    ARDYZ        ARD GRUP BİLİŞİM A.Ş.            42,203.00     3,051,276.90   4.57%
 B) VARANTLAR
"""

# `İ` extracts as `Ġ` and `Ş` as `ġ` from the fonts some houses embed.
GLYPH_FOLDED = """
III-FON PORTFÖY DEĞERĠ TABLOSU
HĠSSE SENETLERĠ
AHGAZ     TL   AHLATCI DOĞALGAZ    1.000.000,00   12,500000   12.500.000,00   13,40   9,10
TÜREV
"""

# The month's transaction registers, which repeat the same tickers.
WITH_REGISTERS = """
3- FON PORTFÖY DEĞERİ TABLOSU
 A) HİSSE SENETLERİ
    THYAO        TÜRK HAVA YOLLARI     100.000,00    30.000.000,00   60,00%
 B) VARANTLAR
IX-PORTFÖYE ALIŞLAR
 A) HİSSE SENETLERİ(ALIŞLAR)
    THYAO        TÜRK HAVA YOLLARI     100.000,00    30.000.000,00   60,00%
"""

BOND_FUND = """
III-FON PORTFÖY DEĞERİ TABLOSU
BORÇLANMA SENETLERİ
TRFAKYM82610  TL  AK YATIRIM   16.000.000,00   17.664.178,30   1,13
MEVDUAT
"""


class TestLetteredLayout:
    def test_reads_ticker_value_and_weight(self):
        report = parse_equity_holdings(LETTERED)
        assert report is not None
        assert report.layout == "lettered"
        assert [holding.ticker for holding in report.holdings] == ["IEYHO", "ISKPL"]

    def test_weight_is_a_share_of_the_equity_book(self):
        # The report says IEYHO is 41.32% of the *fund*; of the equity book it
        # is its value over the two rows' sum. The two denominators are kept
        # apart on purpose — see the module docstring.
        report = parse_equity_holdings(LETTERED)
        book = 13_697_437_455.00 + 1_087_832_313.96
        assert report.holdings[0].weight == pytest.approx(13_697_437_455.00 / book)
        assert sum(holding.weight for holding in report.holdings) == pytest.approx(1.0)

    def test_stops_at_the_next_lettered_section(self):
        # The government bond two sections down must not be read as equity.
        report = parse_equity_holdings(LETTERED)
        assert "TRT12" not in {holding.ticker for holding in report.holdings}

    def test_totals_line_is_not_a_holding(self):
        report = parse_equity_holdings(LETTERED)
        assert "TOPLAM" not in {holding.ticker for holding in report.holdings}

    def test_reads_the_other_decimal_locale(self):
        # `2,543,983.65` and `13.697.437.455,00` both appear in this corpus, so
        # the parser decides per token rather than sniffing the document.
        report = parse_equity_holdings(US_LOCALE)
        assert report is not None
        assert report.total_value == pytest.approx(2_543_983.65 + 3_051_276.90)


class TestWideLayout:
    def test_reads_the_value_from_the_right(self):
        report = parse_equity_holdings(WIDE)
        assert report is not None
        assert report.layout == "wide"
        assert report.holdings[0].ticker == "AKSEN"
        assert report.holdings[0].value == pytest.approx(2_913_436_537.90)

    def test_repo_contract_number_is_not_a_position(self):
        # `80100511` is a Takasbank contract id sitting mid-row. It is larger
        # than the pledged parcel beside it, so taking the largest figure on the
        # line read a contract number as a holding — this is that regression.
        report = parse_equity_holdings(WIDE)
        assert all(holding.value != pytest.approx(80_100_511.0) for holding in report.holdings)

    def test_lots_of_one_holding_are_netted(self):
        # ALKLC files twice: a parcel and a pledged one carrying a minus. The
        # position is the sum, not two rows for one company.
        report = parse_equity_holdings(WIDE)
        alklc = next(h for h in report.holdings if h.ticker == "ALKLC")
        assert alklc.value == pytest.approx(461_922_500.00 - 88_221_250.00)

    def test_derivative_collateral_is_not_equity(self):
        report = parse_equity_holdings(WIDE)
        assert "VIOP" not in {holding.ticker for holding in report.holdings}

    def test_reads_glyph_substituted_fonts(self):
        report = parse_equity_holdings(GLYPH_FOLDED)
        assert report is not None
        assert [holding.ticker for holding in report.holdings] == ["AHGAZ"]


class TestRefusals:
    def test_transaction_registers_do_not_double_the_book(self):
        report = parse_equity_holdings(WITH_REGISTERS)
        assert report is not None
        thyao = next(h for h in report.holdings if h.ticker == "THYAO")
        assert thyao.value == pytest.approx(30_000_000.00)

    def test_a_bond_fund_holds_no_equity_rather_than_being_unreadable(self):
        # The heading is omitted, not printed empty, so the two cases can only
        # be told apart by whether the report itself was recognised.
        report = parse_equity_holdings(BOND_FUND)
        assert report is not None
        assert report.holdings == ()

    def test_an_unrecognised_document_is_none(self):
        assert parse_equity_holdings("Bu bir portföy raporu değil.") is None

    def test_empty_input_is_none(self):
        assert parse_equity_holdings("") is None
