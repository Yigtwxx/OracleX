"""
Tests for POST /api/auth/email/precheck.

The ordering test is the important one. The endpoint tells an anonymous caller
whether an address is registered, which is a deliberate trade (see the router's
docstring) — but it is only affordable because the registration lookup runs
*after* the deliverability checks. If that order ever flips, the endpoint
becomes a cheap enumeration oracle over a generated address list, and this test
is what catches it.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import settings
from routers import auth as auth_router
from services import auth_service, email_guard


@pytest.fixture
def client(monkeypatch):
    """A bare app with just this router, and no DNS or database behind it."""
    monkeypatch.setattr(settings, "EMAIL_DNS_CHECK_ENABLED", False)
    auth_router._precheck_limit.reset()

    app = FastAPI()
    app.include_router(auth_router.router)
    return TestClient(app)


@pytest.fixture
def registered(monkeypatch):
    """Declare which addresses already have an account."""

    def _apply(*addresses: str):
        known = {a.lower() for a in addresses}

        async def _lookup(email: str) -> bool:
            return email.lower() in known

        monkeypatch.setattr(auth_service, "is_email_registered", _lookup)

    return _apply


def test_precheck_a_free_deliverable_address_is_accepted(client, registered):
    registered()

    response = client.post("/api/auth/email/precheck", json={"email": "new@example.com"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deliverable"] is True
    assert body["registered"] is False
    assert body["message"] == ""


def test_precheck_an_existing_address_is_reported_as_registered(client, registered):
    registered("taken@example.com")

    response = client.post("/api/auth/email/precheck", json={"email": "taken@example.com"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["registered"] is True
    assert body["reason"] == "registered"
    assert "already registered" in body["message"]


def test_precheck_matches_an_existing_address_case_insensitively(client, registered):
    registered("taken@example.com")

    response = client.post("/api/auth/email/precheck", json={"email": "  Taken@Example.COM "})

    assert response.json()["registered"] is True


def test_precheck_a_malformed_address_is_refused_with_200(client, registered):
    """A rejected address is a verdict, not an error — the form reads the body."""
    registered()

    response = client.post("/api/auth/email/precheck", json={"email": "nonsense"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deliverable"] is False
    assert body["reason"] == "syntax"
    assert body["message"]


def test_precheck_a_throwaway_domain_is_refused(client, registered):
    registered()

    response = client.post("/api/auth/email/precheck", json={"email": "x@mailinator.com"})

    body = response.json()
    assert body["deliverable"] is False
    assert body["reason"] == "disposable"


def test_precheck_does_not_look_up_registration_for_an_undeliverable_address(client, monkeypatch):
    """
    The enumeration guard: a caller must clear syntax + blocklist + DNS before
    the endpoint will tell them anything about the user table.
    """
    lookups = []

    async def _lookup(email: str) -> bool:
        lookups.append(email)
        return True

    monkeypatch.setattr(auth_service, "is_email_registered", _lookup)

    client.post("/api/auth/email/precheck", json={"email": "x@mailinator.com"})
    client.post("/api/auth/email/precheck", json={"email": "nonsense"})

    assert lookups == [], f"Undeliverable addresses must not be looked up, got {lookups}"


def test_precheck_returns_503_when_the_registration_lookup_fails(client, monkeypatch):
    async def _broken(email: str) -> bool:
        raise auth_service.AuthServiceError("postgres is down")

    monkeypatch.setattr(auth_service, "is_email_registered", _broken)

    response = client.post("/api/auth/email/precheck", json={"email": "new@example.com"})

    assert response.status_code == 503, response.text
    assert "unavailable" in response.json()["detail"]


def test_precheck_is_rate_limited(client, registered):
    registered()

    for _ in range(10):
        assert (
            client.post("/api/auth/email/precheck", json={"email": "a@example.com"}).status_code
            == 200
        )

    response = client.post("/api/auth/email/precheck", json={"email": "a@example.com"})
    assert response.status_code == 429, f"Expected 429, got {response.status_code}"
    assert "Too many attempts" in response.json()["detail"]


def test_precheck_falls_open_when_dns_is_unreachable(client, monkeypatch, registered):
    """A resolver outage must not stop sign-ups; the verdict is still usable."""
    monkeypatch.setattr(settings, "EMAIL_DNS_CHECK_ENABLED", True)
    email_guard._dns_cache.clear()
    registered()

    async def _unreachable(url, **kwargs):
        raise OSError("network is down")

    monkeypatch.setattr(email_guard.http_client, "get_json", _unreachable)

    response = client.post("/api/auth/email/precheck", json={"email": "new@example.com"})

    assert response.status_code == 200, response.text
    assert response.json()["deliverable"] is True
