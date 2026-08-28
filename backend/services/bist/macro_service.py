"""
The Turkish macro backdrop, and the deflators every return on this realm is
measured against.

Two tiers, because one of the two sources needs a key and the other does not:

**Without any configuration** the terminal reads the current inflation rate,
policy rate and exchange rate from the same scanner the equity board uses. That
is enough for the figure that matters most — a one-year return deflated by
one-year inflation — and for dollar-based returns over any window, since the
USDTRY history comes from a public chart endpoint.

**With `TCMB_EVDS_API_KEY` set** the consumer price index series itself becomes
available, and real returns can be computed over any window rather than only
over the trailing year.

The degradation is deliberate and it is one-directional: a window with no
deflator reports its nominal figure and says the real one is unavailable. It
never falls back to a nearby inflation number, because a real return computed
against the wrong window is a specific wrong answer rather than a missing one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, UTC
from typing import Optional

from config import settings
from services.bist.tradingview_client import TradingViewUnavailable
from services.cache import bist_cache
from services.http_client import get_json, get_json_impersonated, post_json

logger = logging.getLogger(__name__)

# Macro series move monthly at best; the policy rate moves eight times a year.
TTL_SNAPSHOT = 30 * 60
TTL_FX = 30 * 60
TTL_CPI = 12 * 60 * 60
MAX_STALE_SNAPSHOT = 7 * 24 * 60 * 60

EVDS_BASE = "https://evds2.tcmb.gov.tr/service/evds"
# TÜFE, 2003=100, monthly. The series every real-return figure in Turkey is
# quoted against.
EVDS_CPI_SERIES = "TP.FG.J0"

# TradingView's economics symbols for Turkey. Keyed by the field they populate
# so a symbol that stops resolving costs one reading rather than the snapshot.
_ECONOMIC_SYMBOLS: dict[str, str] = {
    "inflation_yoy": "ECONOMICS:TRIRYY",
    "ppi_yoy": "ECONOMICS:TRPPIYY",
    "policy_rate": "ECONOMICS:TRINTR",
    "cpi_index": "ECONOMICS:TRCPI",
    "unemployment": "ECONOMICS:TRUR",
    "gdp_yoy": "ECONOMICS:TRGDPYY",
}

_ECONOMIC_COLUMNS = ("name", "description", "close", "change")

# Reported as percentages by the source; stored as fractions everywhere here.
_PERCENT_FIELDS = {"inflation_yoy", "ppi_yoy", "policy_rate", "unemployment", "gdp_yoy"}


class MacroUnavailable(RuntimeError):
    """No macro reading and no recent enough fallback."""


@dataclass(frozen=True)
class MacroSnapshot:
    """Where the Turkish economy is, as of the last published print."""

    inflation_yoy: Optional[float]
    ppi_yoy: Optional[float]
    policy_rate: Optional[float]
    cpi_index: Optional[float]
    unemployment: Optional[float]
    gdp_yoy: Optional[float]
    usdtry: Optional[float]
    eurtry: Optional[float]
    as_of: str
    stale: bool


async def _fetch_economics() -> dict[str, Optional[float]]:
    payload = {
        "symbols": {"tickers": list(_ECONOMIC_SYMBOLS.values()), "query": {"types": []}},
        "columns": list(_ECONOMIC_COLUMNS),
        "options": {"lang": "tr"},
    }
    rows = await _scan_economics(payload)

    by_symbol: dict[str, float] = {}
    for row in rows:
        symbol = row.get("s")
        values = row.get("d")
        if not isinstance(symbol, str) or not isinstance(values, list) or len(values) < 3:
            continue
        close = values[2]
        if isinstance(close, (int, float)) and close == close:
            by_symbol[symbol] = float(close)

    out: dict[str, Optional[float]] = {}
    for field, symbol in _ECONOMIC_SYMBOLS.items():
        value = by_symbol.get(symbol)
        if value is not None and field in _PERCENT_FIELDS:
            value = value / 100
        out[field] = value
    return out


async def _scan_economics(payload: dict) -> list[dict]:
    """
    The economics book lives on its own scanner path.

    Separate from `tradingview_client._scan`, which is pinned to the Turkish
    equity market — the same host, a different universe.
    """
    url = "https://scanner.tradingview.com/economics2/scan"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/",
    }
    try:
        body = await post_json(url, payload=payload, headers=headers, timeout=25.0)
    except Exception as e:  # noqa: BLE001
        raise TradingViewUnavailable(f"economics scan failed: {e}") from e
    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        raise TradingViewUnavailable("economics scan returned no data")
    return body["data"]


async def _fetch_fx_spot() -> dict[str, Optional[float]]:
    """USDTRY and EURTRY, from the chart endpoint that also serves the history."""
    out: dict[str, Optional[float]] = {"usdtry": None, "eurtry": None}
    for field, symbol in (("usdtry", "USDTRY=X"), ("eurtry", "EURTRY=X")):
        try:
            body = await get_json_impersonated(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                params={"range": "5d", "interval": "1d"},
                timeout=15.0,
            )
            out[field] = float(body["chart"]["result"][0]["meta"]["regularMarketPrice"])
        except Exception as e:  # noqa: BLE001
            logger.info("no spot for %s: %s", symbol, e)
    return out


async def fetch_macro_snapshot() -> MacroSnapshot:
    """The current macro readings, or the last ones that resolved."""
    cached = bist_cache.get("macro_snapshot")
    if cached is not None:
        return cached

    try:
        economics = await _fetch_economics()
    except TradingViewUnavailable as e:
        stale = bist_cache.get_with_fallback("macro_snapshot", max_age=MAX_STALE_SNAPSHOT)
        if stale is not None:
            logger.warning("macro snapshot unavailable, serving stale: %s", e)
            return MacroSnapshot(**{**stale.__dict__, "stale": True})
        raise MacroUnavailable(f"Turkish macro series unavailable: {e}") from e

    fx = await _fetch_fx_spot()
    snapshot = MacroSnapshot(
        inflation_yoy=economics.get("inflation_yoy"),
        ppi_yoy=economics.get("ppi_yoy"),
        policy_rate=economics.get("policy_rate"),
        cpi_index=economics.get("cpi_index"),
        unemployment=economics.get("unemployment"),
        gdp_yoy=economics.get("gdp_yoy"),
        usdtry=fx.get("usdtry"),
        eurtry=fx.get("eurtry"),
        as_of=datetime.now(UTC).isoformat(),
        stale=False,
    )
    bist_cache.set("macro_snapshot", snapshot, TTL_SNAPSHOT)
    return snapshot


async def fetch_usdtry_series(range_: str = "5y") -> list[dict]:
    """
    Daily USDTRY, for restating a lira return in dollars over any window.

    Public and unkeyed, which is why dollar-based real returns work on a fresh
    install while inflation-based ones over long windows do not.
    """
    key = f"usdtry:{range_}"
    cached = bist_cache.get(key)
    if cached is not None:
        return cached

    try:
        body = await get_json_impersonated(
            "https://query1.finance.yahoo.com/v8/finance/chart/USDTRY=X",
            params={"range": range_, "interval": "1d"},
            timeout=20.0,
        )
        result = body["chart"]["result"][0]
        stamps = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except Exception as e:  # noqa: BLE001
        logger.info("no USDTRY series: %s", e)
        stale = bist_cache.get_with_fallback(key, max_age=MAX_STALE_SNAPSHOT)
        return stale if stale is not None else []

    series = [
        {
            "date": datetime.fromtimestamp(stamp, tz=UTC).date().isoformat(),
            "rate": float(close),
        }
        for stamp, close in zip(stamps, closes)
        if close is not None
    ]
    if series:
        bist_cache.set(key, series, TTL_FX)
    return series


async def fetch_cpi_series(years: int = 6) -> list[dict]:
    """
    Monthly consumer price index from the central bank's statistical service.

    Returns an empty list when `TCMB_EVDS_API_KEY` is unset — the supported
    no-key state, not a failure. Callers use the presence of a series to decide
    whether a window can be deflated at all; see `deflator_for_window`.
    """
    if not settings.TCMB_EVDS_API_KEY:
        return []

    key = f"cpi:{years}"
    cached = bist_cache.get(key)
    if cached is not None:
        return cached

    end = date.today()
    start = end - timedelta(days=365 * years + 31)
    params = {
        "series": EVDS_CPI_SERIES,
        "startDate": start.strftime("%d-%m-%Y"),
        "endDate": end.strftime("%d-%m-%Y"),
        "type": "json",
    }
    try:
        body = await get_json(
            f"{EVDS_BASE}/series={EVDS_CPI_SERIES}",
            params=params,
            headers={"key": settings.TCMB_EVDS_API_KEY},
            timeout=25.0,
        )
        items = body.get("items", []) if isinstance(body, dict) else []
    except Exception as e:  # noqa: BLE001
        logger.warning("EVDS CPI series unavailable: %s", e)
        stale = bist_cache.get_with_fallback(key, max_age=MAX_STALE_SNAPSHOT)
        return stale if stale is not None else []

    field = EVDS_CPI_SERIES.replace(".", "_")
    series: list[dict] = []
    for item in items:
        raw_month = item.get("Tarih")
        raw_value = item.get(field)
        if not raw_month or raw_value in (None, ""):
            continue
        try:
            series.append({"month": str(raw_month), "index": float(raw_value)})
        except (TypeError, ValueError):
            continue

    if series:
        bist_cache.set(key, series, TTL_CPI)
    return series


# Window keys shared with the fund board, so a caller can ask "what deflates a
# 1y column" without re-deriving the mapping.
WINDOW_MONTHS: dict[str, int] = {"1a": 1, "3a": 3, "6a": 6, "1y": 12, "3y": 36, "5y": 60}


def deflator_for_window(
    window: str,
    snapshot: MacroSnapshot,
    cpi_series: Optional[list[dict]] = None,
) -> Optional[float]:
    """
    Cumulative inflation over a named window, or None if it cannot be known.

    The trailing year is the one case that works with no key at all: a published
    year-on-year inflation rate *is* the deflator for a one-year return, exactly
    and by definition. Every other window needs the index series.

    Returns None rather than approximating. Scaling an annual rate down to six
    months would be a specific wrong number on a page whose entire argument is
    that specific wrong numbers are the problem.
    """
    months = WINDOW_MONTHS.get(window)
    if months is None:
        return None

    if months == 12 and snapshot.inflation_yoy is not None:
        return snapshot.inflation_yoy

    if not cpi_series or len(cpi_series) < months + 1:
        return None

    latest = cpi_series[-1]["index"]
    earlier = cpi_series[-(months + 1)]["index"]
    if earlier <= 0:
        return None
    return latest / earlier - 1
