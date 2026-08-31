"""
The map's two lookup tables, and the claim each of them is allowed to make.

The whole map exists under one constraint: Polymarket publishes no trader
locations, so "where the money came from" cannot be drawn. These tests pin the
substitutes to what they can actually support — a country recognised in a
question is a fact about the question, and a jurisdiction tier is a fact about
the rules, and neither is a fact about a bettor.
"""

import pytest

from services.polymarket.geography import CENTROIDS, countries_in
from services.polymarket.jurisdictions import (
    JURISDICTIONS,
    TIER_BLOCKED,
    TIER_CLOSE_ONLY,
    TIER_DETAIL,
    TIER_FRONTEND_ONLY,
    TIER_LABEL,
    as_layer,
)


class TestCountryDetection:
    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            ("NATO x Russia military clash by August 31, 2026?", "Russia"),
            ("US announces end of Iranian blockade by August 31, 2026?", "Iran"),
            ("Will China invade Taiwan by end of 2026?", "Taiwan"),
            ("Will Belete Molla be the next Prime Minister of Ethiopia?", "Ethiopia"),
        ],
    )
    def test_a_country_is_found_by_name_or_demonym(self, question, expected):
        """Market questions use demonyms freely: "Iranian blockade" is Iran."""
        assert expected in countries_in(question)

    def test_a_country_name_inside_another_word_does_not_count(self):
        """Substring matching would put Chad in "Chadwick" and Oman in "Romania"."""
        assert countries_in("Will Chadwick Boseman's estate settle?") == []

    def test_a_word_that_usually_means_something_else_is_not_a_country(self):
        """
        "Georgia" is a US state far more often than the country in these
        markets, and "Jordan" is usually a basketball player. Both reach the map
        only through unambiguous aliases.
        """
        assert countries_in("Will the Georgia Bulldogs win the title?") == []
        assert countries_in("Will Jordan return to coaching?") == []

    def test_a_market_about_nothing_geographic_names_no_country(self):
        assert countries_in("Will Bitcoin reach $150,000 by the end of 2026?") == []

    def test_an_empty_question_does_not_raise(self):
        assert countries_in("", "") == []


class TestCentroids:
    def test_every_centroid_is_on_the_globe(self):
        """
        Russia and Fiji straddle the antimeridian, and averaging their outlines
        puts Russia in Alaska. Both are hand-set; this is what catches a
        regeneration that drops the override.
        """
        for name, (lon, lat) in CENTROIDS.items():
            assert -180 <= lon <= 180, f"{name} centroid is off the map"
            assert -90 <= lat <= 90, f"{name} centroid is off the map"

    def test_russia_is_in_asia_and_not_in_alaska(self):
        lon, lat = CENTROIDS["Russia"]

        assert 30 < lon < 150
        assert 40 < lat < 75

    def test_every_country_a_question_can_name_can_be_drawn(self):
        """
        A country the detector recognises but the map cannot place is a bubble
        nobody ever sees, which is worse than not detecting it.
        """
        for name in countries_in("Russia Iran China Taiwan Ethiopia Brazil Turkey"):
            assert name in CENTROIDS


class TestJurisdictions:
    def test_every_tier_is_one_of_the_three_published_groups(self):
        allowed = {TIER_BLOCKED, TIER_CLOSE_ONLY, TIER_FRONTEND_ONLY}

        assert {j.tier for j in JURISDICTIONS} <= allowed
        assert set(TIER_LABEL) == allowed
        assert set(TIER_DETAIL) == allowed

    def test_a_partial_restriction_names_the_regions_it_applies_to(self):
        """
        Four Canadian provinces are close-only and the rest of Canada is not.
        Painting the whole country would state something false about the rest.
        """
        partial = [j for j in JURISDICTIONS if j.partial]

        assert partial, "the table should still carry Canada and Ukraine"
        for j in partial:
            assert j.regions, f"{j.name} is partial but names no regions"
            assert j.note, f"{j.name} is partial but does not say so in words"

    def test_close_only_is_not_reported_as_blocked(self):
        """
        Collapsing the tiers into a binary turns a regulatory nuance into a
        prohibition. The United States can still close positions.
        """
        united_states = next(j for j in JURISDICTIONS if j.code == "US")

        assert united_states.tier == TIER_CLOSE_ONLY

    def test_the_layer_carries_its_own_provenance_and_age(self):
        """
        There is nothing to poll — Polymarket's live geoblock endpoint reports
        the caller's own IP — so the list is transcribed, and the reader has to
        be able to see how old it is.
        """
        layer = as_layer()

        assert layer["provenance"] == "measured"
        assert layer["retrieved"]
        assert layer["source_url"].startswith("https://")
        assert len(layer["countries"]) == len(JURISDICTIONS)
