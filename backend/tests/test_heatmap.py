"""
The heatmap board must not invent readings it does not have.

Every failure these lock in was a case of the board making a confident claim out
of an absence or a saturated formula: a missing 24h move rendered as a green
"+0.00%" tile, a volume score that pinned every large asset at exactly 100, a
developer score that could not tell a famous dead repository from an active one,
and a sector "average" that weighted a $300M token like a $2T one.

The rest cover the resilience paths — stale fallback, single-flight, failure
backoff — where the old service either dropped a perfectly good cached board on
the floor or let four broken coin ids starve the refresh rotation forever.
"""

import asyncio
import time

import pytest

from services import heatmap_service as hm


@pytest.fixture(autouse=True)
def clean_cache():
    """The board cache is process-wide; no test may inherit another's board."""
    from services.cache import market_cache

    market_cache.clear()
    yield
    market_cache.clear()


def _row(coin_id, symbol, *, cap=1e9, change=1.0, volume=1e8, price=10.0, change_7d=None):
    """A row in the shape CoinGecko's /coins/markets returns."""
    return {
        "id": coin_id,
        "symbol": symbol.lower(),
        "name": symbol.title(),
        "image": f"https://example.test/{coin_id}.png",
        "current_price": price,
        "market_cap": cap,
        "total_volume": volume,
        "price_change_percentage_24h": change,
        "price_change_percentage_7d_in_currency": change_7d,
    }


class TestVolumeScore:
    def test_unknown_volume_stays_unknown(self):
        assert hm._volume_score(None) is None, "A missing volume must not score 0"

    def test_zero_volume_is_a_real_observation(self):
        assert hm._volume_score(0) == 0.0, "Nothing traded is a reading, not an absence"

    @pytest.mark.parametrize(
        "volume,expected",
        [(1e6, 0.0), (1e7, 20.0), (1e8, 40.0), (1e9, 60.0), (1e10, 80.0), (1e11, 100.0)],
    )
    def test_decade_anchors_land_on_round_scores(self, volume, expected):
        assert hm._volume_score(volume) == expected, f"${volume:,.0f} should score {expected}"

    def test_large_volumes_still_separate(self):
        """
        The regression that made the Volume tab unreadable.

        The linear formula it replaced saturated at $10B, so BTC, ETH, USDT and
        SOL all scored exactly 100 and were indistinguishable from each other.
        """
        assert hm._volume_score(2e10) < hm._volume_score(1e11), (
            "A $20B and a $100B day must not paint the same colour"
        )

    def test_below_the_floor_clamps_rather_than_going_negative(self):
        assert hm._volume_score(1000) == 0.0, "Sub-$1M volume clamps to the bottom of the scale"

    def test_never_exceeds_the_top_of_the_scale(self):
        assert hm._volume_score(9e14) == 100.0, "The scale is 0-100, whatever the volume"

    def test_monotonic_across_the_range(self):
        volumes = [1e6, 5e6, 1e7, 5e8, 1e9, 4e9, 1e10, 6e10, 1e11]
        scores = [hm._volume_score(v) for v in volumes]
        assert scores == sorted(scores), "More volume must never score lower"


