"""
Three panels, two providers, and none of them may print a number it did not get.

The board's failure modes are all the quiet kind: a prediction market ranked as
a perp venue, a routing front-end double-counting the exchange it routes to, a
BTC-denominated volume drawn under a USD axis. Each of these renders as a
plausible bar, which is the class of wrong this codebase refuses.
"""

import time

import pytest

from services import dex_perps_service as svc


def _oi_payload():
    return {
        "protocols": [
            {
                "name": "Hyperliquid Perps",
                "category": "Derivatives",
                "total24h": 12_876_709_725,
                "change_1d": -7.28,
                "logo": "https://icons.llamao.fi/icons/protocols/hyperliquid",
                "chains": ["Hyperliquid L1"],
            },
            {
                "name": "GMX V2 Perps",
                "category": "Derivatives",
                "total24h": 200_000_000,
                "change_1d": 1.0,
                "logo": "https://icons.llamao.fi/icons/protocols/gmx",
                "chains": ["Arbitrum"],
            },
            {
                "name": "GMX V1 Perps",
                "category": "Derivatives",
                "total24h": 5_000_000,
                "change_1d": 2.0,
                "logo": "https://icons.llamao.fi/icons/protocols/gmx",
                "chains": ["Arbitrum"],
            },
            # Filtered: a prediction market is not a perpetual futures exchange.
            {"name": "Kalshi", "category": "Prediction Market", "total24h": 819_165_005},
            # Filtered: a front-end whose open interest is already counted under
            # Hyperliquid Perps.
            {"name": "tradeXYZ", "category": "Interface", "total24h": 3_640_810_503},
            # Dropped: a zero bar is not a fact about a venue, and it makes a
            # log axis undefinable.
            {"name": "Nado Perps", "category": "Derivatives", "total24h": 0},
        ]
    }


def _protocols_payload():
    return [
        {
            "name": "Hyperliquid HLP",
            "category": "Derivatives",
            "tvl": 184_852_887,
            "logo": "x",
            "chains": ["Hyperliquid L1"],
        },
        {
            "name": "GMX V2 Perps",
            "category": "Derivatives",
            "tvl": 205_230_676,
            "logo": "y",
            "chains": ["Arbitrum"],
        },
        {
            "name": "Uniswap V3",
            "category": "Dexs",
            "tvl": 3_000_000_000,
            "logo": "z",
            "chains": ["Ethereum"],
        },
    ]


def _cg_payload():
    return [
        {
            "id": "hyperliquid",
            "name": "Hyperliquid (Futures)",
            "trade_volume_24h_btc": "134432.59",
            "image": "i1",
        },
        {
            "id": "gmx-perpetuals-v2-arbitrum",
            "name": "GMX Perpetuals V2 (Arbitrum)",
            "trade_volume_24h_btc": "900.0",
            "image": "i2",
        },
        {
            "id": "gmx-perpetuals-v2-avalanche",
            "name": "GMX Perpetuals V2 (Avalanche)",
            "trade_volume_24h_btc": "100.0",
            "image": "i3",
        },
        # Not in the registry, therefore a CEX: must never reach the panel.
        {
            "id": "binance_futures",
            "name": "Binance (Futures)",
            "trade_volume_24h_btc": "748841.86",
            "image": "i4",
        },
    ]


