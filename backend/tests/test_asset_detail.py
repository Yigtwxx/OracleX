"""
The asset detail modal must not report a market cap of zero.

Yahoo's `quoteSummary` is crumb-authenticated and answers 401 to anything
without a session, which used to leave every stock detail at `market_cap: 0.0`
while the overview table showed the right number for the same ticker — the
overview reads the NASDAQ screener the registry already holds, the detail path
did not. These pin the crumb session, the registry fallback behind it, and the
CoinGecko null handling that could 404 a whole coin over one missing field.
"""

import pytest

from services import asset_detail_service as ads
from services import http_client
from services.cache import home_cache


@pytest.fixture(autouse=True)
def _clear_detail_cache():
    """Each test starts cold; the service caches by symbol for five minutes."""
    home_cache.clear()
    yield
    home_cache.clear()


def _chart_payload(price=200.0, prev_close=190.0, volume=1_000_000):
    """Minimal Yahoo v8 chart response — the shape `fetch_stock_detail` reads."""
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "regularMarketPrice": price,
                        "chartPreviousClose": prev_close,
                        "regularMarketVolume": volume,
                        "regularMarketDayHigh": price + 2,
                        "regularMarketDayLow": price - 2,
                        "fiftyTwoWeekHigh": price + 50,
                        "fiftyTwoWeekLow": price - 50,
                        "longName": "Acme Corp",
                    }
                }
            ]
        }
    }


def _summary_payload(market_cap=3_000_000_000_000):
    """Minimal Yahoo v10 quoteSummary response, values in `{raw, fmt}` form."""
    return {
        "quoteSummary": {
            "result": [
                {
                    "assetProfile": {
                        "longBusinessSummary": "Acme builds anvils.",
                        "sector": "Industrials",
                        "industry": "Tools",
                    },
                    "financialData": {"totalRevenue": {"raw": 400_000_000}},
                    "defaultKeyStatistics": {"trailingPE": {"raw": 25.5}},
                    "summaryDetail": {"marketCap": {"raw": market_cap}},
                }
            ]
        }
    }


class TestStockMarketCap:
    """`fetch_stock_detail` must produce a non-zero market cap either way."""

    @pytest.fixture(autouse=True)
    def _stub_registry(self, monkeypatch):
        async def fake_metadata(limit=250):
            return {
                "ACME": {
                    "symbol": "ACME",
                    "name": "Acme Corp",
                    "sector": "Industrials",
                    "market_cap": 2_500_000_000_000,
                }
            }

        monkeypatch.setattr(ads.asset_registry, "get_stock_metadata", fake_metadata)
        monkeypatch.setattr(
            ads.asset_registry, "build_stock_logo_url", lambda symbol: f"logo/{symbol}"
        )

    async def test_prefers_quote_summary_market_cap(self, monkeypatch):
        async def fake_chart(url, **kwargs):
            return _chart_payload()

        async def fake_summary(url, **kwargs):
            return _summary_payload(market_cap=3_000_000_000_000)

        monkeypatch.setattr(ads, "get_json_impersonated", fake_chart)
        monkeypatch.setattr(ads, "get_json_yahoo", fake_summary)

        result = await ads.fetch_stock_detail("ACME")

        # Yahoo's own figure wins over the screener's when both are available.
        assert result["market_cap"] == 3_000_000_000_000
        assert result["pe_ratio"] == 25.5
        assert result["description"] == "Acme builds anvils."

    async def test_falls_back_to_registry_when_quote_summary_fails(self, monkeypatch):
        """The regression: a blocked quoteSummary used to yield market_cap 0.0."""

        async def fake_chart(url, **kwargs):
            return _chart_payload()

        async def blocked_summary(url, **kwargs):
            raise RuntimeError("401 Invalid Crumb")

        monkeypatch.setattr(ads, "get_json_impersonated", fake_chart)
        monkeypatch.setattr(ads, "get_json_yahoo", blocked_summary)

        result = await ads.fetch_stock_detail("ACME")

        assert result["market_cap"] == 2_500_000_000_000
        # The price half of the payload is unaffected by the quoteSummary loss.
        assert result["price"] == 200.0
        assert result["sector"] == "Industrials"

    async def test_degraded_payload_is_cached_only_briefly(self, monkeypatch):
        """A transient block must not be pinned for the full five minutes."""
        recorded = {}

        async def fake_chart(url, **kwargs):
            return _chart_payload()

        async def blocked_summary(url, **kwargs):
            raise RuntimeError("401 Invalid Crumb")

        def record_set(key, value, ttl):
            recorded[key] = ttl

        monkeypatch.setattr(ads, "get_json_impersonated", fake_chart)
        monkeypatch.setattr(ads, "get_json_yahoo", blocked_summary)
        monkeypatch.setattr(ads.home_cache, "set", record_set)

        await ads.fetch_stock_detail("ACME")

        assert recorded["asset_detail_stock_ACME"] == ads.DEGRADED_CACHE_DURATION
        assert ads.DEGRADED_CACHE_DURATION < ads.DETAIL_CACHE_DURATION

    async def test_unknown_symbol_without_registry_entry_survives(self, monkeypatch):
        """A ticker outside the screener's top-250 still renders, just without a cap."""

        async def fake_chart(url, **kwargs):
            return _chart_payload()

        async def blocked_summary(url, **kwargs):
            raise RuntimeError("401 Invalid Crumb")

        monkeypatch.setattr(ads, "get_json_impersonated", fake_chart)
        monkeypatch.setattr(ads, "get_json_yahoo", blocked_summary)

        result = await ads.fetch_stock_detail("NOTLISTED")

        assert result is not None
        assert result["market_cap"] == 0.0
        assert result["name"] == "Acme Corp"  # falls back to the chart's longName


