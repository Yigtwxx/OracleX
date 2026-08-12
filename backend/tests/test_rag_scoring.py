"""
Retrieved history must be ranked by what mattered, not by what is nearby.

These pin down the scoring that replaced `similarity = 1 / (1 + distance)`. Two
of them are the reason the change exists at all:

`test_off_topic_sentence_is_rejected` uses a distance measured against the live
embedding model — an off-topic English sentence versus a Bitcoin event. Under
the old formula it scored 0.316, clearing the 0.30 threshold three call sites
used; its true cosine is negative.

`test_contradicted_headline_outranks_consistent_one` is the SEC-v-Ripple case:
a bearish headline whose durable outcome was bullish must rank *above* an
equally similar precedent that did what its headline implied. That precedent is
the only thing that stops a model concluding "lawsuit, therefore down".
"""

from datetime import datetime, timedelta, UTC

import pytest

from config import settings
from services import rag_scoring as scoring

# Distances measured against all-MiniLM-L6-v2 with Chroma's default (squared L2)
# space. The model normalises its output, so cosine == 1 - distance / 2.
DISTANCE_ON_TOPIC = 1.5309  # "ETF rejected by the SEC" vs "Bitcoin Halving 2024"
DISTANCE_OFF_TOPIC = 2.1679  # "How do I bake sourdough bread at home?" vs the same


def _results(rows):
    """A Chroma query response in the nested shape the client returns."""
    return {
        "ids": [[row["id"] for row in rows]],
        "metadatas": [[row.get("metadata", {}) for row in rows]],
        "distances": [[row.get("distance", 1.0) for row in rows]],
    }


class TestRelevanceFromDistance:
    def test_identical_vectors_score_one(self):
        assert scoring.relevance_from_distance(0.0) == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self):
        assert scoring.relevance_from_distance(2.0) == pytest.approx(0.0)

    def test_on_topic_distance_matches_measured_cosine(self):
        assert scoring.relevance_from_distance(DISTANCE_ON_TOPIC) == pytest.approx(0.2346, abs=1e-3)

    def test_off_topic_sentence_is_rejected(self):
        # The old 1/(1+d) mapping gave this 0.316 — above three call sites'
        # thresholds. A negative cosine clamps to zero and is dropped.
        relevance = scoring.relevance_from_distance(DISTANCE_OFF_TOPIC)
        assert relevance == 0.0
        assert relevance < settings.RAG_MIN_RELEVANCE

    def test_on_topic_beats_off_topic_by_a_usable_margin(self):
        on = scoring.relevance_from_distance(DISTANCE_ON_TOPIC)
        off = scoring.relevance_from_distance(DISTANCE_OFF_TOPIC)
        # Under the old mapping the gap was 0.08; a threshold could not sit in it.
        assert on - off > 0.2

    def test_is_monotonically_decreasing(self):
        scores = [scoring.relevance_from_distance(d / 10) for d in range(0, 21)]
        assert scores == sorted(scores, reverse=True)

    def test_missing_distance_is_not_relevant(self):
        assert scoring.relevance_from_distance(None) == 0.0


class TestRecencyWeight:
    def test_half_life_halves_the_weight(self):
        now = datetime(2026, 7, 24)
        weight = scoring.recency_weight(now - timedelta(days=90), half_life_days=90, now=now)
        assert weight == pytest.approx(0.5)

    def test_never_decays_past_the_floor(self):
        now = datetime(2026, 7, 24)
        weight = scoring.recency_weight(datetime(2010, 1, 1), half_life_days=90, now=now)
        assert weight == pytest.approx(settings.RAG_RECENCY_FLOOR)

    def test_old_structural_event_keeps_usable_weight(self):
        # The 2020 halving is old and still the best precedent for a halving
        # question — the events half-life plus the floor must preserve that.
        now = datetime(2026, 7, 24)
        weight = scoring.recency_weight(
            datetime(2020, 5, 11),
            half_life_days=settings.RAG_RECENCY_HALF_LIFE_EVENTS_DAYS,
            now=now,
        )
        assert weight >= settings.RAG_RECENCY_FLOOR

    def test_future_dates_count_as_current(self):
        now = datetime(2026, 7, 24)
        assert scoring.recency_weight(now + timedelta(days=5), half_life_days=90, now=now) == 1.0

    def test_unknown_date_is_neutral(self):
        assert scoring.recency_weight(None, half_life_days=90) == scoring.NEUTRAL


