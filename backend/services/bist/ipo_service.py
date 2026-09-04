"""
The Borsa İstanbul offering board: what is coming, and what the last ones did.

Merges three sources with very different standing, and the whole design turns on
keeping them apart. `halkarz_client` supplies the calendar — dates, price, lot
count, broker — and is a community-maintained site with no contract. The
TradingView scanner supplies today's price. TCMB supplies the price index. The
return this board leads with is computed *here*, from the offering price on
halkarz and the current price from the scanner, so the number a reader acts on
is ours even though the date beside it is not.

Two things bound the cost, because the naive shape is a production incident. The
index is one request for two hundred rows and is cached for hours. A detail page
is ninety kilobytes and there are two hundred of them, so they are fetched under
a per-request budget, newest first, and cached on disk by state rather than by
clock: an offering that has listed and published its allocation can never change
again and is never fetched twice.

Nothing here raises for a missing field. A row whose detail could not be read
still renders from the index alone and names what is missing in `unparsed`,
which is what turns parser rot into something countable rather than a board that
quietly empties.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from services.asset_registry import DATA_DIR
from services.bist import halkarz_client as hz
from services.bist.real_return import deflate
from services.cache import bist_cache

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(DATA_DIR, "bist_ipos")

TTL_INDEX = 6 * 60 * 60
"""The calendar changes a few times a week; the index is one cheap request."""

PENDING_RECHECK_HOURS = 12
"""How long a row that has not settled may be served from disk before a re-read."""

DETAIL_BUDGET = 40
"""
Detail fetches per request.

Two hundred pages at ninety kilobytes is nineteen megabytes and two hundred
requests, which is not something a page load may do. Newest first, so the rows
the board actually shows are the rows that get filled, and the rest arrive on
later requests once the disk cache warms.
"""

CONCURRENCY = 3
REQUEST_SPACING_SECONDS = 0.25

MIN_DAYS_LISTED = 5
"""
Below this a return is real but is not a track record.