class TestDeveloperScore:
    def test_no_repository_reports_no_score(self):
        scored = hm._score_developer({"developer_data": {}})
        assert "developer_score" not in scored, (
            "A coin with no public repo has nothing to measure — the caller must "
            "report None, not a 0 that reads as a measured lack of activity"
        )

    def test_a_score_is_stamped_with_the_formula_version(self):
        scored = hm._score_developer({"developer_data": {"stars": 10, "commit_count_4_weeks": 1}})
        assert scored["score_version"] == hm.SCORE_VERSION
        assert scored["fetched_at"] > 0

    def test_a_dead_famous_repo_scores_below_an_active_one(self):
        """
        The exact case the previous formula collapsed.

        Summing capped linear terms put anything past ~50k stars at exactly 100,
        so a project with no commits in a month outranked nothing and tied with
        everything.
        """
        dead = hm._score_developer(
            {"developer_data": {"stars": 74_000, "commit_count_4_weeks": 0}}
        )["developer_score"]
        active = hm._score_developer(
            {"developer_data": {"stars": 74_000, "commit_count_4_weeks": 300}}
        )["developer_score"]
        assert dead < active, f"Dormant ({dead}) must score below active ({active})"

    def test_monotonic_in_commits_with_reach_held_still(self):
        scores = [
            hm._score_developer({"developer_data": {"stars": 5_000, "commit_count_4_weeks": c}})[
                "developer_score"
            ]
            for c in (0, 10, 50, 200, 800)
        ]
        assert scores == sorted(scores), "More recent commits must never score lower"

    def test_monotonic_in_stars_with_activity_held_still(self):
        scores = [
            hm._score_developer({"developer_data": {"stars": s, "commit_count_4_weeks": 50}})[
                "developer_score"
            ]
            for s in (100, 1_000, 10_000, 90_000)
        ]
        assert scores == sorted(scores), "More reach must never score lower"

    def test_never_exceeds_one_hundred(self):
        scored = hm._score_developer(
            {"developer_data": {"stars": 900_000, "commit_count_4_weeks": 50_000}}
        )
        assert scored["developer_score"] <= 100, "The score is a 0-100 scale"

    def test_forks_alone_do_not_manufacture_a_score_from_nothing(self):
        """Forks are counted as evidence a repo exists, but carry no weight."""
        scored = hm._score_developer({"developer_data": {"forks": 500}})
        assert scored["developer_score"] == 0.0, (
            "A repo with only forks has neither measured activity nor reach"
        )


class TestSectorDerivation:
    def test_unresolved_categories_are_not_a_classification(self):
        assert hm._derive_sector([]) is None, (
            "No categories means not yet known — distinct from 'Other', which "
            "means known and matched nothing"
        )
        assert hm._derive_sector(None) is None

    def test_resolved_but_unmatched_is_other(self):
        assert hm._derive_sector(["Something Unlisted"]) == "Other"

    def test_specific_categories_win_over_the_broad_catch_alls(self):
        """
        Pins the ordering of CATEGORY_TO_SECTOR.

        CoinGecko tags almost every chain "Smart Contract Platform" and
        "Layer 1 (L1)". If those move up the list, every meme coin, oracle and
        exchange token on the board silently becomes "Smart Contracts".
        """
        assert hm._derive_sector(["Meme", "Smart Contract Platform", "Layer 1 (L1)"]) == "Meme"
        assert hm._derive_sector(["Oracle", "Layer 1 (L1)"]) == "Oracle"
        assert hm._derive_sector(["Smart Contract Platform"]) == "Smart Contracts"

    def test_matching_is_case_insensitive(self):
        assert hm._derive_sector(["MEME COINS"]) == "Meme"


class TestPegClassification:
    @pytest.mark.parametrize("symbol", ["USDT", "USDC", "DAI"])
    def test_stablecoins_are_recognised_from_the_symbol_before_categories_land(self, symbol):
        assert hm._classify_peg(symbol, None) == hm.PEG_STABLECOIN

    @pytest.mark.parametrize("symbol", ["WBTC", "STETH", "WSTETH", "WETH"])
    def test_wrapped_assets_are_recognised_from_the_symbol_before_categories_land(self, symbol):
        assert hm._classify_peg(symbol, None) == hm.PEG_WRAPPED

    def test_categories_are_the_real_source(self):
        assert hm._classify_peg("XYZ", ["Stablecoins"]) == hm.PEG_STABLECOIN
        assert hm._classify_peg("XYZ", ["Liquid Staking Tokens"]) == hm.PEG_WRAPPED
        assert hm._classify_peg("XYZ", ["Wrapped Tokens"]) == hm.PEG_WRAPPED

    def test_ordinary_assets_carry_no_peg(self):
        assert hm._classify_peg("BTC", ["Smart Contract Platform"]) is None
        assert hm._classify_peg("BTC", None) is None

    def test_resolved_categories_override_a_symbol_lookalike(self):
        """
        A token merely starting with W is not wrapped.

        Once categories are known they are trusted over the symbol set, which
        exists only to cover the window before the first detail fetch lands.
        """
        assert hm._classify_peg("WETH", ["Smart Contract Platform"]) is None