class TestOpenInterest:
    @pytest.mark.asyncio
    async def test_ranks_derivatives_venues_by_current_open_interest(self, monkeypatch):
        async def fake_get_json(url, **kwargs):
            return _oi_payload()

        monkeypatch.setattr(svc.http_client, "get_json", fake_get_json)
        rows = await svc._fetch_open_interest()

        assert [row["name"] for row in rows] == ["Hyperliquid", "GMX"]
        assert rows[0]["value_usd"] == 12_876_709_725
        assert rows[0]["change_1d_pct"] == -7.28
        assert rows[0]["chains"] == ["Hyperliquid L1"]

    @pytest.mark.asyncio
    async def test_versions_of_one_venue_are_summed(self, monkeypatch):
        async def fake_get_json(url, **kwargs):
            return _oi_payload()

        monkeypatch.setattr(svc.http_client, "get_json", fake_get_json)
        rows = await svc._fetch_open_interest()
        gmx = next(row for row in rows if row["slug"] == "gmx")
        assert gmx["value_usd"] == 205_000_000

    @pytest.mark.asyncio
    async def test_the_summed_bar_lists_every_alias_chain(self, monkeypatch):
        # The tooltip names a venue's chains, so keeping only the leading
        # alias's list would present a subset as the whole answer.
        async def fake_get_json(url, **kwargs):
            return {
                "protocols": [
                    {
                        "name": "GMX V2 Perps",
                        "category": "Derivatives",
                        "total24h": 200_000_000,
                        "chains": ["Arbitrum"],
                    },
                    {
                        "name": "GMX V1 Perps",
                        "category": "Derivatives",
                        "total24h": 5_000_000,
                        "chains": ["Avalanche", "Arbitrum"],
                    },
                ]
            }

        monkeypatch.setattr(svc.http_client, "get_json", fake_get_json)
        (gmx,) = await svc._fetch_open_interest()
        assert gmx["chains"] == ["Arbitrum", "Avalanche"]

    @pytest.mark.asyncio
    async def test_the_summed_bar_carries_the_largest_alias_change(self, monkeypatch):
        # V2 holds 200M and moved 1%, V1 holds 5M and moved 2%. The summed bar
        # follows V2, and averaging the two would report a number neither
        # provider published.
        async def fake_get_json(url, **kwargs):
            return _oi_payload()

        monkeypatch.setattr(svc.http_client, "get_json", fake_get_json)
        rows = await svc._fetch_open_interest()
        gmx = next(row for row in rows if row["slug"] == "gmx")
        assert gmx["change_1d_pct"] == 1.0

    @pytest.mark.asyncio
    async def test_prediction_markets_and_interfaces_are_absent(self, monkeypatch):
        async def fake_get_json(url, **kwargs):
            return _oi_payload()

        monkeypatch.setattr(svc.http_client, "get_json", fake_get_json)
        names = {row["name"] for row in await svc._fetch_open_interest()}
        assert "Kalshi" not in names
        assert "tradeXYZ" not in names

    @pytest.mark.asyncio
    async def test_a_venue_missing_from_the_registry_keeps_its_provider_name(self, monkeypatch):
        # A perp DEX must appear the day it launches, not the day someone
        # remembers to add a registry line.
        async def fake_get_json(url, **kwargs):
            return {
                "protocols": [
                    {"name": "Brand New Perps", "category": "Derivatives", "total24h": 5_000_000}
                ]
            }

        monkeypatch.setattr(svc.http_client, "get_json", fake_get_json)
        (row,) = await svc._fetch_open_interest()
        assert row["name"] == "Brand New Perps"
        assert row["slug"] == "brand-new-perps"

    @pytest.mark.asyncio
    async def test_synthetics_protocols_are_admitted(self, monkeypatch):
        # Unlike TVL, open interest is a position figure a synthetics venue
        # can genuinely report — see TVL_ALLOWED_CATEGORIES for why the two
        # panels disagree on this filter.
        async def fake_get_json(url, **kwargs):
            return {
                "protocols": [
                    {
                        "name": "Alchemix V3",
                        "category": "Synthetics",
                        "total24h": 37_400_000,
                    }
                ]
            }

        monkeypatch.setattr(svc.http_client, "get_json", fake_get_json)
        names = {row["name"] for row in await svc._fetch_open_interest()}
        assert "Alchemix V3" in names


class TestTvl:
    @pytest.mark.asyncio
    async def test_only_derivatives_protocols_are_counted(self, monkeypatch):
        async def fake_get_json(url, **kwargs):
            return _protocols_payload()

        monkeypatch.setattr(svc.http_client, "get_json", fake_get_json)
        rows = await svc._fetch_tvl()
        assert [row["name"] for row in rows] == ["GMX", "Hyperliquid"]
        assert all(row["change_1d_pct"] is None for row in rows)

    @pytest.mark.asyncio
    async def test_synthetics_protocols_never_reach_the_tvl_panel(self, monkeypatch):
        # Regression guard: TVL used to share open interest's wider
        # ALLOWED_CATEGORIES, which let a synthetic-debt protocol with no
        # perpetual product (Alchemix V3, $37.4M) rank inside the live TVL
        # top 15 on a board titled "DEX Perps".
        async def fake_get_json(url, **kwargs):
            return [
                {
                    "name": "Alchemix V3",
                    "category": "Synthetics",
                    "tvl": 37_400_000,
                },
                *_protocols_payload(),
            ]

        monkeypatch.setattr(svc.http_client, "get_json", fake_get_json)
        names = {row["name"] for row in await svc._fetch_tvl()}
        assert "Alchemix V3" not in names


