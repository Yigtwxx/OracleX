"""
VİOP's end-of-day bulletin — the exchange's own file, not a broker's page.

**Why this is not `viop_service`.** That module scrapes a broker's VİOP page
every five minutes: nineteen underlyings, no history, whatever the page happens
to render during the session. This reads what Borsa İstanbul publishes after
the close: forty-seven single-stock underlyings across three expiries, one file
per session, archived at least two years back. Different cadence, different
shape, different failure mode — and `/api/bist/viop` plus the positioning board
depend on the scrape, so it stays exactly as it is.

What this file carries that the scrape does not is the reason the margin map
can exist at all: for every contract, on every session, the **weighted average
price** it traded at and the **change in open interest** that session. Those two
turn "how much was opened, and at what price" from a modelling assumption into
a measurement.

**Three shapes that will read as bugs if you assume otherwise.**

*The numbers are dot-decimal.* `18.39` is eighteen point three nine, not
eighteen thousand. `viop_service._number` parses the Turkish convention
(`1.234,56`) and applied here would silently read that as `1839`, so this
module has its own strict parser that rejects a comma outright — a file that
starts arriving in the other convention should stop the import, not survive it.

*One column header ships with a leading space.* The file publishes
`" AGIRLIKLI ORTALAMA FIYAT"`. Headers are stripped on read rather than the
space being baked into a constant, so the day the exchange fixes it nothing
breaks; the fixture keeps the raw form so both spellings stay pinned.

*A 404 is a holiday, not an error.* The exchange publishes nothing on a day it
did not trade. For a past date that is a permanent fact about that date, so it
is written down once and never requested again — which is what keeps the
backfill from re-walking every weekend in the window on every boot.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Optional

from services.cache import bist_cache
from services.http_client import get_bytes

logger = logging.getLogger(__name__)

BULLETIN_URL = "https://www.borsaistanbul.com/data/vadeli/viop_{day}.csv"

# Single-stock futures. The file also carries options (SSO), index futures and
# options (INF/INO), currency, precious metals and more; none of them belong on
# a board about equity positioning.
SEGMENT_SSF = "SSF"

# The bulletin qualifies an underlying with the equity board's own suffix.
UNDERLYING_SUFFIX = ".E"

# Shares per contract. A fallback, not a fact — see `_multiplier`.
DEFAULT_CONTRACT_MULTIPLIER = 100

# The window the map draws, and how far behind it the simulation starts so the
# first drawn column opens with an already-populated book.
EMIT_SESSIONS = 120
WARMUP_SESSIONS = 40
BACKFILL_SESSIONS = EMIT_SESSIONS + WARMUP_SESSIONS

# Against a public server that owes us nothing. Six at a time finishes a cold
# backfill in a couple of minutes without ever looking like a flood.
FETCH_CONCURRENCY = 6

# How many sessions a warm process will chase on the request path. The boot
# warm-up does the bulk; this only closes the gap since the last write, and
# capping it stops a request that lands after a long weekend from paying for a
# full backfill in the foreground.
MAX_TAIL_FETCH = 10

TTL_BULLETIN = 30 * 60
MAX_STALE_BULLETIN = 7 * 24 * 60 * 60

# The bulletin is around half a megabyte; the ceiling is generous enough to
# absorb growth and still refuse a body that is not this file.
MAX_BULLETIN_BYTES = 8_000_000

# Bump when `SsfRow` changes shape, so a cache written by an older parser is
# discarded rather than read back into the wrong fields.
SCHEMA_VERSION = 1

CACHE_KEY = "viop_bulletin_history"

HISTORY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "viop_bulletin.json",
)

# Column names, stripped. Every one of these must be present or the file is not
# the file we think it is.
COL_DAY = "TARIH"
COL_CONTRACT = "SOZLESME KODU"
COL_SEGMENT = "PAZAR SEGMENTI"
COL_UNDERLYING = "DAYANAK VARLIK"
COL_EXPIRY = "VADE TARIHI"
COL_SETTLEMENT = "UZLASMA FIYATI"
COL_PREVIOUS_SETTLEMENT = "ONCEKI UZLASMA FIYATI"
COL_LOW = "EN DUSUK FIYAT"
COL_HIGH = "EN YUKSEK FIYAT"
COL_WEIGHTED_AVERAGE = "AGIRLIKLI ORTALAMA FIYAT"
COL_VOLUME = "ISLEM HACMI"
COL_QUANTITY = "ISLEM MIKTARI"
COL_OPEN_INTEREST = "ACIK POZISYON"
COL_OPEN_INTEREST_CHANGE = "ACIK POZISYON DEGISIMI"

REQUIRED_COLUMNS = frozenset(
    {
        COL_DAY,
        COL_CONTRACT,
        COL_SEGMENT,
        COL_UNDERLYING,
        COL_EXPIRY,
        COL_SETTLEMENT,
        COL_WEIGHTED_AVERAGE,
        COL_OPEN_INTEREST,
        COL_OPEN_INTEREST_CHANGE,
    }
)

# A contract multiplier outside this range is not a corrected contract size, it
# is a misread. Fall back rather than scale a whole underlying by it.
MIN_MULTIPLIER = 50
MAX_MULTIPLIER = 1000

# Contract sizes in this market are round, so the derived figure is snapped to
# the nearest ten and only believed when it lands close to it. On a thin far
# month the division picks up noise — `F_ASTOR1026` derives 100.86 and
# `F_GUBRF1026` 101.40 on a real session — and rounding those to the nearest
# integer would scale two underlyings by one percent for no reason. A genuine
# restatement lands on a round number exactly and passes.
MULTIPLIER_SNAP = 10
MULTIPLIER_TOLERANCE = 0.01

_ISO_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


class BulletinUnavailable(RuntimeError):
    """No bulletin history, and nothing recent enough on disk to stand in."""


@dataclass(frozen=True)
class SsfRow:
    """One single-stock futures contract, on one session."""

    day: str
    """ISO date."""
    contract: str
    """`F_THYAO0826`."""
    underlying: str
    """Bare ticker — the `.E` suffix is stripped."""
    expiry: str
    settlement: float
    previous_settlement: Optional[float]
    high: Optional[float]
    low: Optional[float]
    weighted_average: Optional[float]
    """
    What the session actually traded at, volume weighted.

    The reason this module exists. The crypto model has to guess an entry price
    for the exposure a candle opened; here the exchange publishes it.
    """
    volume_try: Optional[float]
    contracts_traded: Optional[float]
    open_interest: float
    open_interest_change: float
    multiplier: int


def _decimal(raw: Any) -> Optional[float]:
    """
    A figure from the bulletin, which is dot-decimal and ungrouped.

    A comma is not tolerated. The rest of this realm reads Turkish-formatted
    numbers and this file does not use that convention; if it ever starts, the
    right outcome is an import that stops rather than one that reads `18,39` as
    eighteen thousand three hundred and ninety.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text in {"-", "—"}:
        return None
    if "," in text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return None if value != value else value


