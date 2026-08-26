"""
The electoral calendar parser: what it reads, and what it refuses to guess.

The upstream is prose, not a schema, so almost every test here pins a shape the
live 2026 and 2027 pages actually use rather than one the parser was designed
around. Three of them exist because the first draft got the answer wrong:

* the article writes a shared polling day as a bare `18 April:` with the
  countries on nested bullets beneath it. Requiring a remainder dropped that
  line, and France then inherited the previous bullet's 10 April.
* the italics that mark a dependent territory wrap the countries, not the
  bullet, so unwrapping them before reading the date never fired.
* a month with no announced day ("March: Estonia") is a real scheduled election
  and must not vanish, but it also must not claim the first of the month.

Nothing here touches the network.
"""

import pytest

from services.elections import wikipedia


def _page(*sections: str) -> str:
    return "\n".join(sections)


def _month(name: str, *bullets: str) -> str:
    return "\n".join([f"== {name} ==", *bullets])


# ==========================================
# ROWS
# ==========================================


def test_a_dated_bullet_becomes_one_row():
    rows = wikipedia.parse_calendar(
        _month(
            "January",
            "* 15 January: [[Elections in Uganda|Uganda]], "
            "[[2026 Ugandan general election|President and Parliament]]",
        ),
        2026,
    )

    assert len(rows) == 1
    assert rows[0].date.isoformat() == "2026-01-15"
    assert rows[0].country == "Uganda"
    assert rows[0].office == "President and Parliament"
    assert rows[0].precision == "day"
    assert rows[0].minor is False


def test_the_country_is_the_first_wikilink_display_text():
    """A country containing "and" is why the split cannot be on the comma."""
    rows = wikipedia.parse_calendar(
        _month(
            "October",
            "* 4 October: [[Elections in Bosnia and Herzegovina|Bosnia and Herzegovina]], "
            "[[2026 Bosnian general election|General]]",
        ),
        2026,
    )

    assert rows[0].country == "Bosnia and Herzegovina"
    assert rows[0].office == "General"


def test_an_unpiped_wikilink_is_read_as_its_own_country():
    rows = wikipedia.parse_calendar(
        _month("August", "* 10 August: [[Kenya]], [[2027 Kenyan general election|President]]"),
        2027,
    )

    assert rows[0].country == "Kenya"


def test_the_year_comes_from_the_page_not_from_the_bullet():
    """Which is what makes the year boundary correct without any special case."""
    rows = wikipedia.parse_calendar(
        _month(
            "January", "* 16 January: [[Nigeria]], [[2027 Nigerian general election|President]]"
        ),
        2027,
    )

    assert rows[0].date.year == 2027


# ==========================================
# CITATIONS AND MARKUP
# ==========================================


def test_a_reference_tail_is_not_part_of_the_office():
    rows = wikipedia.parse_calendar(
        _month(
            "January",
            "* 27 January: [[Elections in Kyrgyzstan|Kyrgyzstan]], "
            "[[2027 Kyrgyz presidential election|President]]"
            "<ref>{{Cite web |title=Something |url=https://example.invalid}}</ref>",
        ),
        2027,
    )

    assert rows[0].office == "President"


def test_an_unclosed_reference_does_not_leak_into_the_office():
    """A citation that opens on this line and closes on the next."""
    rows = wikipedia.parse_calendar(
        _month(
            "April",
            "* 10 April: [[Elections in the Gambia|Gambia]], "
            "[[2027 Gambian parliamentary election|Parliament]]<ref>{{Cite web |last=Editor",
        ),
        2027,
    )

    assert rows[0].office == "Parliament"


def test_an_html_comment_is_not_read_as_content():
    rows = wikipedia.parse_calendar(
        _month("May", "* 3 May: [[Burundi]], [[…|President]]<!-- date unconfirmed -->"),
        2027,
    )

    assert rows[0].office == "President"


# ==========================================
# DEPENDENT TERRITORIES
# ==========================================


def test_italics_after_the_date_mark_the_row_minor():
    """
    The article italicises the countries, leaving the date outside the marks.
    Checking the bullet for a wrapping ''…'' therefore never fires.
    """
    rows = wikipedia.parse_calendar(
        _month(
            "February",
            "* 6 February: ''[[Elections in Tokelau|Tokelau]], "
            "[[2026 Tokelauan general election|Parliament]]''",
        ),
        2026,
    )

    assert rows[0].country == "Tokelau"
    assert rows[0].minor is True


def test_a_sovereign_row_beside_a_territory_is_not_marked_minor():
    rows = wikipedia.parse_calendar(
        _month(
            "February",
            "* 6 February: ''[[Elections in Tokelau|Tokelau]], [[…|Parliament]]''",
            "* 6 February: [[Elections in Japan|Japan]], [[…|House of Representatives]]",
        ),
        2026,
    )

    assert [(row.country, row.minor) for row in rows] == [("Tokelau", True), ("Japan", False)]


