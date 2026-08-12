"""
The SSRF guard, and the fact that article fetching now goes through it.

This is a security boundary, so the cases below are tests rather than comments.
The one that matters most is the redirect hop: a guard that only checks the URL
it was handed is defeated by a public host answering `302` into the metadata
endpoint, and that is exactly what `http_client.get_text` — with its
`follow_redirects=True` — would have done for any URL a chat turn picked up.

`services/community/test_community_link_preview.py` covers the same guard from
the community side, where the errors are translated into that module's
vocabulary. Here it is tested in its own terms.
"""

import socket

import pytest

from services import article_service, http_client, url_guard

# ── normalization ────────────────────────────────────────────────────────────


def test_a_bare_host_is_assumed_to_be_https():
    assert url_guard.normalize("example.com/path") == "https://example.com/path"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "file:///etc/passwd",
        # Has a scheme but no "://" — prepending https:// would smuggle it
        # through as a host named "javascript".
        "javascript:alert(1)",
        "data:text/html,<script>x</script>",
        "   ",
        "",
    ],
)
def test_non_http_schemes_are_refused(url):
    with pytest.raises(url_guard.UnsafeURL):
        url_guard.normalize(url)


# ── address checking ─────────────────────────────────────────────────────────


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
        "172.16.0.1",  # private
        "169.254.169.254",  # cloud metadata — the one that actually gets abused
        "0.0.0.0",  # unspecified
        "::1",  # loopback, v6
        "fd00::1",  # unique local, v6
    ],
)
async def test_a_host_resolving_to_a_private_address_is_refused(monkeypatch, address):
    _fake_dns(monkeypatch, {"totally-innocent.example": address})

    with pytest.raises(url_guard.UnsafeURL, match="private address"):
        await url_guard.assert_public("https://totally-innocent.example/page")


async def test_a_public_address_passes(monkeypatch):
    _fake_dns(monkeypatch, {"example.com": "93.184.216.34"})

    await url_guard.assert_public("https://example.com/page")


async def test_an_unresolvable_host_is_a_fetch_failure_not_a_refusal(monkeypatch):
    """
    The distinction is load-bearing: a refusal must never be retried, a name
    that did not resolve is a property of the internet and may be.
    """
    _fake_dns(monkeypatch, {})

    with pytest.raises(url_guard.FetchFailed):
        await url_guard.assert_public("https://nope.example/page")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://example.com/a.png", True),
        ("http://127.0.0.1:9000/a.png", False),
        ("http://localhost/a.png", False),
        ("https://10.0.0.5/a.png", False),
        ("ftp://example.com/a.png", False),
    ],
)
def test_is_public_url_screens_literal_addresses_without_dns(url, expected):
    assert url_guard.is_public_url(url) is expected


# ── the fetch loop ───────────────────────────────────────────────────────────


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


def _fake_http(monkeypatch, responses):
    client = _FakeClient(responses)
    monkeypatch.setattr(url_guard.httpx, "AsyncClient", lambda **_kwargs: client)
    return client


async def test_every_redirect_hop_is_revalidated(monkeypatch):
    """The whole reason this module exists rather than calling get_text."""
    _fake_dns(
        monkeypatch,
        {"public.example": "93.184.216.34", "metadata.example": "169.254.169.254"},
    )
    client = _fake_http(monkeypatch, [_FakeResponse(location="https://metadata.example/latest")])

    with pytest.raises(url_guard.UnsafeURL, match="private address"):
        await url_guard.get_text_guarded("https://public.example/start")

    # It read the redirect, then refused to open a connection to the target.
    assert client.requested == ["https://public.example/start"]


async def test_a_redirect_chain_that_stays_public_is_followed(monkeypatch):
    _fake_dns(monkeypatch, {"a.example": "93.184.216.34", "b.example": "93.184.216.35"})
    client = _fake_http(
        monkeypatch,
        [
            _FakeResponse(location="https://b.example/final"),
            _FakeResponse(body=b"<html>arrived</html>"),
        ],
    )

    body, final_url = await url_guard.get_text_guarded("https://a.example/start")

    assert "arrived" in body
    assert final_url == "https://b.example/final"
    assert client.requested == ["https://a.example/start", "https://b.example/final"]


