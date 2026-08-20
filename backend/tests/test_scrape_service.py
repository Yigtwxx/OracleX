"""
The scrape ladder: which rung runs, and which one must not.

Two properties carry the security of this module and are asserted directly. The
browser rung is reachable only for hosts in `JS_SHELL_HOSTS` — an arbitrary URL
must never launch one, because a browser navigates redirects on its own and no
guard can step between the decision and the connection. And the impersonated
rung, which *can* be guarded, is: it refuses a redirect hop that lands on a
private address exactly as plain HTTP does.

Everything below stubs Scrapling. No browser is launched, and no request leaves
the machine.
"""

import sys
from types import ModuleType

import pytest

from services import article_service, scrape_service, url_guard

BODY = (
    "Regulators approved the exchange-traded product on Tuesday, opening a "
    "mandated-buyer channel that did not previously exist for the asset. "
    "The filing lists a management fee of 0.25 percent and no lockup. "
)
PAGE = f"<html><body><article><p>{BODY}</p><p>{BODY}</p></article></body></html>"


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """
    Fresh caches, and no DNS.

    `assert_public` is stubbed to accept by default so a hostname like
    "news.example" does not send the suite at the real resolver. The tests that
    are *about* refusal install their own stub over this one.
    """
    scrape_service.reset_state()
    article_service.reset_state()
    monkeypatch.setattr(url_guard, "assert_public", _passes)
    yield
    scrape_service.reset_state()
    article_service.reset_state()


@pytest.fixture
def scrapling(monkeypatch):
    """
    Install a stub `scrapling.fetchers` and record what each rung did.

    Both rungs import it lazily inside the function, so replacing the module in
    `sys.modules` is enough — there is no import-time binding to patch.
    """
    calls = {"impersonated": [], "browser": []}

    class _Response:
        def __init__(self, *, status=200, html="", url="", location=None):
            self.status = status
            self.html_content = html
            self.url = url
            self.headers = {"location": location} if location else {}

    def install(*, impersonated=None, browser=None):
        module = ModuleType("scrapling.fetchers")

        class _AsyncFetcher:
            @staticmethod
            async def get(url, **_kwargs):
                calls["impersonated"].append(url)
                if impersonated is None:
                    raise RuntimeError("no impersonated response configured")
                result = impersonated(url) if callable(impersonated) else impersonated
                if isinstance(result, Exception):
                    raise result
                return result

        class _AsyncStealthySession:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def fetch(self, url, **_kwargs):
                calls["browser"].append(url)
                if browser is None:
                    raise RuntimeError("no browser response configured")
                if isinstance(browser, Exception):
                    raise browser
                return browser

        module.AsyncFetcher = _AsyncFetcher
        module.AsyncStealthySession = _AsyncStealthySession
        monkeypatch.setitem(sys.modules, "scrapling.fetchers", module)
        return calls

    return type(
        "Scrapling", (), {"install": staticmethod(install), "Response": _Response, "calls": calls}
    )


def _no_direct_rung(monkeypatch, result=None):
    """Make rung 1 return `result` without touching the network."""

    async def _fetch(*_args, **_kwargs):
        return result

    monkeypatch.setattr(article_service, "fetch_article", _fetch)


def _allow_browser(monkeypatch, allowed=True):
    monkeypatch.setattr(scrape_service.settings, "SCRAPLING_ALLOW_BROWSER", allowed)


# ── host classification ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.reddit.com/r/solana/comments/abc", True),
        ("https://reddit.com/r/solana", True),
        ("https://old.reddit.com/r/solana", True),
        ("https://x.com/someone/status/1", True),
        ("https://stocktwits.com/symbol/BTC.X", True),
        ("https://www.coindesk.com/markets/story", False),
        # A lookalike must not match: the suffix check is on a dot boundary.
        ("https://reddit.com.evil.example/page", False),
        ("https://notreddit.com/page", False),
    ],
)
def test_js_shell_hosts_are_matched_on_a_dot_boundary(url, expected):
    assert scrape_service.is_js_shell_host(url) is expected


# ── rung 1 ───────────────────────────────────────────────────────────────────


async def test_an_ordinary_page_stops_at_the_first_rung(scrapling, monkeypatch):
    """The cheap rung succeeding must not cost a fingerprint replay."""
    calls = scrapling.install()
    _no_direct_rung(monkeypatch, article_service.extract_body(PAGE, "https://news.example/a"))

    result = await scrape_service.scrape("https://news.example/a")

    assert result.page is not None
    assert result.page.via == "direct"
    assert result.browser_used is False
    assert calls["impersonated"] == [] and calls["browser"] == []


# ── rung 2 ───────────────────────────────────────────────────────────────────


