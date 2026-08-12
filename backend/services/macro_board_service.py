"""
The macro board: commodity futures, benchmark equity indices and the dollar.

One payload for one page. The board is small and fixed — 14 commodities and 12
indices from `asset_registry` — so it is built in a single pass and cached whole
rather than per-symbol: a page that showed metals from one minute and indices
from another would invite comparisons that were never true at the same instant.

Two rungs, cheapest first:

  1. Yahoo's v8 chart endpoint through the impersonating client. It answers
     "Too Many Requests" to ordinary clients regardless of User-Agent — it
     fingerprints the TLS handshake — which is why this cannot use `get_json`.
     One request per symbol, all in flight together.
  2. Scrapling's `AsyncFetcher` against investing.com, for the symbols rung 1
     dropped. HTTP only, no browser: this rung costs no download and no
     `SCRAPLING_ALLOW_BROWSER`.

Rung 2 reaches a **constant map** of URLs, never a template built from a caller's
input, for the same reason `scrape_service.JS_SHELL_HOSTS` is a constant: the
only addresses this module will ever visit are the ones written below.

The house rule holds throughout — a reading that could not be taken is `None`,
never `0`. A quote that failed on both rungs keeps its row (so the board does not
silently shrink) with a null price the page renders as an em dash.
"""

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import Any, Optional

from services.asset_registry import GLOBAL_INDICES, MACRO_COMMODITIES
from services.cache import market_cache
from services.home_service import UpstreamUnavailable
from services.http_client import get_json_impersonated
from services.stock_market_service import fetch_stock_sparklines

logger = logging.getLogger(__name__)

# ==========================================
# CONSTANTS
# ==========================================

YAHOO_CHART_API = "https://query1.finance.yahoo.com/v8/finance/chart"
YAHOO_TIMEOUT = 15.0

# Two minutes matches the equity overview. Futures print continuously, but the
# board is read at a glance rather than traded off, and 26 symbols per refresh
# is the cost being paced here.
TTL_BOARD = 120

# How old a replayed board may be before the outage is reported instead. Half an
# hour of drift is still worth showing with a "stale" flag; beyond that the
# numbers stop describing the current session.
MAX_STALE_BOARD = 30 * 60
CACHE_KEY = "macro_board"

SCRAPLING_TIMEOUT = 15.0

# Symbol → investing.com instrument page, for rung 2. A constant map rather than
# a URL template: nothing a caller sends can steer this fetch at an address of
# its choosing. Only the symbols with a stable public page are listed; the rest
# simply have no second rung.
INVESTING_URLS: dict[str, str] = {
    "GC=F": "https://www.investing.com/commodities/gold",
    "SI=F": "https://www.investing.com/commodities/silver",
    "PL=F": "https://www.investing.com/commodities/platinum",
    "PA=F": "https://www.investing.com/commodities/palladium",
    "HG=F": "https://www.investing.com/commodities/copper",
    "CL=F": "https://www.investing.com/commodities/crude-oil",
    "BZ=F": "https://www.investing.com/commodities/brent-oil",
    "NG=F": "https://www.investing.com/commodities/natural-gas",
    "ZW=F": "https://www.investing.com/commodities/us-wheat",
    "ZC=F": "https://www.investing.com/commodities/us-corn",
    "ZS=F": "https://www.investing.com/commodities/us-soybeans",
    "KC=F": "https://www.investing.com/commodities/us-coffee-c",
    "SB=F": "https://www.investing.com/commodities/us-sugar-no11",
    "CT=F": "https://www.investing.com/commodities/us-cotton-no.2",
    "DX-Y.NYB": "https://www.investing.com/indices/usdollar",
    "^GSPC": "https://www.investing.com/indices/us-spx-500",
    "^IXIC": "https://www.investing.com/indices/nasdaq-composite",
    "^DJI": "https://www.investing.com/indices/us-30",
    "^FTSE": "https://www.investing.com/indices/uk-100",
    "^GDAXI": "https://www.investing.com/indices/germany-30",
    "^N225": "https://www.investing.com/indices/japan-ni225",
    "^HSI": "https://www.investing.com/indices/hang-sen-40",
    "^STOXX50E": "https://www.investing.com/indices/eu-stoxx50",
    "^FCHI": "https://www.investing.com/indices/france-40",
    "^AXJO": "https://www.investing.com/indices/aus-200",
    "XU100.IS": "https://www.investing.com/indices/ise-100",
}

