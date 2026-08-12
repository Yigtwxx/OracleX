"""
An event's outcome is a path, not a single endpoint.

The store used to keep one number per event — the change across a fixed ±7-day
window — which labels the two most instructive precedents backwards. Both are
reconstructed here as candle series:

`test_regulatory_shock_reverses_after_ninety_days` is SEC-v-Ripple: a crash and
then a far higher price, with the peak arriving around day 113. Any measurement
that stops at ninety days calls it bearish.

`test_immediate_crash_recovers_within_a_year` is DeepSeek/NVDA: down hard on day
one, still under water at ninety days, strongly up at three hundred and
sixty-five.

If either of these starts passing with a shortened horizon set, the horizon set
is wrong, not the test.
"""

from datetime import datetime, timedelta, UTC

import pytest

from services import rag_outcomes

HORIZONS = [1, 7, 30, 90, 180, 365]
EVENT_DATE = datetime(2020, 12, 22)


def _series(prices, *, start, spread=0.0, hour=0):
    """
    A daily candle series in the shape both market services return.

    `prices` maps a day offset from `start` to that session's close. Offsets that
    are absent are simply missing sessions, which is what a weekend looks like.

    Timestamps are UTC epochs because that is what OKX and Yahoo return; building
    them from local midnight is exactly the mistake that made a crash session
    read as the price *before* the crash.
    """
    candles = []
    for offset, close in sorted(prices.items()):
        day = (start + timedelta(days=offset)).replace(tzinfo=UTC)
        candles.append(
            {
                "time": int(day.timestamp()) + hour * 3600,
                "open": close,
                "high": close + spread,
                "low": close - spread,
                "close": close,
                "volume": 1000.0,
                "volume_usd": 1000.0 * close,
            }
        )
    return candles


def _flat_series(*, start, days, price=100.0, spread=0.0):
    return _series(dict.fromkeys(range(days), price), start=start, spread=spread)


class TestBaseline:
    def test_baseline_is_the_close_before_the_event(self):
        candles = _series({-2: 90.0, -1: 100.0, 0: 50.0, 1: 50.0}, start=EVENT_DATE)
        outcome = rag_outcomes.summarize_outcome(candles, EVENT_DATE, horizons=[1])
        assert outcome is not None
        assert outcome.baseline == pytest.approx(100.0)
        assert outcome.horizons[1] == pytest.approx(-50.0)

    def test_no_pre_event_history_cannot_be_measured(self):
        candles = _series({0: 100.0, 1: 110.0}, start=EVENT_DATE)
        assert rag_outcomes.summarize_outcome(candles, EVENT_DATE, horizons=[1]) is None

    def test_empty_series_cannot_be_measured(self):
        assert rag_outcomes.summarize_outcome([], EVENT_DATE, horizons=[1]) is None

    def test_the_event_session_is_never_the_baseline(self):
        # The measurement is anchored in UTC. Deriving the event instant from the
        # host's local midnight instead let the crash session count as "before",
        # which is how China's 2021 mining ban came out as a +11% first day when
        # bitcoin had fallen roughly 30%.
        candles = _series({-1: 100.0, 0: 70.0, 1: 78.0}, start=EVENT_DATE)
        outcome = rag_outcomes.summarize_outcome(candles, EVENT_DATE, horizons=[1])
        assert outcome is not None
        assert outcome.baseline == pytest.approx(100.0)
        # Horizon N is the session N days after the event date, so the event's
        # own session sits between the baseline and the first horizon. The crash
        # itself is not lost — it is what `max_drawdown_pct` reports.
        assert outcome.horizons[1] == pytest.approx(-22.0)
        assert outcome.max_drawdown_pct == pytest.approx(-30.0)

    def test_an_intraday_candle_timestamp_still_lands_on_the_right_side(self):
        # Yahoo stamps a session at the opening bell, not at midnight.
        candles = _series({-1: 100.0, 0: 70.0, 1: 78.0}, start=EVENT_DATE, hour=14)
        outcome = rag_outcomes.summarize_outcome(candles, EVENT_DATE, horizons=[1])
        assert outcome is not None
        assert outcome.baseline == pytest.approx(100.0)

    def test_a_stale_baseline_is_not_borrowed(self):
        # The last close is three weeks before the event — too far to stand in
        # for the price the market held when the news broke.
        candles = _series({-40: 100.0, 1: 50.0}, start=EVENT_DATE)
        assert rag_outcomes.summarize_outcome(candles, EVENT_DATE, horizons=[1]) is None