class TestBuildBoard:
    def test_a_missing_price_change_stays_missing(self):
        """
        The defect that made the board dishonest.

        The service coerced an absent 24h move to 0, and the UI colours `>= 0`
        as a gain — so "we don't know" rendered as a green +0.00% tile.
        """
        row = _row("ghost", "GHO")
        row["price_change_percentage_24h"] = None
        board = hm._build_board([row], {})
        assert board["coins"][0]["price_change_24h"] is None, (
            "An unknown move must be None, never 0"
        )

    def test_a_missing_price_is_not_reported_as_zero(self):
        row = _row("ghost", "GHO")
        row["current_price"] = None
        board = hm._build_board([row], {})
        assert board["coins"][0]["price"] is None, "A $0 price is a claim, not a placeholder"

    def test_coins_are_ranked_by_market_cap(self):
        board = hm._build_board([_row("small", "SML", cap=1e8), _row("big", "BIG", cap=1e12)], {})
        assert [c["symbol"] for c in board["coins"]] == ["BIG", "SML"]

    def test_sector_change_is_weighted_by_market_cap(self):
        """
        Hand-computed: caps 100 and 900, moves +10% and -1%.

            weighted = (100*10 + 900*-1) / 1000 = +0.10
            unweighted mean = (10 + -1) / 2     = +4.50

        The unweighted figure is what used to reach the generated report.
        """
        details = {
            "tiny": {"sector": "DeFi"},
            "huge": {"sector": "DeFi"},
        }
        board = hm._build_board(
            [_row("tiny", "TNY", cap=100, change=10.0), _row("huge", "HUG", cap=900, change=-1.0)],
            details,
        )
        sector = board["sectors"][0]
        assert sector["weighted_change_24h"] == 0.1
        assert sector["avg_change_24h"] == 4.5
        assert sector["weighted_change_24h"] != sector["avg_change_24h"], (
            "A size spread must move the two figures apart"
        )

    def test_coins_without_a_market_cap_are_listed_but_not_weighted(self):
        details = {"real": {"sector": "DeFi"}, "capless": {"sector": "DeFi"}}
        board = hm._build_board(
            [_row("real", "REA", cap=1000, change=2.0), _row("capless", "CAP", cap=0, change=99.0)],
            details,
        )
        sector = board["sectors"][0]
        assert sector["coin_count"] == 2, "The coin is still on the board"
        assert sector["weighted_change_24h"] == 2.0, (
            "A coin with no market cap cannot carry weight in a cap-weighted mean"
        )

    def test_a_sector_with_no_readings_reports_no_change(self):
        row = _row("ghost", "GHO")
        row["price_change_percentage_24h"] = None
        board = hm._build_board([row], {"ghost": {"sector": "DeFi"}})
        sector = board["sectors"][0]
        assert sector["weighted_change_24h"] is None, "Nothing measured means no figure"
        assert sector["coverage"] == 0.0

    def test_coverage_reports_how_much_of_a_sector_was_actually_measured(self):
        blind = _row("blind", "BLD", cap=500)
        blind["price_change_percentage_24h"] = None
        board = hm._build_board(
            [_row("seen", "SEE", cap=500, change=3.0), blind],
            {"seen": {"sector": "DeFi"}, "blind": {"sector": "DeFi"}},
        )
        assert board["sectors"][0]["coverage"] == 0.5

    def test_pegged_assets_are_excluded_from_the_board_and_its_aggregates(self):
        details = {
            "bitcoin": {"sector": "Proof of Work"},
            "tether": {"sector": "Stablecoin", "peg_type": hm.PEG_STABLECOIN},
        }
        rows = [
            _row("bitcoin", "BTC", cap=1_000, change=5.0),
            _row("tether", "USDT", cap=9_000, change=0.0),
        ]
        board = hm._build_board(rows, details)

        assert [c["symbol"] for c in board["coins"]] == ["BTC"]
        assert board["excluded_pegged"] == 1
        assert board["total_market_cap"] == 1_000, "A hidden asset must not inflate the total"
        assert board["weighted_change_24h"] == 5.0, (
            "USDT's flat 0% would drag the board move to +0.5% if it were counted"
        )
        assert all(s["sector"] != "Stablecoin" for s in board["sectors"])

    def test_pegged_assets_come_back_when_asked_for(self):
        details = {"tether": {"sector": "Stablecoin", "peg_type": hm.PEG_STABLECOIN}}
        board = hm._build_board([_row("tether", "USDT")], details, include_pegged=True)
        assert [c["symbol"] for c in board["coins"]] == ["USDT"]
        assert board["excluded_pegged"] == 0

    def test_unresolved_coins_are_counted_and_kept_out_of_real_sectors(self):
        board = hm._build_board(
            [_row("known", "KNW"), _row("pending", "PND")],
            {"known": {"sector": "DeFi"}},
        )
        assert board["unresolved_count"] == 1
        labels = {s["sector"] for s in board["sectors"]}
        assert hm.UNCLASSIFIED_SECTOR in labels, (
            "A coin awaiting classification must say so rather than being filed "
            "under 'Other', which is a classification"
        )

    def test_limit_trims_after_pegged_assets_are_removed(self):
        details = {"tether": {"peg_type": hm.PEG_STABLECOIN}}
        rows = [
            _row("tether", "USDT", cap=9_000),
            _row("bitcoin", "BTC", cap=8_000),
            _row("ethereum", "ETH", cap=7_000),
        ]
        board = hm._build_board(rows, details, limit=2)
        assert [c["symbol"] for c in board["coins"]] == ["BTC", "ETH"], (
            "A hidden asset must not consume one of the requested slots"
        )

    def test_the_timestamp_carries_a_timezone(self):
        board = hm._build_board([_row("bitcoin", "BTC")], {})
        assert board["timestamp"].endswith("+00:00"), (
            "A naive timestamp leaves the client unable to tell how old the board is"
        )