def _multiplier(volume: Optional[float], quantity: Optional[float], price: Optional[float]) -> int:
    """
    Shares per contract, derived from the row rather than assumed.

    `volume / (quantity × price)` is the contract size the session actually
    settled at. Borsa İstanbul restates contract sizes after a bonus issue, and
    on the name where that happened a hardcoded 100 would scale the whole
    underlying wrong — quietly, because every figure would still look like a
    plausible amount of money.

    An untraded expiry divides by zero, so the constant is what stands in when
    the row cannot answer. It is a fallback, not the fact.
    """
    if not volume or not quantity or not price:
        return DEFAULT_CONTRACT_MULTIPLIER
    derived = volume / (quantity * price)
    if derived != derived:
        return DEFAULT_CONTRACT_MULTIPLIER
    snapped = int(round(derived / MULTIPLIER_SNAP) * MULTIPLIER_SNAP)
    if snapped < MIN_MULTIPLIER or snapped > MAX_MULTIPLIER:
        return DEFAULT_CONTRACT_MULTIPLIER
    if abs(derived - snapped) / snapped > MULTIPLIER_TOLERANCE:
        return DEFAULT_CONTRACT_MULTIPLIER
    return snapped


def parse_bulletin(payload: bytes) -> list[SsfRow]:
    """
    The single-stock futures rows out of one session's file.

    Returns nothing at all when a required column is missing. A file that has
    been reshaped upstream is not a file to read half of: the rows would parse,
    the numbers would land in the wrong fields, and the board would fill with
    plausible wrong prices — the one outcome worse than an empty one.
    """
    text = payload.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=";")

    try:
        header = [cell.strip() for cell in next(reader)]
    except StopIteration:
        return []

    index = {name: position for position, name in enumerate(header)}
    if not REQUIRED_COLUMNS.issubset(index):
        missing = sorted(REQUIRED_COLUMNS - set(index))
        logger.warning("VİOP bulletin is missing columns %s; refusing to parse it", missing)
        return []

    def cell(row: list[str], name: str) -> Optional[str]:
        position = index.get(name)
        if position is None or position >= len(row):
            return None
        return row[position].strip()

    rows: list[SsfRow] = []
    for raw in reader:
        if not raw or cell(raw, COL_SEGMENT) != SEGMENT_SSF:
            continue

        settlement = _decimal(cell(raw, COL_SETTLEMENT))
        open_interest = _decimal(cell(raw, COL_OPEN_INTEREST))
        open_interest_change = _decimal(cell(raw, COL_OPEN_INTEREST_CHANGE))
        day = cell(raw, COL_DAY) or ""
        if settlement is None or open_interest is None or not _ISO_DAY.match(day):
            continue

        underlying = (cell(raw, COL_UNDERLYING) or "").strip()
        if underlying.endswith(UNDERLYING_SUFFIX):
            underlying = underlying[: -len(UNDERLYING_SUFFIX)]
        if not underlying:
            continue

        volume = _decimal(cell(raw, COL_VOLUME))
        quantity = _decimal(cell(raw, COL_QUANTITY))
        weighted = _decimal(cell(raw, COL_WEIGHTED_AVERAGE))

        rows.append(
            SsfRow(
                day=day,
                contract=cell(raw, COL_CONTRACT) or "",
                underlying=underlying,
                expiry=cell(raw, COL_EXPIRY) or "",
                settlement=settlement,
                previous_settlement=_decimal(cell(raw, COL_PREVIOUS_SETTLEMENT)),
                high=_decimal(cell(raw, COL_HIGH)),
                low=_decimal(cell(raw, COL_LOW)),
                weighted_average=weighted,
                volume_try=volume,
                contracts_traded=quantity,
                open_interest=open_interest,
                open_interest_change=open_interest_change or 0.0,
                multiplier=_multiplier(volume, quantity, weighted),
            )
        )
    return rows


