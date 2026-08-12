"""
Holdings derived from Form 4.

The filing reports trades; the share count each trade leaves behind is the only
holding figure in it. Turning that into a position is one arithmetic mistake
away from a fabricated number, so the three rules that keep it honest are pinned
here: take the latest row per ownership bucket, never sum across buckets that
are the same holding worded twice, and never price what has no quote.
"""

from datetime import date

from services.ownership.providers.sec_form4 import _holding_positions

ISSUER = "Trump Media & Technology Group Corp."


def _row(
    key: str,
    shares: float,
    *,
    title: str = "Common Stock",
    ownership: str = "D",
    nature: str | None = None,
    occurred: date = date(2026, 3, 4),
) -> dict:
    return {
        "key": key,
        "issuer": ISSUER,
        "symbol": "DJT",
        "title": title,
        "ownership": ownership,
        "nature": nature,
        "shares": shares,
        "occurred": occurred,
        "filed_at": occurred,
        "url": "https://sec.gov/example",
    }


def test_the_latest_row_wins_and_earlier_ones_are_not_added_to_it():
    rows = [
        _row("direct", 1_000_000.0, occurred=date(2025, 11, 13)),
        _row("direct", 1_327_246.0, occurred=date(2026, 3, 4)),
    ]

    positions = _holding_positions(rows, {"DJT": 10.0})

    assert len(positions) == 1
    assert positions[0].quantity == 1_327_246.0
    assert positions[0].value_usd == 13_272_460.0


def test_one_holding_worded_two_ways_is_counted_once():
    # The same stake appears as a footnote reference on one filing and as the
    # trust's full name on another. Counted twice it doubles a $1bn position.
    rows = [
        _row("a", 114_750_000.0, ownership="I", nature="See Footnote 4"),
        _row(
            "b",
            114_750_000.0,
            ownership="I",
            nature="Held by the Donald J. Trump Revocable Trust",
            occurred=date(2026, 2, 1),
        ),
    ]

    positions = _holding_positions(rows, {})

    assert len(positions) == 1
    assert positions[0].quantity == 114_750_000.0


def test_direct_and_indirect_stakes_are_separate_positions():
    rows = [
        _row("direct", 61_098.0),
        _row("trust", 114_750_000.0, ownership="I", nature="Family trust"),
    ]

    positions = _holding_positions(rows, {})

    assert [p.quantity for p in positions] == [114_750_000.0, 61_098.0]
    assert positions[0].label == f"{ISSUER} · indirect (Family trust)"
    assert positions[1].label == ISSUER


def test_a_footnote_reference_is_not_printed_as_the_nature_of_ownership():
    positions = _holding_positions(
        [_row("trust", 100.0, ownership="I", nature="See Footnote 4")], {}
    )

    assert positions[0].label == f"{ISSUER} · indirect"


def test_a_holding_with_no_quote_keeps_its_shares_and_an_unknown_value():
    positions = _holding_positions([_row("direct", 37_498.0)], {})

    assert positions[0].quantity == 37_498.0
    assert positions[0].value_usd is None
    assert positions[0].value_basis == "unknown"
