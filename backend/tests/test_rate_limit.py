"""
Tests for the per-IP request limiter.

The subtle one is `test_..._window_slides`: an earlier draft stored a counter in
the `TTLCache`, and because `__setitem__` resets an entry's TTL, a caller who
kept knocking pushed their own expiry out forever and was locked out for good.
Storing timestamps and pruning them is what makes the window actually slide.
"""

import time

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from config import settings
from dependencies.rate_limit import RateLimit


def request_from(ip: str, headers: dict | None = None):
    """A Request-shaped double: the limiter only reads `.client` and `.headers`."""
    from starlette.datastructures import Headers
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "client": (ip, 12345),
        "headers": Headers(headers or {}).raw,
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_rate_limit_requests_under_the_cap_are_allowed():
    limiter = RateLimit(name="t", limit=3, window_seconds=60)
    for _ in range(3):
        await limiter(request_from("1.2.3.4"))


@pytest.mark.asyncio
async def test_rate_limit_request_over_the_cap_raises_429():
    limiter = RateLimit(name="t", limit=3, window_seconds=60)
    for _ in range(3):
        await limiter(request_from("1.2.3.4"))

    with pytest.raises(HTTPException) as excinfo:
        await limiter(request_from("1.2.3.4"))

    assert excinfo.value.status_code == 429, f"Expected 429, got {excinfo.value.status_code}"
    assert "Retry-After" in excinfo.value.headers


@pytest.mark.asyncio
async def test_rate_limit_a_second_address_has_its_own_budget():
    limiter = RateLimit(name="t", limit=2, window_seconds=60)
    await limiter(request_from("1.1.1.1"))
    await limiter(request_from("1.1.1.1"))

    # Exhausted for the first caller...
    with pytest.raises(HTTPException):
        await limiter(request_from("1.1.1.1"))
    # ...and untouched for the second.
    await limiter(request_from("2.2.2.2"))


@pytest.mark.asyncio
async def test_rate_limit_window_slides_so_a_blocked_caller_recovers(monkeypatch):
    limiter = RateLimit(name="t", limit=2, window_seconds=10)
    clock = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])

    await limiter(request_from("1.2.3.4"))
    await limiter(request_from("1.2.3.4"))
    with pytest.raises(HTTPException):
        await limiter(request_from("1.2.3.4"))

    # Past the window, the old hits are pruned and the caller is served again —
    # even though they kept knocking while blocked.
    clock[0] += 11
    await limiter(request_from("1.2.3.4"))


@pytest.mark.asyncio
async def test_rate_limit_reset_clears_every_counter():
    limiter = RateLimit(name="t", limit=1, window_seconds=60)
    await limiter(request_from("1.2.3.4"))
    with pytest.raises(HTTPException):
        await limiter(request_from("1.2.3.4"))

    limiter.reset()
    await limiter(request_from("1.2.3.4"))


@pytest.mark.asyncio
async def test_rate_limit_ignores_forwarded_header_unless_proxies_are_trusted(monkeypatch):
    """
    Any client can set `X-Forwarded-For`. Believing it by default would let one
    caller mint a fresh identity per request and make the limit decorative.
    """
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", False)
    limiter = RateLimit(name="t", limit=1, window_seconds=60)

    await limiter(request_from("1.2.3.4", {"x-forwarded-for": "9.9.9.9"}))
    with pytest.raises(HTTPException):
        await limiter(request_from("1.2.3.4", {"x-forwarded-for": "8.8.8.8"}))


@pytest.mark.asyncio
async def test_rate_limit_honours_forwarded_header_when_proxies_are_trusted(monkeypatch):
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)
    limiter = RateLimit(name="t", limit=1, window_seconds=60)

    # Same socket address, two different originating clients behind the proxy.
    await limiter(request_from("10.0.0.1", {"x-forwarded-for": "9.9.9.9, 10.0.0.1"}))
    await limiter(request_from("10.0.0.1", {"x-forwarded-for": "8.8.8.8, 10.0.0.1"}))

    with pytest.raises(HTTPException):
        await limiter(request_from("10.0.0.1", {"x-forwarded-for": "9.9.9.9, 10.0.0.1"}))


def test_rate_limit_surfaces_as_a_429_response_through_fastapi():
    """End to end: the dependency's HTTPException becomes a real 429."""
    limiter = RateLimit(name="t", limit=1, window_seconds=60)
    app = FastAPI()

    @app.get("/ping", dependencies=[Depends(limiter)])
    async def ping():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/ping").status_code == 200
    response = client.get("/ping")
    assert response.status_code == 429, f"Expected 429, got {response.status_code}"
    assert response.headers.get("retry-after")