# ==========================================
# NESTED BULLETS
# ==========================================


def test_a_bare_date_line_gives_its_day_to_the_bullets_beneath_it():
    """
    The regression that matters most. `18 April:` carries no country of its own;
    dropping it put the French presidential election on the 10th.
    """
    rows = wikipedia.parse_calendar(
        _month(
            "April",
            "* 10 April: [[Elections in the Gambia|Gambia]], [[…|Parliament]]",
            "* 18 April: ",
            "** [[Elections in France|France]], [[2027 French presidential election|President]]",
            "** [[Elections in Finland|Finland]], [[…|Parliament]]",
        ),
        2027,
    )

    assert [(row.country, row.date.isoformat()) for row in rows] == [
        ("Gambia", "2027-04-10"),
        ("France", "2027-04-18"),
        ("Finland", "2027-04-18"),
    ]


def test_a_bare_date_line_is_not_a_row_of_its_own():
    rows = wikipedia.parse_calendar(
        _month("October", "* 24 October:", "** [[Argentina]], [[…|President]]"),
        2027,
    )

    assert len(rows) == 1


def test_a_nested_bullet_inherits_the_date_of_the_dated_bullet_above_it():
    rows = wikipedia.parse_calendar(
        _month(
            "September",
            "* 24 September: [[Elections in the Isle of Man|Isle of Man]], [[…|House of Keys]]",
            "** ''[[Elections in Jersey|Jersey]], [[2026 Jersey general election|Parliament]]''",
        ),
        2026,
    )

    assert [(row.country, row.date.isoformat(), row.minor) for row in rows] == [
        ("Isle of Man", "2026-09-24", False),
        ("Jersey", "2026-09-24", True),
    ]


def test_a_nested_bullet_with_no_date_above_it_is_dropped():
    """Rather than attaching to whatever the previous section happened to end on."""
    rows = wikipedia.parse_calendar(
        _page(
            _month("January", "* 15 January: [[Uganda]], [[…|President]]"),
            _month("February", "** [[Nowhere]], [[…|Parliament]]"),
        ),
        2026,
    )

    assert [row.country for row in rows] == ["Uganda"]


# ==========================================
# DATE SHAPES
# ==========================================


def test_a_day_range_records_the_last_polling_day():
    rows = wikipedia.parse_calendar(
        _month("September", "* 13–14 September: [[Nowhere]], [[…|Parliament]]"),
        2026,
    )

    assert rows[0].date.isoformat() == "2026-09-13"
    assert rows[0].through.isoformat() == "2026-09-14"


def test_a_range_crossing_a_month_boundary_resolves_both_ends():
    rows = wikipedia.parse_calendar(
        _month("March", "* 31 March – 1 April: [[Nowhere]], [[…|Parliament]]"),
        2026,
    )

    assert rows[0].date.isoformat() == "2026-03-31"
    assert rows[0].through.isoformat() == "2026-04-01"


def test_a_month_with_no_announced_day_is_kept_but_flagged():
    """Estonia, Greece and Oman all sit like this; dropping them would report
    those countries as holding no election at all."""
    rows = wikipedia.parse_calendar(
        _month(
            "March", "* March: [[Estonia]], [[Next Estonian parliamentary election|Parliament]]"
        ),
        2027,
    )

    assert rows[0].precision == "month"
    assert rows[0].date.isoformat() == "2027-03-01"


def test_two_rounds_written_on_one_line_are_dropped_rather_than_mis_dated():
    """Two rounds are two catalysts. A bullet that will not say which is which
    is a bullet we decline to place."""
    rows = wikipedia.parse_calendar(
        _page(
            _month("March", "* 15 and 22 March: [[Nowhere]], [[…|President]]"),
            _month("April", "* 1 April: [[Somewhere]], [[…|Parliament]]"),
        ),
        2026,
    )

    assert [row.country for row in rows] == ["Somewhere"]


def test_an_impossible_date_drops_the_row_rather_than_raising():
    rows = wikipedia.parse_calendar(
        _page(
            _month("February", "* 31 February: [[Nowhere]], [[…|Parliament]]"),
            _month("March", "* 1 March: [[Somewhere]], [[…|Parliament]]"),
        ),
        2026,
    )

    assert [row.country for row in rows] == ["Somewhere"]


def test_a_row_filed_far_from_its_section_month_is_dropped():
    """A month away is the `31 March – 1 April` case and is allowed; six is a
    mis-tracked section, and a row under the wrong month is a parse error."""
    rows = wikipedia.parse_calendar(
        _page(
            _month("March", "* 4 September: [[Nowhere]], [[…|Parliament]]"),
            _month("April", "* 1 April: [[Somewhere]], [[…|Parliament]]"),
        ),
        2026,
    )

    assert [row.country for row in rows] == ["Somewhere"]


