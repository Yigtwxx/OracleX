"""
The registry is edited by hand, so a bad row must be dropped rather than
trusted. A malformed venue that reached the board would render as a bar with a
blank label, which is indistinguishable from a real venue whose name we failed
to resolve — the two must not be confusable.
"""

import json

import pytest

from services import dex_perps_registry as reg


@pytest.fixture(autouse=True)
def _clear_cache():
    reg.load_venues.cache_clear()
    yield
    reg.load_venues.cache_clear()


def _write(tmp_path, monkeypatch, payload):
    path = tmp_path / "dex_perp_venues.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(reg, "DEX_PERP_VENUES_FILE", str(path))


class TestLoading:
    def test_reads_the_shipped_registry(self):
        venues = reg.load_venues()
        assert len(venues) >= 20
        slugs = {v.slug for v in venues}
        assert "hyperliquid" in slugs

    def test_indexes_every_alias_of_a_venue(self, tmp_path, monkeypatch):
        _write(
            tmp_path,
            monkeypatch,
            {
                "venues": [
                    {
                        "slug": "gmx",
                        "name": "GMX",
                        "llama_oi": ["GMX V2 Perps", "GMX V1 Perps"],
                        "llama_tvl": ["GMX V2 Perps"],
                        "coingecko_ids": ["gmx-a", "gmx-b"],
                    }
                ]
            },
        )
        oi = reg.by_llama_oi_name()
        assert oi["GMX V2 Perps"].slug == "gmx"
        assert oi["GMX V1 Perps"].slug == "gmx"
        assert set(reg.by_coingecko_id()) == {"gmx-a", "gmx-b"}
        assert set(reg.by_llama_tvl_name()) == {"GMX V2 Perps"}

    def test_a_venue_with_no_coingecko_id_still_loads(self, tmp_path, monkeypatch):
        # Jupiter and Reya are on DefiLlama and not on CoinGecko. They belong in
        # the OI and TVL panels and simply have no volume bar.
        _write(
            tmp_path,
            monkeypatch,
            {
                "venues": [
                    {
                        "slug": "jupiter",
                        "name": "Jupiter",
                        "llama_oi": ["Jupiter Perpetual Exchange"],
                    }
                ]
            },
        )
        (venue,) = reg.load_venues()
        assert venue.coingecko_ids == ()
        assert venue.llama_tvl == ()


class TestBadRows:
    @pytest.mark.parametrize(
        "row",
        [
            {"name": "No slug"},
            {"slug": "no-name"},
            {"slug": "", "name": "Empty slug"},
            "not a dict",
        ],
    )
    def test_unusable_rows_are_dropped(self, tmp_path, monkeypatch, row):
        _write(tmp_path, monkeypatch, {"venues": [row]})
        assert reg.load_venues() == ()

    def test_duplicate_slug_keeps_the_first(self, tmp_path, monkeypatch):
        _write(
            tmp_path,
            monkeypatch,
            {
                "venues": [
                    {"slug": "dup", "name": "First"},
                    {"slug": "dup", "name": "Second"},
                ]
            },
        )
        (venue,) = reg.load_venues()
        assert venue.name == "First"

    def test_missing_file_is_empty_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(reg, "DEX_PERP_VENUES_FILE", str(tmp_path / "absent.json"))
        assert reg.load_venues() == ()