@dataclass
class BulletinHistory:
    """Every session held, newest last, plus the days known to have none."""

    rows: list[SsfRow]
    holidays: set[str]
    stored_at: float

    def sessions(self) -> list[str]:
        return sorted({row.day for row in self.rows})

    def underlyings(self) -> set[str]:
        return {row.underlying for row in self.rows}

    def for_underlying(self, underlying: str) -> list[SsfRow]:
        return [row for row in self.rows if row.underlying == underlying]

    def stale(self) -> bool:
        """
        Whether the newest session held is too old to be the last one traded.

        Four days rather than one: the exchange is closed at weekends and the
        bulletin only appears after the close, so a board read on a Monday
        morning is legitimately showing Friday. Beyond that the archive is
        behind and the page should say so.
        """
        sessions = self.sessions()
        if not sessions:
            return True
        try:
            newest = date.fromisoformat(sessions[-1])
        except ValueError:
            return True
        return (date.today() - newest).days > 4


def _empty_history() -> BulletinHistory:
    return BulletinHistory(rows=[], holidays=set(), stored_at=0.0)


def _read_history_file() -> BulletinHistory:
    """The last written window, or an empty one if it is missing or unreadable."""
    try:
        with open(HISTORY_FILE) as handle:
            payload = json.load(handle)
        if int(payload.get("schema_version", 0)) != SCHEMA_VERSION:
            logger.info("VİOP bulletin cache was written by another parser; ignoring it")
            return _empty_history()
        if time.time() - float(payload["stored_at"]) > MAX_STALE_BULLETIN:
            return _empty_history()
        return BulletinHistory(
            rows=[SsfRow(**row) for row in payload["rows"]],
            holidays=set(payload.get("holidays", [])),
            stored_at=float(payload["stored_at"]),
        )
    except FileNotFoundError:
        return _empty_history()
    except Exception as e:  # noqa: BLE001
        # Truncated or reshaped: the history simply pays the cold start it
        # would have paid anyway. Never a reason to fail a read.
        logger.warning("VİOP bulletin cache unreadable, ignoring it: %s", e)
        return _empty_history()


def _write_history_file(history: BulletinHistory) -> None:
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        temp = f"{HISTORY_FILE}.tmp"
        with open(temp, "w") as handle:
            json.dump(
                {
                    "schema_version": SCHEMA_VERSION,
                    "stored_at": history.stored_at,
                    "holidays": sorted(history.holidays),
                    "rows": [asdict(row) for row in history.rows],
                },
                handle,
            )
        os.replace(temp, HISTORY_FILE)
    except Exception as e:  # noqa: BLE001
        logger.warning("VİOP bulletin cache could not be written: %s", e)


