"""
What a financial page's HTML actually says, for the handful of sites that say it
in a table rather than in prose.

`article_service.extract_body` reads pages that are articles. A TradingView
symbol page, a Finviz screener row or a CoinMarketCap listing is not an article:
its content is a grid of labelled numbers, and a prose extractor either returns
navigation chrome or decides there is nothing readable and gives up. The
important half of the page never reaches the prompt.

This module is the other reader. Given HTML it already has, it returns the
labelled figures a specific host is known to publish — or `None`, which means
"this is not a page I understand", not "this page is empty".

Three properties, all of which are what make it safe to add:

* **Pure and synchronous.** Nothing here fetches. The HTML is handed in by
  whichever rung of `scrape_service`'s ladder managed to get it, so this module
  adds no network surface at all and inherits every guarantee `url_guard` makes
  about how that HTML was obtained. Same contract as
  `article_service.extract_body`, and it is testable against fixture HTML.
* **It does not replace prose extraction.** `scrape_service` runs both.
  `extract_body` carries the paywall-stub check and the length floor; a rung
  that parsed its own way would let a "Subscribe to continue" page through that
  the prose path correctly rejects.
* **A miss returns None, never a zero.** `_parse_number` returns None on
  anything it cannot read, and an extractor that finds no price returns None
  rather than an `Extraction` with holes in it. Selectors on financial sites
  break; a stated gap is recoverable and a confident wrong number is not.

The pattern generalises `macro_board_service._scrapling_quote`, which has been
scraping investing.com this way for a while. `_parse_number` and `_first_text`
moved here from that module so there is one parser rather than two that drift.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Embedded JSON blobs can be megabytes. Parsing one is cheap; parsing an
# unbounded one on a page that turned out to be hostile is not.
MAX_JSON_CHARS = 512_000

# A page that yields fewer than this many usable fields is not worth a block —
# one stray number is more likely a parsing accident than a reading.
MIN_FIELDS = 2


@dataclass(frozen=True)
class Extraction:
    """Labelled figures lifted off one page."""

    host: str
    kind: str  # "quote" | "screener" | "profile"
    title: str
    fields: Dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        """The block body — the caller supplies the fence and the header."""
        lines = [f"{self.title}" if self.title else f"{self.host}"]
        lines.extend(f"- {label}: {value}" for label, value in self.fields.items())
        return "\n".join(lines)


Extractor = Callable[[str, str], Optional[Extraction]]


# ═══════════════════════════════════════════════════════════════════════════════
# PARSING PRIMITIVES
# ═══════════════════════════════════════════════════════════════════════════════

_NUMBER = re.compile(r"-?[\d,.]+")
_TAG = re.compile(r"<[^>]+>")


def parse_number(text: Optional[str]) -> Optional[float]:
    """
    A number out of whatever the page printed around it.

    Returns None rather than 0.0 on failure. That distinction is the whole
    reason this is a shared function: a layout change that starts returning
    zeros is indistinguishable from a market that moved to zero, and every
    caller renders the two differently.
    """
    if not text:
        return None
    match = _NUMBER.search(text.replace(" ", " "))
    if not match:
        return None
    raw = match.group(0).rstrip(".,")

    # Separator conventions differ by locale and both appear on the sites this
    # reads: "64,231.55" on a US page and "1.234,56" on a European one mean the
    # same kind of thing with the roles swapped. The rule that covers both:
    # when a number carries two kinds of separator, the rightmost one is the
    # decimal point and the other is grouping.
    has_dot, has_comma = "." in raw, "," in raw
    if has_dot and has_comma:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif has_comma:
        # One kind only, so grouping has to be told from a decimal by shape:
        # a group is exactly three digits followed by another separator or the
        # end. "1,268,000" is grouped; "0,01" is a Turkish decimal.
        grouped = bool(re.fullmatch(r"-?\d{1,3}(?:,\d{3})+", raw))
        raw = raw.replace(",", "") if grouped else raw.replace(",", ".")

    try:
        value = float(raw)
    except ValueError:
        return None
    # A percentage in parentheses is a fall, written without a minus sign.
    if "(" in text and ")" in text:
        value = -abs(value)
    return value


def first_text(response: Any, selector: str) -> Optional[str]:
    """
    The first non-empty text under `selector`, for a Scrapling response.

    Kept for `macro_board_service`, which holds a parsed response rather than a
    string. The extractors below work on raw HTML because that is what
    `scrape_service`'s rungs have in hand.
    """
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


def _strip_tags(html: str) -> str:
    return _TAG.sub(" ", html)


def _json_blobs(html: str, marker: str) -> List[Any]:
    """
    Every JSON object embedded under a script tag matching `marker`.

    Preferred over CSS selectors wherever a site offers it. Selectors are the
    fastest-rotting thing in a scraper; a site's own data layer changes when its
    data model does, which is far less often than when its designers do.
    """
    blobs: List[Any] = []
    for match in re.finditer(
        rf"<script[^>]*{marker}[^>]*>(.*?)</script>", html, re.DOTALL | re.IGNORECASE
    ):
        body = match.group(1).strip()
        if not body or len(body) > MAX_JSON_CHARS:
            continue
        try:
            blobs.append(json.loads(body))
        except ValueError:
            continue
    return blobs


def _walk(node: Any, wanted: str) -> Optional[Any]:
    """Depth-first search for the first value under `wanted`, at any depth."""
    if isinstance(node, dict):
        if wanted in node:
            return node[wanted]
        for value in node.values():
            found = _walk(value, wanted)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _walk(value, wanted)
            if found is not None:
                return found
    return None


def _labelled(html: str, label: str, window: int = 200) -> Optional[str]:
    """
    The text that follows a visible label on the page.

    A deliberately crude reader for grid layouts, and the reason it is
    acceptable: it is the last resort, it is bounded to a small window, and it
    returns None whenever the label is absent — so a redesign degrades this to
    "no fields" rather than to a wrong number.
    """
    index = html.lower().find(label.lower())
    if index < 0:
        return None
    tail = _strip_tags(html[index + len(label) : index + len(label) + window])
    return tail.strip() or None


def _fmt(value: Optional[float], prefix: str = "", suffix: str = "") -> Optional[str]:
    if value is None:
        return None
    text = f"{value:,.2f}".rstrip("0").rstrip(".") if abs(value) < 1e6 else f"{value:,.0f}"
    return f"{prefix}{text}{suffix}"


def _build(
    host: str, kind: str, title: str, fields: Dict[str, Optional[str]]
) -> Optional[Extraction]:
    """An Extraction, or None when too little of it was readable to be worth one."""
    kept = {label: value for label, value in fields.items() if value not in (None, "", "n/a")}
    if len(kept) < MIN_FIELDS:
        return None
    return Extraction(host=host, kind=kind, title=title or host, fields=kept)


# ═══════════════════════════════════════════════════════════════════════════════
# PER-HOST EXTRACTORS
# ═══════════════════════════════════════════════════════════════════════════════


def _og_title(html: str) -> str:
    match = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html, re.IGNORECASE
    )
    if match:
        return match.group(1).strip()
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
    return _strip_tags(match.group(1)).strip() if match else ""


def _coinmarketcap(html: str, url: str) -> Optional[Extraction]:
    """CoinMarketCap ships its whole page state in `__NEXT_DATA__`."""
    for blob in _json_blobs(html, "__NEXT_DATA__"):
        statistics = _walk(blob, "statistics")
        if not isinstance(statistics, dict):
            continue
        name = _walk(blob, "name")
        return _build(
            "coinmarketcap.com",
            "quote",
            str(name or _og_title(html)),
            {
                "Price": _fmt(statistics.get("price"), "$"),
                "24h change": _fmt(statistics.get("priceChangePercentage24h"), "", "%"),
                "Market cap": _fmt(statistics.get("marketCap"), "$"),
                "24h volume": _fmt(statistics.get("volume"), "$"),
                "Circulating supply": _fmt(statistics.get("circulatingSupply")),
                "All-time high": _fmt(statistics.get("totalSupply") and statistics.get("ath"), "$"),
                "Rank": str(statistics.get("rank")) if statistics.get("rank") else None,
            },
        )
    return None


def _tradingview(html: str, url: str) -> Optional[Extraction]:
    """
    TradingView renders through JavaScript, so this reads the JSON-LD block the
    server does emit — which carries the quote even when the grid does not.
    """
    for blob in _json_blobs(html, "application/ld\\+json"):
        candidates = blob if isinstance(blob, list) else [blob]
        for entry in candidates:
            if not isinstance(entry, dict):
                continue
            price = entry.get("price") or _walk(entry, "price")
            if price is None:
                continue
            return _build(
                "tradingview.com",
                "quote",
                str(entry.get("name") or _og_title(html)),
                {
                    "Price": _fmt(parse_number(str(price)), "$"),
                    "Currency": entry.get("priceCurrency"),
                    "Exchange": _walk(entry, "exchange"),
                    "Symbol": entry.get("tickerSymbol"),
                },
            )
    return None


def _investing(html: str, url: str) -> Optional[Extraction]:
    """investing.com, the same page shape `macro_board_service` already reads."""
    return _build(
        "investing.com",
        "quote",
        _og_title(html),
        {
            "Price": _fmt(parse_number(_labelled(html, 'data-test="instrument-price-last"'))),
            "Change": _labelled(html, 'data-test="instrument-price-change-percent"', 60),
            "Previous close": _fmt(parse_number(_labelled(html, "Prev. Close"))),
            "Day range": _labelled(html, "Day's Range", 60),
            "52 week range": _labelled(html, "52 wk Range", 60),
            "Volume": _labelled(html, "Volume", 40),
        },
    )


def _finviz(html: str, url: str) -> Optional[Extraction]:
    """Finviz's snapshot table — static HTML, which is why it needs no browser."""
    return _build(
        "finviz.com",
        "screener",
        _og_title(html),
        {
            "Price": _fmt(parse_number(_labelled(html, ">Price<", 120)), "$"),
            "P/E": _fmt(parse_number(_labelled(html, ">P/E<", 120))),
            "Forward P/E": _fmt(parse_number(_labelled(html, ">Forward P/E<", 120))),
            "Market cap": _labelled(html, ">Market Cap<", 120),
            "EPS (ttm)": _fmt(parse_number(_labelled(html, ">EPS (ttm)<", 120))),
            "Dividend": _labelled(html, ">Dividend<", 120),
            "52W range": _labelled(html, ">52W Range<", 120),
            "Earnings": _labelled(html, ">Earnings<", 120),
        },
    )


