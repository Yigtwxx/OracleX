"""
VİOP — the derivatives side of Borsa İstanbul.

Futures on the BIST 30 index, on USDTRY, on gold and on around forty single
stocks. The open-interest column is the reason this board exists: it is the only
place in the Turkish market where positioning is published rather than inferred.

**Where this comes from.** VİOP has no public data endpoint. Borsa İstanbul
serves the board through a session-bound page, TradingView's Turkish universe
carries no futures at all (`totalCount: 0`), and the global futures universe is
EUREX and EURONEXT. What does work is a broker's public VİOP page, which renders
the exchange's own table server-side and is free to read.

That makes this the one service in the package built on a scrape rather than on
a data feed, with the fragility that implies: a layout change upstream breaks it,
and the parser is written to return nothing rather than to guess when the shape
stops matching.
"""

from __future__ import annotations

import html as html_module
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, UTC
from typing import Optional

from services.cache import bist_cache
from services.http_client import get_text_impersonated

logger = logging.getLogger(__name__)

SOURCE_URL = "https://yatirim.akbank.com/tr-tr/viop/sayfalar/default.aspx"

TTL_BOARD = 5 * 60
MAX_STALE_BOARD = 3 * 24 * 60 * 60

# The columns the upstream table publishes, in order. Fewer cells than this and
# the row is not a contract row; more and the layout has changed under us and
# the safe answer is to skip it rather than to index blindly into it.
_EXPECTED_CELLS = 10

_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")

# `THYAO (31 Ağu 26) Vadeli FIZ.` — underlying, expiry, and whether the contract
# settles physically.
_CONTRACT_RE = re.compile(r"^([A-ZÇĞİÖŞÜ0-9]+)\s*\((.*?)\)\s*(.*)$")


KIND_FUTURE = "future"
KIND_CALL = "call"
KIND_PUT = "put"

# The instrument, off the trailing words of the contract label.
#
# The board is not futures-only and never was. Ten of its forty-odd rows are
# options — `ISCTR (30 Eyl 26) Satim opsiyonu FIZ.` sits directly beneath
# `ISCTR (30 Eyl 26) Vadeli FIZ.` and carries a settlement of 0.13 against the
# future's 13.16, because one is a premium and the other is a price. Read as one
# instrument they produce a term structure in 99% backwardation and an open
# interest total that adds two different books together.
#
# Matched on an ASCII transliteration rather than the literal text. The page
# writes `Alim opsiyonu` with a plain `i` today and `Alım` is the correct
# spelling, so a rule keyed on either one alone is a rule that stops working the
# day the upstream fixes its own typography.
_TR_ASCII = str.maketrans("çğıöşüÇĞİIÖŞÜ", "cgiosucgiiosu")

_KINDS: tuple[tuple[str, str], ...] = (
    ("alimopsiyonu", KIND_CALL),
    ("satimopsiyonu", KIND_PUT),
)


def parse_kind(suffix: str) -> str:
    """
    Which instrument a row is, defaulting to a future.

    Defaulting rather than refusing: `Vadeli` is what the overwhelming majority
    of rows say, an unrecognised suffix is far more likely to be a futures
    variant than a third option type, and a row dropped for an unknown label
    would take its open interest out of the board's totals silently.
    """
    folded = "".join(ch for ch in suffix.translate(_TR_ASCII).lower() if "a" <= ch <= "z")
    for skeleton, kind in _KINDS:
        if skeleton in folded:
            return kind
    return KIND_FUTURE


class ViopUnavailable(RuntimeError):
    """The VİOP board could not be read and no recent enough copy survives."""