class TestMagnitudeWeight:
    def test_no_move_scores_zero(self):
        assert scoring.magnitude_weight(0.0) == pytest.approx(0.0)

    def test_unmeasured_move_is_neutral_not_zero(self):
        # "We could not fetch the candles" is a different claim from
        # "nothing happened", and must not be scored as the latter.
        assert scoring.magnitude_weight(None) == scoring.NEUTRAL

    def test_is_monotonically_increasing(self):
        weights = [scoring.magnitude_weight(pct) for pct in range(0, 60, 5)]
        assert weights == sorted(weights)

    def test_saturates_so_size_alone_cannot_dominate(self):
        # The point of the curve: past ~20% the extra move buys almost nothing,
        # so a once-in-a-decade collapse does not outrank every other factor.
        assert scoring.magnitude_weight(20.0) > 0.95
        assert scoring.magnitude_weight(200.0) - scoring.magnitude_weight(20.0) < 0.05
        assert scoring.magnitude_weight(500.0) <= 1.0

    def test_direction_does_not_matter(self):
        assert scoring.magnitude_weight(-12.0) == pytest.approx(scoring.magnitude_weight(12.0))


class TestClassWeight:
    def test_regulatory_outranks_a_price_milestone(self):
        assert scoring.class_weight("regulatory") > scoring.class_weight("price_milestone")

    def test_unknown_type_gets_the_default(self):
        assert scoring.class_weight("something_new") == scoring.DEFAULT_CLASS_PRIOR

    def test_missing_type_gets_the_default(self):
        assert scoring.class_weight(None) == scoring.DEFAULT_CLASS_PRIOR

    def test_is_case_insensitive(self):
        assert scoring.class_weight("REGULATORY") == scoring.class_weight("regulatory")

    @pytest.mark.parametrize("sentiment", ["bullish", "bearish", "neutral"])
    def test_sentiment_labels_do_not_collide_with_event_classes(self, sentiment):
        # Two services store a news item's sentiment in the field events use for
        # their type, so these strings do reach this table. They must fall
        # through rather than be read as a class of event.
        assert scoring.class_weight(sentiment) == scoring.DEFAULT_CLASS_PRIOR


class TestSymbolWeight:
    def test_exact_match_is_full_weight(self):
        assert scoring.symbol_weight("BTC", "BTC") == scoring.SYMBOL_EXACT

    def test_no_query_symbol_admits_everything(self):
        assert scoring.symbol_weight("BTC", None) == scoring.SYMBOL_EXACT

    def test_unattributed_item_is_discounted_not_dropped(self):
        # `auto_index_recent_news` stores an empty symbol for every item it
        # indexes, so this is the common case, not an edge case.
        assert scoring.symbol_weight("", "BTC") == scoring.SYMBOL_UNATTRIBUTED

    def test_bellwether_precedent_spills_over_to_a_smaller_asset(self):
        weight = scoring.symbol_weight("XRP", "PEPE")
        assert weight == scoring.SYMBOL_SPILLOVER
        assert weight > scoring.SYMBOL_MISMATCH

    def test_semiconductors_share_a_bloc(self):
        assert scoring.symbol_weight("NVDA", "INTC") == scoring.SYMBOL_SAME_BLOC

    def test_two_unrelated_small_assets_barely_apply(self):
        assert scoring.symbol_weight("PEPE", "SHIB") == scoring.SYMBOL_MISMATCH

    def test_weights_are_ordered_by_how_much_the_precedent_applies(self):
        assert (
            scoring.SYMBOL_EXACT
            > scoring.SYMBOL_SPILLOVER
            > scoring.SYMBOL_SAME_BLOC
            > scoring.SYMBOL_UNATTRIBUTED
            > scoring.SYMBOL_MISMATCH
        )

    def test_exchange_qualified_pairs_match_bare_tickers(self):
        assert scoring.symbol_weight("BINANCE:BTCUSDT", "BTC") == scoring.SYMBOL_EXACT