def _yahoo(html: str, url: str) -> Optional[Extraction]:
    """
    Yahoo Finance. A fallback only — `macro_board_service._yahoo_quote` reads
    the JSON API, which is both cheaper and more reliable than this.
    """
    return _build(
        "finance.yahoo.com",
        "quote",
        _og_title(html),
        {
            "Price": _fmt(parse_number(_labelled(html, 'data-field="regularMarketPrice"', 120))),
            "Change": _labelled(html, 'data-field="regularMarketChangePercent"', 80),
            "Market cap": _labelled(html, ">Market Cap<", 120),
            "P/E": _labelled(html, ">PE Ratio (TTM)<", 120),
            "EPS": _labelled(html, ">EPS (TTM)<", 120),
        },
    )


# Host suffix → extractor. Matching is on the suffix so subdomains resolve.
EXTRACTORS: Dict[str, Extractor] = {
    "coinmarketcap.com": _coinmarketcap,
    "tradingview.com": _tradingview,
    "investing.com": _investing,
    "finviz.com": _finviz,
    "finance.yahoo.com": _yahoo,
}


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def has_extractor(url: str) -> bool:
    """Whether this address is one of the pages we know how to read as data."""
    host = host_of(url)
    return any(host == known or host.endswith(f".{known}") for known in EXTRACTORS)


def extract(html: str, url: str) -> Optional[Extraction]:
    """
    The figures this page publishes, or None if it is not one we understand.

    Never raises: an extractor that breaks on a redesign degrades to "no
    structured data on that page", which is exactly what it is.
    """
    if not html:
        return None
    host = host_of(url)
    for known, extractor in EXTRACTORS.items():
        if host == known or host.endswith(f".{known}"):
            try:
                return extractor(html, url)
            except Exception:  # noqa: BLE001 — a broken selector is not a failed turn
                logger.debug("extractor for %s failed", known, exc_info=True)
                return None
    return None