The row is marked rather than dropped: a three-day-old offering's return is a
fact, and hiding it would quietly flatter the distribution by excluding exactly
the newest listings.
"""

MAX_LISTING_AGE_DAYS = 365 * 30
"""
A sanity bound on a date that comes from the same untrusted page as everything
else. A listing date in the future, or thirty years back, is a parse that went
wrong; the nominal return survives it but the inflation window does not, so
`real` is dropped rather than computed over a nonsense span.
"""

STATE_UNDATED = "undated"
STATE_UPCOMING = "upcoming"
STATE_BOOK_OPEN = "book_open"
STATE_LISTED = "listed"


@dataclass(frozen=True)
class CachedDetail:
    slug: str
    fetched_at: str
    fields: dict[str, Any]
    failed: bool = False


# ── Disk cache ───────────────────────────────────────────────────────────────


def _path(slug: str) -> str:
    safe = re.sub(r"[^a-z0-9\-]", "", slug.lower())[:120]
    return os.path.join(CACHE_DIR, f"{safe}.json")


def read_cached(slug: str) -> Optional[CachedDetail]:
    path = _path(slug)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        return CachedDetail(**raw)
    except (OSError, ValueError, TypeError):
        return None


def write_cached(entry: CachedDetail) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _path(entry.slug)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(asdict(entry), handle, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def is_settled(fields: dict[str, Any], today: date) -> bool:
    """
    Whether this offering can still change.

    A listing that has traded and whose allocation table is published is a
    historical record: nothing on its page will move again. Everything else —
    upcoming, in the book, listed but with results not yet posted — is still
    live and gets re-read.
    """
    listing = hz.parse_turkish_date(fields.get("listing_date_raw"))
    return bool(listing and listing.start < today and fields.get("results"))


def is_fresh(entry: CachedDetail, today: date) -> bool:
    if entry.failed:
        return False
    if is_settled(entry.fields, today):
        return True
    try:
        fetched = datetime.fromisoformat(entry.fetched_at)
    except ValueError:
        return False
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    return datetime.now(UTC) - fetched < timedelta(hours=PENDING_RECHECK_HOURS)


# ── Detail fetching, under budget ────────────────────────────────────────────


def _detail_to_dict(fields: hz.DetailFields) -> dict[str, Any]:
    raw = asdict(fields)
    # Dataclasses inside tuples survive `asdict`; dates do not appear here
    # because every parsed date is re-derived from its raw string on read.
    return raw


async def load_details(
    rows: list[hz.IndexRow],
    *,
    today: date,
    budget: int = DETAIL_BUDGET,
) -> tuple[dict[str, dict[str, Any]], int, int]:
    """
    Detail fields per slug, from disk where possible and the network otherwise.

    Returns the map plus how many pages were read and how many failed, so the
    board can say out loud that it is still filling in rather than presenting a
    partial list as complete.
    """
    details: dict[str, dict[str, Any]] = {}
    stale: list[str] = []

    for row in rows:
        cached = read_cached(row.slug)
        if cached is not None and is_fresh(cached, today):
            details[row.slug] = cached.fields
            continue
        if cached is not None:
            # Serve the stale copy while it is re-read: a month-old broker name
            # is a far better row than an empty one.
            details[row.slug] = cached.fields
        stale.append(row.slug)

    wanted = stale[:budget]
    if not wanted:
        return details, 0, 0

    semaphore = asyncio.Semaphore(CONCURRENCY)
    failures = 0

    async def one(slug: str) -> None:
        nonlocal failures
        async with semaphore:
            await asyncio.sleep(REQUEST_SPACING_SECONDS)
            try:
                fields = await hz.fetch_detail(slug)
            except hz.HalkarzUnavailable as e:
                failures += 1
                logger.info("halkarz detail %s unavailable: %s", slug, e)
                return
            payload = _detail_to_dict(fields)
            details[slug] = payload
            write_cached(
                CachedDetail(slug=slug, fetched_at=datetime.now(UTC).isoformat(), fields=payload)
            )

    await asyncio.gather(*(one(slug) for slug in wanted), return_exceptions=True)
    return details, len(wanted) - failures, failures


# ── Shaping ──────────────────────────────────────────────────────────────────


def offering_state(
    offer: Optional[hz.DateRange],
    listing: Optional[hz.DateRange],
    today: date,
    *,
    has_ticker: bool = False,
) -> str:
    """
    Where this offering sits in its own lifecycle.

    The last branch is the one that matters and the one that was wrong first.
    The calendar carries every offering back to 2019, and a detail page is only
    read once the fetch budget reaches it — so hundreds of rows arrive with an
    offer window years in the past and no listing date, because nobody has
    looked at their page yet. Calling those "upcoming" put a 2019 offering in
    the forward tray. A closed book plus an assigned BIST code means the share
    is trading, whatever this page did or did not publish about the first day;
    with no code there is nothing to say, so it is undated rather than guessed
    into either tray.
    """
    if listing and listing.start <= today:
        return STATE_LISTED
    if offer is None:
        return STATE_UNDATED
    if offer.start <= today <= offer.end:
        return STATE_BOOK_OPEN
    if today < offer.start:
        return STATE_UPCOMING
    return STATE_LISTED if has_ticker else STATE_UNDATED


def _cpi_window(cpi_index: dict[str, float], listed_on: date) -> Optional[float]:
    """Consumer prices from the listing month to the newest published one."""
    if not cpi_index:
        return None
    months = sorted(cpi_index)
    start = f"{listed_on.year}-{listed_on.month:02d}"
    if start < months[0] or start > months[-1]:
        return None
    base = cpi_index.get(start)
    if base is None or base <= 0:
        return None
    return cpi_index[months[-1]] / base - 1


def compute_performance(
    *,
    price: Optional[hz.Money],
    listing: Optional[hz.DateRange],
    equity: Any | None,
    cpi_index: dict[str, float],
    today: date,
) -> Optional[dict[str, Any]]:
    """
    What this offering has returned since it started trading.

    Every input has to be present and unambiguous. A band with no struck price
    yields nothing rather than a midpoint; a listing date the sanity bound
    rejects yields a nominal return and no real one. The row is excluded from
    every aggregate above rather than counted at zero, which would read as a
    listing that went nowhere.
    """
    if price is None or price.is_band or listing is None or equity is None:
        return None
    current = getattr(equity, "price", None)
    if current is None or price.low <= 0:
        return None

    listed_on = listing.start
    days = (today - listed_on).days
    if days < 0 or days > MAX_LISTING_AGE_DAYS:
        return None

    nominal = current / price.low - 1
    inflation = _cpi_window(cpi_index, listed_on)
    real = deflate(nominal, inflation) if inflation is not None else None

    return {
        "price": current,
        "nominal": nominal,
        "real": real,
        "days_listed": days,
        "seasoned": days >= MIN_DAYS_LISTED,
        "market_cap": getattr(equity, "market_cap", None),
        "sector": getattr(equity, "sector", None) or None,
        "measured_at": datetime.now(UTC).isoformat(),
    }


def _results_payload(raw: Any) -> Optional[dict[str, Any]]:
    if not raw:
        return None
    groups = [group for group in raw.get("groups") or [] if group]
    if not groups:
        return None
    return {
        "groups": [
            {
                "key": group.get("key"),
                "label": group.get("label"),
                "investors": group.get("investors"),
                "lots": group.get("lots"),
                # Passed through unchanged. The source rounds and its shares can
                # sum to 0.98; normalising would invent precision it never
                # claimed, and the allocation bar is built to leave bare track.
                "share": group.get("share"),
            }
            for group in groups
        ],
        "total_investors": raw.get("total_investors"),
        "total_lots": raw.get("total_lots"),
    }


def build_row(
    row: hz.IndexRow,
    detail: Optional[dict[str, Any]],
    *,
    equity: Any | None,
    cpi_index: dict[str, float],
    today: date,
) -> dict[str, Any]:
    """One offering, from the index row and whatever the detail page gave up."""
    detail = detail or {}
    unparsed: list[str] = []

    raw_offer = detail.get("offer_dates_raw") or row.offer_dates_raw
    offer = hz.parse_turkish_date(raw_offer)
    if raw_offer and offer is None:
        unparsed.append("offer_dates")

    raw_listing = detail.get("listing_date_raw")
    listing = hz.parse_turkish_date(raw_listing)
    if raw_listing and listing is None:
        unparsed.append("listing_date")

    raw_price = detail.get("price_raw")
    price = hz.parse_try_amount(raw_price)
    if raw_price and price is None:
        unparsed.append("price")

    if not detail:
        unparsed.append("detail")

    # The detail page assigns the code once the exchange does, so it wins over
    # the index, which is written earlier.
    ticker = detail.get("ticker") or row.ticker

    return {
        "slug": row.slug,
        "url": row.url,
        "company": row.company,
        "ticker": ticker,
        "state": offering_state(offer, listing, today, has_ticker=bool(ticker)),
        "is_new": row.is_new,
        "offer_dates": (
            {"start": offer.start.isoformat(), "end": offer.end.isoformat(), "raw": raw_offer}
            if offer
            else None
        ),
        "listing_date": listing.start.isoformat() if listing else None,
        "price": (
            {"low": price.low, "high": price.high, "is_band": price.is_band, "raw": raw_price}
            if price
            else None
        ),
        "lots": hz.parse_lots(detail.get("lots_raw")),
        "free_float_lots": hz.parse_lots(detail.get("free_float_lots_raw")),
        "free_float_pct": hz.parse_percent(detail.get("free_float_pct_raw")),
        "broker": detail.get("broker"),
        "method": detail.get("method"),
        "market": detail.get("market"),
        "structure": detail.get("structure"),
        "use_of_proceeds": (
            [dict(line) for line in detail.get("use_of_proceeds")]
            if detail.get("use_of_proceeds")
            else None
        ),
        "proceeds_source": detail.get("proceeds_source"),
        "results": _results_payload(detail.get("results")),
        "performance": compute_performance(
            price=price, listing=listing, equity=equity, cpi_index=cpi_index, today=today
        ),
        "updated_at": detail.get("updated_at"),
        "unparsed": unparsed,
    }


def in_window(row: dict[str, Any], *, months_back: int, days_ahead: int, today: date) -> bool:
    """Whether this offering falls inside the board's window, in either direction."""
    if row["state"] == STATE_LISTED:
        # A listing we cannot date cannot be placed in a window. Counting it
        # anyway would let a 2019 offering into a two-year board and inflate
        # every "listed in this window" figure the note quotes.
        if not row["listing_date"]:
            return False
        listed = date.fromisoformat(row["listing_date"])
        return listed >= today - timedelta(days=months_back * 31)
    if row["state"] == STATE_UNDATED:
        # An offering with no announced date is genuinely pending only if the
        # calendar has not already carried it past its own book. One whose
        # window closed and which has no code is a row nobody has read yet.
        return row["offer_dates"] is None
    if not row["offer_dates"]:
        return True
    start = date.fromisoformat(row["offer_dates"]["start"])
    return start <= today + timedelta(days=days_ahead)


