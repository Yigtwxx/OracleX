"""
Article body extraction for the news-analysis pipeline.

An RSS item carries a headline and a summary the feed truncates to a couple of
hundred characters. Judging whether a story moves a price from that is guesswork:
the mechanism, the figures and the sourcing all live in the body. This module
fetches the page the publisher linked from their own feed and pulls the prose
out of it.

Three properties matter more than extraction cleverness:

* **It never stalls the pipeline.** One hard timeout, one retry, and a per-host
  circuit breaker so a wedged publisher costs the next caller nothing.
* **It never raises.** A failure is a named gap the prompt reports, not an error
  the user sees.
* **It never guesses.** A paywall stub is rejected rather than passed off as the
  article, because a model handed "Subscribe to continue reading" will analyse
  the headline and claim it read the source.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from services import url_guard
from services.cache import ServiceCache
from services.http_client import get_text, get_text_impersonated

logger = logging.getLogger(__name__)

# Transfer cap for a URL we did not choose. Below `http_client`'s 2 MB, above
# the 512 KB a preview card needs: an article body has to survive the cap, a
# malicious response should not get to stream indefinitely.
UNTRUSTED_MAX_BYTES = 1_000_000

# A body shorter than this is a teaser, a consent wall or a paywall stub — not
# an article. Better to report the gap than to analyse boilerplate.
MIN_BODY_CHARS = 400

# News front-loads: the lede and the mechanism are in the first few paragraphs,
# and the tail is related-links and disclaimers. Keeping the head bounds the
# prompt without losing what the judgement turns on.
MAX_BODY_CHARS = 6000

# Paragraphs shorter than this are captions, bylines, share prompts and
# datelines rather than prose.
MIN_PARAGRAPH_CHARS = 40

FETCH_TIMEOUT_SECONDS = 6.0

# An article body does not change. Re-reading the same URL on every click is
# pure latency.
CACHE_TTL_SECONDS = 6 * 60 * 60

# Circuit breaker: after this many failures inside the window, the host is
# skipped outright until the window passes. Without it one dead publisher adds
# the full timeout to every analysis of its items.
BREAKER_THRESHOLD = 3
BREAKER_WINDOW_SECONDS = 600.0

# Structural chrome that carries no article prose.
_STRIP_TAGS = (
    "script",
    "style",
    "nav",
    "aside",
    "footer",
    "header",
    "figure",
    "form",
    "noscript",
    "iframe",
    "button",
)

# Substrings that mark a line as furniture rather than reporting. Matched
# case-insensitively against whole paragraphs, so an article that happens to
# discuss newsletters is not mangled.
_BOILERPLATE_MARKERS = (
    "sign up",
    "subscribe",
    "read more",
    "related:",
    "related articles",
    "follow us",
    "share this",
    "cookie",
    "privacy policy",
    "terms of service",
    "all rights reserved",
    "advertisement",
    "newsletter",
)

# A short body containing one of these is a paywall interstitial, not an article.
_PAYWALL_MARKERS = (
    "subscribe to continue",
    "subscribe to read",
    "this article is for subscribers",
    "create a free account",
    "already a subscriber",
    "sign in to read",
    "become a member",
)

_WHITESPACE = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n{3,}")

_cache = ServiceCache(maxsize=256)
# host -> (failure_count, window_started_at). Plain dict: the event loop is
# single-threaded and a lost increment costs one wasted fetch, not correctness.
_failures: dict[str, tuple[int, float]] = {}


@dataclass
class Article:
    """A publisher's article body, as extracted from their page."""

    text: str
    char_count: int
    url: str
    extracted_via: str  # "json-ld" | "article-tag" | "density"
    truncated: bool


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _breaker_is_open(host: str) -> bool:
    """True when this host has failed enough recently to be worth skipping."""
    if not host:
        return False
    entry = _failures.get(host)
    if not entry:
        return False
    count, started = entry
    if time.monotonic() - started > BREAKER_WINDOW_SECONDS:
        _failures.pop(host, None)
        return False
    return count >= BREAKER_THRESHOLD


def _record_failure(host: str) -> None:
    if not host:
        return
    now = time.monotonic()
    count, started = _failures.get(host, (0, now))
    if now - started > BREAKER_WINDOW_SECONDS:
        count, started = 0, now
    _failures[host] = (count + 1, started)