class TestRefreshTargets:
    def test_unresolved_coins_come_before_stale_ones(self):
        now = 1_000_000.0
        stored = {"old": {"fetched_at": now - hm.METRICS_TTL_SECONDS - 1}}
        sectors = {"old": {"fetched_at": now}}
        targets = hm._select_refresh_targets(
            ["old", "fresh_unknown"], stored, sectors, now=now, limit=2
        )
        assert targets[0] == "fresh_unknown", "A coin showing no score at all goes first"

    def test_the_stalest_reading_is_renewed_first(self):
        now = 1_000_000.0
        stale = now - hm.METRICS_TTL_SECONDS - 1
        stored = {"a": {"fetched_at": stale - 500}, "b": {"fetched_at": stale - 5_000}}
        sectors = {"a": {"fetched_at": now}, "b": {"fetched_at": now}}
        targets = hm._select_refresh_targets(["a", "b"], stored, sectors, now=now, limit=2)
        assert targets == ["b", "a"]

    def test_fresh_coins_are_left_alone(self):
        now = 1_000_000.0
        stored = {"a": {"fetched_at": now - 10}}
        sectors = {"a": {"fetched_at": now - 10}}
        assert hm._select_refresh_targets(["a"], stored, sectors, now=now, limit=4) == []

    def test_a_failing_coin_is_skipped_while_it_backs_off(self):
        """
        The starvation defect.

        Only a 200 used to write anything back, so four permanently-404ing ids
        stayed "unresolved" forever, sat at the front of every round, and no
        other coin on the board ever got its turn.
        """
        now = 1_000_000.0
        stored = {"broken": {"failed_at": now - 60, "failure_count": 1}}
        targets = hm._select_refresh_targets(["broken", "ok"], stored, {}, now=now, limit=4)
        assert targets == ["ok"], "A coin inside its retry window must not hold a slot"

    def test_backoff_expires_and_the_coin_is_retried(self):
        now = 1_000_000.0
        stored = {"broken": {"failed_at": now - hm.FAILURE_BACKOFF_BASE_SECONDS - 1}}
        targets = hm._select_refresh_targets(["broken"], stored, {}, now=now, limit=4)
        assert targets == ["broken"]

    def test_backoff_doubles_with_each_failure(self):
        now = 1_000_000.0
        elapsed = hm.FAILURE_BACKOFF_BASE_SECONDS * 1.5
        once = {"failed_at": now - elapsed, "failure_count": 1}
        twice = {"failed_at": now - elapsed, "failure_count": 2}
        assert not hm._in_backoff(once, now), "One failure backs off for the base delay"
        assert hm._in_backoff(twice, now), "Two failures back off for twice as long"

    def test_backoff_is_capped(self):
        now = 1_000_000.0
        entry = {"failed_at": now - hm.FAILURE_BACKOFF_MAX_SECONDS - 1, "failure_count": 40}
        assert not hm._in_backoff(entry, now), (
            "The doubling must stop somewhere or a coin is retired permanently"
        )

    def test_a_success_clears_the_failure_state(self):
        entry = hm._record_failure({"failure_count": 2})
        assert entry["failure_count"] == 3
        rescored = hm._score_developer({"developer_data": {"stars": 1}})
        assert "failed_at" not in rescored, "A fresh score replaces the failure record"

    def test_targets_are_capped_at_the_request_budget(self):
        now = 1_000_000.0
        coin_ids = [f"coin{i}" for i in range(20)]
        targets = hm._select_refresh_targets(coin_ids, {}, {}, now=now, limit=4)
        assert len(targets) == 4, "The rotation may not outspend its rate-limit budget"

    def test_scores_from_an_older_formula_are_treated_as_unresolved(self):
        stored = hm._valid_scores(
            {"a": {"fetched_at": time.time(), "score_version": 1, "developer_score": 100}}
        )
        assert "developer_score" not in stored.get("a", {}), (
            "A score from a superseded formula must be recomputed, not served"
        )

    def test_failure_state_survives_a_formula_version_bump(self):
        stored = hm._valid_scores(
            {"a": {"score_version": 1, "failed_at": 123.0, "failure_count": 3}}
        )
        assert stored["a"]["failure_count"] == 3, (
            "Otherwise every version bump gives broken ids a fresh round of retries"
        )


