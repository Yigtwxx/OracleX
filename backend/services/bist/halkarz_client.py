"""
Borsa İstanbul's IPO calendar, from the only populated public source there is.

There is no official one, and that is a finding rather than an assumption. KAP
publishes no queryable disclosure API — `/tr/api/disclosure/byCriteria` answers
404 and the tape in `kap_service` is a rolling window a few days deep, so it
sees no offering that closed last month. KAP's company list carries no listing
date. The scanner backfills a trailing-year return for every BIST name, so even
"listed within a year" cannot be inferred from it. What remains is
`halkarz.com`, a community-maintained calendar, and this module treats it as
exactly that: a useful secondary source with no contract, no versioning and no
obligation to keep its markup stable.

Three consequences run through everything below.

**Every field is parsed by its own label, not by position.** The detail page is
a list of Turkish label/value pairs. Keying off the third `<span>` in the fourth
`<div>` would make any layout change cost the whole page; keying off the words
"Bist İlk İşlem Tarihi" makes it cost one field, and the caller records which.

**Nothing is ever guessed.** A date that does not parse is `None`, not today's
date and not a year inferred from context — a 2019 offering with a mangled date
would otherwise appear in the upcoming tray. A price band with no struck price
yields no price. Callers record the field name in `unparsed` and the board says
"belli değil" out loud, which is what makes parser rot countable rather than
invisible.

**The whole document is untrusted third-party text.** Every free-text field is
length-capped and stripped of control characters at parse time, before it can
reach a cache, a payload or a prompt.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field as dataclass_field
from datetime import date
from typing import Any, Optional

from bs4 import BeautifulSoup

from services.bist.text import fold
from services.http_client import get_text

logger = logging.getLogger(__name__)

BASE = "https://halkarz.com"
INDEX_URL = f"{BASE}/"

# Length caps, applied at parse time. The board displays these and the note
# module sanitises them again before any of them can reach a prompt.
MAX_COMPANY = 200
MAX_BROKER = 120
MAX_SHORT = 80

TR_MONTHS: dict[str, int] = {
    "ocak": 1,
    "subat": 2,
    "mart": 3,
    "nisan": 4,
    "mayis": 5,
    "haziran": 6,
    "temmuz": 7,
    "agustos": 8,
    "eylul": 9,
    "ekim": 10,
    "kasim": 11,
    "aralik": 12,
}

TICKER_RE = re.compile(r"^[A-Z]{3,6}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SLUG_RE = re.compile(r"^https?://[^/]+/([A-Za-z0-9\-]+)/?$")
_TIMESTAMP_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})")


class HalkarzUnavailable(RuntimeError):
    """halkarz.com did not answer, or answered with nothing parseable."""


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date


@dataclass(frozen=True)
class Money:
    low: float
    high: float
    is_band: bool


@dataclass(frozen=True)
class ResultGroup:
    key: str
    label: str
    investors: Optional[int]
    lots: Optional[int]
    share: Optional[float]


@dataclass(frozen=True)
class IpoResults:
    groups: tuple[ResultGroup, ...]
    total_investors: Optional[int]
    total_lots: Optional[int]


@dataclass(frozen=True)
class IpoStructure:
    capital_increase_lots: Optional[int]
    share_sale_lots: Optional[int]
    capital_increase_share: Optional[float]
    spk_bulletin: Optional[str]


@dataclass(frozen=True)
class ProceedsLine:
    label: str
    share: Optional[float]


@dataclass(frozen=True)
class IndexRow:
    slug: str
    url: str
    company: str
    ticker: Optional[str]
    offer_dates_raw: Optional[str]
    is_new: bool


@dataclass(frozen=True)
class DetailFields:
    ticker: Optional[str] = None
    offer_dates_raw: Optional[str] = None
    listing_date_raw: Optional[str] = None
    price_raw: Optional[str] = None
    lots_raw: Optional[str] = None
    free_float_lots_raw: Optional[str] = None
    free_float_pct_raw: Optional[str] = None
    broker: Optional[str] = None
    method: Optional[str] = None
    market: Optional[str] = None
    updated_at: Optional[str] = None
    results: Optional[IpoResults] = None
    structure: Optional[IpoStructure] = None
    use_of_proceeds: Optional[tuple[ProceedsLine, ...]] = None
    proceeds_source: Optional[str] = None
    """The prospectus page the split was read from, as the site cites it."""
    labels_seen: tuple[str, ...] = dataclass_field(default_factory=tuple)


# ── Text hygiene ─────────────────────────────────────────────────────────────


def clean(raw: Any, limit: int = MAX_SHORT) -> Optional[str]:
    """Untrusted text as a bounded single line, or None when there is nothing."""
    if raw is None:
        return None
    text = _CONTROL_RE.sub(" ", str(raw))
    text = " ".join(text.split())
    text = text[:limit].strip()
    return text or None


# NFKD decomposes ş, ğ, ç, ö and ü into a base letter plus a combining mark, so
# stripping the marks folds them. It does **not** touch ı (U+0131): the dotless i
# is its own letter, not an i with something removed, and it survives every
# normalisation form intact. Every label key below is written with a plain `i`,
# so without this mapping "Aracı Kurum" folds to "aracı kurum", misses "araci
# kurum", and the field comes back empty with nothing raising anywhere.
_LATINISE = str.maketrans({"ı": "i", "İ": "i", "ﬁ": "fi"})


def _ascii_fold(text: str) -> str:
    """Turkish-folded, de-accented and dotless-i mapped, for matching labels."""
    decomposed = unicodedata.normalize("NFKD", fold(text).translate(_LATINISE))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


# ── Scalar parsers ───────────────────────────────────────────────────────────


def parse_lots(raw: Optional[str]) -> Optional[int]:
    """
    `40.000.000 Lot` → 40000000.

    The dot is a thousands separator. `float("40.000.000")` raises, but
    `float("40.000")` does not — it returns 40.0, which is the failure mode that
    would silently turn a forty-million-lot offering into forty.
    """
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", str(raw).replace(",", "."))
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _decimal(raw: str) -> Optional[float]:
    """A Turkish-formatted number: dot groups thousands, comma is the point."""
    text = raw.strip().replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def parse_try_amount(raw: Optional[str]) -> Optional[Money]:
    """
    `53,60 TL` → a single price; `12,00 - 14,50 TL` → a band.

    Both hyphen and en-dash appear on the site. A band is flagged rather than
    collapsed to a midpoint: a midpoint is a specific number nobody offered at,
    and a return computed against it would be wrong in a way that looks measured.
    """
    if not raw:
        return None
    text = str(raw).replace("–", "-").replace("—", "-")
    numbers = [
        value
        for value in (_decimal(match) for match in re.findall(r"\d[\d.]*(?:,\d+)?", text))
        if value is not None
    ]
    if not numbers:
        return None
    if len(numbers) == 1:
        return Money(numbers[0], numbers[0], False)
    low, high = min(numbers[0], numbers[1]), max(numbers[0], numbers[1])
    return Money(low, high, low != high)


def parse_percent(raw: Optional[str]) -> Optional[float]:
    """`%24,99` or `24,99%` → 0.2499."""
    if not raw:
        return None
    match = re.search(r"\d[\d.]*(?:,\d+)?", str(raw))
    if match is None:
        return None
    value = _decimal(match.group(0))
    return None if value is None else value / 100


def parse_turkish_date(raw: Optional[str], *, today: Optional[date] = None) -> Optional[DateRange]:
    """
    `26-27 Ağustos 2026` → a two-day window; `1 Eylül 2026` → one day.

    Also handles a range crossing a month boundary, where the leading day
    belongs to the *earlier* month: `31 Ağustos - 1 Eylül 2026`.

    Returns None for anything else, including `Hazırlanıyor...` — the site's
    marker for an offering with no announced date — and for any date without a
    year. Inferring the current year is the one shortcut that must not be taken:
    it would file an old offering as an upcoming one.
    """
    if not raw:
        return None
    text = _ascii_fold(str(raw)).replace("–", "-").replace("—", "-")
    if "hazirlaniyor" in text:
        return None

    year_match = re.search(r"\b(19|20)\d{2}\b", text)
    if year_match is None:
        return None
    year = int(year_match.group(0))

    # Every (day, month) pair the string carries, in order. A bare leading day
    # with no month of its own borrows the first month that follows it.
    months = [
        (match.start(), TR_MONTHS[match.group(0)])
        for match in re.finditer("|".join(TR_MONTHS), text)
    ]
    if not months:
        return None

    days: list[tuple[int, int]] = []
    for match in re.finditer(r"\b(\d{1,2})\b(?!\d)", text):
        day = int(match.group(1))
        if not 1 <= day <= 31:
            continue
        if match.start() >= year_match.start():
            continue
        following = [month for position, month in months if position > match.start()]
        if not following:
            continue
        days.append((day, following[0]))

    if not days:
        return None

    try:
        start_day, start_month = days[0]
        end_day, end_month = days[-1]
        start = date(year, start_month, start_day)
        end = date(year, end_month, end_day)
    except ValueError:
        return None

    # A range that ends before it starts is a parse that went wrong, not a
    # window to silently swap into shape.
    if end < start:
        return None
    return DateRange(start, end)


def parse_timestamp(raw: Optional[str]) -> Optional[str]:
    """`03.09.2026 17:01` → `2026-09-03T17:01`. The site's own freshness stamp."""
    if not raw:
        return None
    match = _TIMESTAMP_RE.search(str(raw))
    if match is None:
        return None
    day, month, year, hour, minute = match.groups()
    try:
        date(int(year), int(month), int(day))
    except ValueError:
        return None
    return f"{year}-{month}-{day}T{hour}:{minute}"


