"""
Fetching a URL somebody else chose.

Every other HTTP helper in this backend talks to an endpoint we picked —
CoinGecko, OKX, a curated RSS feed. This module is for the opposite case: a URL
that arrived from a user, a search result, or a model's plan. That URL is an
instruction to make an outbound request from inside our network, and the danger
is not the page it names but the address that name resolves to.

`services/http_client.get_text` cannot be used for this. It sets
``follow_redirects=True``, so a perfectly public host answering ``302
http://169.254.169.254/latest/meta-data/`` gets chased into the cloud metadata
endpoint, and whatever comes back is returned as page text. The guard therefore
has to own the redirect loop:

  * http and https only — a scheme check that runs before anything is prepended,
    so ``javascript:alert(1)`` cannot be laundered into a host named "javascript"
  * every hostname resolved and every resolved address checked against
    ``ipaddress.is_global`` *before* the connection is made
  * redirects followed by hand, three at most, each hop re-checked
  * ``Content-Type`` must be HTML when asked for, body capped, one timeout

This started as the private half of `services/community/link_preview.py`, which
was the only place fetching a user-chosen URL. It moved here when the chat turn
gained the ability to read a page: the same protection now has two callers, and
a second copy of an SSRF check is a second place for it to drift.

Two error types, because callers need to tell them apart. `UnsafeURL` means we
refused — the URL is not something we will fetch, and retrying is pointless.
`FetchFailed` means we tried and could not read it.
"""

import asyncio
import ipaddress
import logging
import re
import socket
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = {"http", "https"}

# RFC 3986 scheme production. Used to tell "example.com" (no scheme, add one)
# from "javascript:alert(1)" (has a scheme, reject it).
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")

MAX_REDIRECTS = 3
DEFAULT_TIMEOUT = 5.0
DEFAULT_MAX_BYTES = 1_000_000

DEFAULT_HEADERS = {
    "User-Agent": "Oracle-X/1.0 (+https://oracle-x.local)",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class UnsafeURL(ValueError):
    """We refuse to fetch this URL. Not retryable."""


class FetchFailed(RuntimeError):
    """We tried to fetch the URL and could not read a page from it."""


def normalize(url: str) -> str:
    """
    Canonicalise a pasted URL, or raise `UnsafeURL`.

    A bare "example.com" is what people actually paste, so it gets a scheme. The
    test is for *any* scheme, not for "://" — "javascript:alert(1)" has no
    slashes, and prepending https:// to it would smuggle it past the scheme
    check below as a host named "javascript".
    """
    candidate = url.strip()
    if not candidate:
        raise UnsafeURL("no URL given")

    if not _SCHEME_RE.match(candidate):
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURL("only http and https links are supported")
    if not parsed.hostname:
        raise UnsafeURL("that does not look like a URL")
    return candidate


async def assert_public(url: str) -> None:
    """
    Resolve the hostname and refuse anything that is not a public address.

    Raises `UnsafeURL` for a private target and `FetchFailed` when the name does
    not resolve at all — the second is a property of the internet, not of the
    URL, and a caller may want to retry it.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURL("only http and https links are supported")

    host = parsed.hostname
    if not host:
        raise UnsafeURL("that does not look like a URL")

    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None, 0, socket.SOCK_STREAM)
    except socket.gaierror:
        raise FetchFailed("that hostname does not resolve")

    if not infos:
        raise FetchFailed("that hostname does not resolve")

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        # `is_global` is false for loopback, private, link-local (which covers
        # the 169.254.169.254 cloud metadata endpoint), shared and reserved
        # space — one check instead of a list that is easy to leave a hole in.
        if not address.is_global:
            raise UnsafeURL("that URL points at a private address")


def is_public_url(url: str) -> bool:
    """
    Cheap, DNS-free check for a URL we are about to hand to someone else.

    Used for assets a browser will load on our behalf, where the resolution
    happens on the client and a round trip here would buy nothing.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.hostname:
        return False
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        # A name rather than a literal. The browser will resolve it; we are only
        # guarding against an explicit 127.0.0.1-style address here.
        return parsed.hostname.lower() not in {"localhost", "localhost.localdomain"}
    return address.is_global


async def get_text_guarded(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    html_only: bool = True,
    headers: Optional[dict] = None,
) -> tuple[str, str]:
    """
    Fetch `url` as text, validating every redirect hop.

    Returns ``(body, final_url)``. The final URL is not decoration: relative
    links in the body resolve against it, and it is the one the caller should
    record as the source.
    """
    current = url

    async with httpx.AsyncClient(
        timeout=timeout, headers=headers or DEFAULT_HEADERS, follow_redirects=False
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await assert_public(current)

            try:
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise FetchFailed("redirect without a Location header")
                        current = urljoin(current, location)
                        continue

                    response.raise_for_status()

                    if html_only:
                        content_type = response.headers.get("content-type", "")
                        if "html" not in content_type.lower():
                            raise UnsafeURL("that URL does not point at a web page")

                    body = await _read_capped(response, max_bytes)
                    encoding = response.encoding or "utf-8"
                    return body.decode(encoding, errors="replace"), current
            except httpx.HTTPStatusError as exc:
                raise FetchFailed(f"the page answered {exc.response.status_code}")
            except httpx.HTTPError as exc:
                raise FetchFailed(f"could not reach the page: {exc.__class__.__name__}")

    raise FetchFailed("too many redirects")


async def _read_capped(response: httpx.Response, max_bytes: int) -> bytes:
    chunks = []
    total = 0
    async for chunk in response.aiter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total >= max_bytes:
            break
    return b"".join(chunks)[:max_bytes]
