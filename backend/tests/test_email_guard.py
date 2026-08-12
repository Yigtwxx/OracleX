"""
Tests for the sign-up email checks.

Three independent gates, and one property that matters more than any of them:
the guard must fail *open*. A DNS outage that blocked every sign-up on the site
would be a far worse failure than letting a few dead domains through, so the
last test here is the one to keep working.

No test reaches the network — the DoH call goes through `http_client.get_json`,
which is patched throughout.
"""

import pytest

from config import settings
from services import email_guard


@pytest.fixture(autouse=True)
def clear_dns_cache():
    """Verdicts are cached per domain for an hour; tests must not share them."""
    email_guard._dns_cache.clear()
    yield
    email_guard._dns_cache.clear()


@pytest.fixture
def no_dns(monkeypatch):
    """Skip the DNS stage so syntax/blocklist tests stay offline and fast."""
    monkeypatch.setattr(settings, "EMAIL_DNS_CHECK_ENABLED", False)


def fake_resolver(answers: dict):
    """
    Build a `get_json` stand-in from `{(domain, record): payload}`.

    A missing key means the resolver answered NOERROR with no records, which is
    what a domain with no mail exchanger really looks like.
    """

    async def _get_json(url, *, params=None, headers=None, timeout=None):
        key = (params["name"], params["type"])
        return answers.get(key, {"Status": 0})

    return _get_json


# ── Syntax ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "address",
    [
        "user@example.com",
        "first.last@sub.example.co.uk",
        "user+tag@example.org",
        "u@e.io",
    ],
)
@pytest.mark.asyncio
async def test_check_deliverable_well_formed_address_passes_syntax(address, no_dns):
    verdict = await email_guard.check_deliverable(address)
    assert verdict.ok, f"Expected {address} to pass, got {verdict.reason}"


@pytest.mark.parametrize(
    "address",
    [
        "",
        "not-an-email",
        "@example.com",
        "user@",
        "user@example",  # no TLD
        "user@@example.com",
        "user name@example.com",
        "user@exa mple.com",
        "a" * 250 + "@example.com",  # past the 254-character ceiling
    ],
)
@pytest.mark.asyncio
async def test_check_deliverable_malformed_address_is_refused_on_syntax(address, no_dns):
    verdict = await email_guard.check_deliverable(address)
    assert not verdict.ok, f"Expected {address!r} to be refused"
    assert verdict.reason == "syntax", f"Expected syntax, got {verdict.reason}"


# ── Disposable domains ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_deliverable_known_throwaway_domain_is_refused(no_dns):
    verdict = await email_guard.check_deliverable("someone@mailinator.com")
    assert not verdict.ok
    assert verdict.reason == "disposable", f"Expected disposable, got {verdict.reason}"


@pytest.mark.asyncio
async def test_check_deliverable_subdomain_of_throwaway_domain_is_refused(no_dns):
    """The throwaway services hand out unlimited subdomains; exact match is not enough."""
    verdict = await email_guard.check_deliverable("someone@inbox.mailinator.com")
    assert not verdict.ok
    assert verdict.reason == "disposable", f"Expected disposable, got {verdict.reason}"


@pytest.mark.asyncio
async def test_check_deliverable_is_case_insensitive_about_the_domain(no_dns):
    verdict = await email_guard.check_deliverable("Someone@MailInator.COM")
    assert not verdict.ok
    assert verdict.reason == "disposable"


# ── DNS ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_deliverable_domain_with_an_mx_record_passes(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_DNS_CHECK_ENABLED", True)
    monkeypatch.setattr(
        email_guard.http_client,
        "get_json",
        fake_resolver(
            {("example.com", "MX"): {"Status": 0, "Answer": [{"data": "10 mx.example"}]}}
        ),
    )

    verdict = await email_guard.check_deliverable("user@example.com")
    assert verdict.ok, f"Expected ok, got {verdict.reason}"
    assert verdict.reason == "ok"