def slug_from_href(href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    match = _SLUG_RE.match(str(href).strip())
    return match.group(1) if match else None


def normalise_ticker(raw: Optional[str]) -> Optional[str]:
    """A BIST code, or None. Structural trust stops here."""
    text = clean(raw, 12)
    if not text:
        return None
    code = text.upper()
    return code if TICKER_RE.match(code) else None


# ── Index ────────────────────────────────────────────────────────────────────


def parse_index(html: str) -> list[IndexRow]:
    """
    Every offering the calendar lists, newest first.

    A row whose BIST code is still blank is kept. The code is assigned only once
    the exchange admits the share, so dropping unassigned rows would delete
    exactly the upcoming offerings the calendar exists for.
    """
    soup = BeautifulSoup(html, "lxml")
    rows: list[IndexRow] = []
    seen: set[str] = set()

    for article in soup.select("article.index-list"):
        heading = article.select_one("h3.il-halka-arz-sirket a")
        if heading is None:
            # One malformed article must not cost the other two hundred.
            continue
        slug = slug_from_href(heading.get("href"))
        if not slug or slug in seen:
            continue
        seen.add(slug)

        company = clean(heading.get("title") or heading.get_text(), MAX_COMPANY)
        if not company:
            continue

        code_node = article.select_one(".il-bist-kod")
        time_node = article.select_one(".il-halka-arz-tarihi time")
        raw_date = None
        if time_node is not None:
            raw_date = clean(time_node.get("datetime") or time_node.get_text(), MAX_SHORT)

        rows.append(
            IndexRow(
                slug=slug,
                url=f"{BASE}/{slug}/",
                company=company,
                ticker=normalise_ticker(code_node.get_text() if code_node else None),
                offer_dates_raw=raw_date,
                is_new=article.select_one(".il-new") is not None,
            )
        )
    return rows


# ── Detail ───────────────────────────────────────────────────────────────────

# Label → the `DetailFields` attribute it fills. Matched on folded text so
# casing and stray whitespace on the page cannot cost a field.
_LABELS: dict[str, str] = {
    "halka arz tarihi": "offer_dates_raw",
    "halka arz fiyati/araligi": "price_raw",
    "halka arz fiyati": "price_raw",
    "dagitim yontemi": "method",
    "pay": "lots_raw",
    "araci kurum": "broker",
    "fiili dolasimdaki pay": "free_float_lots_raw",
    "fiili dolasimdaki pay orani (%)": "free_float_pct_raw",
    "bist kodu": "ticker",
    "pazar": "market",
    "bist ilk islem tarihi": "listing_date_raw",
    "son guncelleme": "updated_at",
}

_GROUP_KEYS: dict[str, str] = {
    "yurt ici bireysel": "domestic_retail",
    "yurt ici kurumsal": "domestic_institutional",
    "yurt disi bireysel": "foreign_retail",
    "yurt disi kurumsal": "foreign_institutional",
}


def _label_values(soup: BeautifulSoup) -> dict[str, str]:
    """
    Every `Label : Value` pair on the page, keyed by folded label.

    Read out of the flattened text rather than by walking a container, because
    the site wraps these in a different element on completed and upcoming pages
    and the words are the one thing common to both.
    """
    text = soup.get_text("\n")
    found: dict[str, str] = {}
    lines = [" ".join(line.split()) for line in text.split("\n")]
    lines = [line for line in lines if line]

    for index, line in enumerate(lines):
        stripped = line.rstrip(":").strip()
        key = _ascii_fold(stripped)
        if key not in _LABELS:
            continue
        # The value is either on the same line after the colon, or the next
        # non-empty line — both shapes appear on the same page.
        if ":" in line and line.split(":", 1)[1].strip():
            value = line.split(":", 1)[1].strip()
        elif index + 1 < len(lines):
            value = lines[index + 1]
        else:
            continue
        found.setdefault(key, value)
    return found


def parse_results_table(soup: BeautifulSoup) -> Optional[IpoResults]:
    """
    The allocation table, present only once the book has closed.

    The `Toplam` row is used as a sanity denominator and is not emitted as a
    group. Shares that sum to 0.98 are passed through unchanged: the source
    rounds, and normalising to 1.0 would invent precision the page never claimed.
    """
    # Only the allocation table. The page carries other four-column tables —
    # a summary of the company's own financials, for one — and a row-shape
    # match alone happily reads "Brüt Kâr" as an investor group.
    table = None
    for candidate in soup.select("table"):
        header = _ascii_fold(candidate.get_text(" "))
        if "yatirimci grubu" in header:
            table = candidate
            break
    if table is None:
        return None

    groups: list[ResultGroup] = []
    total_investors: Optional[int] = None
    total_lots: Optional[int] = None

    for row in table.select("tr"):
        cells = [clean(cell.get_text(), MAX_SHORT) or "" for cell in row.find_all(["td", "th"])]
        if len(cells) < 4:
            continue
        label = cells[0]
        key = _ascii_fold(label)
        if key.startswith("toplam"):
            total_investors = parse_lots(cells[1])
            total_lots = parse_lots(cells[2])
            continue
        mapped = _GROUP_KEYS.get(key)
        investors, lots, share = parse_lots(cells[1]), parse_lots(cells[2]), parse_percent(cells[3])
        if investors is None and lots is None and share is None:
            continue
        groups.append(
            ResultGroup(
                # An unrecognised Turkish label keeps its own text and is
                # bucketed as `other`, never dropped: a missing slice would make
                # the allocation bar add up to less than the page says.
                key=mapped or "other",
                label=label,
                investors=investors,
                lots=lots,
                share=share,
            )
        )

    if not groups:
        return None
    return IpoResults(tuple(groups), total_investors, total_lots)


def parse_structure(soup: BeautifulSoup) -> Optional[IpoStructure]:
    """Capital increase against shareholder sale, and the SPK bulletin it cites."""
    text = " ".join(soup.get_text(" ").split())
    folded = _ascii_fold(text)

    def lots_after(needle: str) -> Optional[int]:
        position = folded.find(needle)
        if position < 0:
            return None
        window = text[position : position + 120]
        match = re.search(r"([\d.]+)\s*Lot", window, re.IGNORECASE)
        return parse_lots(match.group(1)) if match else None

    increase = lots_after("sermaye artirimi")
    sale = lots_after("ortak satisi")
    if increase is None and sale is None:
        return None

    total = (increase or 0) + (sale or 0)
    bulletin_match = re.search(r"SPK B[üu]lteni,?\s*([\d/]+)", text, re.IGNORECASE)

    return IpoStructure(
        capital_increase_lots=increase,
        share_sale_lots=sale,
        capital_increase_share=(increase or 0) / total if total else None,
        spk_bulletin=clean(bulletin_match.group(1), 20) if bulletin_match else None,
    )


def parse_proceeds(soup: BeautifulSoup) -> Optional[tuple[ProceedsLine, ...]]:
    """
    What the prospectus says the money is for.

    Kept in document order rather than sorted by size: the order is the
    company's own stated priority, and re-ranking it would be editorialising a
    filing.
    """
    text = " ".join(soup.get_text(" ").split())
    folded = _ascii_fold(text)
    position = folded.find("fonun kullanim yeri")
    if position < 0:
        return None

    # The block ends at its own citation marker — "* İzahname, Sayfa 319." —
    # which is the page's structural boundary between sections. A fixed
    # character window instead ran into "Halka Arz Satış Yöntemi" below it and
    # read a percentage out of the next section as a third use of proceeds.
    tail = text[position + len("Fonun Kullanım Yeri") :]
    end = tail.find("*")
    window = tail[: end if end > 0 else 400]

    lines = [
        ProceedsLine(label=label, share=share)
        for label, share in (
            (clean(match.group(2), MAX_SHORT), parse_percent(match.group(1)))
            # Anchored on the page's own bullet, so a percentage in running
            # prose cannot be mistaken for a line item.
            for match in re.finditer(r"-\s*%\s*([\d,]+)\s*([^%\-\*\n]{3,70})", window)
        )
        if label and share is not None
    ]
    return tuple(lines) if lines else None


def parse_proceeds_source(soup: BeautifulSoup) -> Optional[str]:
    """The prospectus page the use-of-proceeds split cites, so the board can attribute it."""
    text = " ".join(soup.get_text(" ").split())
    match = re.search(r"İzahname,?\s*Sayfa\s*(\d{1,5})", text, re.IGNORECASE)
    return f"İzahname, sayfa {match.group(1)}" if match else None


def parse_detail(html: str) -> DetailFields:
    """One offering's page. Every block below the fold is optional."""
    soup = BeautifulSoup(html, "lxml")
    values = _label_values(soup)

    picked: dict[str, Any] = {}
    for label, attribute in _LABELS.items():
        if label in values:
            picked.setdefault(attribute, values[label])

    return DetailFields(
        ticker=normalise_ticker(picked.get("ticker")),
        offer_dates_raw=clean(picked.get("offer_dates_raw"), MAX_SHORT),
        listing_date_raw=clean(picked.get("listing_date_raw"), MAX_SHORT),
        price_raw=clean(picked.get("price_raw"), MAX_SHORT),
        lots_raw=clean(picked.get("lots_raw"), MAX_SHORT),
        free_float_lots_raw=clean(picked.get("free_float_lots_raw"), MAX_SHORT),
        free_float_pct_raw=clean(picked.get("free_float_pct_raw"), MAX_SHORT),
        broker=clean(picked.get("broker"), MAX_BROKER),
        method=clean(picked.get("method"), MAX_SHORT),
        market=clean(picked.get("market"), MAX_SHORT),
        updated_at=parse_timestamp(picked.get("updated_at")),
        results=parse_results_table(soup),
        structure=parse_structure(soup),
        use_of_proceeds=parse_proceeds(soup),
        proceeds_source=parse_proceeds_source(soup),
        labels_seen=tuple(sorted(values)),
    )


# ── Fetching ─────────────────────────────────────────────────────────────────


async def fetch_index() -> list[IndexRow]:
    try:
        html = await get_text(INDEX_URL, timeout=25.0)
    except Exception as e:  # noqa: BLE001
        raise HalkarzUnavailable(f"halkarz index unavailable: {e}") from e
    rows = parse_index(html)
    if not rows:
        raise HalkarzUnavailable("halkarz index carried no parseable rows")
    return rows


async def fetch_detail(slug: str) -> DetailFields:
    try:
        html = await get_text(f"{BASE}/{slug}/", timeout=25.0)
    except Exception as e:  # noqa: BLE001
        raise HalkarzUnavailable(f"halkarz detail for {slug} unavailable: {e}") from e
    return parse_detail(html)