class TestVolume:
    @pytest.mark.asyncio
    async def test_converts_btc_volume_to_usd(self, monkeypatch):
        async def fake_cg(path, **kwargs):
            return _cg_payload()

        async def fake_price(symbol):
            return 100_000.0

        monkeypatch.setattr(svc.coingecko, "get_json", fake_cg)
        monkeypatch.setattr(svc.price_service, "get_current_price", fake_price)

        rows = await svc._fetch_volume()
        assert rows[0]["name"] == "Hyperliquid"
        assert rows[0]["value_usd"] == pytest.approx(13_443_259_000.0)

    @pytest.mark.asyncio
    async def test_centralised_venues_never_reach_the_panel(self, monkeypatch):
        async def fake_cg(path, **kwargs):
            return _cg_payload()

        async def fake_price(symbol):
            return 100_000.0

        monkeypatch.setattr(svc.coingecko, "get_json", fake_cg)
        monkeypatch.setattr(svc.price_service, "get_current_price", fake_price)

        names = {row["name"] for row in await svc._fetch_volume()}
        assert "Binance (Futures)" not in names
        # Both GMX deployments collapse into one bar.
        assert names == {"Hyperliquid", "GMX"}

    @pytest.mark.asyncio
    async def test_an_empty_provider_response_is_not_a_registry_failure(self, monkeypatch):
        # The raise guarding a failed registry load sits before the row loop.
        # This pins the distinction: a healthy provider that listed nothing
        # yields an empty panel, it does not claim the registry is broken.
        async def fake_cg(path, **kwargs):
            return []

        async def fake_price(symbol):
            return 100_000.0

        monkeypatch.setattr(svc.coingecko, "get_json", fake_cg)
        monkeypatch.setattr(svc.price_service, "get_current_price", fake_price)

        assert await svc._fetch_volume() == []

    @pytest.mark.asyncio
    async def test_no_btc_price_refuses_rather_than_serving_btc(self, monkeypatch):
        async def fake_cg(path, **kwargs):
            return _cg_payload()

        async def fake_price(symbol):
            return None

        monkeypatch.setattr(svc.coingecko, "get_json", fake_cg)
        monkeypatch.setattr(svc.price_service, "get_current_price", fake_price)

        with pytest.raises(svc.DexPerpsSourceError):
            await svc._fetch_volume()

    @pytest.mark.asyncio
    async def test_an_empty_registry_index_refuses_rather_than_serving_nothing(self, monkeypatch):
        # `read_json_cache` returns None for a missing *or JSON-corrupt* file,
        # which makes `by_coingecko_id()` come back empty — every CoinGecko row
        # then misses the allowlist, and the panel would silently render as a
        # measured "no venues" instead of surfacing the registry failure.
        async def fake_cg(path, **kwargs):
            return _cg_payload()

        async def fake_price(symbol):
            return 100_000.0

        monkeypatch.setattr(svc.coingecko, "get_json", fake_cg)
        monkeypatch.setattr(svc.price_service, "get_current_price", fake_price)
        monkeypatch.setattr(svc, "by_coingecko_id", lambda: {})

        with pytest.raises(svc.DexPerpsSourceError):
            await svc._fetch_volume()