class TestSurpriseBoost:
    def test_contradicted_headline_is_promoted(self):
        assert scoring.surprise_boost("bearish", "bullish") == settings.RAG_SURPRISE_BOOST

    def test_diverging_horizons_get_the_smaller_boost(self):
        assert (
            scoring.surprise_boost("bearish", "bearish", inverted=True)
            == settings.RAG_INVERSION_BOOST
        )

    def test_consistent_precedent_is_not_boosted(self):
        assert scoring.surprise_boost("bullish", "bullish") == 1.0

    def test_a_neutral_outcome_is_not_a_contradiction(self):
        assert scoring.surprise_boost("bearish", "neutral") == 1.0

    def test_unknown_direction_is_not_a_contradiction(self):
        assert scoring.surprise_boost("bearish", None) == 1.0
        assert scoring.surprise_boost(None, "bullish") == 1.0


class TestIsSurprising:
    def test_opposite_directions_are_a_contradiction(self):
        assert scoring.is_surprising("bearish", "bullish") is True
        assert scoring.is_surprising("bullish", "bearish") is True

    def test_agreeing_directions_are_not(self):
        assert scoring.is_surprising("bearish", "bearish") is False

    def test_a_neutral_outcome_contradicts_nothing(self):
        assert scoring.is_surprising("bearish", "neutral") is False

    def test_missing_either_side_is_not_a_contradiction(self):
        assert scoring.is_surprising("bearish", None) is False
        assert scoring.is_surprising(None, "bullish") is False
        assert scoring.is_surprising("", "") is False

    def test_survives_the_boost_being_switched_off(self, monkeypatch):
        # Setting the boost to 1.0 is the way to disable the promotion. Deriving
        # "surprised" from the multiplier instead of the directions made every
        # item satisfy `surprise >= boost` under that setting, which would have
        # stamped a contradiction onto all 34 catalogue events at once.
        monkeypatch.setattr(settings, "RAG_SURPRISE_BOOST", 1.0)

        consistent = scoring.item_from_metadata(
            "e1",
            {
                "date": "2024-01-11",
                "symbol": "BTC",
                "apparent_sentiment": "bullish",
                "durable_direction": "bullish",
            },
            1.0,
            scoring.SOURCE_EVENT,
        )
        scored = scoring.score_item(consistent, now=datetime(2026, 7, 24))
        assert scored.surprise == 1.0
        assert scored.surprised is False


class TestHorizonsFromMetadata:
    def test_reads_every_horizon(self):
        horizons = scoring.horizons_from_metadata(
            {"price_change_1d": -17.0, "price_change_365d": 30.7, "symbol": "NVDA"}
        )
        assert horizons == {1: -17.0, 365: 30.7}

    def test_ignores_similarly_named_keys(self):
        # v1 news rows carry `price_change_percent`; it is not a horizon.
        assert scoring.horizons_from_metadata({"price_change_percent": -8.5}) == {}

    def test_skips_a_malformed_key_instead_of_raising(self):
        # Metadata outlives any one version of this code, so a key that looks
        # like a horizon but carries no number must not take retrieval down.
        horizons = scoring.horizons_from_metadata(
            {"price_change_sincelaunchd": 4.0, "price_change_7d": 1.5}
        )
        assert horizons == {7: 1.5}

    def test_skips_non_numeric_values(self):
        assert scoring.horizons_from_metadata({"price_change_7d": "n/a"}) == {}

    def test_empty_metadata_is_empty(self):
        assert scoring.horizons_from_metadata({}) == {}
        assert scoring.horizons_from_metadata(None) == {}


class TestLongestHorizon:
    def test_returns_the_furthest_measured_move(self):
        value = scoring.longest_horizon(
            {"price_change_1d": -17.0, "price_change_90d": -22.2, "price_change_365d": 30.7}
        )
        assert value == pytest.approx(30.7)

    def test_unmeasured_event_has_none(self):
        assert scoring.longest_horizon({"symbol": "BTC"}) is None


class TestDirectionFromPct:
    def test_small_moves_are_not_a_direction(self):
        assert scoring.direction_from_pct(0.4) == scoring.NEUTRAL_DIRECTION

    def test_reads_the_sign_of_a_real_move(self):
        assert scoring.direction_from_pct(12.0) == scoring.BULLISH
        assert scoring.direction_from_pct(-12.0) == scoring.BEARISH

    def test_unknown_move_has_no_direction(self):
        assert scoring.direction_from_pct(None) is None