# ==========================================
# SECTIONS
# ==========================================


def test_rows_under_unknown_date_are_not_dated_rows():
    rows = wikipedia.parse_calendar(
        _page(
            _month("January", "* 15 January: [[Uganda]], [[…|President]]"),
            _month("Unknown date", "* [[Libya]], [[…|President]]"),
        ),
        2026,
    )

    assert [row.country for row in rows] == ["Uganda"]


def test_rows_under_indirect_elections_are_not_dated_rows():
    rows = wikipedia.parse_calendar(
        _page(
            _month("January", "* 15 January: [[Uganda]], [[…|President]]"),
            _month("Indirect elections", "* 3 March: [[Nowhere]], [[…|President]]"),
        ),
        2026,
    )

    assert [row.country for row in rows] == ["Uganda"]


def test_a_section_the_page_invents_is_ignored_rather_than_parsed():
    """
    The reason sections are allowlisted by month name instead of blocklisted.
    A denylist fails open on exactly the heading nobody foresaw.
    """
    rows = wikipedia.parse_calendar(
        _page(
            _month("January", "* 15 January: [[Uganda]], [[…|President]]"),
            _month("Provisionally scheduled", "* 3 March: [[Nowhere]], [[…|President]]"),
        ),
        2026,
    )

    assert [row.country for row in rows] == ["Uganda"]


def test_references_and_see_also_contribute_nothing():
    rows = wikipedia.parse_calendar(
        _page(
            _month("January", "* 15 January: [[Uganda]], [[…|President]]"),
            _month("See also", "* [[Lists of elections]]"),
            _month("References", "{{Reflist}}"),
        ),
        2026,
    )

    assert len(rows) == 1


# ==========================================
# REFUSAL
# ==========================================


def test_a_page_with_no_dated_rows_is_a_broken_shape():
    """
    A year page always has dated rows, even in December when all of them are
    past. Reporting an empty parse as "no elections this year" would be a claim
    about the world rather than about the fetch.
    """
    with pytest.raises(ValueError):
        wikipedia.parse_calendar(_month("Unknown date", "* [[Libya]], [[…|President]]"), 2026)


def test_one_row_is_enough():
    """The threshold is a shape check, not a coverage check — a page for a year
    two out legitimately carries a handful of rows."""
    rows = wikipedia.parse_calendar(
        _month("January", "* 16 January: [[Nigeria]], [[…|President]]"), 2028
    )

    assert len(rows) == 1


# ==========================================
# THE REQUEST
# ==========================================


async def test_the_request_asks_for_wikitext_at_formatversion_two(monkeypatch):
    captured = {}

    async def get_json(url, *, params=None, headers=None, timeout=None):
        captured.update(url=url, params=params, headers=headers, timeout=timeout)
        return {"parse": {"wikitext": "== January ==\n* 15 January: [[Uganda]], [[…|President]]"}}

    monkeypatch.setattr(wikipedia, "get_json", get_json)
    await wikipedia.fetch_year(2026)

    assert captured["params"]["page"] == "2026_national_electoral_calendar"
    assert captured["params"]["prop"] == "wikitext"
    assert captured["params"]["formatversion"] == "2"
    assert captured["params"]["redirects"] == "1"


async def test_the_request_identifies_the_client_to_wikimedia(monkeypatch):
    """
    Wikimedia enforces its User-Agent policy with 403s, and the shared default
    advertises a host nobody can reach. A block here would be silent and
    permanent.
    """
    captured = {}

    async def get_json(url, *, params=None, headers=None, timeout=None):
        captured.update(headers=headers)
        return {"parse": {"wikitext": "== January ==\n* 15 January: [[Uganda]], [[…|President]]"}}

    monkeypatch.setattr(wikipedia, "get_json", get_json)
    await wikipedia.fetch_year(2026)

    agent = (captured["headers"] or {}).get("User-Agent", "")
    assert "oracle-x.local" not in agent
    assert "github.com" in agent


async def test_a_page_that_does_not_exist_yet_raises(monkeypatch):
    """How `missingtitle` arrives for a year nobody has written up. Normal for a
    future year — the service above decides that, not this module."""

    async def get_json(url, *, params=None, headers=None, timeout=None):
        return {"error": {"code": "missingtitle"}}

    monkeypatch.setattr(wikipedia, "get_json", get_json)

    with pytest.raises(ValueError):
        await wikipedia.fetch_year(2031)


async def test_an_empty_body_raises_rather_than_parsing_to_nothing(monkeypatch):
    async def get_json(url, *, params=None, headers=None, timeout=None):
        return {"parse": {"wikitext": "   "}}

    monkeypatch.setattr(wikipedia, "get_json", get_json)

    with pytest.raises(ValueError):
        await wikipedia.fetch_year(2026)
