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
* Asset allocation survived the migration under a new name and an inverted
  shape: `dagilimSiraliGetirT` ignores `fonKodu` entirely and answers with the
  **whole book** for a date range. So allocation is the cheap call and prices
  are the expensive one, which is the opposite of how the old API read.
* Fund size and investor counts are still gone. No public endpoint carries
  them.

The payloads are fussier than they look, and each endpoint is fussy in its own
way.

The screener returns HTTP 200 with `resultList: null` and no error message when
`calismaTipi` or `getiriOrani` is omitted, which reads exactly like "no funds
matched". Both are sent on every call for that reason. Its dates are rejected
in ISO *and* in Turkish format; the only thing that works is sending null and
filtering client-side.

The allocation endpoint wants the opposite. Its dates are mandatory and only
`yyyyMMdd` parses — ISO fails "at index 4", Turkish "at index 0". It also wants
`basSira`/`bitSira`, and without them answers `errorMessage: "Index 0 out of
bounds for length 0"`. A date with no published data answers with that same
message rather than an empty list, so "the market was shut" and "the request
was malformed" are indistinguishable from the response; `fetch_fund_allocations`
therefore asks for a window of days in one call instead of probing day by day.

Both endpoints sit behind a throttle that answers a second call within roughly a
minute with HTTP 429 and a body in a different shape entirely
(`{"faultCode": "ERR-224"}`). Retrying tightly makes it worse; `fund_service`
caches instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional

# Every call still goes through `services.http_client`. httpx is imported only
# to read a status code back off the exception that helper re-raises — a 429
# here is routine and has to be told apart from an outage.
import httpx

from services.http_client import post_json

logger = logging.getLogger(__name__)

ROOT = "https://www.tefas.gov.tr"
SCREENER_ENDPOINT = f"{ROOT}/api/funds/fonGetiriBazliBilgiGetir"
PRICE_ENDPOINT = f"{ROOT}/api/funds/fonFiyatBilgiGetir"
ALLOCATION_ENDPOINT = f"{ROOT}/api/funds/dagilimSiraliGetirT"

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


class TefasThrottled(TefasUnavailable):
    """
    TEFAS refused a request that arrived too soon after the last one.

    A subclass so every existing `except TefasUnavailable` keeps working, but
    named apart because the two mean opposite things to a caller: an outage is
    worth a warning and a retry, a throttle is worth waiting out quietly. The
    health badge reads the same distinction — logging a rate limit as a failed
    upstream paints the BIST panel red for a service that is working.
    """


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


@dataclass(frozen=True)
class FundAllocationRow:
    """One fund's portfolio split on one day, as TEFAS reports it."""

    code: str
    title: str
    day: date
    weights: dict[str, float]
    """Fractions of the portfolio, keyed by the codes in `ALLOCATION_FIELDS`.

    Fractions rather than the percentages TEFAS sends, for the same reason
    `FundRow.returns` converts: the conversion happens once at this boundary, so
    nothing downstream has to remember which numbers are pre-multiplied.
    `bist-format.formatPercent` then prints a weight and a return the same way.

    Only the fields the fund actually reported are present. An absent field is
    absent, never 0: a fund that holds no gold and a fund whose gold line was
    not published are different claims.
    """


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