class TestStoredDetailMigration:
    def test_a_legacy_sector_string_is_read_as_an_undated_entry(self):
        """Sectors used to be stored as a bare string with no timestamp."""
        migrated = hm._normalise_sectors({"tether": "Stablecoin"})
        assert migrated["tether"]["sector"] == "Stablecoin"
        assert migrated["tether"]["fetched_at"] is None, (
            "An undated entry is what marks it for re-resolution"
        )

    def test_a_legacy_entry_still_gets_its_peg_recognised(self):
        """
        The migration gap: entries written before peg classification existed
        carry no `peg_type`, and trusting that absence put USDT and USDC back
        among the largest tiles on the board, each reading a flat 0.00%.
        """
        sectors = hm._normalise_sectors({"tether": "Stablecoin"})
        details = hm._merge_details(["tether"], sectors, {}, {"tether": "USDT"})
        assert details["tether"]["peg_type"] == hm.PEG_STABLECOIN

    def test_a_current_entry_saying_no_peg_is_believed(self):
        sectors = {"weth-lookalike": {"sector": "DeFi", "peg_type": None, "fetched_at": 1.0}}
        details = hm._merge_details(["weth-lookalike"], sectors, {}, {"weth-lookalike": "WETH"})
        assert details["weth-lookalike"]["peg_type"] is None, (
            "A resolved verdict must win over the symbol lookalike fallback"
        )

    def test_a_legacy_entry_is_queued_for_re_resolution(self):
        now = 1_000_000.0
        sectors = hm._normalise_sectors({"tether": "Stablecoin"})
        assert hm._select_refresh_targets(["tether"], {}, sectors, now=now, limit=4) == [
            "tether"
        ], "An undated sector has no TTL of its own and must be renewed"


