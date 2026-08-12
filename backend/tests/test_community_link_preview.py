"""
Tests for the link-preview fetcher.

Two things are being pinned down here. The extractor, which is ordinary parsing,
and the SSRF guard, which is the security boundary: this is the only endpoint in
the backend that makes the server fetch a URL a user chose, so "does it refuse
the metadata endpoint" is a test and not a code comment.
"""

import socket

import pytest

from services import url_guard
from services.community import link_preview
from services.community.errors import InvalidRequest, UpstreamFailure

# ── extraction ───────────────────────────────────────────────────────────────

FULL_PAGE = """
<html><head>
  <title>Fallback title</title>
  <meta property="og:title" content="  Fed holds rates steady  ">
  <meta property="og:description" content="The committee left the target range unchanged.">
  <meta property="og:image" content="/static/card.png">
  <meta property="og:site_name" content="Example Wire">
</head><body>ignored</body></html>
"""

BARE_PAGE = """
<html><head>
  <title>Just a title</title>
  <meta name="description" content="A plain description.">
</head><body></body></html>
"""


def test_opengraph_tags_win_and_are_whitespace_normalized():
    preview = link_preview.extract_preview(FULL_PAGE, "https://example.com/story")

    assert preview.title == "Fed holds rates steady"
    assert preview.description == "The committee left the target range unchanged."
    assert preview.site_name == "Example Wire"


def test_relative_og_image_is_resolved_against_the_page():
    preview = link_preview.extract_preview(FULL_PAGE, "https://example.com/news/story")

    assert preview.image_url == "https://example.com/static/card.png"


def test_page_without_opengraph_falls_back_to_title_and_description():
    preview = link_preview.extract_preview(BARE_PAGE, "https://example.com/plain")

    assert preview.title == "Just a title"
    assert preview.description == "A plain description."
    assert preview.image_url is None
    # No og:site_name, so the host stands in for it.
    assert preview.site_name == "example.com"


def test_an_og_image_on_a_private_host_is_dropped():
    """The browser would be the one making that request, so it is our problem."""
    html = (
        '<html><head><meta property="og:image" content="http://127.0.0.1:9000/x.png"></head></html>'
    )

    preview = link_preview.extract_preview(html, "https://example.com/")

    assert preview.image_url is None


# ── URL normalization ────────────────────────────────────────────────────────


def test_a_bare_host_is_assumed_to_be_https():
    assert link_preview._normalize("example.com/path") == "https://example.com/path"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "   ",
    ],
)
def test_non_http_schemes_are_refused(url):
    with pytest.raises(InvalidRequest):
        link_preview._normalize(url)


# ── the SSRF guard ───────────────────────────────────────────────────────────


def _fake_dns(monkeypatch, mapping):
    """Point getaddrinfo at a lookup table instead of the resolver."""

    def _getaddrinfo(host, *_args, **_kwargs):
        if host not in mapping:
            raise socket.gaierror(f"unknown host {host}")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (mapping[host], 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "10.4.4.4",  # private
        "192.168.1.20",  # private
        "169.254.169.254",  # cloud metadata — the one that actually gets abused
        "0.0.0.0",  # unspecified
    ],
)
async def test_hosts_resolving_to_a_private_address_are_refused(monkeypatch, address):
    _fake_dns(monkeypatch, {"totally-innocent.example": address})

    with pytest.raises(InvalidRequest, match="private address"):
        await link_preview._assert_public("https://totally-innocent.example/page")


async def test_a_public_address_passes(monkeypatch):
    _fake_dns(monkeypatch, {"example.com": "93.184.216.34"})

    await link_preview._assert_public("https://example.com/page")


async def test_an_unresolvable_host_is_an_upstream_failure(monkeypatch):
    _fake_dns(monkeypatch, {})

    with pytest.raises(UpstreamFailure):
        await link_preview._assert_public("https://nope.example/page")


# ── redirects ────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, *, body=b"", location=None, content_type="text/html"):
        self.is_redirect = location is not None
        self.headers = {"location": location} if location else {"content-type": content_type}
        self.encoding = "utf-8"
        self._body = body

    def raise_for_status(self):
        return None

    async def aiter_bytes(self):
        yield self._body


class _FakeStream:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *_exc):
        return False


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requested = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    def stream(self, _method, url):
        self.requested.append(url)
        return _FakeStream(self._responses.pop(0))


async def test_every_redirect_hop_is_revalidated(monkeypatch):
    """
    The reason this module does not use `http_client.get_text`.

    A public host that 302s to the metadata endpoint defeats a guard that only
    checks the URL the user typed.
    """
    _fake_dns(
        monkeypatch,
        {"public.example": "93.184.216.34", "metadata.example": "169.254.169.254"},
    )

    client = _FakeClient([_FakeResponse(location="https://metadata.example/latest")])
    monkeypatch.setattr(url_guard.httpx, "AsyncClient", lambda **_kwargs: client)

    with pytest.raises(InvalidRequest, match="private address"):
        await link_preview._fetch("https://public.example/start")

    # It followed the redirect, then refused to connect to the target.
    assert client.requested == ["https://public.example/start"]


async def test_a_non_html_response_is_refused(monkeypatch):
    _fake_dns(monkeypatch, {"cdn.example": "93.184.216.34"})

    client = _FakeClient([_FakeResponse(body=b"%PDF-1.7", content_type="application/pdf")])
    monkeypatch.setattr(url_guard.httpx, "AsyncClient", lambda **_kwargs: client)

    with pytest.raises(InvalidRequest, match="web page"):
        await link_preview._fetch("https://cdn.example/report.pdf")


async def test_a_successful_fetch_returns_the_body_and_final_url(monkeypatch):
    _fake_dns(monkeypatch, {"example.com": "93.184.216.34"})

    client = _FakeClient([_FakeResponse(body=BARE_PAGE.encode())])
    monkeypatch.setattr(url_guard.httpx, "AsyncClient", lambda **_kwargs: client)

    html, final_url = await link_preview._fetch("https://example.com/plain")

    assert "Just a title" in html
    assert final_url == "https://example.com/plain"
