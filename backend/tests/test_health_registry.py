"""Tests for the data-source health registry behind the LIVE badge."""

import time

import httpx
import pytest

from services.health_registry import (
    DOWN_AFTER_FAILURES,
    STALE_AFTER_S,
    HealthRegistry,
    category_for_url,
    is_rate_limited,
    summarize_error,
)


@pytest.fixture
def registry() -> HealthRegistry:
    return HealthRegistry()


def _row(snapshot: dict, key: str) -> dict:
    return next(c for c in snapshot["categories"] if c["key"] == key)


def _http_error(status: int) -> httpx.HTTPStatusError:
    """An upstream rejection, shaped the way httpx raises one."""
    request = httpx.Request("GET", "https://api.coingecko.com/api/v3/coins/markets")
    return httpx.HTTPStatusError(
        "boom", request=request, response=httpx.Response(status, request=request)
    )


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

    def test_a_first_call_failure_degrades_rather_than_downs(self, registry: HealthRegistry):
        # Nothing has succeeded yet, but one refusal is not yet an outage.
        registry.record("prices_crypto", ok=False, error=httpx.ConnectTimeout("x"))
        assert _row(registry.snapshot(), "prices_crypto")["state"] == "degraded"

    def test_a_rate_limited_provider_never_downs_its_category(self, registry: HealthRegistry):
        registry.record("prices_crypto", ok=True)
        for _ in range(DOWN_AFTER_FAILURES * 2):
            registry.record("prices_crypto", ok=False, error=_http_error(429))
        row = _row(registry.snapshot(), "prices_crypto")
        assert row["state"] == "degraded"
        assert row["detail"] == "rate limited (429)"

    def test_a_rate_limit_does_not_hide_a_real_outage(self, registry: HealthRegistry):
        registry.record("prices_crypto", ok=True)
        registry.record("prices_crypto", ok=False, error=_http_error(429))
        for _ in range(DOWN_AFTER_FAILURES):
            registry.record("prices_crypto", ok=False, error=httpx.ConnectTimeout("x"))
        assert _row(registry.snapshot(), "prices_crypto")["state"] == "down"

    def test_a_success_clears_the_outage_count_too(self, registry: HealthRegistry):
        for _ in range(DOWN_AFTER_FAILURES - 1):
            registry.record("prices_crypto", ok=False, error=httpx.ConnectTimeout("x"))
        registry.record("prices_crypto", ok=True)
        registry.record("prices_crypto", ok=False, error=httpx.ConnectTimeout("x"))
        assert _row(registry.snapshot(), "prices_crypto")["state"] == "degraded"


def _age(registry: HealthRegistry, key: str, seconds: float) -> None:
    """Backdate a category's last success, as if it had gone quiet."""
    registry._sources[key].last_ok_at = time.time() - seconds


class TestStaleness:
    def test_a_quiet_polled_category_is_stale_not_degraded(self, registry: HealthRegistry):
        registry.record("macro", ok=True, latency_ms=403)
        _age(registry, "macro", STALE_AFTER_S + 60)
        row = _row(registry.snapshot(), "macro")
        assert row["state"] == "stale"
        # Nothing failed, so the row must not invent a reason.
        assert row["detail"] is None

    def test_staleness_does_not_colour_the_badge(self, registry: HealthRegistry):
        registry.record("prices_crypto", ok=True)
        registry.record("macro", ok=True)
        _age(registry, "macro", STALE_AFTER_S + 60)
        assert registry.snapshot()["status"] == "live"

    @pytest.mark.parametrize("key", ["ai", "database"])
    def test_demand_driven_categories_never_go_stale(self, registry: HealthRegistry, key: str):
        # Nothing polls these, so a long silence means nobody asked — an idle
        # afternoon must not read as a fault.
        registry.record(key, ok=True, latency_ms=9)
        _age(registry, key, STALE_AFTER_S * 10)
        assert _row(registry.snapshot(), key)["state"] == "ok"

    def test_a_fault_outranks_staleness(self, registry: HealthRegistry):
        registry.record("macro", ok=True)
        _age(registry, "macro", STALE_AFTER_S + 60)
        registry.record("macro", ok=False, error=httpx.ConnectTimeout("x"))
        row = _row(registry.snapshot(), "macro")
        assert row["state"] == "degraded"
        assert row["detail"] == "timeout"


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

    def test_a_throttled_provider_does_not_speak_for_its_category(self, registry: HealthRegistry):
        # CoinGecko shares `prices_crypto` with four exchanges. Its quota being
        # spent leaves the board thinner, not the app offline.
        registry.record("prices_crypto", ok=True)
        for _ in range(DOWN_AFTER_FAILURES):
            registry.record_url(
                "https://api.coingecko.com/api/v3/coins/markets",
                ok=False,
                error=_http_error(429),
            )
        assert registry.snapshot()["status"] == "degraded"

    def test_a_rate_limit_during_boot_does_not_report_offline(self, registry: HealthRegistry):
        # A restart resets every verdict, so the first CoinGecko call of the
        # process used to be able to paint the badge red on its own.
        registry.record_url(
            "https://api.coingecko.com/api/v3/coins/markets", ok=False, error=_http_error(429)
        )
        assert registry.snapshot()["status"] == "degraded"


class TestIsRateLimited:
    def test_only_429_counts_as_a_quota_refusal(self):
        assert is_rate_limited(_http_error(429))
        assert not is_rate_limited(_http_error(503))
        assert not is_rate_limited(httpx.ConnectTimeout("x"))
        assert not is_rate_limited(None)
