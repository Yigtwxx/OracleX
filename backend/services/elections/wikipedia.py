"""
Election dates, from Wikipedia's national electoral calendar.

Chosen over the alternatives on availability rather than elegance. Wikidata's
SPARQL endpoint answers 502 or times out often enough that a panel cannot depend
on it; IFES ElectionGuide's API needs credentials requested by email; Google
Civic and Democracy Works are United States only. The `YYYY_national_electoral
_calendar` articles need no key, are edited daily, and carry a `<ref>` per row.

The cost is that the source is prose, not a schema, and one restructure into a
wikitable would leave this parser with nothing. That is why zero dated rows is
raised as a broken shape rather than returned as a quiet year, and why the
service above keeps a week of fallback: an editor should be able to cost us the
panel for an afternoon, not put a wrong date on the board.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date

from services.http_client import get_json

logger = logging.getLogger(__name__)

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
PAGE_TEMPLATE = "{year}_national_electoral_calendar"
SOURCE_TEMPLATE = "https://en.wikipedia.org/wiki/{year}_national_electoral_calendar"

# Wikimedia enforces its User-Agent policy on API traffic with 403s, and the
# shared default advertises `+https://oracle-x.local` — a host nobody can reach.
# A blocked client here would fail permanently and silently, so this is the one
# upstream in the codebase that overrides the header rather than inheriting it.
_HEADERS = {
    "User-Agent": "Oracle-X/1.0 (+https://github.com/Yigtwxx/crypto-stock-lens)",
}

_TIMEOUT = 20.0

_MONTHS: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_NAMES = "|".join(_MONTHS)

# Wikipedia writes ranges with an en dash; the other two are here because
# editors type what their keyboard offers.
_DASH = r"[–—-]"

_HEADING = re.compile(r"^(={2,6})\s*(?P<title>.+?)\s*\1\s*$")
_BULLET = re.compile(r"^(?P<depth>\*+)\s*(?P<body>.+?)\s*$")

# The remainder is `.*` rather than `.+` in all three: the article writes a
# shared polling day as a bare "18 April:" with the countries on nested bullets
# beneath it. Requiring a remainder dropped that line, and the countries under
# it then inherited the *previous* dated bullet — which put the 2027 French
# presidential election on 10 April instead of the 18th. A wrong date is the one
# thing this panel cannot recover from, so the empty remainder is parsed.

# Same-month: "15 January:" or "13–14 September:".
_DATE_SAME_MONTH = re.compile(
    rf"^(?P<d1>\d{{1,2}})(?:\s*{_DASH}\s*(?P<d2>\d{{1,2}}))?"
    rf"\s+(?P<m1>{_MONTH_NAMES})\s*:\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
# Cross-month: "31 March – 1 April:".
_DATE_CROSS_MONTH = re.compile(
    rf"^(?P<d1>\d{{1,2}})\s+(?P<m1>{_MONTH_NAMES})\s*{_DASH}\s*"
    rf"(?P<d2>\d{{1,2}})\s+(?P<m2>{_MONTH_NAMES})\s*:\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
# Month only: "March: Estonia, Parliament". A scheduled election whose day is
# not fixed yet — Estonia, Greece, Oman and the Marshall Islands all sit like
# this. Dropping them would report those countries as having no election at all,
# so they are carried with `precision="month"` and the board declines to count
# down to a day nobody has announced.
_DATE_MONTH_ONLY = re.compile(
    rf"^(?P<m1>{_MONTH_NAMES})\s*:\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

_REF_SELF_CLOSING = re.compile(r"<ref[^>]*/>", re.IGNORECASE)
_REF_PAIRED = re.compile(r"<ref[^>]*>.*?</ref>", re.IGNORECASE | re.DOTALL)
# A citation that opens on this line and closes on the next. Without this the
# `{{Cite web |url=...` tail is read as part of the office.
_REF_DANGLING = re.compile(r"<ref[^>]*>.*$", re.IGNORECASE)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]|]*)\]\]")
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")


@dataclass(frozen=True)
class ElectionDate:
    """One dated row of the calendar, as Wikipedia states it."""

    date: date
    # The last polling day when the vote spans more than one, else None. Kept
    # separate from `date` so the board still sorts and counts down off day one.
    through: date | None
    # "day" when the article names one, "month" when it only names the month.
    # A month-precision row carries the first of the month so it still sorts,
    # which is exactly why the flag has to travel with it: rendered as a date it
    # would assert a polling day nobody has announced.
    precision: str
    # Wikipedia's own country string. Deliberately not normalised here: the
    # registry maps it, and a name this module invented would be a third
    # spelling nobody else knows.
    country: str
    office: str
    # Italicised on Wikipedia, which is how the article marks a dependent
    # territory or a state with limited recognition — Jersey, Tokelau,
    # Transnistria. Kept on the board, but filtered by default: a market desk
    # is not repositioning for the Isle of Man.
    minor: bool
    source_url: str


async def fetch_year(year: int) -> str:
    """The raw wikitext of one year's calendar page. Raises; the caller owns fallback."""
    payload = await get_json(
        WIKIPEDIA_API,
        params={
            "action": "parse",
            "page": PAGE_TEMPLATE.format(year=year),
            "prop": "wikitext",
            "format": "json",
            "formatversion": "2",
            # Costs nothing and covers the article being moved to a variant
            # title. It does not cover a change of *structure* — see the module
            # docstring — which is a parser fork, not a second URL.
            "redirects": "1",
        },
        headers=_HEADERS,
        timeout=_TIMEOUT,
    )
    if not isinstance(payload, dict):
        raise ValueError(f"wikipedia returned {type(payload).__name__} for {year}")

    error = payload.get("error")
    if error:
        # How `missingtitle` arrives for a year whose page nobody has written
        # yet. A future year having no page is normal; the caller decides that.
        raise ValueError(f"wikipedia: {error.get('code', 'error')} for {year}")

    wikitext = (payload.get("parse") or {}).get("wikitext")
    if isinstance(wikitext, dict):
        wikitext = wikitext.get("*")
    if not isinstance(wikitext, str) or not wikitext.strip():
        raise ValueError(f"wikipedia returned no wikitext for {year}")
    return wikitext