class TestReadPath:
    async def test_a_cached_board_is_served_without_touching_the_network(self, monkeypatch):
        async def explode():
            raise AssertionError("upstream must not be called on a cache hit")

        hm._store_coins(hm._build_coins([_row("bitcoin", "BTC")], {}))
        monkeypatch.setattr(hm, "_build_fresh_coins", explode)

        board = await hm.fetch_heatmap_data()
        assert [c["symbol"] for c in board["coins"]] == ["BTC"]
        assert board["stale"] is False

    async def test_a_failed_refresh_falls_back_to_the_last_good_board(self, monkeypatch):
        """
        The board used to be thrown away wholesale on any upstream error.

        `_get_fallback_heatmap_data()` returned an empty grid with a 200 even
        when a six-minute-old, perfectly good board was sitting in the cache.
        """
        from services.cache import market_cache

        hm._store_coins(hm._build_coins([_row("bitcoin", "BTC")], {}))
        market_cache.invalidate(hm.HEATMAP_CACHE_KEY)  # expire the TTL, keep the fallback

        async def fail():
            raise RuntimeError("CoinGecko is down")

        monkeypatch.setattr(hm, "_build_fresh_coins", fail)

        board = await hm.fetch_heatmap_data()
        assert board is not None, "A recent board beats an error page"
        assert [c["symbol"] for c in board["coins"]] == ["BTC"]
        assert board["stale"] is True, "The client must be able to say the board is old"
        assert board["age_seconds"] is not None

    async def test_a_board_past_the_stale_ceiling_is_not_passed_off_as_current(self, monkeypatch):
        from services.cache import market_cache

        hm._store_coins(hm._build_coins([_row("bitcoin", "BTC")], {}))
        market_cache.invalidate(hm.HEATMAP_CACHE_KEY)
        # Backdate the fallback past the ceiling.
        value, _ = market_cache._fallback[hm.HEATMAP_CACHE_KEY]
        market_cache._fallback[hm.HEATMAP_CACHE_KEY] = (
            value,
            time.time() - hm.HEATMAP_STALE_MAX_AGE_SECONDS - 60,
        )

        async def fail():
            raise RuntimeError("CoinGecko is down")

        monkeypatch.setattr(hm, "_build_fresh_coins", fail)
        assert await hm.fetch_heatmap_data() is None, (
            "An hour-old board is no longer a picture of the current market"
        )

    async def test_a_cold_cache_and_a_failed_fetch_report_unavailable(self, monkeypatch):
        async def fail():
            raise RuntimeError("CoinGecko is down")

        monkeypatch.setattr(hm, "_build_fresh_coins", fail)
        assert await hm.fetch_heatmap_data() is None, (
            "An empty board served with a 200 is indistinguishable from a market "
            "where nothing is listed"
        )

    async def test_a_cold_cache_builds_and_stores_the_board(self, monkeypatch):
        async def build():
            return hm._build_coins([_row("bitcoin", "BTC")], {})

        monkeypatch.setattr(hm, "_build_fresh_coins", build)

        board = await hm.fetch_heatmap_data()
        assert [c["symbol"] for c in board["coins"]] == ["BTC"]

        from services.cache import market_cache

        assert market_cache.get(hm.HEATMAP_CACHE_KEY) is not None, "The build must be cached"


class TestSingleFlight:
    async def test_concurrent_cold_readers_issue_one_upstream_fetch(self, monkeypatch):
        """
        Without a lock, N simultaneous readers each ran the full refresh against
        the same rate-limited endpoint and each rewrote the same disk stores.
        """
        calls = []

        async def build():
            calls.append(1)
            await asyncio.sleep(0.01)
            return hm._build_coins([_row("bitcoin", "BTC")], {})

        monkeypatch.setattr(hm, "_build_fresh_coins", build)

        boards = await asyncio.gather(*(hm.fetch_heatmap_data() for _ in range(5)))
        assert len(calls) == 1, f"Expected one upstream fetch, got {len(calls)}"
        assert all(b is not None for b in boards), "Every caller still gets a board"


class TestSectorBreadthCompatibility:
    def test_the_weighted_sector_list_is_read_directly(self):
        from services.analysis_data import _sector_breadth

        rows = _sector_breadth(
            {
                "sectors": [
                    {"sector": "DeFi", "coin_count": 2, "weighted_change_24h": 0.1},
                    {"sector": "Meme", "coin_count": 3, "weighted_change_24h": 4.2},
                ]
            }
        )
        assert rows[0]["sector"] == "Meme", "Strongest sector first"
        assert rows[0]["avg_change_24h"] == 4.2
        assert all(r["weighted"] for r in rows)

    def test_the_legacy_mapping_shape_still_renders(self):
        """A payload cached before the change must not break the report."""
        from services.analysis_data import _sector_breadth

        rows = _sector_breadth(
            {"sectors": {"L1": [{"price_change_24h": 2.0}, {"price_change_24h": 4.0}]}}
        )
        assert rows == [{"sector": "L1", "coin_count": 2, "avg_change_24h": 3.0, "weighted": False}]