# investing.com's own test hooks. They survive class-name churn in a way CSS
# structure selectors do not, which is what makes this rung worth having.
PRICE_SELECTOR = '[data-test="instrument-price-last"]'
CHANGE_PCT_SELECTOR = '[data-test="instrument-price-change-percent"]'

# The primary cash session of each region, in local time, as (open, close) minutes
# from midnight. Weekends are excluded; public holidays and half-days are NOT
# modelled — the badge describes the ordinary schedule, which is why it says
# "Open"/"Closed" rather than claiming to know today's calendar.
_REGION_SESSIONS: dict[str, tuple[str, int, int]] = {
    "US": ("America/New_York", 9 * 60 + 30, 16 * 60),
    "UK": ("Europe/London", 8 * 60, 16 * 60 + 30),
    "DE": ("Europe/Berlin", 9 * 60, 17 * 60 + 30),
    "FR": ("Europe/Paris", 9 * 60, 17 * 60 + 30),
    "EU": ("Europe/Berlin", 9 * 60, 17 * 60 + 30),
    # The Tokyo midday recess (11:30–12:30) is deliberately not modelled: the
    # badge marks the session, not the tape.
    "JP": ("Asia/Tokyo", 9 * 60, 15 * 60 + 30),
    "HK": ("Asia/Hong_Kong", 9 * 60 + 30, 16 * 60),
    "AU": ("Australia/Sydney", 10 * 60, 16 * 60),
    "TR": ("Europe/Istanbul", 10 * 60, 18 * 60),
}

# Ratios the board derives. Each is (key, label, numerator, denominator,
# decimals) — every leg is already on the board, so none of these costs a
# request. The decimal count is per-ratio because they do not share a scale:
# copper-over-gold lands near 0.0015, and two decimals would round a live
# reading down to a flat 0.00, which is precisely the fake zero this module
# refuses to print anywhere else.
_RATIOS: tuple[tuple[str, str, str, str, int], ...] = (
    ("gold_silver", "Gold / Silver", "GC=F", "SI=F", 2),
    ("gold_oil", "Gold / Oil", "GC=F", "CL=F", 2),
    ("copper_gold", "Copper / Gold", "HG=F", "GC=F", 5),
)


# ==========================================
# RUNG 1 — Yahoo
# ==========================================


def _quote_from_chart(payload: Any) -> Optional[dict[str, Any]]:
    """
    Pull the quote fields out of a v8 chart response.

    Returns `None` rather than a zero-filled dict when the payload carries no
    price: the caller distinguishes "no reading" from "a reading of zero", and
    a commodity cannot trade at zero anyway.
    """
    try:
        meta = payload["chart"]["result"][0]["meta"]
    except (KeyError, IndexError, TypeError):
        return None

    price = meta.get("regularMarketPrice")
    if price is None:
        return None

    previous = meta.get("chartPreviousClose") or meta.get("previousClose")
    change_24h = None
    if previous:
        change_24h = round((float(price) - float(previous)) / float(previous) * 100, 2)

    high_52w = meta.get("fiftyTwoWeekHigh")
    low_52w = meta.get("fiftyTwoWeekLow")

    return {
        "price": float(price),
        "change_24h": change_24h,
        "high_52w": float(high_52w) if high_52w else None,
        "low_52w": float(low_52w) if low_52w else None,
        "currency": meta.get("currency"),
        "source": "yahoo",
    }


