"""
Reading a fund's equity positions out of its monthly KAP portfolio report.

TEFAS answers "how much of this fund is stocks". Only KAP answers "which
stocks", and it answers in a PDF — the disclosure's own JSON body carries the
XBRL cover sheet and not one holding row. So this module exists to turn a
regulatory PDF into a list of tickers, which is exactly as unpleasant as it
sounds and is why everything here is written to refuse rather than to guess.

**Two layouts, one rule.** The SPK form is the same for every fund; the
rendering is not. Two families cover what has been seen:

* *lettered* — sections are `A) HİSSE SENETLERİ` … `Y) DİĞER`, one line per
  holding, ending in an explicit `%`.
* *wide* — sections are bare headings (`HİSSE SENETLERİ`, `TÜREV`, `DİĞER`), the
  table is a transaction register forty columns wide, issuer names wrap over
  five lines, and a holding can appear several times as separate lots.

They differ in every column position and in decimal mark (`1.234,56` against
`1,234.56`), so nothing here reads a fixed column. The one thing both layouts
guarantee is the shape of a row: **a ticker, then somewhere the position's
value as the largest number on the line, then the fund weight as the next
number that could be a percentage.** That rule is the parser.

**The published weight is a share of the fund's equity book, computed from the
values.** The percentage columns cannot be used directly, because the two
layouts do not mean the same thing by them: the lettered one prints a share of
the fund, the wide one a share of the equity group. LTL's rows sum to exactly
100.00% and PHE's to 101.24%, against 80.23% of the fund — that is the tell.
Publishing them side by side would put one fund's holding on a denominator the
next fund's was not measured against, which is worse than either number alone.

Value is the one column both layouts agree on, so the weight is derived from it
and has one meaning everywhere: how the fund's equity is split. The fund-level
figure a reader also wants is already on the page — it is the `hisse` bucket of
the TEFAS allocation card — and the two are kept apart rather than multiplied
together, because that product is a number no filing contains.

**It refuses.** No recognisable section, no rows, or weights that sum past a
plausible ceiling all return None. A partial holdings list is indistinguishable
from a fund that sold everything, and on this board that is the one mistake
worth engineering against.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from typing import Optional

from pypdf import PdfReader

logger = logging.getLogger(__name__)

# A BIST ticker is ASCII, which is most of what separates one from a Turkish
# word that happens to start a line — `TİCARET` carries a dotted İ, `TOPLAM`
# does not, so the stop list below covers the ASCII ones by hand.
_TICKER = re.compile(r"^[A-Z][A-Z0-9]{2,5}$")

# ASCII uppercase words that begin a line in one layout or the other and are not
# holdings: column headings, running totals and the currency column.
_NOT_A_TICKER = frozenset(
    {
        "TOPLAM",
        "GRUP",
        "TL",
        "USD",
        "EUR",
        "GBP",
        "DOVIZ",
        "VADE",
        "ISIN",
        "NET",
        "REPO",
        "BORSA",
        "SATIN",
        "ORANI",
        "TARIH",
        "NOMINAL",
        "PORT",
        "FON",
        "KAP",
        "SAYISI",
        "GUN",
        # Section labels in the wide layout that begin a line the way a ticker
        # does. VIOP is the one that mattered: its cash-collateral line carries
        # a 100% weight and single-handedly breached the sanity ceiling.
        "VIOP",
        "OPSIYON",
        "TAKASBANK",
        "NAKIT",
    }
)

# A figure in either layout. The percent sign leads in some renderings
# (`%6,05`) and trails in others (`6,05%`), and the currency column means a
# token can also be a bare integer with no separator at all.
_NUMERIC = re.compile(r"^%?-?\d[\d.,]*%?$")

# One layout prints the ISIN in the middle of the issuer name. It is not part of
# the name, and the ticker beside it already identifies the company.
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")

# Some houses embed a font whose Turkish capitals extract as Latin Extended-A
# look-alikes: `HİSSE SENETLERİ` comes out `HĠSSE SENETLERĠ`. It is not an
# encoding bug this end — the glyphs really are those code points in the file —
# so the text is folded before anything is matched against it. Left unfolded,
# every report from those houses reads as an unrecognised layout.
_GLYPH_FOLD = str.maketrans({"Ġ": "İ", "ġ": "Ş", "Ģ": "Ş"})

# How many trailing percentage columns a row may carry. The wide layout prints
# three (share of portfolio, of fund total value, of issuer capital); allowing a
# few more costs nothing, allowing unlimited would let a row of small numbers
# swallow the value itself.
_MAX_PERCENT_TAIL = 5

# Both families title the holdings table the same way, and it is the only line
# that says "this is a portfolio report and it was read". Without it a None from
# the parser means "unknown layout"; with it and no equity section, the fund
# simply holds no stocks — two different sentences on the page.
# `\s+` rather than a space: one layout breaks the title across two lines, so a
# literal space matches nothing and that whole family reads as unrecognised.
_TABLE_HEADER = re.compile(r"FON PORTF[ÖO]Y DE[ĞG]ER[İI]\s+TABLOSU", re.I)

# The lettered layout's equity section, and anything that ends it.
_LETTERED_START = re.compile(r"^\s*A\)\s*H[İI]SSE SENETLER[İI]\s*:?\s*$", re.M)
_LETTERED_STOP = re.compile(r"^\s*[B-ZÇĞÖŞÜ]\)\s", re.M)

# The wide layout's, whose headings carry no letter. Listed rather than matched
# by shape because the same file is full of wrapped issuer names that are also
# bare uppercase lines — `SANAYİ`, `TİCARET`, `A.Ş.` — and a shape rule would
# stop the table at the first of them.
_WIDE_START = re.compile(r"^\s*H[İI]SSE SENETLER[İI]\s*$", re.M)
_WIDE_STOP = re.compile(
    r"^\s*(?:T[ÜU]REV|D[İI][ĞG]ER|BOR[ÇC]LANMA SENETLER[İI]|K[İI]RA SERT[İI]F[İI]KALARI"
    r"|VDMK|T\.REPO|TERS REPO|MEVDUAT|KATILMA|ALTIN|YABANCI|VARANT|VIOP|OPS[İI]YON"
    # The roman-numbered sections that follow the table, and the lettered
    # `A) HİSSE SENETLERİ(ALIŞLAR)` / `(SATIŞLAR)` registers inside them. Those
    # two are the dangerous ones: they list the same tickers again as the
    # month's transactions, and swept in they double a fund's book.
    r"|[IVX]{1,4}\s*-|[A-Z]\))",
    re.M,
)

# Past this the parse is not a parse. A fund's equity book cannot be 105% of it,
# so a sum above the ceiling means rows from the next section were swept in.
_WEIGHT_CEILING = 105.0

# Below this a "holding" is almost certainly a stray number off a header line.
_MIN_ROWS = 1


@dataclass(frozen=True)
class Holding:
    """One equity position, as the fund's own filing states it."""

    ticker: str
    label: str
    """The issuer name as printed. Often clipped — the wide layout wraps it over
    five lines and only the first is on the row. The ticker is the identity; the
    label is a fallback for a code the equity board cannot resolve."""
    value: float
    """Market value in lira, on the report's date."""
    weight: float
    """Share of the fund's **equity book**, as a fraction — not of the fund.
    See the module docstring for why this denominator and not the other."""


