"""
Reading a page the chat turn picked, through whichever door opens.

`article_service` already fetches and extracts article bodies, and for a news
site it is the right tool: one guarded request, three extraction strategies, a
per-host circuit breaker. It fails on two kinds of page that a chat turn asks
for constantly — publishers who fingerprint the TLS handshake and answer 403 to
anything that is not a browser, and sites that serve a JavaScript shell with no
prose in the HTML at all (Reddit, X, StockTwits). Those are exactly the pages a
question about sentiment points at.

So this module is a ladder, cheapest rung first:

  1. `article_service` over the guarded HTTP client — ~1-2s, no new dependency,
     handles the ordinary case and is the only rung with a circuit breaker.
  2. Scrapling's `AsyncFetcher`, which replays a real browser's TLS/HTTP2
     fingerprint — ~2-4s, for the 403 that rung 1 cannot get past.
  3. Scrapling's stealth browser, which actually executes the page — ~6-15s and
     hundreds of megabytes of browser, so it is reserved for hosts known to be
     useless without it.

Extraction is deliberately *not* Scrapling's. Every rung hands its HTML to
`article_service.extract_body`, so all three produce the same shape and inherit
the same refusals — the paywall-stub check, the minimum body length, the 6000
character cap. A rung that parsed its own way would let a "Subscribe to continue
reading" page through on rung 3 that rung 1 correctly rejected.

## Where the SSRF guard applies, and where it cannot

Rungs 1 and 2 are fully guarded: both resolve every hostname before connecting
and walk redirects by hand, refusing any hop that lands on a private address.
Rung 2 can do this because Scrapling's `AsyncFetcher` exposes
`follow_redirects=False` along with the response status and headers, so the loop
stays ours.

Rung 3 cannot. A browser navigates on its own; there is no hook between "decide
to follow this redirect" and "connect". The mitigation is that rung 3 is not
reachable for an arbitrary URL at all — it runs only for hosts in
`JS_SHELL_HOSTS`, a constant in this file. A model or a user cannot steer the
browser at an address of their choosing, because the only addresses it will ever
visit are the five written below.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlparse

from config import settings
from services import article_service, url_guard
from services.cache import ServiceCache

logger = logging.getLogger(__name__)

# Hosts that answer with a JavaScript shell rather than prose. Rung 3 exists for
# these and is restricted to them — see the module docstring on why this list
# being a constant is what makes an unguarded browser acceptable.
#
# x.com is here to be *reached*, not because it works well: even a real browser
# gets a login wall for most of it. It earns its place because the alternative
# is a rung-1 attempt that spends its whole budget to return an empty shell.
JS_SHELL_HOSTS = frozenset(
    {
        "reddit.com",
        "x.com",
        "twitter.com",
        "stocktwits.com",
        "threads.net",
    }
)

# Per-rung budgets. The ladder as a whole is bounded by the caller's `budget`;
# these keep one rung from eating the allowance the next one needs.
DIRECT_TIMEOUT = 8.0
IMPERSONATED_TIMEOUT = 12.0
BROWSER_TIMEOUT = 30.0

# Scrapling's default is 3, which would let one rung spend 3 x IMPERSONATED_
# TIMEOUT. It must not be 0 either: a one-off `AsyncFetcher.get` with retries=0
# builds no session and every call dies with "No active session available", so
# 0 reads as "never retry" and behaves as "never work". 1 is the real floor.
IMPERSONATED_RETRIES = 1

DEFAULT_BUDGET = 25.0

# Rung 1 caches inside `article_service`. Rungs 2 and 3 are the expensive ones
# and had no cache at all — a browser launch repeated for the same URL in the
# same conversation is the single most wasteful thing this module could do.
CACHE_TTL_SECONDS = 6 * 60 * 60
_cache = ServiceCache(maxsize=128)


@dataclass(frozen=True)
class ScrapedPage:
    """Prose pulled off a page, plus which rung produced it."""

    text: str
    char_count: int
    url: str
    via: str  # "direct" | "impersonated" | "browser"
    truncated: bool


@dataclass(frozen=True)
class ScrapeResult:
    """
    The outcome of one ladder run.

    `page` is None whenever nothing readable came back. `reason` says why in the
    words the UI will show the user, because "we did not read that page" and
    "that publisher is not responding" lead to different follow-up questions.

    `browser_used` is separate from `via` on purpose: a browser attempt that
    failed still spent the budget, and the caller's per-turn browser quota has
    to count it.
    """

    page: Optional[ScrapedPage]
    browser_used: bool = False
    reason: str = ""


def is_js_shell_host(url: str) -> bool:
    """Whether `url` points at a host that needs a real browser to say anything."""
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    return any(host == known or host.endswith(f".{known}") for known in JS_SHELL_HOSTS)


def browser_available() -> bool:
    """Whether rung 3 is switched on for this deployment."""
    return bool(settings.SCRAPLING_ALLOW_BROWSER)


async def scrape(
    url: str,
    *,
    budget: float = DEFAULT_BUDGET,
    allow_browser: bool = True,
) -> ScrapeResult:
    """
    Read `url`, climbing the ladder until something returns prose.

    Never raises. `allow_browser` is the caller's per-turn quota talking: pass
    False once a browser has already been spent this turn.
    """
    try:
        target = url_guard.normalize(url)
    except url_guard.UnsafeURL as exc:
        return ScrapeResult(None, reason=str(exc))

    cached = _cache.get(target)
    if cached is not None:
        # A miss is cached as False so a dead page is not re-climbed.
        return ScrapeResult(
            cached or None, reason="" if cached else "nothing readable on that page"
        )

    try:
        return await asyncio.wait_for(_climb(target, allow_browser=allow_browser), timeout=budget)
    except TimeoutError:
        logger.info("scrape of %s ran out of its %.0fs budget", target, budget)
        return ScrapeResult(None, reason="that page took too long to read")
    except Exception as exc:  # noqa: BLE001 — a scrape must never take the turn down
        logger.warning("scrape of %s failed: %s", target, exc)
        return ScrapeResult(None, reason="that page could not be read")


async def _climb(target: str, *, allow_browser: bool) -> ScrapeResult:
    # Check the address once, up front, so a refusal is reported as a refusal.
    #
    # Every rung guards itself, so nothing unsafe was ever fetched without this
    # — but each rung reports its refusal as "no page", and the ladder then read
    # two silent Nones as "the page had nothing on it". The user, and the model
    # reading the step label, were told the wrong thing about why. It also saves
    # climbing rungs that cannot possibly succeed.
    try:
        await url_guard.assert_public(target)
    except url_guard.UnsafeURL as exc:
        return ScrapeResult(None, reason=str(exc))
    except url_guard.FetchFailed as exc:
        return ScrapeResult(None, reason=str(exc))

    browser_wanted = is_js_shell_host(target)
    browser_possible = allow_browser and browser_available()

    # A JS-shell host skips the cheap rungs entirely: they cannot succeed, and
    # spending 20s proving it again is the whole reason this branch exists.
    if browser_wanted and browser_possible:
        return await _browser_rung(target)

    page = await _direct_rung(target)
    if page is None:
        page = await _impersonated_rung(target)

    if page is not None:
        _remember(target, page)
        return ScrapeResult(page)

    if browser_wanted:
        reason = (
            "that site needs a browser to show anything, and one is not available this turn"
            if not browser_possible
            else "that site returned nothing readable"
        )
        return ScrapeResult(None, reason=reason)

    _remember(target, None)
    return ScrapeResult(None, reason="nothing readable on that page")


def _remember(target: str, page: Optional[ScrapedPage]) -> None:
    _cache.set(target, page or False, ttl=CACHE_TTL_SECONDS)


# ── rung 1: the guarded HTTP client ──────────────────────────────────────────


async def _direct_rung(target: str) -> Optional[ScrapedPage]:
    """
    `article_service` over `url_guard`.

    Called through `fetch_article` rather than reaching for the extractor
    directly, so this rung inherits the per-host circuit breaker: a publisher
    that has failed three times recently costs the next turn nothing at all.
    """
    article = await article_service.fetch_article(target, timeout=DIRECT_TIMEOUT)
    return _from_article(article, via="direct")


# ── rung 2: fingerprint impersonation, still guarded ─────────────────────────


async def _impersonated_rung(target: str) -> Optional[ScrapedPage]:
    html, final_url = await _impersonated_get(target)
    if not html:
        return None
    return _from_article(article_service.extract_body(html, final_url), via="impersonated")


async def _impersonated_get(target: str) -> tuple[Optional[str], str]:
    """
    Fetch with a replayed browser fingerprint, walking redirects by hand.

    `follow_redirects=False` is what keeps this rung guarded: with the status
    and Location in our hands, every hop goes through `assert_public` before a
    connection is opened, exactly as `url_guard` does for plain HTTP.
    """
    try:
        from scrapling.fetchers import AsyncFetcher
    except ImportError:
        logger.debug("scrapling is not installed; skipping the impersonated rung")
        return None, target

    current = target
    for _ in range(url_guard.MAX_REDIRECTS + 1):
        try:
            await url_guard.assert_public(current)
        except (url_guard.UnsafeURL, url_guard.FetchFailed) as exc:
            logger.info("impersonated fetch of %s stopped: %s", current, exc)
            return None, current

        try:
            response = await AsyncFetcher.get(
                current,
                timeout=IMPERSONATED_TIMEOUT,
                follow_redirects=False,
                stealthy_headers=True,
                retries=IMPERSONATED_RETRIES,
            )
        except Exception as exc:  # noqa: BLE001 — this rung is optional by design
            logger.info("impersonated fetch of %s failed: %s", current, exc)
            return None, current

        status = getattr(response, "status", 0) or 0
        if status in (301, 302, 303, 307, 308):
            location = (getattr(response, "headers", None) or {}).get("location")
            if not location:
                return None, current
            current = urljoin(current, location)
            continue

        if status >= 400:
            logger.info("impersonated fetch of %s answered %s", current, status)
            return None, current

        return getattr(response, "html_content", "") or "", getattr(response, "url", current)

    return None, current


# ── rung 3: a real browser, allowlisted hosts only ───────────────────────────


async def _browser_rung(target: str) -> ScrapeResult:
    """
    Drive a stealth browser at `target`.

    Reachable only for `JS_SHELL_HOSTS`; see the module docstring. The address
    is still checked before launching — the allowlist stops a chosen target, and
    this stops a listed host that currently resolves somewhere it should not.
    """
    try:
        await url_guard.assert_public(target)
    except (url_guard.UnsafeURL, url_guard.FetchFailed) as exc:
        return ScrapeResult(None, reason=str(exc))

    try:
        from scrapling.fetchers import AsyncStealthySession
    except ImportError:
        return ScrapeResult(None, reason="the browser backend is not installed")

    # `load_dom=True`, deliberately, rather than `network_idle=True`.
    #
    # Measured on r/solana: network_idle took 46.6s and yielded 6000 characters;
    # load_dom took 2.7s and yielded 1224. Reddit streams as you scroll, so the
    # network never goes idle and that rung simply burns its whole timeout. The
    # extra characters are not worth 44 seconds of a chat turn — and the caller
    # clips this block to a couple of thousand characters before it reaches the
    # prompt anyway, so most of what the wait bought was discarded unread.
    try:
        async with AsyncStealthySession(
            headless=True,
            block_ads=True,
            disable_resources=True,
            timeout=BROWSER_TIMEOUT * 1000,
        ) as session:
            response = await session.fetch(target, load_dom=True)
    except Exception as exc:  # noqa: BLE001 — a browser failure is a gap, not a crash
        logger.warning("browser fetch of %s failed: %s", target, exc)
        return ScrapeResult(None, browser_used=True, reason="that site could not be loaded")

    html = getattr(response, "html_content", "") or ""
    final_url = getattr(response, "url", target)
    page = _from_article(article_service.extract_body(html, final_url), via="browser")

    if page is None:
        return ScrapeResult(
            None, browser_used=True, reason="that page had no readable text even in a browser"
        )

    _remember(target, page)
    return ScrapeResult(page, browser_used=True)


# ── shared ───────────────────────────────────────────────────────────────────


def _from_article(article, via: str) -> Optional[ScrapedPage]:
    """Adapt an `article_service.Article` to this module's shape."""
    if not article:
        return None
    return ScrapedPage(
        text=article.text,
        char_count=article.char_count,
        url=article.url,
        via=via,
        truncated=article.truncated,
    )


def reset_state() -> None:
    """Clear the rung-2/3 cache. For tests."""
    _cache.clear()