@pytest.mark.asyncio
async def test_check_deliverable_domain_with_only_an_a_record_passes(monkeypatch):
    """RFC 5321 §5.1: an address record with no MX is still a mail destination."""
    monkeypatch.setattr(settings, "EMAIL_DNS_CHECK_ENABLED", True)
    monkeypatch.setattr(
        email_guard.http_client,
        "get_json",
        fake_resolver({("example.com", "A"): {"Status": 0, "Answer": [{"data": "1.2.3.4"}]}}),
    )

    verdict = await email_guard.check_deliverable("user@example.com")
    assert verdict.ok, f"Expected ok, got {verdict.reason}"


@pytest.mark.asyncio
async def test_check_deliverable_domain_with_no_mail_destination_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_DNS_CHECK_ENABLED", True)
    monkeypatch.setattr(email_guard.http_client, "get_json", fake_resolver({}))

    verdict = await email_guard.check_deliverable("user@example.com")
    assert not verdict.ok
    assert verdict.reason == "no_mx", f"Expected no_mx, got {verdict.reason}"
    assert "example.com" in verdict.message


@pytest.mark.asyncio
async def test_check_deliverable_nonexistent_domain_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_DNS_CHECK_ENABLED", True)
    monkeypatch.setattr(
        email_guard.http_client,
        "get_json",
        fake_resolver({("nope.invalid", "MX"): {"Status": 3}}),  # NXDOMAIN
    )

    verdict = await email_guard.check_deliverable("user@nope.invalid")
    assert not verdict.ok
    assert verdict.reason == "no_mx", f"Expected no_mx, got {verdict.reason}"


@pytest.mark.asyncio
async def test_check_deliverable_falls_open_when_no_resolver_can_be_reached(monkeypatch):
    """
    The property that matters most: a resolver outage must not stop sign-ups.
    """
    monkeypatch.setattr(settings, "EMAIL_DNS_CHECK_ENABLED", True)

    async def _unreachable(url, **kwargs):
        raise OSError("network is down")

    monkeypatch.setattr(email_guard.http_client, "get_json", _unreachable)

    verdict = await email_guard.check_deliverable("user@example.com")
    assert verdict.ok, "A DNS outage must not block sign-up"
    assert verdict.reason == "unresolved", f"Expected unresolved, got {verdict.reason}"


@pytest.mark.asyncio
async def test_check_deliverable_falls_back_to_the_second_resolver(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_DNS_CHECK_ENABLED", True)
    working = fake_resolver(
        {("example.com", "MX"): {"Status": 0, "Answer": [{"data": "10 mx.example"}]}}
    )

    async def _first_fails(url, **kwargs):
        if url == email_guard._RESOLVERS[0]:
            raise OSError("cloudflare is down")
        return await working(url, **kwargs)

    monkeypatch.setattr(email_guard.http_client, "get_json", _first_fails)

    verdict = await email_guard.check_deliverable("user@example.com")
    assert verdict.ok, f"Expected ok, got {verdict.reason}"


@pytest.mark.asyncio
async def test_check_deliverable_caches_the_dns_verdict_per_domain(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_DNS_CHECK_ENABLED", True)
    calls = []

    async def _counting(url, *, params=None, headers=None, timeout=None):
        calls.append(params["name"])
        return {"Status": 0, "Answer": [{"data": "10 mx.example"}]}

    monkeypatch.setattr(email_guard.http_client, "get_json", _counting)

    await email_guard.check_deliverable("one@example.com")
    await email_guard.check_deliverable("two@example.com")

    assert len(calls) == 1, f"Expected one lookup for the shared domain, got {len(calls)}"


# ── Normalisation ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  User@Example.COM  ", "User@example.com"),
        ("user@example.com", "user@example.com"),
        ("no-at-sign", "no-at-sign"),
    ],
)
def test_normalize_folds_the_domain_and_leaves_the_local_part_alone(raw, expected):
    """The local part is case-sensitive per RFC 5321; only the domain may fold."""
    assert email_guard.normalize(raw) == expected, f"Expected {expected}"
