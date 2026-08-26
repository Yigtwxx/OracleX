"""
The country table: what it guarantees, and what it refuses to guarantee.

The file exists because `services/polymarket/geography.py` cannot do this job —
its patterns read "South Sudan" as Sudan and "Equatorial Guinea" as Guinea, and
they cannot name Georgia, Jordan or Chad at all. Three of those are the wrong
country rather than a miss, so identity is hand-written here and the loader's
whole responsibility is refusing to admit a half-written row.

The last test reads the shipped seed. It is the one that will fail on a bad edit.
"""

import json

import pytest

from services.elections.registry import (
    REGISTRY_PATH,
    UNKNOWN_COUNTRY,
    load_registry,
)


@pytest.fixture
def seed(tmp_path):
    """Write a registry file and load it."""

    def write(payload: dict):
        path = tmp_path / "elections.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return load_registry(path)

    return write


# ==========================================
# IDENTITY
# ==========================================


def test_a_country_with_no_tickers_is_still_listed():
    """Most of the world is identity-only, and identity is the point of the file."""
    registry = load_registry()

    entry = registry.get("Uganda")
    assert entry.flag == "🇺🇬"
    assert entry.tickers == ()
    assert entry.tier is None


def test_an_unlisted_country_gets_a_blank_entry_rather_than_a_key_error():
    registry = load_registry()

    assert registry.get("Wakanda") is UNKNOWN_COUNTRY
    assert UNKNOWN_COUNTRY.flag == "🏳️"
    assert UNKNOWN_COUNTRY.tickers == ()


def test_a_row_without_a_flag_is_dropped(seed):
    """Identity is the one thing this file exists to supply."""
    registry = seed({"Nowhere": {"iso2": "NW"}})

    assert registry.entries == {}


def test_a_row_with_a_malformed_iso2_is_dropped(seed):
    registry = seed({"Nowhere": {"iso2": "nowhere", "flag": "🏳️"}})

    assert registry.entries == {}


def test_a_partially_recognised_state_may_carry_no_iso2(seed):
    """Somaliland, Transnistria and South Ossetia all sit like this."""
    registry = seed({"Somaliland": {"iso2": None, "flag": "🏳️"}})

    assert registry.get("Somaliland").iso2 is None
    assert registry.get("Somaliland").flag == "🏳️"


def test_the_files_own_documentation_is_not_a_country(seed):
    registry = seed({"_readme": ["not a row"], "Uganda": {"iso2": "UG", "flag": "🇺🇬"}})

    assert list(registry.entries) == ["Uganda"]


# ==========================================
# MARKET RELEVANCE
# ==========================================


def test_an_unknown_tier_leaves_the_country_untracked_rather_than_dropped(seed):
    registry = seed({"Nowhere": {"iso2": "NW", "flag": "🏳️", "tier": "critical"}})

    assert registry.get("Nowhere").tier is None
    assert registry.get("Nowhere").flag == "🏳️"


def test_an_alias_short_enough_to_mean_something_else_is_rejected(seed):
    """ "us", "in" and "no" are all ISO codes and all English words."""
    registry = seed({"Nowhere": {"iso2": "NW", "flag": "🏳️", "aliases": ["us", "nowherian"]}})

    assert registry.get("Nowhere").aliases == ("nowherian",)


def test_aliases_are_lowercased_so_the_match_does_not_depend_on_the_seed(seed):
    registry = seed({"Nowhere": {"iso2": "NW", "flag": "🏳️", "aliases": ["  Nowherian "]}})

    assert registry.get("Nowhere").aliases == ("nowherian",)


def test_the_alias_index_carries_only_countries_that_have_any(seed):
    registry = seed(
        {
            "Georgia": {"iso2": "GE", "flag": "🇬🇪", "aliases": ["georgian dream"]},
            "Uganda": {"iso2": "UG", "flag": "🇺🇬"},
        }
    )

    assert registry.alias_index() == {"Georgia": ("georgian dream",)}


# ==========================================
# REFUSAL
# ==========================================


def test_an_unreadable_file_yields_an_empty_registry_not_an_exception(tmp_path):
    """A seed that will not parse costs the board its flags, not its dates."""
    registry = load_registry(tmp_path / "does-not-exist.json")

    assert registry.entries == {}
    assert registry.get("Brazil") is UNKNOWN_COUNTRY


def test_a_file_that_is_not_an_object_yields_an_empty_registry(tmp_path):
    path = tmp_path / "elections.json"
    path.write_text("[]", encoding="utf-8")

    assert load_registry(path).entries == {}


# ==========================================
# THE SHIPPED SEED
# ==========================================


def test_the_shipped_seed_parses_and_every_row_carries_identity():
    registry = load_registry()

    assert len(registry.entries) > 150
    assert all(entry.flag for entry in registry.entries.values())
    assert all(name == name.strip() for name in registry.entries)


def test_the_shipped_seed_names_the_countries_geography_cannot():
    """
    The three countries in `geography.AMBIGUOUS` with no aliases of their own,
    for which `countries_in` compiles no pattern at all. Without a row here they
    would be unmatchable and flagless.
    """
    registry = load_registry()

    for country in ("Georgia", "Jordan", "Chad"):
        assert registry.get(country).aliases, country


def test_the_shipped_seed_separates_south_sudan_from_sudan():
    """`countries_in("South Sudan general election")` answers "Sudan"."""
    registry = load_registry()

    assert registry.get("South Sudan").iso2 == "SS"
    assert registry.get("Sudan").iso2 == "SD"


def test_every_tracked_row_records_when_it_was_last_reviewed():
    """A ticker mapping rots silently; a date on the claim is what makes it visible."""
    registry = load_registry()

    unreviewed = [
        name for name, entry in registry.entries.items() if entry.tickers and not entry.reviewed
    ]
    assert unreviewed == []


def test_the_seed_on_disk_is_where_the_loader_looks():
    assert REGISTRY_PATH.exists()