def parse_calendar(wikitext: str, year: int) -> list[ElectionDate]:
    """
    Every dated row on one year's calendar page.

    Sections are tracked by *allowlisting* the twelve month names rather than by
    blocklisting "Unknown date" and "Indirect elections". The difference matters:
    a denylist fails open on the section an editor adds next year, silently
    admitting undated or indirectly-decided rows as if they were polling days.
    An allowlist fails closed, which for a calendar is the right direction.

    Raises rather than returning [] when nothing parses. A year page always has
    dated rows — even in December, when all of them are past — so an empty parse
    means the page shape changed, and reporting that as "no elections this year"
    would be a claim about the world rather than about the fetch.
    """
    source_url = SOURCE_TEMPLATE.format(year=year)
    rows: list[ElectionDate] = []
    current_month: int | None = None
    # Nested bullets carry no date of their own; Jersey is filed under the Isle
    # of Man's line this way.
    last_date: tuple[date, date | None, str] | None = None
    skipped = 0

    for line in wikitext.splitlines():
        heading = _HEADING.match(line.strip())
        if heading:
            current_month = _MONTHS.get(_plain(heading.group("title")).lower())
            last_date = None
            continue
        if current_month is None:
            continue

        bullet = _BULLET.match(line)
        if not bullet:
            continue

        body = _strip_refs(bullet.group("body"))
        if not body:
            continue

        parsed = _parse_dates(body, year, current_month)
        if parsed is not None:
            start, through, precision, rest = parsed
            last_date = (start, through, precision)
        elif len(bullet.group("depth")) > 1 and last_date is not None:
            # A nested bullet under a dated one: same polling day, own row.
            start, through, precision = last_date
            rest = body
        else:
            skipped += 1
            continue

        # After the date, not before it: the article italicises the countries,
        # leaving the date outside the marks — "6 February: ''Tokelau, …''".
        rest, minor = _unwrap_italics(rest)
        if not rest:
            # A bare "18 April:" introducing nested bullets. It has done its job
            # by setting the date above; it is not a row of its own.
            continue

        country, office = _split_country_and_office(rest)
        if not country:
            skipped += 1
            continue

        rows.append(
            ElectionDate(
                date=start,
                through=through,
                precision=precision,
                country=country,
                office=office,
                minor=minor,
                source_url=source_url,
            )
        )

    if skipped:
        logger.debug("%s electoral calendar: %d bullet(s) not understood", year, skipped)
    if not rows:
        raise ValueError(f"{year} electoral calendar parsed no dated rows")
    return rows