def _record_success(host: str) -> None:
    _failures.pop(host, None)


def _clean_paragraphs(raw: str) -> str:
    """Drop furniture and collapse whitespace, preserving paragraph breaks."""
    kept: list[str] = []
    for line in raw.splitlines():
        text = _WHITESPACE.sub(" ", line).strip()
        if len(text) < MIN_PARAGRAPH_CHARS:
            continue
        lowered = text.lower()
        if any(marker in lowered for marker in _BOILERPLATE_MARKERS):
            continue
        kept.append(text)
    return _BLANK_LINES.sub("\n\n", "\n\n".join(kept)).strip()


def _from_json_ld(soup: BeautifulSoup) -> str:
    """
    Prefer the publisher's own schema.org `articleBody`.

    When present this is the cleanest possible source: it is the text the
    publisher considers the article, with no navigation to guess around.
    """
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        for node in _iter_ld_nodes(data):
            body = node.get("articleBody")
            if isinstance(body, str) and body.strip():
                return body
    return ""


def _iter_ld_nodes(data: Any):
    """Walk the JSON-LD shapes publishers actually emit (object, list, @graph)."""
    if isinstance(data, list):
        for item in data:
            yield from _iter_ld_nodes(item)
    elif isinstance(data, dict):
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_ld_nodes(item)
        yield data


def _from_article_tag(soup: BeautifulSoup) -> str:
    node = soup.find("article")
    if not node:
        return ""
    return "\n".join(p.get_text(" ", strip=True) for p in node.find_all("p"))


def _from_density(soup: BeautifulSoup) -> str:
    """
    Fall back to the container holding the most prose.

    Scored by total paragraph text length rather than paragraph count, so a
    sidebar of twenty one-line links loses to a two-paragraph story.

    A wrapper always scores at least as high as the container it wraps, so
    scoring alone would keep climbing to <body> and drag the chrome back in.
    Among the containers within a whisker of the best score, the deepest one
    wins — that is the story without its shell.
    """
    candidates: list[tuple[int, int, str]] = []  # (score, depth, text)
    for node in soup.find_all(["div", "section", "main", "article"]):
        paragraphs = node.find_all("p", recursive=True)
        if not paragraphs:
            continue
        texts = [p.get_text(" ", strip=True) for p in paragraphs]
        score = sum(len(t) for t in texts)
        if score:
            candidates.append((score, len(list(node.parents)), "\n".join(texts)))

    if not candidates:
        return ""

    best_score = max(score for score, _, _ in candidates)
    near_best = [c for c in candidates if c[0] >= best_score * 0.9]
    return max(near_best, key=lambda c: c[1])[2]


def _looks_like_paywall(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _PAYWALL_MARKERS)


def extract_body(html: str, url: str) -> Optional[Article]:
    """
    Pull the article prose out of a page. Returns None when nothing usable
    survives — a caller must treat that as "no body", never as an empty article.

    Pure and synchronous, so it is directly testable against fixture HTML.
    """
    if not html or not html.strip():
        return None

    soup = BeautifulSoup(html, "lxml")

    # JSON-LD lives in a <script> tag, so it has to be read before the chrome is
    # stripped — decomposing first silently disabled the best extractor.
    ld_body = _from_json_ld(soup)

    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    strategies = (
        ("json-ld", lambda _soup: ld_body),
        ("article-tag", _from_article_tag),
        ("density", _from_density),
    )

    for name, strategy in strategies:
        try:
            candidate = _clean_paragraphs(strategy(soup))
        except Exception as e:  # a malformed page must not break the pipeline
            logger.debug("article extraction strategy %s failed for %s: %s", name, url, e)
            continue
        if len(candidate) < MIN_BODY_CHARS:
            continue
        if _looks_like_paywall(candidate):
            logger.info("article at %s looks like a paywall stub; treating as unavailable", url)
            return None
        truncated = len(candidate) > MAX_BODY_CHARS
        text = candidate[:MAX_BODY_CHARS].rstrip()
        return Article(
            text=text,
            char_count=len(text),
            url=url,
            extracted_via=name,
            truncated=truncated,
        )

    return None