@dataclass(frozen=True)
class HoldingsReport:
    layout: str
    """`lettered` or `wide` — recorded so a coverage regression names a family."""
    holdings: tuple[Holding, ...]
    """Largest first."""
    total_value: float
    """The equity book in lira, on the report's date. The denominator every
    `Holding.weight` is struck against."""


def _number(token: str) -> Optional[float]:
    """
    A figure from either layout, without being told which locale it is in.

    The last separator is the decimal mark and the other is a thousands group.
    That one rule reads `13.697.437.455,00` and `2,543,983.65` correctly without
    sniffing the document, which matters because the two appear in the same
    corpus and occasionally — a lira value beside a foreign one — in one file.
    """
    text = token.strip().strip("%")
    negative = text.startswith("-")
    text = text.lstrip("-")
    if not text or not text[0].isdigit():
        return None

    cut = max(text.rfind("."), text.rfind(","))
    if cut == -1:
        digits = text
    else:
        head, tail = text[:cut], text[cut + 1 :]
        if not tail.isdigit():
            return None
        digits = head.replace(".", "").replace(",", "") + "." + tail

    try:
        value = float(digits)
    except ValueError:
        return None
    return -value if negative else value


def _has_fraction(token: str) -> bool:
    """True when the token is printed with decimals, e.g. `1.234,56`."""
    text = token.strip().strip("%").lstrip("-")
    cut = max(text.rfind("."), text.rfind(","))
    return cut != -1 and text[cut + 1 :].isdigit()


def _equity_section(text: str) -> Optional[tuple[str, str]]:
    """The equity block and which layout it came from, or None if neither fits."""
    start = _LETTERED_START.search(text)
    if start:
        rest = text[start.end() :]
        stop = _LETTERED_STOP.search(rest)
        return "lettered", rest[: stop.start()] if stop else rest

    start = _WIDE_START.search(text)
    if start:
        rest = text[start.end() :]
        stop = _WIDE_STOP.search(rest)
        return "wide", rest[: stop.start()] if stop else rest

    return None