async def test_a_blocked_page_falls_through_to_the_impersonated_rung(scrapling, monkeypatch):
    calls = scrapling.install(
        impersonated=scrapling.Response(html=PAGE, url="https://news.example/a")
    )
    _no_direct_rung(monkeypatch, None)
    monkeypatch.setattr(url_guard, "assert_public", _passes)

    result = await scrape_service.scrape("https://news.example/a")

    assert result.page is not None
    assert result.page.via == "impersonated"
    assert calls["impersonated"] == ["https://news.example/a"]
    assert calls["browser"] == []


async def test_the_impersonated_rung_revalidates_every_redirect_hop(scrapling, monkeypatch):
    """
    The rung Scrapling *can* be guarded on, so it is.

    `follow_redirects=False` keeps the loop ours; without it a public host's 302
    into the metadata endpoint would be followed inside the library.
    """
    seen = []

    async def _assert_public(url):
        seen.append(url)
        if "metadata" in url:
            raise url_guard.UnsafeURL("that URL points at a private address")

    calls = scrapling.install(
        impersonated=scrapling.Response(status=302, location="https://metadata.example/latest")
    )
    _no_direct_rung(monkeypatch, None)
    monkeypatch.setattr(url_guard, "assert_public", _assert_public)

    result = await scrape_service.scrape("https://public.example/start")

    assert result.page is None
    # The ladder checks the entry URL once up front, then the rung checks the
    # hop it was redirected to — and never fetches it.
    assert seen == [
        "https://public.example/start",
        "https://public.example/start",
        "https://metadata.example/latest",
    ]
    assert calls["impersonated"] == ["https://public.example/start"]


async def test_the_impersonated_rung_passes_follow_redirects_false(scrapling, monkeypatch):
    """A regression guard: losing this flag silently un-guards the rung."""
    seen_kwargs = {}

    module = ModuleType("scrapling.fetchers")

    class _AsyncFetcher:
        @staticmethod
        async def get(url, **kwargs):
            seen_kwargs.update(kwargs)
            return scrapling.Response(html=PAGE, url=url)

    module.AsyncFetcher = _AsyncFetcher
    module.AsyncStealthySession = object
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", module)

    _no_direct_rung(monkeypatch, None)
    monkeypatch.setattr(url_guard, "assert_public", _passes)

    await scrape_service.scrape("https://news.example/a")

    assert seen_kwargs.get("follow_redirects") is False
    # retries=0 looks like "do not retry" and behaves like "never work": a
    # one-off AsyncFetcher.get builds no session at that value and every call
    # raises "No active session available". Stubs cannot catch that, so the
    # floor is asserted here instead.
    assert seen_kwargs.get("retries", 0) >= 1


# ── rung 3 ───────────────────────────────────────────────────────────────────


async def test_a_js_shell_host_goes_straight_to_the_browser(scrapling, monkeypatch):
    """Rungs 1 and 2 cannot succeed here; spending their budget proves nothing."""
    calls = scrapling.install(
        browser=scrapling.Response(html=PAGE, url="https://www.reddit.com/r/solana/x")
    )
    _allow_browser(monkeypatch)
    monkeypatch.setattr(url_guard, "assert_public", _passes)

    result = await scrape_service.scrape("https://www.reddit.com/r/solana/x")

    assert result.page is not None
    assert result.page.via == "browser"
    assert result.browser_used is True
    assert calls["impersonated"] == []
    assert calls["browser"] == ["https://www.reddit.com/r/solana/x"]


async def test_an_arbitrary_host_never_reaches_the_browser(scrapling, monkeypatch):
    """
    The property that makes an unguarded browser acceptable.

    A browser follows redirects itself, so nothing can check the address it
    ends up at. The allowlist is the whole mitigation — if this test fails, a
    model-chosen URL can drive a browser anywhere.
    """
    calls = scrapling.install(impersonated=scrapling.Response(status=403))
    _allow_browser(monkeypatch)
    _no_direct_rung(monkeypatch, None)
    monkeypatch.setattr(url_guard, "assert_public", _passes)

    result = await scrape_service.scrape("https://attacker.example/anything")

    assert result.page is None
    assert result.browser_used is False
    assert calls["browser"] == []


async def test_the_browser_is_skipped_when_the_caller_spent_its_quota(scrapling, monkeypatch):
    calls = scrapling.install()
    _allow_browser(monkeypatch)
    _no_direct_rung(monkeypatch, None)
    monkeypatch.setattr(url_guard, "assert_public", _passes)

    result = await scrape_service.scrape("https://www.reddit.com/r/solana/x", allow_browser=False)

    assert result.page is None
    assert calls["browser"] == []
    assert "browser" in result.reason