class TestHorizons:
    def test_each_horizon_is_measured_against_the_baseline(self):
        prices = {-1: 100.0}
        prices.update({d: 100.0 + d for d in range(0, 400)})
        outcome = rag_outcomes.summarize_outcome(
            _series(prices, start=EVENT_DATE), EVENT_DATE, horizons=HORIZONS
        )
        assert outcome is not None
        assert outcome.horizons[1] == pytest.approx(1.0)
        assert outcome.horizons[365] == pytest.approx(365.0)

    def test_a_horizon_beyond_the_data_is_left_unmeasured(self):
        prices = {-1: 100.0}
        prices.update(dict.fromkeys(range(0, 40), 110.0))
        outcome = rag_outcomes.summarize_outcome(
            _series(prices, start=EVENT_DATE), EVENT_DATE, horizons=HORIZONS
        )
        assert outcome is not None
        assert 30 in outcome.horizons
        assert 90 not in outcome.horizons
        assert 365 not in outcome.horizons

    def test_a_missing_session_within_tolerance_uses_the_last_close(self):
        # Day 90 falls on a market holiday; day 88 is the last session.
        prices = {-1: 100.0, 0: 100.0, 88: 150.0}
        outcome = rag_outcomes.summarize_outcome(
            _series(prices, start=EVENT_DATE), EVENT_DATE, horizons=[90]
        )
        assert outcome is not None
        assert outcome.horizons[90] == pytest.approx(50.0)

    def test_a_gap_wider_than_tolerance_is_not_measured(self):
        prices = {-1: 100.0, 0: 100.0, 80: 150.0}
        outcome = rag_outcomes.summarize_outcome(
            _series(prices, start=EVENT_DATE), EVENT_DATE, horizons=[90]
        )
        assert outcome is not None
        assert 90 not in outcome.horizons


class TestPathStatistics:
    def test_drawdown_and_runup_capture_what_the_endpoints_hide(self):
        # Closes flat at the baseline, but the path went to 30 and to 260.
        prices = {-1: 100.0, 0: 100.0, 10: 30.0, 200: 260.0, 365: 100.0}
        outcome = rag_outcomes.summarize_outcome(
            _series(prices, start=EVENT_DATE), EVENT_DATE, horizons=HORIZONS
        )
        assert outcome is not None
        assert outcome.horizons[365] == pytest.approx(0.0)
        assert outcome.max_drawdown_pct == pytest.approx(-70.0)
        assert outcome.max_runup_pct == pytest.approx(160.0)

    def test_path_uses_intraday_extremes_not_closes(self):
        prices = {-1: 100.0, 0: 100.0, 5: 100.0}
        outcome = rag_outcomes.summarize_outcome(
            _series(prices, start=EVENT_DATE, spread=20.0), EVENT_DATE, horizons=[7]
        )
        assert outcome is not None
        assert outcome.max_drawdown_pct == pytest.approx(-20.0)
        assert outcome.max_runup_pct == pytest.approx(20.0)

    def test_abs_impact_is_the_largest_move_anywhere(self):
        prices = {-1: 100.0, 0: 100.0, 10: 27.0, 180: 120.0}
        outcome = rag_outcomes.summarize_outcome(
            _series(prices, start=EVENT_DATE), EVENT_DATE, horizons=HORIZONS
        )
        assert outcome is not None
        assert outcome.abs_impact == pytest.approx(73.0)


