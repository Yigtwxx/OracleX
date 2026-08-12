"""
Article extraction has to be right about two things above all: it must find the
prose when it is there, and it must say "nothing" rather than hand the model a
paywall stub or a page of navigation.

Every fetch below passes `trusted_source=True`, because every fetch below stubs
`get_text` / `get_text_impersonated` — that pair *is* the trusted path. The
untrusted default routes through `services/url_guard` instead and is covered in
`test_url_guard.py`, including the assertion that it can never fall back to the
unguarded client. Dropping the flag here would not test the guard; it would send
these tests at real DNS.
"""

import asyncio

import httpx
import pytest

from services import article_service
from services.article_service import extract_body, fetch_article, render_article_block

BODY = (
    "Regulators approved the exchange-traded product on Tuesday, opening a "
    "mandated-buyer channel that did not previously exist for the asset. "
    "The filing lists a management fee of 0.25 percent and no lockup. "
)


def _page(inner: str) -> str:
    return f"<html><head><title>t</title></head><body>{inner}</body></html>"


@pytest.fixture(autouse=True)
def clean_state():
    article_service.reset_state()
    yield
    article_service.reset_state()


# ── extraction strategies ────────────────────────────────────────────────────


def test_json_ld_article_body_is_preferred():
    html = _page(
        '<script type="application/ld+json">'
        f'{{"@type":"NewsArticle","articleBody":"{BODY * 3}"}}'
        "</script>"
        "<article><p>a different and much shorter body that should lose</p></article>"
    )
    article = extract_body(html, "https://example.com/a")

    assert article is not None
    assert article.extracted_via == "json-ld"
    assert "mandated-buyer channel" in article.text


def test_json_ld_inside_a_graph_is_found():
    html = _page(
        '<script type="application/ld+json">'
        f'{{"@graph":[{{"@type":"WebPage"}},{{"@type":"NewsArticle","articleBody":"{BODY * 3}"}}]}}'
        "</script>"
    )
    article = extract_body(html, "https://example.com/a")

    assert article is not None
    assert article.extracted_via == "json-ld"


def test_article_tag_is_used_when_no_json_ld():
    html = _page(f"<article><p>{BODY}</p><p>{BODY}</p></article>")
    article = extract_body(html, "https://example.com/a")

    assert article is not None
    assert article.extracted_via == "article-tag"


def test_density_fallback_prefers_the_container_with_the_most_prose():
    html = _page(
        "<div id='sidebar'><p>Markets</p><p>Crypto</p><p>Stocks</p><p>More</p></div>"
        f"<div id='body'><p>{BODY}</p><p>{BODY}</p></div>"
    )
    article = extract_body(html, "https://example.com/a")

    assert article is not None
    assert article.extracted_via == "density"
    assert "mandated-buyer channel" in article.text


def test_malformed_json_ld_falls_through_instead_of_raising():
    html = _page(
        '<script type="application/ld+json">{not valid json,,,}</script>'
        f"<article><p>{BODY}</p><p>{BODY}</p></article>"
    )
    article = extract_body(html, "https://example.com/a")

    assert article is not None
    assert article.extracted_via == "article-tag"


# ── cleaning ─────────────────────────────────────────────────────────────────


def test_chrome_tags_are_stripped():
    html = _page(
        "<nav><p>Home About Contact Markets Crypto Stocks Commodities Bonds</p></nav>"
        "<script>var x = 'Regulators approved the exchange-traded product today';</script>"
        f"<article><p>{BODY}</p><p>{BODY}</p></article>"
    )
    article = extract_body(html, "https://example.com/a")

    assert article is not None
    assert "Home About Contact" not in article.text
    assert "var x" not in article.text


def test_boilerplate_paragraphs_are_dropped():
    html = _page(
        f"<article><p>{BODY}</p>"
        "<p>Sign up for our newsletter to get the latest market updates daily.</p>"
        f"<p>{BODY}</p></article>"
    )
    article = extract_body(html, "https://example.com/a")

    assert article is not None
    assert "newsletter" not in article.text.lower()


def test_short_captions_are_dropped():
    html = _page(f"<article><p>Photo: Reuters</p><p>{BODY}</p><p>{BODY}</p></article>")
    article = extract_body(html, "https://example.com/a")

    assert article is not None
    assert "Photo: Reuters" not in article.text


def test_long_bodies_are_truncated_to_the_head_and_flagged():
    html = _page(f"<article><p>{BODY * 200}</p></article>")
    article = extract_body(html, "https://example.com/a")

    assert article is not None
    assert article.truncated is True
    assert article.char_count <= article_service.MAX_BODY_CHARS
    assert article.text.startswith("Regulators approved")


# ── rejection ────────────────────────────────────────────────────────────────


def test_paywall_stub_is_rejected():
    stub = (
        "Subscribe to continue reading this article. Already a subscriber? Sign in to "
        "read the full story and get unlimited access to our market coverage today. "
        "Members get exclusive analysis from our newsroom every single trading day."
    )
    html = _page(f"<article><p>{stub}</p></article>")

    assert extract_body(html, "https://example.com/a") is None


def test_too_short_a_body_is_not_an_article():
    html = _page("<article><p>Bitcoin rose on Tuesday, traders said after the open.</p></article>")

    assert extract_body(html, "https://example.com/a") is None


