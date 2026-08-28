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
from datetime import datetime, UTC
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


def summarise(contracts: list[ViopContract]) -> dict:
    """
    What the board says as a whole.

    Open interest is summed per underlying rather than per contract: a reader
    asking "how big is the USDTRY position" means across every expiry, and the
    near month alone understates it by roughly half.
    """
    by_underlying: dict[str, dict] = {}
    for contract in contracts:
        entry = by_underlying.setdefault(
            contract.underlying,
            {
                "underlying": contract.underlying,
                "open_interest": 0.0,
                "change": 0.0,
                "contracts": 0,
            },
        )
        entry["contracts"] += 1
        if contract.open_interest is not None:
            entry["open_interest"] += contract.open_interest
        if contract.open_interest_change is not None:
            entry["change"] += contract.open_interest_change

    ranked = sorted(by_underlying.values(), key=lambda row: row["open_interest"], reverse=True)
    return {
        "total_open_interest": sum(row["open_interest"] for row in ranked),
        "by_underlying": ranked,
    }
