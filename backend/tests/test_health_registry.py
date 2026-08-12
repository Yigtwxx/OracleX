"""Tests for the data-source health registry behind the LIVE badge."""

import httpx
import pytest

from services.health_registry import (
    DOWN_AFTER_FAILURES,
    HealthRegistry,
    category_for_url,
    summarize_error,
)


@pytest.fixture
def registry() -> HealthRegistry:
    return HealthRegistry()


def _row(snapshot: dict, key: str) -> dict:
    return next(c for c in snapshot["categories"] if c["key"] == key)


class TestCategoryForUrl:
    def test_maps_the_most_specific_host_suffix(self):
        assert category_for_url("https://query1.finance.yahoo.com/v8/chart") == "stocks"
        assert category_for_url("https://api.coingecko.com/api/v3/x") == "prices_crypto"

    def test_unmapped_hosts_are_not_attributed(self):
        assert category_for_url("https://example.invalid/feed") is None
        assert category_for_url("not a url") is None


class TestSummarizeError:
    def test_leaks_nothing_identifying(self):
        request = httpx.Request("GET", "https://api.coingecko.com/secret?key=abc123")
        response = httpx.Response(429, request=request)
        detail = summarize_error(httpx.HTTPStatusError("boom", request=request, response=response))
        assert detail == "rate limited (429)"
        assert "coingecko" not in detail and "abc123" not in detail

    def test_classifies_transport_failures(self):
        assert summarize_error(httpx.ConnectTimeout("x")) == "timeout"
        assert summarize_error(httpx.ConnectError("x")) == "unreachable"


class TestStateTransitions:
    def test_an_untouched_category_is_idle_not_broken(self, registry: HealthRegistry):
        assert _row(registry.snapshot(), "news")["state"] == "idle"

    def test_a_single_failure_degrades_rather_than_downs(self, registry: HealthRegistry):
        registry.record("news", ok=True)
        registry.record("news", ok=False, error=httpx.ConnectTimeout("x"))
        row = _row(registry.snapshot(), "news")
        assert row["state"] == "degraded"
        assert row["detail"] == "timeout"

    def test_repeated_failures_go_down(self, registry: HealthRegistry):
        registry.record("news", ok=True)
        for _ in range(DOWN_AFTER_FAILURES):
            registry.record("news", ok=False, error=httpx.ConnectTimeout("x"))
        assert _row(registry.snapshot(), "news")["state"] == "down"

    def test_a_success_clears_the_fault(self, registry: HealthRegistry):
        for _ in range(DOWN_AFTER_FAILURES):
            registry.record("news", ok=False, error=httpx.ConnectTimeout("x"))
        registry.record("news", ok=True, latency_ms=42)
        row = _row(registry.snapshot(), "news")
        assert row["state"] == "ok"
        assert row["detail"] is None
        assert row["latency_ms"] == 42

    def test_unknown_categories_are_dropped(self, registry: HealthRegistry):
        registry.record("not_a_category", ok=False, error=httpx.ConnectTimeout("x"))
        assert registry.snapshot()["status"] == "starting"


class TestOverallStatus:
    def test_all_idle_reports_starting(self, registry: HealthRegistry):
        assert registry.snapshot()["status"] == "starting"

    def test_a_failing_optional_category_only_degrades(self, registry: HealthRegistry):
        registry.record("prices_crypto", ok=True)
        for _ in range(DOWN_AFTER_FAILURES):
            registry.record("news", ok=False, error=httpx.ConnectTimeout("x"))
        assert registry.snapshot()["status"] == "degraded"

    def test_a_downed_critical_category_goes_offline(self, registry: HealthRegistry):
        registry.record("news", ok=True)
        for _ in range(DOWN_AFTER_FAILURES):
            registry.record("prices_crypto", ok=False, error=httpx.ConnectTimeout("x"))
        assert registry.snapshot()["status"] == "offline"

    def test_idle_categories_do_not_hold_back_a_live_verdict(self, registry: HealthRegistry):
        registry.record("prices_crypto", ok=True)
        assert registry.snapshot()["status"] == "live"
