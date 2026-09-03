"""
One company's shareholder table, read off İş Yatırım's company card.

**Why this host and not KAP.** KAP carries the same "Sermaye ve Ortaklık
Yapısı" block, but reaching it needs the company's opaque KAP id and the page
is rendered client-side. İş Yatırım's card is addressed by ticker, is served as
one static document, and embeds the shareholder table as a JavaScript literal
for its pie chart — `var OrtaklikYapisidata = [{name: 'Türkiye Varlık Fonu',
y: 49.12}, …]` — which is the most machine-readable form the figure is
published in anywhere. The host was already mapped to the `bist` health
category with nothing calling it.

**What the table is.** Holders above the 5% disclosure threshold, as a share
of paid-in capital, plus one `Diğer` row that is the rest — the free float and
every holder below the threshold, together. `Diğer` is therefore not a holder
and is kept apart as `other_pct`. A card with no named row (KRDMD, 93% float,
which does not even render the table) is a real answer: nobody crosses 5%.

**Units.** Everything here is in percent, as the card prints it. The board
converts to fractions when it stores a card, because every `/api/bist/*`
payload carries percentages as fractions and the frontend formats them on
that assumption.

**What is truncated.** Names are clipped to fifty characters — `Family
Danışmanlık Gayrimenkul Ve Ticaret Anonim Ş` — so a registry alias may have to
be the clipped form, and the matcher in `registry` allows a prefix match on a
row that long. Foreign names arrive title-cased with Turkish dotless `ı`
(`Banco Bılbao Vızcaya Argentarıa`), which is what Turkish-folding is for.

The page is about 1.1 MB, almost all of it navigation. `max_bytes` is raised
for this host so the table, which sits near the end, is not cut off.
"""

from __future__ import annotations

import html as html_module
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from services.http_client import get_text

logger = logging.getLogger(__name__)

SOURCE_HOST = "www.isyatirim.com.tr"
SOURCE_LABEL = "İş Yatırım"
CARD_URL = (
    "https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/sirket-karti.aspx?hisse={ticker}"
)

# The card is ~1.1 MB and the shareholder literal sits past the first megabyte.
# The default 2 MB cap would usually hold, but a longer card would lose exactly
# the part this module exists to read, so the ceiling is explicit.
CARD_MAX_BYTES = 4_000_000

# The row that is not a holder.
OTHER_LABEL = "Diğer"

# What says "this is a company card": the shareholder table element or the
# summary table with the headline ratios. Either alone is enough — KRDMD's
# card carries the ratios and no shareholder table at all, because nobody
# crosses 5% of it — and neither means the page is not a card. An unknown
# ticker renders the same template with none of them.
_TABLE_MARKER = re.compile(r'id="partnerShipTable"')
_LITERAL = re.compile(r"var\s+OrtaklikYapisidata\s*=\s*(\[.*?\]);", re.S)
_ROW = re.compile(r"\{\s*name:\s*'((?:[^'\\]|\\.)*)'\s*,\s*y:\s*(-?[\d.]+)\s*\}")

# `<th>Yabancı Oranı (%)</th> <td>53,22</td>` and its neighbours. Turkish
# decimal marks throughout: `.` groups thousands and `,` is the point.
_FOREIGN = re.compile(r"Yabancı Oranı \(%\)</th>\s*<td>\s*([^<]*?)\s*</td>")
_FREE_FLOAT = re.compile(r"Halka Açıklık Oranı \(%\)</th>\s*<td>\s*([^<]*?)\s*</td>")
_MARKET_CAP = re.compile(r"Piyasa Değeri</th>\s*<td>\s*([^<]*?)\s*</td>")


class IsYatirimUnavailable(RuntimeError):
    """The card could not be fetched, or was fetched and was not a company card."""


@dataclass(frozen=True)
class Shareholder:
    name: str
    """As printed — title-cased, possibly clipped at fifty characters."""
    pct: float
    """Share of paid-in capital, in percent."""


@dataclass(frozen=True)
class CompanyCard:
    ticker: str
    shareholders: tuple[Shareholder, ...]
    other_pct: float | None
    """The `Diğer` row: free float plus every holder under the threshold."""
    foreign_ratio_pct: float | None
    free_float_pct: float | None
    market_cap_try: float | None
    """From the card's own summary table, in lira. The equity board's figure is
    preferred where both exist; this one is a fallback for a ticker the board
    does not carry."""
    url: str
    retrieved_at: str


def _turkish_number(raw: str) -> float | None:
    """`544.457,3` → 544457.3. Returns None for anything that is not a number."""
    text = raw.strip().replace("\xa0", "")
    if not text:
        return None
    text = re.sub(r"[^\d,.\-]", "", text)
    text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _market_cap(raw: str) -> float | None:
    # `544.457,3 mnTL` — the unit is millions of lira. Anything else (an
    # absent unit, a different one) is refused rather than guessed at.
    if "mnTL" not in raw:
        return None
    value = _turkish_number(raw.replace("mnTL", ""))
    return value * 1_000_000 if value is not None else None


def parse_company_card(body: str, ticker: str, *, url: str = "") -> CompanyCard | None:
    """
    The card's shareholder table and headline ratios, or None if the body is
    not a company card.

    None rather than an empty card: a ticker İş Yatırım does not know renders
    the same template with the table absent, and treating that as "no holder
    above 5%" would be the plausible wrong answer this file is written against.
    """
    foreign = _FOREIGN.search(body)
    free_float = _FREE_FLOAT.search(body)
    market_cap = _MARKET_CAP.search(body)
    if not (_TABLE_MARKER.search(body) or free_float or market_cap):
        return None

    shareholders: list[Shareholder] = []
    other_pct: float | None = None
    literal = _LITERAL.search(body)
    if literal:
        for raw_name, raw_pct in _ROW.findall(literal.group(1)):
            name = html_module.unescape(raw_name.replace("\\'", "'")).strip()
            try:
                pct = float(raw_pct)
            except ValueError:
                continue
            if name == OTHER_LABEL:
                other_pct = pct
                continue
            if not name:
                continue
            shareholders.append(Shareholder(name=name, pct=pct))

    return CompanyCard(
        ticker=ticker,
        shareholders=tuple(sorted(shareholders, key=lambda s: -s.pct)),
        other_pct=other_pct,
        foreign_ratio_pct=_turkish_number(foreign.group(1)) if foreign else None,
        free_float_pct=_turkish_number(free_float.group(1)) if free_float else None,
        market_cap_try=_market_cap(market_cap.group(1)) if market_cap else None,
        url=url or CARD_URL.format(ticker=ticker),
        retrieved_at=datetime.now(UTC).isoformat(),
    )


async def fetch_company_card(ticker: str) -> CompanyCard:
    """One card. Raises `IsYatirimUnavailable` rather than returning a hollow one."""
    code = ticker.strip().upper()
    if ":" in code:
        code = code.rsplit(":", 1)[1]
    if not code:
        raise ValueError("ticker is required")

    url = CARD_URL.format(ticker=code)
    try:
        body = await get_text(url, max_bytes=CARD_MAX_BYTES, timeout=30.0)
    except (httpx.HTTPError, OSError) as e:
        raise IsYatirimUnavailable(f"İş Yatırım card for {code} unavailable: {e}") from e

    card = parse_company_card(body, code, url=url)
    if card is None:
        raise IsYatirimUnavailable(f"İş Yatırım returned no company card for {code}")
    return card
