"""
OpenGraph preview for link posts.

The SSRF guard this module used to own now lives in `services/url_guard.py`: the
chat turn gained the ability to read a page, so a second caller needed the same
protection, and two copies of an SSRF check is two places for it to drift. What
stays here is the part that is specific to a community post — extracting a
preview card, and translating the guard's errors into the community error
vocabulary that `routers/community.py` maps to status codes.

The guard's properties still hold, and are the reason `http_client.get_text` is
not used: http/https only, every resolved address checked before connecting,
redirects walked by hand with each hop re-checked, HTML content-type enforced.

Results are cached in the shared `ServiceCache`, and the winning values are
copied onto the post row at create time so the feed never re-fetches.
"""

import logging
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from models.community import LinkPreview
from services import url_guard
from services.cache import ServiceCache

from .errors import InvalidRequest, UpstreamFailure

logger = logging.getLogger(__name__)

# A preview card is a thumbnail and two lines of text; it never needs the
# megabyte the guard allows a chat turn to read.
MAX_BYTES = 512_000
FETCH_TIMEOUT_SECONDS = 5.0
CACHE_TTL_SECONDS = 60 * 60 * 6

_HEADERS = {
    **url_guard.DEFAULT_HEADERS,
    "User-Agent": "Oracle-X/1.0 (+https://oracle-x.local) link-preview",
}

_cache = ServiceCache(maxsize=256)


async def fetch_link_preview(url: str) -> LinkPreview:
    """
    Resolve `url` to a preview card.

    Raises `InvalidRequest` for a URL we refuse to fetch and `UpstreamFailure`
    when the remote page cannot be read. A caller that would rather show a bare
    domain than an error should catch both.
    """
    normalized = _normalize(url)

    cached = _cache.get(normalized)
    if cached is not None:
        return cached

    html, final_url = await _fetch(normalized)
    preview = extract_preview(html, final_url)
    _cache.set(normalized, preview, ttl=CACHE_TTL_SECONDS)
    return preview


def extract_preview(html: str, url: str) -> LinkPreview:
    """
    Pull the card fields out of a page.

    Pure and synchronous so it can be tested against fixture HTML. Falls back
    from OpenGraph to Twitter cards to the plain `<title>`/`<meta description>`,
    because plenty of pages worth linking never adopted `og:`.
    """
    soup = BeautifulSoup(html, "lxml")

    title = (
        _meta(soup, "og:title")
        or _meta(soup, "twitter:title")
        or (soup.title.string.strip() if soup.title and soup.title.string else None)
    )
    description = (
        _meta(soup, "og:description")
        or _meta(soup, "twitter:description")
        or _meta(soup, "description")
    )
    image = _meta(soup, "og:image") or _meta(soup, "twitter:image")
    site_name = _meta(soup, "og:site_name") or urlparse(url).netloc or None

    # A relative og:image is common and useless to the browser as-is.
    if image and not urlparse(image).netloc:
        image = urljoin(url, image)

    # An image on a host we would refuse to fetch is an image the browser should
    # not be asked to load either.
    if image and not _is_public_url(image):
        image = None

    return LinkPreview(
        url=url,
        title=_clip(title, 300),
        description=_clip(description, 500),
        image_url=image,
        site_name=_clip(site_name, 120),
    )


# ── guard adapters ───────────────────────────────────────────────────────────
#
# `url_guard` raises `UnsafeURL` for a URL it refuses and `FetchFailed` for one
# it could not read. Community routes speak `InvalidRequest` / `UpstreamFailure`.
# The split is the same one, so the translation is mechanical — but it has to
# stay mechanical: mapping a refusal to `UpstreamFailure` would tell the caller
# to retry a URL we will never fetch.


async def _fetch(url: str) -> tuple:
    """Follow redirects by hand, validating every hop. See `url_guard`."""
    try:
        return await url_guard.get_text_guarded(
            url, timeout=FETCH_TIMEOUT_SECONDS, max_bytes=MAX_BYTES, headers=_HEADERS
        )
    except url_guard.UnsafeURL as exc:
        raise InvalidRequest(str(exc))
    except url_guard.FetchFailed as exc:
        raise UpstreamFailure(str(exc))


def _normalize(url: str) -> str:
    try:
        return url_guard.normalize(url)
    except url_guard.UnsafeURL as exc:
        raise InvalidRequest(str(exc))


async def _assert_public(url: str) -> None:
    """Resolve the hostname and refuse anything that is not a public address."""
    try:
        await url_guard.assert_public(url)
    except url_guard.UnsafeURL as exc:
        raise InvalidRequest(str(exc))
    except url_guard.FetchFailed as exc:
        raise UpstreamFailure(str(exc))


def _is_public_url(url: str) -> bool:
    """Cheap, DNS-free check used for the og:image we hand to the browser."""
    return url_guard.is_public_url(url)


# ── parsing helpers ──────────────────────────────────────────────────────────


def _meta(soup: BeautifulSoup, key: str) -> Optional[str]:
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    if not tag:
        return None
    content = tag.get("content")
    return content.strip() if isinstance(content, str) and content.strip() else None


def _clip(value: Optional[str], limit: int) -> Optional[str]:
    if not value:
        return None
    collapsed = " ".join(value.split())
    return collapsed[:limit] if collapsed else None