async def test_the_browser_is_skipped_when_the_deployment_disables_it(scrapling, monkeypatch):
    calls = scrapling.install()
    _allow_browser(monkeypatch, allowed=False)
    _no_direct_rung(monkeypatch, None)
    monkeypatch.setattr(url_guard, "assert_public", _passes)

    result = await scrape_service.scrape("https://www.reddit.com/r/solana/x")

    assert result.page is None
    assert calls["browser"] == []


async def test_a_failed_browser_attempt_still_counts_against_the_quota(scrapling, monkeypatch):
    """It spent the time and the memory; the caller has to know."""
    scrapling.install(browser=RuntimeError("browser crashed"))
    _allow_browser(monkeypatch)
    monkeypatch.setattr(url_guard, "assert_public", _passes)

    result = await scrape_service.scrape("https://www.reddit.com/r/solana/x")

    assert result.page is None
    assert result.browser_used is True


# ── refusals and degradation ─────────────────────────────────────────────────


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "   "])
async def test_a_refused_url_never_starts_the_ladder(scrapling, url):
    calls = scrapling.install()

    result = await scrape_service.scrape(url)

    assert result.page is None and result.reason
    assert calls["impersonated"] == [] and calls["browser"] == []


async def test_a_private_address_is_reported_as_a_refusal_not_an_empty_page(scrapling, monkeypatch):
    """
    Every rung refuses a private target on its own, so nothing unsafe is ever
    fetched. But each rung reports that refusal as "no page", and two silent
    Nones in a row read as "the page was empty" — which tells the user, and the
    model reading the step label, the wrong thing about what happened.
    """
    calls = scrapling.install()

    async def _private(_url):
        raise url_guard.UnsafeURL("that URL points at a private address")

    monkeypatch.setattr(url_guard, "assert_public", _private)

    result = await scrape_service.scrape("http://169.254.169.254/latest/meta-data/")

    assert result.page is None
    assert "private address" in result.reason
    # And it did not waste two rungs proving what the address already said.
    assert calls["impersonated"] == [] and calls["browser"] == []


async def test_a_missing_scrapling_install_degrades_to_a_gap(monkeypatch):
    """The dependency is optional at runtime; its absence is not a crash."""
    _no_direct_rung(monkeypatch, None)
    monkeypatch.setattr(url_guard, "assert_public", _passes)
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", None)

    result = await scrape_service.scrape("https://news.example/a")

    assert result.page is None
    assert result.reason


async def test_a_successful_scrape_is_cached(scrapling, monkeypatch):
    """A browser launch repeated for one URL is the worst thing this can do."""
    calls = scrapling.install(
        browser=scrapling.Response(html=PAGE, url="https://www.reddit.com/r/solana/x")
    )
    _allow_browser(monkeypatch)
    monkeypatch.setattr(url_guard, "assert_public", _passes)

    first = await scrape_service.scrape("https://www.reddit.com/r/solana/x")
    second = await scrape_service.scrape("https://www.reddit.com/r/solana/x")

    assert first.page is not None and second.page is not None
    assert calls["browser"] == ["https://www.reddit.com/r/solana/x"]


async def _passes(_url):
    """Stand-in for `url_guard.assert_public` that accepts everything."""
    return None


# ── the browser allowlist, after finance hosts were added as extractors ──────


def test_tradingview_is_on_the_browser_allowlist():
    """
    It renders entirely client-side, so the data rung can only read the JSON-LD
    the server emits. This is a deliberate widening of the set of addresses an
    unguarded browser will ever visit — see the comment on JS_SHELL_HOSTS.
    """
    assert scrape_service.is_js_shell_host("https://www.tradingview.com/symbols/BTCUSD/")


@pytest.mark.parametrize(
    "url",
    [
        "https://coinmarketcap.com/currencies/bitcoin/",
        "https://finviz.com/quote.ashx?t=NVDA",
        "https://uk.investing.com/indices/us-30",
        "https://finance.yahoo.com/quote/NVDA",
    ],
)
def test_a_finance_host_with_an_extractor_is_not_automatically_allowlisted(url):
    """
    Having an extractor and needing a browser are different things. These four
    ship usable static HTML, so adding them to the allowlist would widen the
    unguarded surface for nothing.
    """
    from services import finance_extractors

    assert finance_extractors.has_extractor(url)
    assert not scrape_service.is_js_shell_host(url)


def test_the_allowlist_did_not_grow_by_accident():
    """
    A canary. Every entry here is an address an unguarded browser may navigate
    to; the set should change only when someone means it to.
    """
    assert scrape_service.JS_SHELL_HOSTS == frozenset(
        {
            "reddit.com",
            "x.com",
            "twitter.com",
            "stocktwits.com",
            "threads.net",
            "tradingview.com",
        }
    )