async def _fetch_html(url: str, timeout: float, trusted_source: bool) -> str:
    """
    Fetch the page, by one of two routes depending on where the URL came from.

    **Untrusted** (the default, and what the chat turn uses): straight through
    `url_guard`, which resolves and checks every redirect hop. The impersonated
    retry is deliberately *not* available here — `curl_cffi` runs its own
    redirect loop that the guard cannot step through, so offering it would hand
    back the SSRF hole the guard exists to close. The cost is that publishers
    who fingerprint the TLS handshake are unreadable from chat.

    **Trusted** (the news pipeline): the URL came out of an RSS feed we chose,
    so the guard buys nothing and the impersonated retry is worth keeping. That
    retry is narrow by design — it only helps against fingerprint-based
    blocking, which surfaces as a 403/406 or a transport-level rejection. There
    is no point replaying a 404.
    """
    if not trusted_source:
        html, _final_url = await url_guard.get_text_guarded(
            url, timeout=timeout, max_bytes=UNTRUSTED_MAX_BYTES
        )
        return html

    try:
        return await get_text(url, timeout=timeout)
    except httpx.HTTPStatusError as e:
        if e.response.status_code not in (401, 403, 406, 418, 429):
            raise
        logger.debug(
            "article fetch for %s got %s; retrying impersonated", url, e.response.status_code
        )
    except httpx.TransportError as e:
        logger.debug(
            "article fetch for %s failed at transport level (%s); retrying impersonated", url, e
        )

    return await get_text_impersonated(url, timeout=timeout)


async def fetch_article(
    url: Optional[str],
    *,
    timeout: float = FETCH_TIMEOUT_SECONDS,
    trusted_source: bool = False,
) -> Optional[Article]:
    """
    Fetch and extract the article at `url`, or return None.

    Never raises. None means "no body available" for any reason — no URL, an
    open circuit breaker, a timeout, a block, a paywall, or a page with no
    extractable prose. The caller renders that as a stated gap.

    `trusted_source` says where the URL came from, and defaults to False so that
    a new caller is guarded unless it opts out on purpose. See `_fetch_html`.
    """
    if not url or not url.strip():
        return None

    cached = _cache.get(url)
    if cached is not None:
        # Misses are cached as False so a dead link is not refetched every click.
        return cached or None

    host = _host_of(url)
    if _breaker_is_open(host):
        logger.debug("skipping article fetch for %s: breaker open for %s", url, host)
        return None

    try:
        html = await asyncio.wait_for(_fetch_html(url, timeout, trusted_source), timeout=timeout)
    except url_guard.UnsafeURL as e:
        # A refusal is a property of the URL, not of the host's health. Counting
        # it towards the breaker would let one bad link close the circuit on a
        # publisher that is answering perfectly well. It is not cached either:
        # the guard is cheap, and caching would mask a later fix.
        logger.info("article fetch for %s refused: %s", url, e)
        return None
    except TimeoutError:
        logger.info("article fetch for %s timed out after %.1fs", url, timeout)
        _record_failure(host)
        return None
    except Exception as e:
        logger.info("article fetch for %s failed: %s", url, e)
        _record_failure(host)
        return None

    _record_success(host)

    article = extract_body(html, url)
    # Cache the miss too: an unextractable page stays unextractable, and the
    # 6h TTL is short enough that a site redesign is picked up the same day.
    _cache.set(url, article or False, ttl=CACHE_TTL_SECONDS)
    if article:
        logger.info(
            "extracted %d chars from %s via %s", article.char_count, url, article.extracted_via
        )
    return article


def render_article_block(article: Optional[Article]) -> str:
    """
    Render the article for the prompt, or state plainly that there isn't one.

    The unavailable branch matters as much as the available one: without it the
    model quietly infers detail the body would have contained and reports it
    with the confidence of something it read.
    """
    if not article:
        return (
            "SOURCE ARTICLE: not retrievable. You have the headline and a truncated feed "
            "summary only. Do not infer detail the body would have contained; lower your "
            "confidence accordingly and report this gap in your reasoning."
        )

    suffix = " (truncated to the opening section)" if article.truncated else ""
    return (
        f"SOURCE ARTICLE ({article.char_count} characters{suffix}) — the only admissible "
        "source of quotes about what this item says. Quote it verbatim; never paraphrase a "
        "figure it contains.\n\n"
        f"{article.text}"
    )


def reset_state() -> None:
    """Clear the cache and breaker. For tests."""
    _cache.clear()
    _failures.clear()