# TEFAS's own column dictionary for the allocation endpoint, lifted verbatim
# from the labels the site ships. The names stay in Turkish because they are the
# regulator's own terms and the BIST surface is a Turkish-language surface —
# translating "Kamu Kira Sertifikaları" would invent a term no filing uses.
#
# Every code the endpoint can return is listed even though only about forty are
# ever populated today. A field missing from this map would be dropped silently,
# and a fund's bar would quietly stop summing to a hundred.
ALLOCATION_FIELDS: dict[str, str] = {
    "hs": "Hisse Senedi",
    "yhs": "Yabancı Hisse Senedi",
    "dt": "Devlet Tahvili",
    "hb": "Hazine Bonosu",
    "kibd": "Döviz Cinsi Kamu İç Borçlanma Araçları",
    "kba": "Kamu Dış Borçlanma Araçları",
    "eut": "Eurobonds",
    "kks": "Kamu Kira Sertifikaları",
    "kkstl": "Kamu Kira Sertifikaları (TL)",
    "kksd": "Kamu Kira Sertifikaları (Döviz)",
    "kksyd": "Kamu Yurt Dışı Kira Sertifikaları",
    "ost": "Özel Sektör Tahvili",
    "fb": "Finansman Bonosu",
    "bb": "Banka Bonosu",
    "vdm": "Varlığa Dayalı Menkul Kıymetler",
    "osdb": "Özel Sektör Dış Borçlanma Araçları",
    "osks": "Özel Sektör Kira Sertifikaları",
    "oksyd": "Özel Sektör Yurt Dışı Kira Sertifikaları",
    "db": "Döviz Ödemeli Bono",
    "dot": "Dövize Ödemeli Tahvil",
    "ybkb": "Yabancı Kamu Borçlanma Araçları",
    "ybosb": "Yabancı Özel Sektör Borçlanma Araçları",
    "yba": "Yabancı Borçlanma Aracı",
    "ymk": "Yabancı Menkul Kıymet",
    "vm": "Vadeli Mevduat",
    "vmtl": "Mevduat (TL)",
    "vmd": "Mevduat (Döviz)",
    "vmau": "Mevduat (Altın)",
    "kh": "Katılım Hesabı",
    "khtl": "Katılma Hesabı (TL)",
    "khd": "Katılma Hesabı (Döviz)",
    "khau": "Katılma Hesabı (Altın)",
    "r": "Repo",
    "tr": "Ters-Repo",
    "bpp": "Borsa İstanbul Para Piyasası",
    "tpp": "Takasbank Para Piyasası",
    "btaa": "BİST Taahhütlü İşlem Pazarı Alım",
    "btas": "BİST Taahhütlü İşlem Pazarı Satım",
    "km": "Kıymetli Madenler",
    "kmbyf": "Kıymetli Madenler Cinsinden BYF",
    "kmkba": "Kıymetli Madenler Cinsinden İhraç Edilen Kamu Borçlanma Araçları",
    "kmkks": "Kıymetli Madenler Cinsinden İhraç Edilen Kamu Kira Sertifikaları",
    "yyf": "Yatırım Fonları Katılma Payları",
    "byf": "Borsa Yatırım Fonları Katılma Payları",
    "ybyf": "Yabancı Borsa Yatırım Fonları",
    "fkb": "Fon Katılma Belgesi",
    "gykb": "Gayrimenkul Yatırım Fonları Katılma Payları",
    "gsykb": "Girişim Sermayesi Yatırım Fonları Katılma Payları",
    "gyy": "Gayrimenkul Yatırımları",
    "gsyy": "Girişim Sermayesi Yatırımları",
    "gas": "Gayrı Menkul Sertifikası",
    "t": "Türev Araçları",
    "vint": "Vadeli İşlemler Nakit Teminatları",
    "d": "Diğer",
}

# A weekend either side of a public holiday is the run this has to survive. Past
# that the exchange has been shut for a week and last week's split is still the
# true one, so `fund_service` leans on its stale window rather than a longer
# request that would move ten more megabytes on every refresh.
ALLOCATION_WINDOW_DAYS = 7

