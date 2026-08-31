"""
Shared async HTTP helpers.

Provides a single place for sane defaults (timeout, user-agent) and a thin
`get_json` wrapper so individual services don't repeat the
`async with httpx.AsyncClient(...)` + `raise_for_status()` + `.json()` boilerplate.
Callers keep their own try/except so they can apply service-specific fallbacks
(e.g. returning stale cache data).

`get_json_impersonated` is the escape hatch for hosts that refuse ordinary
clients. Several upstreams this project reads — CNN's Fear & Greed data feed,
Yahoo Finance's chart API — now fingerprint the TLS handshake itself and answer
418 or "Too Many Requests" to anything that is not a real browser, no matter
what User-Agent header it sends. `curl_cffi` replays a browser's TLS and HTTP/2
fingerprint, which is enough for all of them; it is not a headless browser and
costs no more than a normal request.

`get_json_yahoo` goes one step further, for the Yahoo endpoints that also demand
a session. `v10/finance/quoteSummary` answers 401 `"Invalid Crumb"` to any
request without a matching cookie jar and `crumb` query parameter — a browser
fingerprint alone is not enough. This helper holds the cookie/crumb pair and
replays it, so callers keep writing a plain GET.
"""

import asyncio
import functools
import logging
import time
from typing import Any, Optional

import httpx

from services.health_registry import health

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
DEFAULT_HEADERS = {"User-Agent": "Oracle-X/1.0 (+https://oracle-x.local)"}

# Ceiling on a streamed HTML body. Article pages are tens of kilobytes; anything
# past this is either a mis-served asset or an upstream that would happily send
# until memory ran out.
DEFAULT_MAX_BYTES = 2_000_000

# Sent in addition to DEFAULT_HEADERS when fetching pages rather than APIs.
# Some publishers serve a JSON error or a stub to clients that do not ask for
# HTML at all.
HTML_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Browser fingerprint replayed for the impersonated path. "chrome" tracks
# curl_cffi's newest supported Chrome rather than pinning a version that ages
# into being conspicuous.
IMPERSONATE_PROFILE = "chrome"

# Priming this host is what puts the session cookies in the jar that Yahoo
# issues a crumb against; the crumb endpoint then hands back a bare token.
YAHOO_COOKIE_URL = "https://fc.yahoo.com"
YAHOO_CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"