def _strip_refs(text: str) -> str:
    """Citations and comments, in the order that leaves nothing behind."""
    text = _COMMENT.sub("", text)
    text = _REF_SELF_CLOSING.sub("", text)
    text = _REF_PAIRED.sub("", text)
    text = _REF_DANGLING.sub("", text)
    return text.strip()


def _unwrap_italics(text: str) -> tuple[str, bool]:
    """
    Strip a wrapping ''…'' and report that it was there.

    Runs before the date is read because the italics wrap the whole bullet,
    date included — checking for them afterwards would never fire.
    """
    stripped = text.strip()
    if len(stripped) > 4 and stripped.startswith("''") and stripped.endswith("''"):
        return stripped[2:-2].strip(), True
    return stripped, False


def _parse_dates(
    body: str, year: int, section_month: int
) -> tuple[date, date | None, str, str] | None:
    """
    The leading date of a bullet, as (first day, last day or None, precision, remainder).

    Returns None for anything that is not one of the three shapes the article
    uses. "15 and 22 March" — a two-round election written on one line — falls
    through deliberately: two rounds are two catalysts and belong on two rows,
    so a bullet that refuses to say which is which is dropped rather than
    guessed at.
    """
    cross = _DATE_CROSS_MONTH.match(body)
    if cross:
        start = _safe_date(year, _MONTHS[cross.group("m1").lower()], int(cross.group("d1")))
        end = _safe_date(year, _MONTHS[cross.group("m2").lower()], int(cross.group("d2")))
        if start is None or not _month_fits(start.month, section_month):
            return None
        return start, end, "day", cross.group("rest")

    same = _DATE_SAME_MONTH.match(body)
    if same:
        month = _MONTHS[same.group("m1").lower()]
        start = _safe_date(year, month, int(same.group("d1")))
        if start is None or not _month_fits(month, section_month):
            return None
        end = _safe_date(year, month, int(same.group("d2"))) if same.group("d2") else None
        return start, end, "day", same.group("rest")

    month_only = _DATE_MONTH_ONLY.match(body)
    if month_only:
        month = _MONTHS[month_only.group("m1").lower()]
        start = _safe_date(year, month, 1)
        if start is None or not _month_fits(month, section_month):
            return None
        return start, None, "month", month_only.group("rest")

    return None


def _month_fits(month: int, section_month: int) -> bool:
    """
    A row belongs to its section's month, or to the next one.

    The neighbour is allowed for the `31 March – 1 April` case, which the
    article files under March. Anything further apart means the section was
    mis-tracked, and a row filed under the wrong month is more likely a parse
    error than an editorial one.
    """
    return month in (section_month, section_month % 12 + 1)


def _safe_date(year: int, month: int, day: int) -> date | None:
    """None rather than an exception: an editor's `31 February` drops one row."""
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _split_country_and_office(rest: str) -> tuple[str, str]:
    """
    The country and what is being elected.

    The country is the display text of the *first wikilink*, not the text before
    the first comma. `[[Elections in Bosnia and Herzegovina|Bosnia and
    Herzegovina]], [[…|General]]` is the case that settles it — splitting on the
    comma would work there but breaks the moment a bullet carries a
    parenthetical or a second link ahead of it. Comma-splitting survives only as
    the fallback for a bullet with no link at all.
    """
    link = _LINK.search(rest)
    if link:
        country = _plain(link.group(1))
        office = _plain(rest[link.end() :].lstrip(" ,"))
        return country, office

    head, _, tail = rest.partition(",")
    return _plain(head), _plain(tail)


def _plain(markup: str) -> str:
    """Wikitext reduced to what a reader would see."""
    text = _LINK.sub(r"\1", markup)
    text = _TEMPLATE.sub("", text)
    text = text.replace("'''", "").replace("''", "")
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip(" ,")