# The largest book is around 2,100 funds and the window multiplies it. Asking
# for a cap this far above the real count means hitting it can only mean the
# endpoint changed shape — better to fail loudly than to serve a book missing
# its last alphabetical third.
_ALLOCATION_ROW_CAP = 25_000


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
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            raise TefasThrottled(f"TEFAS refused the request: {e}") from e
        raise TefasUnavailable(f"TEFAS request failed: {e}") from e
    except Exception as e:  # noqa: BLE001 — transport and decode both mean the same here
        raise TefasUnavailable(f"TEFAS request failed: {e}") from e

    if not isinstance(body, dict):
        raise TefasUnavailable("TEFAS returned an unexpected body")

    # The throttle answer is not the usual {errorCode, errorMessage, resultList}
    # envelope at all — it is {faultCode: "ERR-224", faultString: ...}. Checked
    # before the two below, which would otherwise read it as "no result list"
    # and report an outage that is not happening.
    fault = body.get("faultCode")
    if fault:
        raise TefasThrottled(f"TEFAS refused the request: {fault}")

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


def _allocation_payload(fund_type: str, start: date, end: date, cap: int) -> dict:
    """
    The allocation body, in full.

    `basSira`/`bitSira` are the pair that took the longest to find: without them
    the endpoint answers "Index 0 out of bounds for length 0" against a 200,
    which reads like a server fault rather than a missing argument. `fonKodu` is
    present because the site sends it, and null because the endpoint ignores it
    either way — sending a code does not filter anything.
    """
    return {
        "fonTipi": fund_type,
        "fonKodu": None,
        "fonTurKod": None,
        "fonGrubu": None,
        "sfonTurKod": None,
        "fonTurAciklama": None,
        "kurucuKod": None,
        # yyyyMMdd and nothing else. ISO fails at index 4, Turkish at index 0.
        "basTarih": start.strftime("%Y%m%d"),
        "bitTarih": end.strftime("%Y%m%d"),
        "basSira": 1,
        "bitSira": cap,
        "dil": "TR",
    }


async def fetch_fund_allocations(
    fund_type: str = "YAT", *, window_days: int = ALLOCATION_WINDOW_DAYS
) -> list[FundAllocationRow]:
    """
    Every fund's portfolio split, one row per fund, from its newest published day.

    This is the whole book or nothing: the endpoint accepts `fonKodu` and then
    ignores it, so there is no per-fund form to call. Which is the good news —
    an allocation column on the screener costs one request, where the same
    column built from the price endpoint would have cost two thousand.

    The window is not an optimisation, it is the only way to ask. A date TEFAS
    published nothing for answers with an error rather than an empty list, so a
    probe loop walking backwards day by day cannot tell a closed market from a
    broken request, and would spend a request per attempt against a throttle
    that blocks the second call inside a minute. One window covers the weekend,
    the holiday and the gap before the evening publish at once.
    """
    if fund_type not in FUND_TYPES:
        raise ValueError(f"fund_type must be one of {FUND_TYPES}, got {fund_type!r}")

    end = date.today()
    start = end - timedelta(days=window_days)
    rows = await _post(
        ALLOCATION_ENDPOINT, _allocation_payload(fund_type, start, end, _ALLOCATION_ROW_CAP)
    )
    if len(rows) >= _ALLOCATION_ROW_CAP:
        raise TefasUnavailable("TEFAS allocation response hit the row cap and may be truncated")

    newest: dict[str, FundAllocationRow] = {}
    for row in rows:
        code = (row.get("fonKodu") or "").strip().upper()
        raw_day = row.get("tarih")
        if not code or not raw_day:
            continue
        try:
            day = datetime.strptime(str(raw_day), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue

        seen = newest.get(code)
        if seen is not None and seen.day >= day:
            continue

        weights: dict[str, float] = {}
        for field in ALLOCATION_FIELDS:
            value = row.get(field)
            if value is None:
                continue
            weight = _as_fraction(value)
            # A reported zero carries no more information than a missing line
            # and would draw a legend entry for a holding that is not there.
            if weight is not None and weight > 0:
                weights[field] = weight

        newest[code] = FundAllocationRow(
            code=code,
            title=(row.get("fonUnvan") or "").strip(),
            day=day,
            weights=weights,
        )

    return sorted(newest.values(), key=lambda allocation: allocation.code)