async def _fetch_session(day: date) -> Optional[list[SsfRow]]:
    """
    One session's rows, or None when the exchange published nothing that day.

    None means holiday. An exception means the fetch failed and the day should
    be tried again — the caller keeps those apart because only the first is a
    permanent fact worth writing down.
    """
    url = BULLETIN_URL.format(day=day.strftime("%Y%m%d"))
    try:
        payload = await get_bytes(url, timeout=45.0, max_bytes=MAX_BULLETIN_BYTES)
    except Exception as e:  # noqa: BLE001
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 404:
            return None
        raise
    # Half a megabyte of CSV per session, and a backfill parses a hundred and
    # sixty of them. Individually small, collectively a visible stall.
    return await asyncio.to_thread(parse_bulletin, payload)


def _candidate_days(count: int, *, end: Optional[date] = None) -> list[date]:
    """
    Calendar days back from `end`, weekends dropped.

    Weekdays only is a cheap filter that removes two fifths of the requests
    before they are made; public holidays still come back 404 and are recorded
    as they are met.
    """
    last = end or date.today()
    days: list[date] = []
    step = 0
    # Calendar days needed to cover `count` weekdays, with slack for holidays.
    while len(days) < count and step < count * 3:
        current = last - timedelta(days=step)
        step += 1
        if current.weekday() >= 5:
            continue
        days.append(current)
    return sorted(days)


async def _collect(days: Iterable[date], history: BulletinHistory) -> int:
    """Fetch `days` into `history`. Returns how many sessions were added."""
    wanted = [day for day in days if day.isoformat() not in history.holidays]
    held = set(history.sessions())
    wanted = [day for day in wanted if day.isoformat() not in held]
    if not wanted:
        return 0

    semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def one(day: date):
        async with semaphore:
            return await _fetch_session(day)

    results = await asyncio.gather(*(one(day) for day in wanted), return_exceptions=True)

    added = 0
    for day, result in zip(wanted, results):
        if isinstance(result, BaseException):
            # One session failing is not the backfill failing. It stays absent
            # and is retried on the next pass.
            logger.warning("VİOP bulletin for %s unavailable: %s", day, result)
            continue
        if result is None:
            history.holidays.add(day.isoformat())
            continue
        if not result:
            # Parsed to nothing: either a reshaped file or a session with no
            # single-stock futures. Neither is a holiday, so it is not recorded
            # as one — the next pass will look again.
            continue
        history.rows.extend(result)
        added += 1

    if added or wanted:
        history.stored_at = time.time()
    return added


def _trim(history: BulletinHistory, keep: int) -> None:
    """Hold `keep` sessions, oldest dropped."""
    sessions = history.sessions()
    if len(sessions) <= keep:
        return
    cutoff = set(sessions[-keep:])
    history.rows = [row for row in history.rows if row.day in cutoff]


async def ensure_history(sessions: int = BACKFILL_SESSIONS) -> BulletinHistory:
    """
    Fill the window, however long that takes. For the boot warm-up.

    The cold cost is real — around a hundred and sixty requests — and it is paid
    here, in the background, once. The disk cache carries it across restarts,
    which in development is every save.
    """
    # Reading the window back is a four-megabyte JSON parse and twenty-odd
    # thousand dataclass constructions, and writing it is the same in reverse.
    # On the event loop that is a third of a second where nothing else is
    # served — which the startup gate measures and rejects.
    history = await asyncio.to_thread(_read_history_file)
    await _collect(_candidate_days(sessions), history)
    _trim(history, sessions)
    await asyncio.to_thread(_write_history_file, history)
    bist_cache.set(CACHE_KEY, history, TTL_BULLETIN)
    return history


async def get_history(sessions: int = BACKFILL_SESSIONS) -> BulletinHistory:
    """
    The window as it stands, chasing at most `MAX_TAIL_FETCH` missing sessions.

    The request path never runs a full backfill: a reader who arrives before the
    warm-up finishes gets the short window that exists, and the payload says how
    short it is.
    """
    cached = bist_cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    history = await asyncio.to_thread(_read_history_file)
    held = set(history.sessions())
    candidates = _candidate_days(sessions)
    missing = [day for day in candidates if day.isoformat() not in held]
    if missing:
        await _collect(missing[-MAX_TAIL_FETCH:], history)
        _trim(history, sessions)
        await asyncio.to_thread(_write_history_file, history)

    if not history.rows:
        raise BulletinUnavailable("no VİOP bulletin history available")

    bist_cache.set(CACHE_KEY, history, TTL_BULLETIN)
    return history
