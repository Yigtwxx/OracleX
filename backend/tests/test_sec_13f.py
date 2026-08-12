"""
Parsing of the 13F information table.

The rule under test is the one that fails silently and expensively: the `value`
column carries no unit, and reading a thousands-scaled filing as dollars puts a
$3bn book on the board as $3m without anything looking broken.
"""

from services.ownership.providers.sec_13f import _parse_info_table


def _table(rows: list[tuple[str, str, float, float]]) -> str:
    entries = "".join(
        f"""
        <infoTable>
          <nameOfIssuer>{issuer}</nameOfIssuer>
          <cusip>{cusip}</cusip>
          <value>{value:.0f}</value>
          <shrsOrPrnAmt><sshPrnamt>{shares:.0f}</sshPrnamt></shrsOrPrnAmt>
        </infoTable>
        """
        for cusip, issuer, value, shares in rows
    )
    return f"<informationTable>{entries}</informationTable>"


def test_values_reported_in_dollars_are_left_alone():
    xml = _table(
        [
            ("037833100", "APPLE INC", 250_000_000.0, 1_000_000.0),
            ("67066G104", "NVIDIA CORP", 180_000_000.0, 1_200_000.0),
        ]
    )

    holdings = _parse_info_table(xml)

    assert holdings["037833100"]["value"] == 250_000_000.0


def test_values_reported_in_thousands_are_scaled_to_dollars():
    # Duquesne's shape: 3.06m shares of Natera carried at 612,691, which is the
    # position in thousands and an implied 20c share price if read as dollars.
    xml = _table(
        [
            ("632307104", "NATERA INC", 612_691.0, 3_063_606.0),
            ("457669307", "INSMED INC", 188_717.0, 1_154_090.0),
        ]
    )

    holdings = _parse_info_table(xml)

    assert holdings["632307104"]["value"] == 612_691_000.0
    # Shares are not a scaled column and must survive untouched.
    assert holdings["632307104"]["shares"] == 3_063_606.0


def test_a_filing_with_no_share_counts_is_not_rescaled():
    # Principal-amount rows report 0 shares; with nothing to imply a price from,
    # guessing at the scale would be inventing a fact.
    xml = _table([("912828U24", "US TREASURY", 5_000.0, 0.0)])

    holdings = _parse_info_table(xml)

    assert holdings["912828U24"]["value"] == 5_000.0