class TestCryptoNullHandling:
    """CoinGecko sends `null` for currency maps it has no data for."""

    def test_usd_reader_tolerates_a_null_bucket(self):
        assert ads._usd({"market_cap": None}, "market_cap") == 0
        assert ads._usd({}, "market_cap") == 0
        assert ads._usd({"ath_date": None}, "ath_date", "") == ""

    def test_usd_reader_tolerates_a_null_usd_value(self):
        assert ads._usd({"market_cap": {"usd": None}}, "market_cap") == 0

    def test_usd_reader_returns_the_value_when_present(self):
        assert ads._usd({"market_cap": {"usd": 1_234}}, "market_cap") == 1_234
        # Zero is a real reading and must not be swapped for the default.
        assert ads._usd({"market_cap": {"usd": 0}}, "market_cap", 99) == 0


class TestYahooCrumbSession:
    """`get_json_yahoo` holds a crumb and re-opens the session when it expires."""

    @pytest.fixture(autouse=True)
    def _reset_session(self):
        http_client._yahoo_session = None
        http_client._yahoo_crumb = None
        yield
        http_client._yahoo_session = None
        http_client._yahoo_crumb = None

    async def test_reuses_one_crumb_across_calls(self, monkeypatch):
        opens = []

        class FakeResponse:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"ok": True}

        class FakeSession:
            def get(self, url, **kwargs):
                assert kwargs["params"]["crumb"] == "CRUMB-1"
                return FakeResponse()

        def fake_open():
            opens.append(1)
            return FakeSession(), "CRUMB-1"

        monkeypatch.setattr(http_client, "_open_yahoo_session", fake_open)

        assert await http_client.get_json_yahoo("https://example.test/a") == {"ok": True}
        assert await http_client.get_json_yahoo("https://example.test/b") == {"ok": True}
        assert len(opens) == 1

    async def test_reopens_the_session_once_on_401(self, monkeypatch):
        crumbs_used = []

        class FakeResponse:
            def __init__(self, status_code):
                self.status_code = status_code

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP {self.status_code}")

            def json(self):
                return {"ok": True}

        class FakeSession:
            def __init__(self, crumb):
                self.crumb = crumb

            def get(self, url, **kwargs):
                crumbs_used.append(kwargs["params"]["crumb"])
                # The first crumb is stale; the replacement is accepted.
                return FakeResponse(401 if self.crumb == "STALE" else 200)

        issued = iter(["STALE", "FRESH"])

        def fake_open():
            crumb = next(issued)
            return FakeSession(crumb), crumb

        monkeypatch.setattr(http_client, "_open_yahoo_session", fake_open)

        assert await http_client.get_json_yahoo("https://example.test/a") == {"ok": True}
        assert crumbs_used == ["STALE", "FRESH"]

    async def test_a_second_401_is_raised(self, monkeypatch):
        class FakeResponse:
            status_code = 401

            def raise_for_status(self):
                raise RuntimeError("HTTP 401")

        class FakeSession:
            def get(self, url, **kwargs):
                return FakeResponse()

        monkeypatch.setattr(
            http_client, "_open_yahoo_session", lambda: (FakeSession(), "NEVER-VALID")
        )

        with pytest.raises(RuntimeError, match="HTTP 401"):
            await http_client.get_json_yahoo("https://example.test/a")