def _inflation_state(
    cpi_index: dict[str, float],
    measured: list[dict[str, Any]],
    *,
    key_configured: bool,
) -> dict[str, Any]:
    """
    Whether the board can actually show a real frame, not merely whether a
    series exists.

    The distinction is not pedantic. TCMB's index runs months behind on
    occasion, and every listing newer than its last month has a nominal return
    and no real one. Reporting "inflation available" off the series alone would
    leave the reel toggle live above a chart with nothing on it, which reads as
    a broken board rather than as an index that has not caught up.
    """
    if not cpi_index:
        return {
            "available": False,
            "reason": "cpi_key_missing" if not key_configured else "cpi_unavailable",
        }
    if not any(row["performance"].get("real") is not None for row in measured):
        return {"available": False, "reason": "cpi_too_short"}
    return {"available": True, "reason": None}


async def build_ipos(
    *,
    months_back: int = 24,
    days_ahead: int = 120,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """The whole offering board."""
    from services.bist import equity_service, macro_service
    from services.bist.deflator import index_by_month

    now = today or date.today()

    cached_index = bist_cache.get("ipo:index")
    if cached_index is None:
        rows = await hz.fetch_index()
        bist_cache.set("ipo:index", rows, TTL_INDEX)
    else:
        rows = cached_index

    details, read, failed = await load_details(rows, today=now)

    equities: dict[str, Any] = {}
    try:
        board = await equity_service.fetch_equity_board()
        equities = {row.ticker: row for row in board.equities}
    except Exception as e:  # noqa: BLE001
        # A scanner outage costs every return on the board and nothing else.
        logger.info("no equity board for the IPO board: %s", e)

    cpi_series: list[dict[str, Any]] = []
    try:
        cpi_series = await macro_service.fetch_cpi_series(years=6)
    except Exception as e:  # noqa: BLE001
        logger.info("no CPI series for the IPO board: %s", e)
    cpi_index = index_by_month(cpi_series)

    built = [
        build_row(
            row,
            details.get(row.slug),
            equity=equities.get(row.ticker or (details.get(row.slug) or {}).get("ticker") or ""),
            cpi_index=cpi_index,
            today=now,
        )
        for row in rows
    ]
    windowed = [
        row
        for row in built
        if in_window(row, months_back=months_back, days_ahead=days_ahead, today=now)
    ]

    upcoming = [row for row in windowed if row["state"] != STATE_LISTED]
    past = sorted(
        (row for row in windowed if row["state"] == STATE_LISTED),
        key=lambda row: row["listing_date"] or "",
        reverse=True,
    )
    measured = [row for row in past if row["performance"]]

    stamps = [row["updated_at"] for row in windowed if row["updated_at"]]

    from config import settings

    return {
        "upcoming": upcoming,
        "past": past,
        "as_of": datetime.now(UTC).isoformat(),
        "source": "halkarz.com",
        # The source's own stamp, not our fetch time. What the reader wants to
        # know is how current the calendar is, not how recently we asked.
        "source_updated_at": max(stamps) if stamps else None,
        "window": {"months_back": months_back, "days_ahead": days_ahead},
        "coverage": {
            "index_rows": len(rows),
            "in_window": len(windowed),
            "detail_pages_read": read,
            "detail_pages_failed": failed,
            "returns_measured": len(measured),
            "returns_unmeasured": len(past) - len(measured),
            "undated": sum(1 for row in windowed if row["state"] == STATE_UNDATED),
        },
        "inflation": _inflation_state(
            cpi_index, measured, key_configured=bool(settings.TCMB_EVDS_API_KEY)
        ),
        "delay_minutes": 15,
        "stale": False,
    }