def _row(line: str) -> Optional[tuple[str, str, float, float]]:
    """
    One holding row, or None for a heading, a total or a wrapped name.

    The value is found from the **right**, not by taking the largest figure on
    the line. That was the first version and it was wrong in a way worth
    recording: the wide layout files a pledged parcel as a negative lot, and on
    those rows the repo contract number — an eight-digit integer sitting in the
    middle of the table — is larger than the position itself, so the parser read
    a contract number as a holding and the unit price beside it as a weight.

    Read from the right the shape is unambiguous in both layouts: a short tail
    of percentages, and immediately before it the value.
    """
    tokens = line.split()
    if len(tokens) < 3:
        return None

    ticker = tokens[0]
    if not _TICKER.match(ticker) or ticker in _NOT_A_TICKER:
        return None

    numbers = [(i, _number(t), _has_fraction(t)) for i, t in enumerate(tokens) if _NUMERIC.match(t)]
    numbers = [(i, v, frac) for i, v, frac in numbers if v is not None]
    if len(numbers) < 2:
        return None

    tail: list[float] = []
    value_at: Optional[int] = None
    for index, figure, has_fraction in reversed(numbers):
        # A Takasbank repo contract number is an eight-digit integer sitting in
        # the middle of the wide layout, and on a pledged parcel it is the only
        # figure on the row above the percentage band — so without this the
        # parser reads a contract number as a position. Every money column in
        # these reports is printed to two decimals; a bare integer is not one.
        if not has_fraction:
            continue
        if abs(figure) <= 100 and len(tail) < _MAX_PERCENT_TAIL:
            tail.append(figure)
            continue
        value_at, value = index, figure
        break

    if value_at is None or not tail:
        return None

    # The leftmost of the tail: the first percentage after the value is the
    # share of the portfolio, and the ones after it are other denominators.
    weight = tail[-1]

    first_number = numbers[0][0]
    label = " ".join(
        token
        for token in tokens[1:first_number]
        if token not in _NOT_A_TICKER and not _ISIN.match(token)
    ).strip()
    return ticker, label, value, weight


def _no_equity() -> HoldingsReport:
    """A report that was read and lists no equity. Empty is the answer, not a gap."""
    return HoldingsReport(layout="none", holdings=(), total_value=0.0)


def parse_equity_holdings(text: str) -> Optional[HoldingsReport]:
    """
    The fund's equity positions, or None when the report cannot be read.

    A None here is an ordinary outcome, not an error: about one report in three
    is rendered by a house whose layout is not one of the two below, and a fund
    holding no equity at all reaches this with nothing to find. The caller says
    "could not be read" either way, which is the honest thing to say.
    """
    text = text.translate(_GLYPH_FOLD)
    recognised = bool(_TABLE_HEADER.search(text))

    section = _equity_section(text)
    if section is None:
        # A bond or money-market fund omits the equity heading entirely rather
        # than printing an empty one, so a recognised report with no section is
        # a fund holding no stocks — not a report this parser failed on.
        return _no_equity() if recognised else None
    layout, block = section

    # Lots are summed rather than listed. The wide layout files a pledged parcel
    # as its own line with a negative sign, so a holding can appear three times
    # and the position is the sum — listing them separately would show the same
    # company three times with three partial weights.
    merged: dict[str, tuple[str, float, float]] = {}
    for line in block.splitlines():
        parsed = _row(line)
        if parsed is None:
            continue
        ticker, label, value, weight = parsed
        seen = merged.get(ticker)
        if seen is None:
            merged[ticker] = (label, value, weight)
        else:
            # Keep the first label: a negative lot's line often has none.
            merged[ticker] = (seen[0] or label, seen[1] + value, seen[2] + weight)

    positions = [
        (ticker, label, value, weight)
        for ticker, (label, value, weight) in merged.items()
        if value > 0 and weight > 0
    ]
    if len(positions) < _MIN_ROWS:
        return _no_equity() if recognised else None

    # The percentages are not published, but they are still the best available
    # check that the section boundary held: rows swept in from the next section
    # push the sum past what a fund's equity book can be, under either layout's
    # denominator. Publishing those would attribute someone else's bonds here.
    stated = sum(weight for _, _, _, weight in positions)
    if stated > _WEIGHT_CEILING:
        logger.debug("holdings parse rejected: %s layout summed to %.1f%%", layout, stated)
        return None

    total_value = sum(value for _, _, value, _ in positions)
    if total_value <= 0:
        return _no_equity()

    holdings = sorted(
        (
            Holding(ticker=ticker, label=label, value=value, weight=value / total_value)
            for ticker, label, value, _ in positions
        ),
        key=lambda holding: holding.value,
        reverse=True,
    )
    return HoldingsReport(layout=layout, holdings=tuple(holdings), total_value=total_value)


def pdf_text(pdf: bytes) -> Optional[str]:
    """
    The report's text with its columns still standing.

    `extraction_mode="layout"` is the whole reason pypdf is a dependency here.
    The default mode returns the words in drawing order, which for these tables
    means a ticker, then a value from a different row, then a heading — the
    columns are what carry the meaning and the layout mode is what preserves
    them.
    """
    try:
        reader = PdfReader(io.BytesIO(pdf))
        return "\n".join(page.extract_text(extraction_mode="layout") or "" for page in reader.pages)
    except Exception as e:  # noqa: BLE001 — a malformed attachment is a coverage gap, not a fault
        logger.info("portfolio report could not be read as a PDF: %s", e)
        return None


def parse_pdf(pdf: bytes) -> Optional[HoldingsReport]:
    """`pdf_text` then `parse_equity_holdings`, refusing at either step."""
    text = pdf_text(pdf)
    if text is None:
        return None
    return parse_equity_holdings(text)