@dataclass(frozen=True)
class ViopContract:
    contract: str
    """The row's own label, verbatim."""
    underlying: str
    expiry: str
    physical: bool
    """`FIZ.` — settles in shares rather than in cash."""
    last: Optional[float]
    change_pct: Optional[float]
    high: Optional[float]
    low: Optional[float]
    open_interest: Optional[float]
    open_interest_change: Optional[float]
    settlement: Optional[float]
    previous_settlement: Optional[float]
    traded_at: str
    kind: str = KIND_FUTURE
    """
    `future`, `call` or `put`.

    Carried rather than inferred at each call site because the distinction
    decides whether two rows belong on the same axis at all, and every surface
    that draws a curve, a total or a positioning quadrant has to make the same
    call. `parse_board` always sets it; the default exists only so the quote
    columns above do not each need one.
    """
    expiry_date: Optional[str] = None
    """
    `expiry` as an ISO day, or None when the label could not be read.

    The column publishes `31 Ağu 26`, which sorts alphabetically into nonsense —
    Ağustos before Eylül before Ekim is the calendar, but `A` before `E` before
    `E` is the string. Anything ordering contracts by time needs a real date, and
    two of them do: the term-structure curve and the roll split both put expiries
    on an axis.

    Last in the class with a default rather than beside `expiry` where it
    belongs, because a dataclass cannot carry a defaulted field ahead of
    undefaulted ones and the alternative was giving every quote column a default
    it has no business having.
    """


# Characters that only appear when a UTF-8 payload was decoded as Latin-1.
_MOJIBAKE_MARKERS = ("Ã", "Ä", "Å", "Â")


def _repair_encoding(text: str) -> str:
    """
    Undo a UTF-8 payload that was decoded as Latin-1 upstream.

    The page is UTF-8 but arrives without a charset the client believes, so `ğ`
    (0xC4 0x9F) reads back as `Ä` plus a control byte, and every Turkish month
    name in the expiry column comes out as `31 AÄŸu 26`.

    Applied per cell rather than to the whole document, which is what the first
    attempt did and why it silently did nothing: one `—` or `’` anywhere on a
    125 KB page makes `encode("latin-1")` raise, and the whole repair was
    abandoned for the sake of a character in the footer. A cell is short, and a
    cell that cannot round-trip is left exactly as it was.
    """
    if not any(marker in text for marker in _MOJIBAKE_MARKERS):
        return text
    # cp1252 before latin-1, and that order is the whole fix. The upstream
    # decoded with cp1252, which maps 0x9F to `Ÿ` — a character latin-1 does not
    # contain at all, so re-encoding `AÄŸu` as latin-1 raises and the repair
    # gives up on exactly the strings that need it.
    for encoding in ("cp1252", "latin-1"):
        try:
            return text.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return text


def _clean(cell: str) -> str:
    return _repair_encoding(html_module.unescape(_TAG_RE.sub("", cell)).strip())


def _number(raw: str) -> Optional[float]:
    """
    A Turkish-formatted figure as a float.

    `1.234,56` is one thousand two hundred and thirty four point five six, and
    `%-0,92` is a signed percentage. Reading either with a plain `float()`
    silently produces 1.234 and a crash respectively.
    """
    text = raw.replace("%", "").replace("\xa0", "").strip()
    if not text or text in {"-", "—"}:
        return None
    text = text.replace(".", "").replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return None if value != value else value


# Turkish month abbreviations, as the expiry column writes them.
#
# A table rather than `strptime("%d %b %y")`: `%b` reads the process locale, and
# the backend runs under whatever the host image happens to set. A container
# with the C locale would parse every expiry to None and quietly empty the two
# panels built on it, which is a failure no test running on a Turkish laptop
# would ever see.
_MONTHS: dict[str, int] = {
    "oca": 1,
    "şub": 2,
    "sub": 2,
    "mar": 3,
    "nis": 4,
    "may": 5,
    "haz": 6,
    "tem": 7,
    "ağu": 8,
    "agu": 8,
    "eyl": 9,
    "eki": 10,
    "kas": 11,
    "ara": 12,
}