class TestDirections:
    def test_regulatory_shock_reverses_after_ninety_days(self):
        # SEC v. Ripple, 2020-12-22. $0.75 -> $0.17 within weeks, $1.96 by April.
        prices = {
            -1: 0.75,
            0: 0.64,
            1: 0.55,
            7: 0.40,
            30: 0.28,
            90: 0.55,
            113: 1.96,
            180: 1.35,
            365: 0.95,
        }
        prices[15] = 0.17  # the trough
        outcome = rag_outcomes.summarize_outcome(
            _series(prices, start=EVENT_DATE), EVENT_DATE, horizons=HORIZONS
        )
        assert outcome is not None
        assert outcome.immediate_direction == "bearish"
        assert outcome.durable_direction == "bullish"
        assert outcome.inverted is True
        assert outcome.max_drawdown_pct == pytest.approx(-77.33, abs=0.1)

    def test_immediate_crash_recovers_within_a_year(self):
        # DeepSeek/NVDA, 2025-01-27: -17% day one, still down at 90 days, +58% at a year.
        event = datetime(2025, 1, 27)
        prices = {
            -1: 142.0,
            0: 118.0,
            1: 128.0,
            7: 124.0,
            30: 131.0,
            90: 108.0,
            180: 155.0,
            365: 184.0,
        }
        outcome = rag_outcomes.summarize_outcome(
            _series(prices, start=event), event, horizons=HORIZONS
        )
        assert outcome is not None
        assert outcome.horizons[1] == pytest.approx(-9.86, abs=0.1)
        assert outcome.horizons[90] < 0
        assert outcome.horizons[365] > 0
        assert outcome.immediate_direction == "bearish"
        assert outcome.durable_direction == "bullish"
        assert outcome.inverted is True

    def test_ninety_day_horizon_alone_would_call_it_bearish(self):
        # The reason the horizon set runs to 365. Same series, truncated set.
        event = datetime(2025, 1, 27)
        prices = {-1: 142.0, 0: 118.0, 1: 128.0, 7: 124.0, 30: 131.0, 90: 108.0}
        outcome = rag_outcomes.summarize_outcome(
            _series(prices, start=event), event, horizons=[1, 7, 30, 90]
        )
        assert outcome is not None
        assert outcome.durable_direction == "bearish"
        assert outcome.inverted is False

    def test_the_verdict_is_read_off_the_longest_horizon_not_averaged(self):
        # Averaging hands the verdict to whichever horizon is numerically
        # largest. Here the year ended down, and a mean over 90/180/365 would
        # still call it bullish because of the interim spike.
        prices = {-1: 100.0, 0: 100.0, 90: 400.0, 180: 300.0, 365: 80.0}
        outcome = rag_outcomes.summarize_outcome(
            _series(prices, start=EVENT_DATE), EVENT_DATE, horizons=HORIZONS
        )
        assert outcome is not None
        assert outcome.durable_direction == "bearish"

    def test_a_consistent_event_is_not_marked_inverted(self):
        prices = {-1: 100.0}
        prices.update(dict.fromkeys(range(0, 400), 60.0))
        outcome = rag_outcomes.summarize_outcome(
            _series(prices, start=EVENT_DATE), EVENT_DATE, horizons=HORIZONS
        )
        assert outcome is not None
        assert outcome.immediate_direction == "bearish"
        assert outcome.durable_direction == "bearish"
        assert outcome.inverted is False

    def test_a_flat_outcome_is_not_an_inversion(self):
        outcome = rag_outcomes.summarize_outcome(
            _flat_series(start=EVENT_DATE - timedelta(days=1), days=400),
            EVENT_DATE,
            horizons=HORIZONS,
        )
        assert outcome is not None
        assert outcome.durable_direction == "neutral"
        assert outcome.inverted is False


class TestMetadata:
    def test_measured_values_are_written_and_gaps_are_omitted(self):
        prices = {-1: 100.0}
        prices.update(dict.fromkeys(range(0, 40), 120.0))
        outcome = rag_outcomes.summarize_outcome(
            _series(prices, start=EVENT_DATE), EVENT_DATE, horizons=HORIZONS
        )
        assert outcome is not None

        metadata = outcome.as_metadata()
        assert metadata["price_change_30d"] == pytest.approx(20.0)
        # Chroma rejects null metadata, so an unreached horizon must be absent
        # rather than present-and-empty.
        assert "price_change_365d" not in metadata
        assert all(value is not None for value in metadata.values())

    def test_metadata_carries_the_verdict(self):
        prices = {-1: 100.0, 0: 60.0, 1: 55.0, 7: 58.0, 90: 140.0, 180: 160.0, 365: 190.0}
        outcome = rag_outcomes.summarize_outcome(
            _series(prices, start=EVENT_DATE), EVENT_DATE, horizons=HORIZONS
        )
        assert outcome is not None

        metadata = outcome.as_metadata()
        assert metadata["immediate_direction"] == "bearish"
        assert metadata["durable_direction"] == "bullish"
        assert metadata["inverted"] is True
        assert metadata["abs_impact"] == pytest.approx(90.0)


class TestScoringReadsTheMetadata:
    def test_the_written_metadata_produces_a_surprise_boost(self):
        # The two halves of the change have to meet: what the measurement writes
        # is what the scorer reads.
        from config import settings
        from services import rag_scoring

        prices = {-1: 100.0, 0: 60.0, 1: 55.0, 7: 58.0, 90: 140.0, 180: 160.0, 365: 190.0}
        outcome = rag_outcomes.summarize_outcome(
            _series(prices, start=EVENT_DATE), EVENT_DATE, horizons=HORIZONS
        )
        assert outcome is not None

        metadata = dict(outcome.as_metadata())
        metadata.update(
            {
                "date": "2020-12-22",
                "symbol": "XRP",
                "event_type": "regulatory",
                "apparent_sentiment": "bearish",
            }
        )

        item = rag_scoring.item_from_metadata("e1", metadata, 1.0, rag_scoring.SOURCE_EVENT)
        scored = rag_scoring.score_item(item, query_symbol="XRP", now=datetime(2026, 7, 24))
        assert scored.surprise == settings.RAG_SURPRISE_BOOST
        assert scored.surprised is True