class TestParseDate:
    def test_reads_a_plain_date(self):
        assert scoring.parse_date("2024-04-20") == datetime(2024, 4, 20)

    def test_reads_an_iso_timestamp(self):
        assert scoring.parse_date("2024-04-20T10:33:00.123456") == datetime(
            2024, 4, 20, 10, 33, 0, 123456
        )

    def test_flattens_timezone_aware_values(self):
        # Stored dates are naive; mixing the two raises on subtraction.
        parsed = scoring.parse_date(datetime(2024, 4, 20, tzinfo=UTC))
        assert parsed is not None and parsed.tzinfo is None

    def test_unparseable_values_are_none(self):
        assert scoring.parse_date("not a date") is None
        assert scoring.parse_date("") is None
        assert scoring.parse_date(None) is None


class TestItemFromMetadata:
    def test_news_sentiment_is_read_as_tone_not_as_an_event_class(self):
        item = scoring.item_from_metadata(
            "n1",
            {"title": "SEC sues someone", "sentiment": "bearish", "symbol": "XRP"},
            1.0,
            scoring.SOURCE_NEWS,
        )
        assert item.apparent_sentiment == "bearish"
        assert item.event_type is None
        assert scoring.class_weight(item.event_type) == scoring.DEFAULT_CLASS_PRIOR

    def test_event_magnitude_is_the_largest_measured_move(self):
        item = scoring.item_from_metadata(
            "e1",
            {
                "date": "2020-12-22",
                "event_type": "regulatory",
                "price_change_1d": -14.9,
                "price_change_7d": -46.1,
                "price_change_180d": 183.7,
                "max_drawdown_pct": -73.4,
                "max_runup_pct": 241.2,
            },
            1.0,
            scoring.SOURCE_EVENT,
        )
        assert item.magnitude_pct == pytest.approx(241.2)

    def test_event_without_measured_outcome_has_no_magnitude(self):
        item = scoring.item_from_metadata(
            "e2", {"date": "2020-12-22", "event_type": "macro"}, 1.0, scoring.SOURCE_EVENT
        )
        assert item.magnitude_pct is None
        assert scoring.magnitude_weight(item.magnitude_pct) == scoring.NEUTRAL


class TestIterChromaHits:
    def test_unpacks_parallel_lists(self):
        rows = list(
            scoring.iter_chroma_hits(
                _results(
                    [
                        {"id": "a", "metadata": {"symbol": "BTC"}, "distance": 0.5},
                        {"id": "b", "metadata": {"symbol": "ETH"}, "distance": 0.9},
                    ]
                )
            )
        )
        assert [row[0] for row in rows] == ["a", "b"]
        assert rows[0][1]["symbol"] == "BTC"
        assert rows[1][2] == 0.9

    def test_empty_response_yields_nothing(self):
        assert list(scoring.iter_chroma_hits(_results([]))) == []
        assert list(scoring.iter_chroma_hits({})) == []
        assert list(scoring.iter_chroma_hits(None)) == []

    def test_missing_distances_do_not_raise(self):
        rows = list(scoring.iter_chroma_hits({"ids": [["a"]], "metadatas": [[{}]]}))
        assert rows[0][2] is None