# The Turkish letters with the ASCII they fold to once a byte is lost.
#
# Not a nicety. The broker's own page serves `26 Şubat 27` as
# `26 \xc3\x85\xef\xbf\xbdub 27` — it double-encoded the cell and then replaced
# the byte its own decoder could not read, so `Ş` reaches us as `Å` plus a
# replacement character and no amount of re-decoding on this side can recover
# it. `_repair_encoding` cannot help: the information is gone before the
# response leaves their server.
#
# What survives is the ASCII tail, and it is enough. Stripped of everything
# outside `a-z`, the twelve month abbreviations become `oca ub mar nis may haz
# tem au eyl eki kas ara` — still twelve distinct strings, none of them a prefix
# of another. So a month whose distinctive letter was destroyed is still
# identifiable, and the alternative was dropping USDTRY's February contract off
# the term-structure curve every time that expiry is listed.
_ASCII_MONTHS: dict[str, int] = {
    "".join(ch for ch in name if "a" <= ch <= "z"): month
    for name, month in {
        "oca": 1,
        "şub": 2,
        "mar": 3,
        "nis": 4,
        "may": 5,
        "haz": 6,
        "tem": 7,
        "ağu": 8,
        "eyl": 9,
        "eki": 10,
        "kas": 11,
        "ara": 12,
    }.items()
}

# `31 Ağu 26`, and also `31 Ağustos 2026` — the abbreviation is what the page
# serves today, and matching the long form costs nothing here.
#
# The month is `\S+` rather than a letter class on purpose: a replacement
# character is punctuation to `re`, so a class of letters would refuse the very
# rows the fold above exists to rescue.
_EXPIRY_RE = re.compile(r"^(\d{1,2})\s+(\S+)\s+(\d{2}|\d{4})$")


def _month_of(text: str) -> Optional[int]:
    """
    A month name as its number, exactly first and then by its ASCII skeleton.

    The exact table runs first so every ordinary row takes the cheap path and
    the fold below can never reinterpret a label that was already readable.
    `.lower()` rather than `.casefold()`: casefold maps `İ` to an `i` with a
    combining dot, which no key here contains.
    """
    month = _MONTHS.get(text[:3].lower())
    if month is not None:
        return month

    folded = "".join(ch for ch in text.lower() if "a" <= ch <= "z")
    for skeleton, number in _ASCII_MONTHS.items():
        if folded.startswith(skeleton):
            return number
    return None


def parse_expiry(raw: str) -> Optional[str]:
    """
    An expiry label as an ISO day, or None.

    None rather than a guess, for the reason the rest of this parser returns
    nothing rather than half a row: a contract placed on the wrong month of a
    term-structure curve does not look like missing data, it looks like a market
    in backwardation.
    """
    match = _EXPIRY_RE.match((raw or "").strip())
    if not match:
        return None

    day_text, month_text, year_text = match.groups()
    month = _month_of(month_text)
    if month is None:
        return None

    year = int(year_text)
    if year < 100:
        year += 2000

    try:
        return date(year, month, int(day_text)).isoformat()
    except ValueError:
        # `31 Nis 26` — a day the month does not have. The row is still a
        # contract and still carries its quote; only its place on a time axis is
        # unknown.
        return None


def parse_board(html: str) -> list[ViopContract]:
    """
    Contracts out of the broker's table.

    Rows that do not match the expected shape are skipped rather than
    half-parsed. A scrape that starts guessing produces a board of plausible
    wrong numbers, which is the one outcome worse than an empty one.
    """
    contracts: list[ViopContract] = []

    for row in _ROW_RE.findall(html):
        cells = [_clean(cell) for cell in _CELL_RE.findall(row)]
        if len(cells) < _EXPECTED_CELLS:
            continue

        label = cells[0]
        match = _CONTRACT_RE.match(label)
        if not match:
            continue
        underlying, expiry, suffix = match.groups()

        contracts.append(
            ViopContract(
                contract=label,
                underlying=underlying,
                expiry=expiry.strip(),
                physical="FIZ" in suffix.upper(),
                change_pct=(lambda v: v / 100 if v is not None else None)(_number(cells[1])),
                last=_number(cells[2]),
                high=_number(cells[3]),
                low=_number(cells[4]),
                open_interest=_number(cells[5]),
                open_interest_change=_number(cells[6]),
                settlement=_number(cells[7]),
                previous_settlement=_number(cells[8]),
                traded_at=cells[9],
                expiry_date=parse_expiry(expiry),
                kind=parse_kind(suffix),
            )
        )
    return contracts