def _observe(fetch):
    """
    Report every call through this helper to the health registry.

    Applied here rather than in each service because this is the one place all
    of them already share: attributing an outcome to a data-source category
    needs the URL, and this is the last point at which it is still in hand.

    The registry only remembers hosts it has a mapping for, so decorating a
    helper that also fetches article pages and images costs nothing — unmapped
    hosts are dropped rather than counted against anything.
    """

    @functools.wraps(fetch)
    async def wrapper(url: str, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            result = await fetch(url, *args, **kwargs)
        except BaseException as e:
            health.record_url(url, ok=False, error=e)
            raise
        health.record_url(url, ok=True, latency_ms=int((time.perf_counter() - started) * 1000))
        return result

    return wrapper


@_observe
async def get_json(
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """
    GET `url` and return parsed JSON.

    Raises `httpx.HTTPStatusError` on non-2xx responses and the usual
    `httpx` transport exceptions on network failures — the caller decides
    how to handle them.
    """
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    async with httpx.AsyncClient(timeout=timeout, headers=merged_headers) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()


@_observe
async def post_json(
    url: str,
    *,
    payload: Any,
    headers: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """
    POST `payload` as JSON to `url` and return the parsed JSON response.

    Added for JSON-RPC, which is POST-only: the chain adapters ask a node for a
    block the same way every other service asks an API for a quote, and routing
    it through here is what puts those nodes on the health badge without each
    adapter reporting itself.

    `payload` is deliberately untyped. A JSON-RPC batch is a *list* of request
    objects sent as one body, and that is the shape the EVM adapter relies on to
    read a dozen blocks in a single round trip.

    Same contract as `get_json`: raises on non-2xx and on transport failures.
    Note that this only covers HTTP-level failure. JSON-RPC reports its own
    errors inside a 200 body, so callers must still check for an `error` member.
    """
    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    async with httpx.AsyncClient(timeout=timeout, headers=merged_headers) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


@_observe
async def get_text(
    url: str,
    *,
    headers: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    verify: Any = None,
) -> str:
    """
    GET `url` and return the decoded body, following redirects.

    Reads the response as a stream and stops after `max_bytes`, so a
    mis-advertised or hostile upstream cannot pull an unbounded body into
    memory. The truncated text is still returned — a partially read article is
    more useful than nothing, and the caller's extractor is tolerant of a body
    cut mid-tag.

    `verify` takes an `ssl.SSLContext` for hosts whose chain httpx cannot
    complete on its own. It exists for servers that omit their intermediate
    certificate — the caller supplies the missing link so verification still
    happens, which is the opposite of switching verification off. Leave it None
    and the default certifi bundle is used.

    Raises `httpx.HTTPStatusError` on non-2xx and the usual transport
    exceptions, same contract as `get_json`.
    """
    merged_headers = {**DEFAULT_HEADERS, **HTML_HEADERS, **(headers or {})}
    client_kwargs: dict[str, Any] = {}
    if verify is not None:
        client_kwargs["verify"] = verify
    async with httpx.AsyncClient(
        timeout=timeout, headers=merged_headers, follow_redirects=True, **client_kwargs
    ) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                chunks.append(chunk)
                total += len(chunk)
                if total >= max_bytes:
                    break
            body = b"".join(chunks)[:max_bytes]
            encoding = response.encoding or "utf-8"
    return body.decode(encoding, errors="replace")


@_observe
async def get_text_impersonated(
    url: str,
    *,
    headers: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> str:
    """
    GET `url` with a browser TLS fingerprint and return the decoded body.

    The HTML counterpart to `get_json_impersonated`. Several news publishers
    (MarketWatch, Investing.com, Seeking Alpha) fingerprint the handshake and
    answer 403 to anything that is not a real browser, so an article fetch that
    fails through `get_text` is worth one retry through this path.

    Raises `RuntimeError` if `curl_cffi` is not installed.
    """
    try:
        from curl_cffi import requests as impersonating_requests
    except ImportError as e:  # optional dependency; see requirements.txt
        raise RuntimeError(
            "curl_cffi is required to reach bot-protected upstreams (pip install curl_cffi)"
        ) from e

    merged_headers = {**HTML_HEADERS, **(headers or {})}

    def _fetch() -> str:
        response = impersonating_requests.get(
            url,
            headers=merged_headers,
            timeout=timeout,
            impersonate=IMPERSONATE_PROFILE,
        )
        response.raise_for_status()
        return response.text[: max_bytes // 2]

    return await asyncio.to_thread(_fetch)


@_observe
async def get_json_impersonated(
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """
    GET `url` while replaying a real browser's TLS fingerprint, and return JSON.

    Use this only for hosts that reject ordinary clients — it exists so those
    feeds return their real data instead of the service having to report a
    permanent gap. Everything else should use `get_json`.

    Raises on non-2xx or transport failure, same contract as `get_json`, so the
    caller keeps deciding what a failure means. Raises `RuntimeError` if
    `curl_cffi` is not installed.

    `curl_cffi` is synchronous, so the call runs in a worker thread rather than
    blocking the event loop.
    """
    try:
        from curl_cffi import requests as impersonating_requests
    except ImportError as e:  # optional dependency; see requirements.txt
        raise RuntimeError(
            "curl_cffi is required to reach bot-protected upstreams (pip install curl_cffi)"
        ) from e

    merged_headers = {**(headers or {})}

    def _fetch() -> Any:
        response = impersonating_requests.get(
            url,
            params=params,
            headers=merged_headers or None,
            timeout=timeout,
            impersonate=IMPERSONATE_PROFILE,
        )
        response.raise_for_status()
        return response.json()

    return await asyncio.to_thread(_fetch)


# ── Yahoo Finance session ───────────────────────────────────────────────────
#
# Yahoo's `v10/finance/quoteSummary` authenticates with a cookie jar plus a
# matching `crumb` query parameter and answers 401 "Invalid Crumb" without one —
# a browser TLS fingerprint on its own is not enough, so `get_json_impersonated`
# cannot reach it. The pair is cheap to obtain (two GETs) and good for many
# requests, so it is held module-wide and only re-fetched when Yahoo rejects it.

_yahoo_session: Any = None
_yahoo_crumb: Optional[str] = None
# Built on first use rather than at import: on Python 3.9 `asyncio.Lock()` binds
# to whatever loop is current when it is constructed, and at import time that is
# not the loop the server ends up running on.
_yahoo_lock: Optional[asyncio.Lock] = None


def _get_yahoo_lock() -> asyncio.Lock:
    global _yahoo_lock
    if _yahoo_lock is None:
        _yahoo_lock = asyncio.Lock()
    return _yahoo_lock


def _open_yahoo_session() -> tuple:
    """Open a Yahoo session and fetch a crumb for it. Blocking; runs in a thread."""
    try:
        from curl_cffi import requests as impersonating_requests
    except ImportError as e:  # optional dependency; see requirements.txt
        raise RuntimeError(
            "curl_cffi is required to reach bot-protected upstreams (pip install curl_cffi)"
        ) from e

    session = impersonating_requests.Session(impersonate=IMPERSONATE_PROFILE)
    try:
        session.get(YAHOO_COOKIE_URL, timeout=DEFAULT_TIMEOUT)
    except Exception as e:
        # Yahoo often drops this connection outright. The crumb request sets
        # usable cookies on its own, so this is worth trying but not worth
        # failing on.
        logger.debug("Yahoo cookie priming failed (%s); continuing to crumb request", e)

    response = session.get(YAHOO_CRUMB_URL, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    crumb = response.text.strip()
    # A rejected crumb request answers with an HTML consent page rather than an
    # error status, so check the shape and not just the status code.
    if not crumb or "<" in crumb:
        raise RuntimeError(f"Yahoo returned no usable crumb (got {crumb[:40]!r})")
    return session, crumb


async def _get_yahoo_session(stale_crumb: Optional[str] = None) -> tuple:
    """
    Return the shared (session, crumb) pair, opening one if needed.

    Pass the crumb that was just rejected as `stale_crumb` to force a refresh.
    If another caller already replaced it, that newer crumb is returned instead
    of opening a second session for the same rejection.
    """
    global _yahoo_session, _yahoo_crumb
    async with _get_yahoo_lock():
        if _yahoo_session is None or not _yahoo_crumb or _yahoo_crumb == stale_crumb:
            _yahoo_session, _yahoo_crumb = await asyncio.to_thread(_open_yahoo_session)
        return _yahoo_session, _yahoo_crumb


@_observe
async def get_json_yahoo(
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """
    GET a crumb-authenticated Yahoo Finance endpoint and return JSON.

    Same contract as `get_json`: raises on non-2xx or transport failure, so the
    caller decides what a failure means. Crumbs expire, so a 401 is retried once
    against a freshly opened session before being raised.
    """
    stale_crumb: Optional[str] = None

    def _fetch(session: Any, crumb: str) -> Any:
        return session.get(
            url,
            params={**(params or {}), "crumb": crumb},
            headers=headers or None,
            timeout=timeout,
        )

    for final_attempt in (False, True):
        session, crumb = await _get_yahoo_session(stale_crumb)
        response = await asyncio.to_thread(_fetch, session, crumb)
        if response.status_code == 401 and not final_attempt:
            logger.info("Yahoo rejected the crumb for %s; reopening session", url)
            stale_crumb = crumb
            continue

        response.raise_for_status()
        return response.json()