class TestRankCandidates:
    def test_contradicted_headline_outranks_consistent_one(self):
        # The SEC-v-Ripple case. Both precedents are equally close to the query
        # and equally large; the only difference is that one of them did the
        # opposite of what its headline implied.
        results = _results(
            [
                {
                    "id": "consistent",
                    "distance": 1.0,
                    "metadata": {
                        "date": "2020-12-22",
                        "symbol": "XRP",
                        "event_type": "regulatory",
                        "apparent_sentiment": "bearish",
                        "durable_direction": "bearish",
                        "price_change_180d": -60.0,
                    },
                },
                {
                    "id": "contradicted",
                    "distance": 1.0,
                    "metadata": {
                        "date": "2020-12-22",
                        "symbol": "XRP",
                        "event_type": "regulatory",
                        "apparent_sentiment": "bearish",
                        "durable_direction": "bullish",
                        "inverted": True,
                        "price_change_7d": -46.1,
                        "price_change_180d": 183.7,
                        "max_drawdown_pct": -73.4,
                    },
                },
            ]
        )
        ranked = scoring.rank_candidates(
            results,
            source=scoring.SOURCE_EVENT,
            query_symbol="XRP",
            k=5,
            now=datetime(2026, 7, 24),
        )
        assert [s.item.doc_id for s in ranked] == ["contradicted", "consistent"]
        assert ranked[0].surprised is True
        assert ranked[0].inverted is True
        assert ranked[1].surprised is False

    def test_immediate_reaction_does_not_decide_the_verdict(self):
        # The DeepSeek/NVDA shape: down 17% on day one, still under water at 90
        # days, far above a year later. The durable direction is what counts.
        results = _results(
            [
                {
                    "id": "deepseek",
                    "distance": 1.0,
                    "metadata": {
                        "date": "2025-01-27",
                        "symbol": "NVDA",
                        "event_type": "macro",
                        "apparent_sentiment": "bearish",
                        "durable_direction": "bullish",
                        "inverted": True,
                        "price_change_1d": -17.0,
                        "price_change_90d": -8.0,
                        "price_change_365d": 58.0,
                    },
                }
            ]
        )
        ranked = scoring.rank_candidates(
            results,
            source=scoring.SOURCE_EVENT,
            query_symbol="NVDA",
            now=datetime(2026, 7, 24),
        )
        assert ranked[0].surprised is True
        assert ranked[0].item.magnitude_pct == pytest.approx(58.0)

    def test_items_below_the_relevance_floor_are_dropped(self):
        results = _results([{"id": "sourdough", "distance": DISTANCE_OFF_TOPIC, "metadata": {}}])
        assert scoring.rank_candidates(results, source=scoring.SOURCE_EVENT) == []

    def test_empty_response_gives_no_results(self):
        assert scoring.rank_candidates(_results([]), source=scoring.SOURCE_EVENT) == []

    def test_results_are_capped_at_k(self):
        results = _results([{"id": str(i), "distance": 0.5, "metadata": {}} for i in range(10)])
        assert len(scoring.rank_candidates(results, source=scoring.SOURCE_NEWS, k=3)) == 3

    def test_results_are_ordered_by_score(self):
        results = _results([{"id": str(i), "distance": 0.2 * i, "metadata": {}} for i in range(6)])
        ranked = scoring.rank_candidates(results, source=scoring.SOURCE_NEWS, k=10)
        assert [s.score for s in ranked] == sorted([s.score for s in ranked], reverse=True)


class TestCandidatePoolSize:
    def test_over_fetches_so_reranking_has_room(self):
        assert scoring.candidate_pool_size(5, 1000) == 5 * settings.RAG_CANDIDATE_MULTIPLIER

    def test_never_asks_for_more_than_the_collection_holds(self):
        assert scoring.candidate_pool_size(5, 3) == 3

    def test_empty_collection_asks_for_nothing(self):
        assert scoring.candidate_pool_size(5, 0) == 0


class TestWeightedAggregation:
    def test_weighted_mean_follows_the_heavier_sample(self):
        assert scoring.weighted_mean([10.0, -10.0], [3.0, 1.0]) == pytest.approx(5.0)

    def test_weighted_mean_of_nothing_is_none(self):
        assert scoring.weighted_mean([], []) is None
        assert scoring.weighted_mean([None], [1.0]) is None
        assert scoring.weighted_mean([1.0], [0.0]) is None

    def test_one_strong_match_outvotes_three_weak_ones(self):
        # `Counter.most_common` returned "bullish" here, which is how a stack of
        # barely-related headlines used to overrule the precedent that fit.
        winner, share = scoring.weighted_vote(
            ["bullish", "bullish", "bullish", "bearish"],
            [0.05, 0.05, 0.05, 0.9],
        )
        assert winner == "bearish"
        assert share > 0.8

    def test_vote_ignores_blank_labels(self):
        # `auto_index_recent_news` writes an empty sentiment for every item.
        assert scoring.weighted_vote(["", None, "bullish"], [9.0, 9.0, 0.1]) == (
            "bullish",
            pytest.approx(1.0),
        )

    def test_vote_without_usable_labels_is_none(self):
        assert scoring.weighted_vote([], []) is None
        assert scoring.weighted_vote(["", ""], [1.0, 1.0]) is None

    def test_percentile_range_excludes_the_outliers(self):
        values = [-50.0] + [1.0] * 18 + [50.0]
        weights = [1.0] * 20
        low, high = scoring.weighted_percentile_range(values, weights)
        assert low == 1.0 and high == 1.0

    def test_percentile_range_of_nothing_is_none(self):
        assert scoring.weighted_percentile_range([], []) is None