@dataclass(frozen=True)
class ViopBoard:
    contracts: list[ViopContract]
    as_of: str
    stale: bool


async def fetch_viop_board() -> ViopBoard:
    """Every contract on the board, ordered as the exchange publishes them."""
    cached = bist_cache.get("viop_board")
    if cached is not None:
        return cached

    try:
        html = await get_text_impersonated(SOURCE_URL, timeout=30.0)
        contracts = parse_board(html)
    except Exception as e:  # noqa: BLE001
        stale = bist_cache.get_with_fallback("viop_board", max_age=MAX_STALE_BOARD)
        if stale is not None:
            logger.warning("VİOP board unreadable, serving stale: %s", e)
            return ViopBoard(contracts=stale.contracts, as_of=stale.as_of, stale=True)
        raise ViopUnavailable(f"VİOP board unavailable: {e}") from e

    if not contracts:
        stale = bist_cache.get_with_fallback("viop_board", max_age=MAX_STALE_BOARD)
        if stale is not None:
            logger.warning("VİOP board parsed to nothing; the layout may have changed")
            return ViopBoard(contracts=stale.contracts, as_of=stale.as_of, stale=True)
        raise ViopUnavailable("VİOP board parsed to no contracts")

    board = ViopBoard(contracts=contracts, as_of=datetime.now(UTC).isoformat(), stale=False)
    bist_cache.set("viop_board", board, TTL_BOARD)
    return board


@dataclass(frozen=True)
class UnderlyingRoll:
    """One underlying's futures, summed across every expiry."""

    underlying: str
    contracts: int
    """How many expiries. An underlying present in the roll always has at least one."""
    open_interest: Optional[float]
    """
    None rather than 0.0 when no expiry published a figure.

    The distinction is the whole reason this type exists. "There are contracts
    on this name but the column was empty" and "there is no position" look
    identical once both collapse to zero, and a board that colours the first as
    a measured nothing is stating something it does not know.
    """
    open_interest_change: Optional[float]


def roll_by_underlying(
    contracts: Optional[list[ViopContract]],
) -> dict[str, UnderlyingRoll]:
    """
    Every contract folded onto its underlying.

    Open interest is summed per underlying rather than per contract: a reader
    asking "how big is the USDTRY position" means across every expiry, and the
    near month alone understates it by roughly half.

    Open interest and its change are summed independently — a row can publish
    one and not the other, and pairing them would drop a reading that is there.
    """
    counts: dict[str, int] = {}
    interest: dict[str, float] = {}
    change: dict[str, float] = {}

    for contract in contracts or []:
        counts[contract.underlying] = counts.get(contract.underlying, 0) + 1
        if contract.open_interest is not None:
            interest[contract.underlying] = (
                interest.get(contract.underlying, 0.0) + contract.open_interest
            )
        if contract.open_interest_change is not None:
            change[contract.underlying] = (
                change.get(contract.underlying, 0.0) + contract.open_interest_change
            )

    return {
        underlying: UnderlyingRoll(
            underlying=underlying,
            contracts=count,
            open_interest=interest.get(underlying),
            open_interest_change=change.get(underlying),
        )
        for underlying, count in counts.items()
    }


def summarise(contracts: list[ViopContract]) -> dict:
    """
    What the board says as a whole.

    The unreadable-versus-absent distinction `roll_by_underlying` keeps is
    flattened back to 0.0 here on purpose: `/api/bist/viop` has published these
    fields as numbers since it existed, and a null arriving where a client
    expects a figure is a breaking change for a nuance this particular payload
    never carried.
    """
    rolls = roll_by_underlying(contracts)
    ranked = sorted(
        (
            {
                "underlying": roll.underlying,
                "open_interest": roll.open_interest or 0.0,
                "change": roll.open_interest_change or 0.0,
                "contracts": roll.contracts,
            }
            for roll in rolls.values()
        ),
        key=lambda row: row["open_interest"],
        reverse=True,
    )
    return {
        "total_open_interest": sum(row["open_interest"] for row in ranked),
        "by_underlying": ranked,
    }