async def test_a_redirect_loop_gives_up(monkeypatch):
    _fake_dns(monkeypatch, {"loop.example": "93.184.216.34"})
    _fake_http(
        monkeypatch,
        [
            _FakeResponse(location="https://loop.example/again")
            for _ in range(url_guard.MAX_REDIRECTS + 1)
        ],
    )

    with pytest.raises(url_guard.FetchFailed, match="too many redirects"):
        await url_guard.get_text_guarded("https://loop.example/start")


async def test_a_non_html_response_is_refused_when_html_is_required(monkeypatch):
    _fake_dns(monkeypatch, {"cdn.example": "93.184.216.34"})
    _fake_http(monkeypatch, [_FakeResponse(body=b"%PDF-1.7", content_type="application/pdf")])

    with pytest.raises(url_guard.UnsafeURL, match="web page"):
        await url_guard.get_text_guarded("https://cdn.example/report.pdf")


async def test_the_body_is_capped(monkeypatch):
    _fake_dns(monkeypatch, {"big.example": "93.184.216.34"})
    _fake_http(monkeypatch, [_FakeResponse(body=b"x" * 5000)])

    body, _ = await url_guard.get_text_guarded("https://big.example/huge", max_bytes=100)

    assert len(body) == 100


# ── article_service goes through the guard ───────────────────────────────────


async def test_an_untrusted_article_fetch_never_reaches_the_unguarded_client(monkeypatch):
    """
    `http_client.get_text` sets follow_redirects=True. If the untrusted path
    ever routes through it again, this test is the thing that says so.
    """
    article_service.reset_state()
    _fake_dns(monkeypatch, {"publisher.example": "93.184.216.34"})

    async def _explode(*_args, **_kwargs):
        raise AssertionError("untrusted fetch must not use the unguarded client")

    monkeypatch.setattr(http_client, "get_text", _explode)
    monkeypatch.setattr(http_client, "get_text_impersonated", _explode)
    monkeypatch.setattr(article_service, "get_text", _explode)
    monkeypatch.setattr(article_service, "get_text_impersonated", _explode)
    _fake_http(monkeypatch, [_FakeResponse(body=b"<html><body></body></html>")])

    # Returns None because the page has no extractable prose — the point is that
    # it got there via the guard rather than raising the AssertionError above.
    assert await article_service.fetch_article("https://publisher.example/story") is None


async def test_a_refused_url_does_not_trip_the_host_breaker(monkeypatch):
    """
    A refusal says something about the URL, not the publisher's health. Counting
    it would let one bad link close the circuit on a host that is answering.
    """
    article_service.reset_state()
    _fake_dns(monkeypatch, {"publisher.example": "127.0.0.1"})

    assert await article_service.fetch_article("https://publisher.example/story") is None
    assert not article_service._breaker_is_open("publisher.example")


async def test_a_trusted_article_fetch_still_uses_the_impersonated_retry(monkeypatch):
    """The news pipeline's behaviour is unchanged; only the default flipped."""
    article_service.reset_state()
    calls = []

    async def _fake_get_text(url, **_kwargs):
        calls.append("plain")
        raise article_service.httpx.HTTPStatusError(
            "blocked",
            request=article_service.httpx.Request("GET", url),
            response=article_service.httpx.Response(403),
        )

    async def _fake_impersonated(_url, **_kwargs):
        calls.append("impersonated")
        return "<html><body>" + ("word " * 200) + "</body></html>"

    monkeypatch.setattr(article_service, "get_text", _fake_get_text)
    monkeypatch.setattr(article_service, "get_text_impersonated", _fake_impersonated)

    await article_service.fetch_article("https://publisher.example/story", trusted_source=True)

    assert calls == ["plain", "impersonated"]