async def _yahoo_quote(symbol: str) -> Optional[dict[str, Any]]:
    """One symbol from Yahoo, or `None` if it did not answer with a price."""
    try:
        payload = await get_json_impersonated(
            f"{YAHOO_CHART_API}/{symbol}",
            params={"interval": "1d", "range": "2d"},
            timeout=YAHOO_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — one symbol failing is not the board failing
        logger.info("Yahoo quote for %s failed: %s", symbol, exc)
        return None

    return _quote_from_chart(payload)


# ==========================================
# RUNG 2 — Scrapling / investing.com
# ==========================================


def _parse_number(text: str) -> Optional[float]:
    """
    Read a displayed number: '4,377.15' → 4377.15, '(+1.80%)' → 1.80.

    Anything that does not contain a number returns `None` rather than 0.0 — a
    layout change upstream must surface as a missing reading, not a flat quote.
    """
    match = re.search(r"[-+]?\d[\d,]*\.?\d*", text or "")
    if not match:
        return None
    try:
        value = float(match.group(0).replace(",", ""))
    except ValueError:
        return None
    # The percent element wraps a fall in parentheses without a minus sign.
    if "(" in text and "-" in text:
        value = -abs(value)
    return value


def _first_text(response: Any, selector: str) -> Optional[str]:
    try:
        elements = response.css(selector)
    except Exception as exc:  # noqa: BLE001 — a selector miss is not fatal
        logger.debug("selector %s failed: %s", selector, exc)
        return None
    for element in elements:
        text = element.get_all_text().strip()
        if text:
            return text
    return None


async def _scrapling_quote(symbol: str) -> Optional[dict[str, Any]]:
    """
    Second-rung quote for `symbol`, scraped from its fixed investing.com page.

    Only price and 24h change: the page's 52-week range and history live behind
    separate widgets, and inventing those fields from a different source than
    the price would let the board compare two different instants.
    """
    url = INVESTING_URLS.get(symbol)
    if not url:
        return None

    try:
        from scrapling.fetchers import AsyncFetcher
    except ImportError:
        logger.debug("scrapling is not installed; skipping the scraped rung")
        return None

    try:
        response = await AsyncFetcher.get(
            url,
            timeout=SCRAPLING_TIMEOUT,
            stealthy_headers=True,
        )
    except Exception as exc:  # noqa: BLE001 — this rung is optional by design
        logger.info("scraped quote for %s failed: %s", symbol, exc)
        return None

    status = getattr(response, "status", 0) or 0
    if status >= 400:
        logger.info("scraped quote for %s answered %s", symbol, status)
        return None

    price = _parse_number(_first_text(response, PRICE_SELECTOR) or "")
    if price is None:
        return None

    return {
        "price": price,
        "change_24h": _parse_number(_first_text(response, CHANGE_PCT_SELECTOR) or ""),
        "high_52w": None,
        "low_52w": None,
        "currency": None,
        "source": "investing",
    }


# ==========================================
# DERIVED FIELDS
# ==========================================


def _region_status(region: str) -> dict[str, str]:
    """
    Whether `region`'s primary cash session is running right now.

    Unknown regions and a broken timezone database both report "unknown" rather
    than defaulting to closed — a badge that says "Closed" during trading hours
    is worse than one that admits it does not know.
    """
    session = _REGION_SESSIONS.get(region)
    if not session:
        return {"status": "unknown", "label": "—"}

    zone, opens, closes = session
    try:
        import pytz  # type: ignore

        now = datetime.now(pytz.timezone(zone))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not resolve timezone %s: %s", zone, exc)
        return {"status": "unknown", "label": "—"}

    if now.weekday() >= 5:
        return {"status": "closed", "label": "Closed"}

    minutes = now.hour * 60 + now.minute
    if opens <= minutes < closes:
        return {"status": "open", "label": "Open"}
    return {"status": "closed", "label": "Closed"}


def _change_from_series(series: Optional[list[float]]) -> Optional[float]:
    """
    Percent change across the drawn series.

    Derived from the very points the sparkline plots so the number and the line
    can never disagree — the same rule the equity overview follows.
    """
    if not series or len(series) < 2:
        return None
    first, last = series[0], series[-1]
    if not first:
        return None
    return round((last - first) / first * 100, 2)


def _build_ratios(prices: dict[str, Optional[float]]) -> list[dict[str, Any]]:
    """
    Classic macro quotients, from prices the board already holds.

    A missing leg yields a `None` value, never a 0 or a silently dropped row: the
    ratio strip keeps its shape so a gap reads as a gap. No historical baseline
    is attached — the board has no such series, and quoting a remembered average
    would be an assertion nothing here can support.
    """
    ratios: list[dict[str, Any]] = []
    for key, label, numerator, denominator, decimals in _RATIOS:
        top, bottom = prices.get(numerator), prices.get(denominator)
        value = round(top / bottom, decimals) if top and bottom else None
        caption = f"{top:,.2f} / {bottom:,.2f}" if top and bottom else "Unavailable"
        ratios.append(
            {"key": key, "label": label, "value": value, "decimals": decimals, "caption": caption}
        )
    return ratios


# ==========================================
# BOARD
# ==========================================


async def _resolve_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Every symbol through rung 1, then the stragglers through rung 2."""
    primary = await asyncio.gather(*(_yahoo_quote(symbol) for symbol in symbols))
    quotes = {symbol: quote for symbol, quote in zip(symbols, primary) if quote}

    missing = [symbol for symbol in symbols if symbol not in quotes]
    if missing:
        logger.info("Yahoo dropped %d macro symbols; trying the scraped rung", len(missing))
        fallback = await asyncio.gather(*(_scrapling_quote(symbol) for symbol in missing))
        quotes.update({symbol: quote for symbol, quote in zip(missing, fallback) if quote})

    return quotes


def _row(
    symbol: str,
    meta: dict[str, str],
    quote: Optional[dict[str, Any]],
    series: Optional[list[float]],
) -> dict[str, Any]:
    """One board row. Absent readings stay `None` so the page can render them as such."""
    quote = quote or {}
    return {
        "symbol": symbol,
        "name": meta["name"],
        "price": quote.get("price"),
        "change_24h": quote.get("change_24h"),
        "change_7d": _change_from_series(series),
        "high_52w": quote.get("high_52w"),
        "low_52w": quote.get("low_52w"),
        "currency": quote.get("currency"),
        "sparkline": series or [],
        "source": quote.get("source"),
    }


async def fetch_macro_board() -> dict[str, Any]:
    """
    The whole board: commodities, indices and derived ratios.

    Serves the cached copy while it is fresh. On an upstream failure it replays
    the last good board, flagged `stale`, for up to `MAX_STALE_BOARD`; past that
    it raises rather than presenting half-hour-old prices as current.
    """
    cached = market_cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    commodity_symbols = list(MACRO_COMMODITIES)
    index_symbols = list(GLOBAL_INDICES)
    symbols = commodity_symbols + index_symbols

    try:
        quotes, sparklines = await asyncio.gather(
            _resolve_quotes(symbols),
            fetch_stock_sparklines(symbols),
        )
    except Exception as exc:  # noqa: BLE001 — degrade to the last good board
        logger.error("Macro board fetch failed: %s", exc)
        quotes, sparklines = {}, {}

    if not quotes:
        return _replay_or_fail("no macro quotes could be resolved")

    commodities = [
        _row(symbol, MACRO_COMMODITIES[symbol], quotes.get(symbol), sparklines.get(symbol))
        | {
            "group": MACRO_COMMODITIES[symbol]["group"],
            "unit": MACRO_COMMODITIES[symbol]["unit"],
        }
        for symbol in commodity_symbols
    ]

    indices = [
        _row(symbol, GLOBAL_INDICES[symbol], quotes.get(symbol), sparklines.get(symbol))
        | {
            "region": GLOBAL_INDICES[symbol]["region"],
            "market_status": _region_status(GLOBAL_INDICES[symbol]["region"]),
        }
        for symbol in index_symbols
    ]

    board = {
        "commodities": commodities,
        "indices": indices,
        "ratios": _build_ratios(
            {symbol: quotes.get(symbol, {}).get("price") for symbol in symbols}
        ),
        "as_of": datetime.now(UTC).isoformat(),
        "stale": False,
    }

    market_cache.set(CACHE_KEY, board, TTL_BOARD)
    return board


def _replay_or_fail(reason: str) -> dict[str, Any]:
    """Last good board flagged stale, or `UpstreamUnavailable` if none is recent enough."""
    stale = market_cache.get_with_fallback(CACHE_KEY, max_age=MAX_STALE_BOARD)
    if stale:
        # The status is recomputed: sessions open and close while a board sits in
        # the fallback slot, and a replayed "Open" badge would be a fresh claim
        # made from stale data.
        replayed = {
            **stale,
            "stale": True,
            "indices": [
                {**row, "market_status": _region_status(row["region"])} for row in stale["indices"]
            ],
        }
        return replayed
    raise UpstreamUnavailable(f"Macro board is unavailable: {reason}")


async def fetch_macro_indices() -> list[dict[str, Any]]:
    """
    The board's index rows in the shape `/api/market/indices` has always served.

    Exists so the global ticker reads from the same cached board as the macro
    page instead of its own uncached fetch — the two used to disagree by minutes.
    Rows without a price are dropped here: the ticker scrolls a fixed strip and
    has nowhere to put an em dash.
    """
    board = await fetch_macro_board()
    return [
        {
            "symbol": row["symbol"],
            "name": row["name"],
            "price": round(row["price"], 2),
            "change_24h": row["change_24h"] if row["change_24h"] is not None else 0.0,
            "region": row["region"],
        }
        for row in board["indices"]
        if row["price"] is not None
    ]
