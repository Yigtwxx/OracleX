"""
Raw access to TEFAS, Turkey's electronic fund trading platform.

Shape adaptation only: this module turns tefas.gov.tr's JSON into dataclasses
and does nothing else with it. Screening, ranking and risk statistics belong to
`fund_service` and `fund_metrics`.

**The API changed in 2026 and the old recipes no longer work.** The ASP.NET
endpoints (`BindHistoryInfo`, `BindHistoryAllocation`) that every tutorial and
scraping library still documents were retired. Two JSON endpoints replaced them
and the shapes are not equivalent:

* The screener returns every fund with its period returns in one call — good.
* Prices are **per fund only**, over a fixed look-back enum. There is no
  all-funds-on-one-date call any more, so building a cross-section means one
  request per fund, which is why `fund_service` caches hard.
* Asset allocation, fund size and investor counts are **gone**. No public
  endpoint carries them. Anything in this codebase that wants a fund's holdings
  has to find them somewhere else — see `holdings_service`.

The screener payload is fussier than it looks. Omitting `calismaTipi` or
`getiriOrani` returns HTTP 200 with `resultList: null` and no error message at
all, which reads exactly like "no funds matched". Both are sent on every call
for that reason. Dates are rejected in ISO *and* in Turkish format; the only
thing that works is sending null and filtering client-side.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from services.http_client import post_json

logger = logging.getLogger(__name__)

ROOT = "https://www.tefas.gov.tr"
SCREENER_ENDPOINT = f"{ROOT}/api/funds/fonGetiriBazliBilgiGetir"
PRICE_ENDPOINT = f"{ROOT}/api/funds/fonFiyatBilgiGetir"

# TEFAS rejects an unfamiliar client outright, and the platform is behind a WAF
# that blocks automated browsers while letting a plain request through. These
# are the headers that work.
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{ROOT}/",
    "Origin": ROOT,
}

# The three books TEFAS keeps. `YAT` is retail mutual funds — the ones a person
# buys through their bank — and is what the terminal shows by default.
FUND_TYPES = ("YAT", "EMK", "BYF")
FUND_TYPE_LABELS = {
    "YAT": "Yatırım fonu",
    "EMK": "Emeklilik fonu",
    "BYF": "Borsa yatırım fonu",
}

# The look-back is an enum, not a date range. Asking for anything else returns
# an empty list rather than an error.
VALID_PERIODS = (1, 3, 6, 12, 36, 60)


class TefasUnavailable(RuntimeError):
    """TEFAS did not answer, or answered with something unusable."""


@dataclass(frozen=True)
class FundRow:
    """One fund as the screener describes it."""

    code: str
    title: str
    umbrella: str
    """Şemsiye fon type — "Hisse Senedi Şemsiye Fonu" and so on."""
    tradable: bool
    """`tefasDurum`: false means the fund exists but is closed to TEFAS orders."""
    risk_value: Optional[int]
    """TEFAS's own 1–7 risk grade. Not derived from the price series."""
    returns: dict[str, Optional[float]]
    """Period returns as fractions, keyed by `1a`, `3a`, `6a`, `1y`, `3y`, `5y`, `yb`."""


@dataclass(frozen=True)
class PricePoint:
    """One day's net asset value."""

    day: date
    price: float


@dataclass(frozen=True)
class FundPrices:
    code: str
    title: str
    category_rank: Optional[int]
    category_size: Optional[int]
    points: list[PricePoint]


# The screener reports returns as percentages; everything downstream works in
# fractions, so the conversion happens once, here, at the boundary.
_RETURN_FIELDS = {
    "1a": "getiri1a",
    "3a": "getiri3a",
    "6a": "getiri6a",
    "1y": "getiri1y",
    "3y": "getiri3y",
    "5y": "getiri5y",
    "yb": "getiriyb",
}