class TestAssembly:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        svc._cache.clear()
        svc._last_good.clear()
        yield
        svc._cache.clear()
        svc._last_good.clear()

    @staticmethod
    def _patch(monkeypatch, *, oi=None, tvl=None, volume=None):
        async def ok(rows):
            return rows

        async def boom():
            raise svc.DexPerpsSourceError("provider down")

        def wire(name, rows):
            if rows is None:
                monkeypatch.setattr(svc, name, boom)
            else:
                monkeypatch.setattr(svc, name, lambda rows=rows: ok(rows))

        wire("_fetch_open_interest", oi)
        wire("_fetch_tvl", tvl)
        wire("_fetch_volume", volume)

    @pytest.mark.asyncio
    async def test_all_three_panels_report_their_provider(self, monkeypatch):
        row = {
            "slug": "hyperliquid",
            "name": "Hyperliquid",
            "value_usd": 1.0,
            "change_1d_pct": None,
            "logo": "",
            "chains": [],
        }
        self._patch(monkeypatch, oi=[row], tvl=[row], volume=[row])

        board = await svc.get_dex_perps()

        assert board["sources"] == {
            "open_interest": svc.SOURCE_DEFILLAMA,
            "tvl": svc.SOURCE_DEFILLAMA,
            "volume_24h": svc.SOURCE_COINGECKO,
        }
        assert board["stale"] == {"open_interest": False, "tvl": False, "volume_24h": False}
        assert board["updated_at"] > 0

    @pytest.mark.asyncio
    async def test_a_failed_panel_is_empty_and_named_while_the_others_stand(self, monkeypatch):
        row = {
            "slug": "hyperliquid",
            "name": "Hyperliquid",
            "value_usd": 1.0,
            "change_1d_pct": None,
            "logo": "",
            "chains": [],
        }
        self._patch(monkeypatch, oi=[row], tvl=[row], volume=None)

        board = await svc.get_dex_perps()

        assert board["volume_24h"] == []
        assert board["sources"]["volume_24h"] == svc.SOURCE_UNAVAILABLE
        assert len(board["open_interest"]) == 1
        assert board["sources"]["open_interest"] == svc.SOURCE_DEFILLAMA

    @pytest.mark.asyncio
    async def test_every_panel_failing_still_answers(self, monkeypatch):
        self._patch(monkeypatch)
        board = await svc.get_dex_perps()
        assert board["open_interest"] == [] and board["tvl"] == [] and board["volume_24h"] == []
        assert set(board["sources"].values()) == {svc.SOURCE_UNAVAILABLE}

    @pytest.mark.asyncio
    async def test_a_failed_panel_replays_the_last_good_rows(self, monkeypatch):
        row = {
            "slug": "hyperliquid",
            "name": "Hyperliquid",
            "value_usd": 1.0,
            "change_1d_pct": None,
            "logo": "",
            "chains": [],
        }
        self._patch(monkeypatch, oi=[row], tvl=[row], volume=[row])
        await svc.get_dex_perps()
        svc._cache.invalidate(svc.CACHE_KEY)

        self._patch(monkeypatch, oi=[row], tvl=[row], volume=None)
        board = await svc.get_dex_perps()

        assert len(board["volume_24h"]) == 1
        assert board["stale"]["volume_24h"] is True
        assert board["stale"]["open_interest"] is False
        assert board["sources"]["volume_24h"] == svc.SOURCE_COINGECKO

    @pytest.mark.asyncio
    async def test_a_second_call_inside_the_ttl_makes_no_request(self, monkeypatch):
        calls = {"n": 0}
        row = {
            "slug": "hyperliquid",
            "name": "Hyperliquid",
            "value_usd": 1.0,
            "change_1d_pct": None,
            "logo": "",
            "chains": [],
        }

        async def counted():
            calls["n"] += 1
            return [row]

        monkeypatch.setattr(svc, "_fetch_open_interest", counted)
        monkeypatch.setattr(svc, "_fetch_tvl", counted)
        monkeypatch.setattr(svc, "_fetch_volume", counted)

        await svc.get_dex_perps()
        await svc.get_dex_perps()
        assert calls["n"] == 3

    @pytest.mark.asyncio
    async def test_a_last_good_record_past_the_ceiling_is_not_replayed(self, monkeypatch):
        """
        A panel that has been down longer than STALE_MAX_AGE_SECONDS must stop
        replaying its last-good rows and degrade to empty/unavailable, even
        though the *board's* cache entry keeps getting re-stamped by every poll.
        This is the freshness ceiling the docstring promises — regression guard
        for it never firing because the whole-board cache shared one timestamp.
        """
        row = {
            "slug": "hyperliquid",
            "name": "Hyperliquid",
            "value_usd": 1.0,
            "change_1d_pct": None,
            "logo": "",
            "chains": [],
        }
        self._patch(monkeypatch, oi=[row], tvl=[row], volume=[row])
        await svc.get_dex_perps()
        svc._cache.invalidate(svc.CACHE_KEY)

        # Backdate the recorded last-good write for volume past the ceiling,
        # simulating a provider outage that has outlasted the freshness window.
        stale_rows, _ = svc._last_good["volume_24h"]
        svc._last_good["volume_24h"] = (
            stale_rows,
            time.time() - svc.STALE_MAX_AGE_SECONDS - 1,
        )

        self._patch(monkeypatch, oi=[row], tvl=[row], volume=None)
        board = await svc.get_dex_perps()

        assert board["volume_24h"] == []
        assert board["sources"]["volume_24h"] == svc.SOURCE_UNAVAILABLE
        assert board["stale"]["volume_24h"] is False


class TestRoute:
    @pytest.mark.asyncio
    async def test_the_route_returns_the_board(self, monkeypatch):
        from routers import derivatives

        async def fake_board():
            return {
                "open_interest": [],
                "volume_24h": [],
                "tvl": [],
                "sources": {},
                "stale": {},
                "updated_at": 1,
            }

        monkeypatch.setattr(derivatives, "get_dex_perps", fake_board)
        assert await derivatives.dex_perps() == {
            "open_interest": [],
            "volume_24h": [],
            "tvl": [],
            "sources": {},
            "stale": {},
            "updated_at": 1,
        }


class TestHealthRegistry:
    def test_defillama_is_attributed_to_the_onchain_category(self):
        from services import health_registry

        assert health_registry.category_for_url("https://api.llama.fi/protocols") == "onchain"
        assert (
            health_registry.category_for_url("https://api.llama.fi/overview/open-interest")
            == "onchain"
        )
