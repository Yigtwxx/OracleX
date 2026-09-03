"""
Reading a shareholder table off İş Yatırım's company card.

What is pinned is the shape of the page as observed, not the parser's
internals: the table is a JavaScript literal for a pie chart, `Diğer` is the
free float and not a holder, the headline ratios use Turkish decimal marks,
and a page without the table element is not a company card at all — which
must come back as "no card" and never as "no holder above 5%".
"""

import pytest

from services.bist.ownership.isyatirim_client import parse_company_card

CARD = """
<html><body>
<table><tbody>
<tr> <th>FD/Satışlar</th> <td>0,7</td> </tr>
<tr> <th>Yabancı Oranı (%)</th> <td>53,22</td> </tr>
<tr> <th>Piyasa Değeri</th> <td>544.457,3 mnTL</td> </tr>
<tr> <th>Halka Açıklık Oranı (%)</th> <td>26,3</td> </tr>
</tbody></table>
<div class="table vertical zebra"> <table id="partnerShipTable" class="partnerShipTable">
<thead> <tr> <th>Ticari Ünvan</th> <th>Pay Oranı(%)</th> </tr> </thead> <tbody></tbody> </table> </div>
<script type="text/javascript">
var OrtaklikYapisidata = [{name: 'Diğer',y: 42.81},{name: 'Semahat Sevim Arsel',y: 6.15},
{name: 'Family Danışmanlık Gayrimenkul Ve Ticaret Anonim Ş',y: 43.75},{name: 'Vehbi Koç Vakfı',y: 7.29}];
jqueryCompletefunctions.push(function () { site.components.charts.chartPartnerShip.init(OrtaklikYapisidata); });
</script>
</body></html>
"""


def test_reads_holders_largest_first_and_keeps_other_apart():
    card = parse_company_card(CARD, "KCHOL")

    assert card is not None
    assert [s.name for s in card.shareholders] == [
        "Family Danışmanlık Gayrimenkul Ve Ticaret Anonim Ş",
        "Vehbi Koç Vakfı",
        "Semahat Sevim Arsel",
    ]
    assert card.shareholders[0].pct == 43.75
    # The free float is not a shareholder. Listed as one it would be the
    # biggest holder of most companies on the board.
    assert card.other_pct == 42.81
    assert all(s.name != "Diğer" for s in card.shareholders)


def test_reads_headline_ratios_with_turkish_decimal_marks():
    card = parse_company_card(CARD, "KCHOL")

    assert card is not None
    assert card.foreign_ratio_pct == 53.22
    assert card.free_float_pct == 26.3
    # `544.457,3 mnTL` is millions of lira.
    assert card.market_cap_try == pytest.approx(544_457_300_000.0)


def test_a_page_with_neither_table_is_not_a_card():
    body = (
        CARD.replace('id="partnerShipTable"', 'id="something-else"')
        .replace("Halka Açıklık Oranı (%)", "x")
        .replace("Piyasa Değeri", "y")
    )

    assert parse_company_card(body, "NOPE") is None


def test_a_card_without_the_shareholder_table_is_still_a_card():
    # KRDMD: 93% free float, nobody above 5%, and İş Yatırım does not render
    # the table at all. The ratios are there and the answer is "no holder".
    body = CARD.replace('id="partnerShipTable"', 'id="something-else"')

    card = parse_company_card(body, "KRDMD")

    assert card is not None
    assert card.free_float_pct == 26.3


def test_a_card_with_the_table_and_no_named_holder_is_a_real_answer():
    body = CARD.replace(
        "var OrtaklikYapisidata = [{name: 'Diğer',y: 42.81},{name: 'Semahat Sevim Arsel',y: 6.15},\n"
        "{name: 'Family Danışmanlık Gayrimenkul Ve Ticaret Anonim Ş',y: 43.75},{name: 'Vehbi Koç Vakfı',y: 7.29}];",
        "var OrtaklikYapisidata = [];",
    )
    card = parse_company_card(body, "KRDMD")

    assert card is not None
    assert card.shareholders == ()
    assert card.other_pct is None


def test_unescapes_quotes_and_entities_in_names():
    body = CARD.replace(
        "{name: 'Vehbi Koç Vakfı',y: 7.29}",
        "{name: 'O\\'Neil &amp; Sons',y: 7.29}",
    )
    card = parse_company_card(body, "KCHOL")

    assert card is not None
    assert "O'Neil & Sons" in [s.name for s in card.shareholders]


def test_market_cap_in_an_unexpected_unit_is_refused():
    body = CARD.replace("544.457,3 mnTL", "544.457,3 bnUSD")
    card = parse_company_card(body, "KCHOL")

    assert card is not None
    assert card.market_cap_try is None