@pytest.mark.parametrize("html", ["", "   ", "<html><body></body></html>"])
def test_empty_pages_return_none(html):
    assert extract_body(html, "https://example.com/a") is None


# ── fetch: failures never raise ──────────────────────────────────────────────


@pytest.mark.parametrize("url", [None, "", "   "])
async def test_missing_url_returns_none(url):
    assert await fetch_article(url) is None


async def test_transport_failure_returns_none(monkeypatch):
    async def boom(*_args, **_kwargs):
        raise httpx.ConnectError("dns")

    monkeypatch.setattr(article_service, "get_text", boom)
    monkeypatch.setattr(article_service, "get_text_impersonated", boom)

    assert await fetch_article("https://example.com/a", trusted_source=True) is None


async def test_timeout_returns_none(monkeypatch):
    async def hang(*_args, **_kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(article_service, "get_text", hang)

    assert await fetch_article("https://example.com/a", timeout=0.05, trusted_source=True) is None


async def test_forbidden_falls_back_to_the_impersonated_path(monkeypatch):
    calls = []

    async def blocked(url, **_kwargs):
        calls.append("plain")
        request = httpx.Request("GET", url)
        response = httpx.Response(403, request=request)
        raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    async def impersonated(_url, **_kwargs):
        calls.append("impersonated")
        return _page(f"<article><p>{BODY}</p><p>{BODY}</p></article>")

    monkeypatch.setattr(article_service, "get_text", blocked)
    monkeypatch.setattr(article_service, "get_text_impersonated", impersonated)

    article = await fetch_article("https://example.com/a", trusted_source=True)

    assert calls == ["plain", "impersonated"]
    assert article is not None


async def test_not_found_is_not_retried_impersonated(monkeypatch):
    calls = []

    async def missing(url, **_kwargs):
        calls.append("plain")
        request = httpx.Request("GET", url)
        raise httpx.HTTPStatusError(
            "nf", request=request, response=httpx.Response(404, request=request)
        )

    async def impersonated(*_args, **_kwargs):
        calls.append("impersonated")
        return ""

    monkeypatch.setattr(article_service, "get_text", missing)
    monkeypatch.setattr(article_service, "get_text_impersonated", impersonated)

    assert await fetch_article("https://example.com/a", trusted_source=True) is None
    assert calls == ["plain"], "a 404 is not a fingerprint block; retrying it wastes the budget"


# ── cache and breaker ────────────────────────────────────────────────────────


async def test_a_successful_fetch_is_cached(monkeypatch):
    calls = []

    async def once(*_args, **_kwargs):
        calls.append(1)
        return _page(f"<article><p>{BODY}</p><p>{BODY}</p></article>")

    monkeypatch.setattr(article_service, "get_text", once)

    first = await fetch_article("https://example.com/a", trusted_source=True)
    second = await fetch_article("https://example.com/a", trusted_source=True)

    assert first is not None and second is not None
    assert len(calls) == 1, "the body of an article does not change; it must not be refetched"


async def test_an_unextractable_page_is_cached_as_a_miss(monkeypatch):
    calls = []

    async def once(*_args, **_kwargs):
        calls.append(1)
        return _page("<div><p>too short</p></div>")

    monkeypatch.setattr(article_service, "get_text", once)

    assert await fetch_article("https://example.com/a", trusted_source=True) is None
    assert await fetch_article("https://example.com/a", trusted_source=True) is None
    assert len(calls) == 1, "a dead link must not be refetched on every click"


async def test_the_breaker_opens_after_repeated_host_failures(monkeypatch):
    calls = []

    async def boom(*_args, **_kwargs):
        calls.append(1)
        raise httpx.ConnectError("down")

    monkeypatch.setattr(article_service, "get_text", boom)
    monkeypatch.setattr(article_service, "get_text_impersonated", boom)

    for i in range(article_service.BREAKER_THRESHOLD):
        assert await fetch_article(f"https://slow.example/{i}", trusted_source=True) is None

    attempts_before = len(calls)
    assert await fetch_article("https://slow.example/next", trusted_source=True) is None
    assert len(calls) == attempts_before, "an open breaker must skip the fetch entirely"


async def test_a_success_clears_the_breaker_counter(monkeypatch):
    state = {"fail": True}

    async def flaky(*_args, **_kwargs):
        if state["fail"]:
            raise httpx.ConnectError("down")
        return _page(f"<article><p>{BODY}</p><p>{BODY}</p></article>")

    monkeypatch.setattr(article_service, "get_text", flaky)
    monkeypatch.setattr(article_service, "get_text_impersonated", flaky)

    assert await fetch_article("https://flaky.example/1", trusted_source=True) is None
    state["fail"] = False
    assert await fetch_article("https://flaky.example/2", trusted_source=True) is not None

    assert "flaky.example" not in article_service._failures


# ── prompt rendering ─────────────────────────────────────────────────────────


def test_the_unavailable_block_forbids_inferring_the_body():
    block = render_article_block(None)

    assert "not retrievable" in block
    assert "Do not infer" in block
    assert "report this gap" in block


def test_the_available_block_states_the_length_and_carries_the_text():
    html = _page(f"<article><p>{BODY}</p><p>{BODY}</p></article>")
    article = extract_body(html, "https://example.com/a")
    block = render_article_block(article)

    assert str(article.char_count) in block
    assert "mandated-buyer channel" in block
    assert "Quote it verbatim" in block