def _as_fraction(value: Any) -> Optional[float]:
    """A percentage from TEFAS as a fraction, or None if it is not a number."""
    if value is None:
        return None
    try:
        return float(value) / 100
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _post(endpoint: str, payload: dict) -> list[dict]:
    """
    POST to TEFAS and return `resultList`, or raise.

    A null `resultList` is treated as a failure rather than as an empty result.
    TEFAS uses it for a malformed request as readily as for a genuine miss, and
    the two are indistinguishable from the response — so the safe reading is
    "something is wrong", not "there are no funds".
    """
    try:
        body = await post_json(endpoint, payload=payload, headers=_HEADERS, timeout=30.0)
    except Exception as e:  # noqa: BLE001 — transport, status and decode all mean the same here
        raise TefasUnavailable(f"TEFAS request failed: {e}") from e

    if not isinstance(body, dict):
        raise TefasUnavailable("TEFAS returned an unexpected body")

    error = body.get("errorMessage")
    if error:
        raise TefasUnavailable(f"TEFAS reported: {error}")

    rows = body.get("resultList")
    if rows is None:
        raise TefasUnavailable("TEFAS returned no result list")
    if not isinstance(rows, list):
        raise TefasUnavailable("TEFAS result list was not a list")
    return rows


def _screener_payload(fund_type: str) -> dict:
    """
    The screener body, in full.

    Every null here is load-bearing — the endpoint wants the keys present even
    when it wants no value in them. `calismaTipi` and `getiriOrani` are the two
    that were missing when this first returned a null list against a 200.
    """
    return {
        "dil": "TR",
        "fonTipi": fund_type,
        "kurucuKodu": None,
        "sfonTurKod": None,
        "fonTurAciklama": None,
        "islem": 1,
        "fonTurKod": None,
        "fonGrubu": None,
        "donemGetiri1a": "1",
        "donemGetiri3a": "1",
        "donemGetiri6a": "1",
        "donemGetiri1y": "1",
        "donemGetiriyb": "1",
        "donemGetiri3y": "1",
        "donemGetiri5y": "1",
        "basTarih": None,
        "bitTarih": None,
        "calismaTipi": 2,
        "getiriOrani": "1",
    }


async def fetch_fund_rows(fund_type: str = "YAT") -> list[FundRow]:
    """Every fund of one type, with its published period returns."""
    if fund_type not in FUND_TYPES:
        raise ValueError(f"fund_type must be one of {FUND_TYPES}, got {fund_type!r}")

    rows = await _post(SCREENER_ENDPOINT, _screener_payload(fund_type))

    funds: list[FundRow] = []
    for row in rows:
        code = (row.get("fonKodu") or "").strip().upper()
        if not code:
            continue
        funds.append(
            FundRow(
                code=code,
                title=(row.get("fonUnvan") or "").strip(),
                umbrella=(row.get("fonTurAciklama") or "").strip(),
                tradable=bool(row.get("tefasDurum")),
                risk_value=_as_int(row.get("riskDegeri")),
                returns={
                    key: _as_fraction(row.get(field)) for key, field in _RETURN_FIELDS.items()
                },
            )
        )
    return funds


async def fetch_fund_prices(code: str, months: int = 12) -> FundPrices:
    """
    One fund's daily net asset value over the requested look-back.

    `months` is snapped to the nearest supported value rather than rejected: the
    enum is an upstream quirk and every caller asking for 24 months means "as
    close to two years as you can give me".
    """
    code = code.strip().upper()
    if not code:
        raise ValueError("fund code is required")

    period = min(VALID_PERIODS, key=lambda valid: abs(valid - months))
    rows = await _post(PRICE_ENDPOINT, {"fonKodu": code, "dil": "TR", "periyod": period})

    points: list[PricePoint] = []
    title = ""
    rank: Optional[int] = None
    size: Optional[int] = None

    for row in rows:
        title = title or (row.get("fonUnvan") or "").strip()
        rank = rank if rank is not None else _as_int(row.get("kategoriDerece"))
        size = size if size is not None else _as_int(row.get("kategoriFonSay"))

        raw_day = row.get("tarih")
        raw_price = row.get("fiyat")
        if not raw_day or raw_price is None:
            continue
        try:
            day = datetime.strptime(str(raw_day), "%Y-%m-%d").date()
            price = float(raw_price)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        points.append(PricePoint(day=day, price=price))

    # TEFAS returns the series in date order, but sorting here rather than
    # trusting that is what keeps every statistic downstream honest — a single
    # out-of-order row silently inverts a drawdown.
    points.sort(key=lambda point: point.day)

    return FundPrices(code=code, title=title, category_rank=rank, category_size=size, points=points)
