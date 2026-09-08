"""
The track record's scoring rules, which are where a flattering number would hide.

None of these touch the database. The point of keeping the arithmetic in pure
functions is that the interesting failures — a neutral verdict counted in the
directional rate, a rate printed over four samples, a keyword fallback scored as
something the model said — are all reachable without one, and every one of them
would produce a plausible page rather than an error.
"""

from datetime import datetime, timedelta, UTC

import pytest

from services import track_record


NOW = datetime(2026, 9, 8, tzinfo=UTC)
HORIZONS = [1, 7, 30, 90, 180, 365]


def _entry(
    *,
    news_id="n1",
    sentiment="bullish",
    symbol="OKX:BTCUSDT",
    asset_type="crypto",
    confidence=0.7,
    analysed_at="2026-08-03T15:45:08.320375",
    published_at="2026-08-03 15:41:38.951000",
    source=None,
    materiality="significant",
):
    return {
        "news_id": news_id,
        "pipeline_version": "abc123",
        "analysis": {
            "sentiment": sentiment,
            "confidence": confidence,
            "analysed_at": analysed_at,
            "source": source,
            "materiality": materiality,
            "model": "qwen3.6:35b-a3b",
        },
        "news": {"symbol": symbol, "asset_type": asset_type, "published_at": published_at},
        "stored_at": analysed_at,
        "outcome": None,
    }


def _prediction(pid, **overrides):
    row = {
        "id": pid,
        "news_id": f"n{pid}",
        "pipeline_version": "abc123",
        "symbol": "OKX:BTCUSDT",
        "asset_type": "crypto",
        "predicted_direction": "bullish",
        "confidence": 0.7,
        "materiality": "significant",
        "verdict_source": None,
        "predicted_at": (NOW - timedelta(days=400)).isoformat(),
    }
    row.update(overrides)
    return row


def _outcome(pid, days, *, hit=True, direction="bullish", pct=5.0, status="measured"):
    return {
        "prediction_id": pid,
        "horizon_days": days,
        "status": status,
        "price_change_pct": pct,
        "measured_direction": direction,
        "hit": hit,
    }


# ── Reading the store ────────────────────────────────────────────────────────


def test_naive_timestamps_are_read_as_local_not_utc():
    """
    The store writes `datetime.now()`, which is the server's zone.

    Reading it as UTC would shift every verdict by the host's offset — three
    hours here — which on a one-day horizon is enough to take the session before
    the call as its baseline.
    """
    row = track_record.prediction_from_entry(_entry())
    predicted_at = track_record._as_utc(row["predicted_at"])

    naive = datetime.fromisoformat("2026-08-03T15:45:08.320375")
    assert predicted_at == naive.astimezone().astimezone(UTC)


def test_publication_is_read_in_the_feeds_frame_not_the_servers():
    """`parse_feed_date` returns naive UTC+3, which is not the server's zone."""
    from services.news_service import FEED_TZ

    row = track_record.prediction_from_entry(_entry())
    published = track_record._as_utc(row["published_at"])

    expected = datetime.fromisoformat("2026-08-03T15:41:38.951000").replace(tzinfo=FEED_TZ)
    assert published == expected.astimezone(UTC)


@pytest.mark.parametrize(
    "entry",
    [
        _entry(symbol=""),  # nothing to measure a price against
        _entry(sentiment="mildly optimistic"),  # not one of the three verdicts
        _entry(analysed_at=None) | {"stored_at": None},  # nothing to measure from
    ],
)
def test_an_unscoreable_entry_is_refused_rather_than_guessed(entry):
    assert track_record.prediction_from_entry(entry) is None


# ── Which horizons may be read ───────────────────────────────────────────────


def test_a_horizon_is_not_read_until_its_session_has_closed():
    """
    Without the settle day the newest bar is the one still forming, and the
    measurement describes a shorter window than its label claims.
    """
    predicted_at = NOW - timedelta(days=7)
    assert track_record.reachable_horizons(predicted_at, now=NOW, horizons=HORIZONS) == [1]


def test_an_old_unmeasured_horizon_is_eventually_abandoned():
    """
    Otherwise a symbol the venues do not carry is re-fetched every hour for the
    life of the install.
    """
    predicted_at = NOW - timedelta(days=100)
    assert track_record.abandoned_horizons(
        predicted_at, now=NOW, horizons=HORIZONS, give_up_days=30
    ) == [1, 7, 30]


# ── Scoring one horizon ──────────────────────────────────────────────────────


def test_a_move_inside_the_flat_band_is_neutral_not_a_hit_for_a_bullish_call():
    row = track_record.measured_row(
        1, horizon_days=7, price_change_pct=0.1, predicted_direction="bullish"
    )
    assert row["measured_direction"] == "neutral"
    assert row["hit"] is False


def test_an_unreadable_direction_never_counts_as_a_miss():
    """
    `hit` is null, not False. A horizon that could not be read is not evidence
    against the call, and counting it as one would quietly deflate the record.
    """
    row = track_record.unmeasurable_row(1, horizon_days=30)
    assert row["hit"] is None
    assert row["status"] == track_record.STATUS_UNMEASURABLE
    assert row["price_change_pct"] is None


# ── The summary's honesty rules ──────────────────────────────────────────────


def test_neutral_verdicts_never_enter_the_directional_rate():
    """
    "Neutral" is the easiest of the three claims and the one the model reaches
    for most often. Pooling it would lift the headline with the verdict that
    risks least.
    """
    predictions = [_prediction(1, predicted_direction="neutral")]
    outcomes = [_outcome(1, 1, hit=True, direction="neutral", pct=0.0)]

    board = track_record.summarise(predictions, outcomes, horizons=HORIZONS, min_samples=1, now=NOW)

    assert board["directional"]["overall"]["n"] == 0
    assert board["neutral"]["by_horizon"][0]["n"] == 1
    assert board["neutral"]["by_horizon"][0]["hits"] == 1


def test_a_rate_is_withheld_below_the_sample_floor():
    predictions = [_prediction(i) for i in range(1, 5)]
    outcomes = [_outcome(i, 1) for i in range(1, 5)]

    board = track_record.summarise(
        predictions, outcomes, horizons=HORIZONS, min_samples=10, now=NOW
    )

    bucket = board["directional"]["by_horizon"][0]
    assert bucket["n"] == 4
    assert bucket["hits"] == 4
    # Four for four is 100%, and printing that is the failure this guards.
    assert bucket["hit_rate"] is None


def test_the_rate_appears_once_the_floor_is_cleared():
    predictions = [_prediction(i) for i in range(1, 11)]
    outcomes = [_outcome(i, 1, hit=i <= 6) for i in range(1, 11)]

    board = track_record.summarise(
        predictions, outcomes, horizons=HORIZONS, min_samples=10, now=NOW
    )

    assert board["directional"]["by_horizon"][0]["hit_rate"] == 0.6


def test_a_keyword_fallback_is_not_counted_as_something_the_model_said():
    predictions = [
        _prediction(1),
        _prediction(2, verdict_source=track_record.KEYWORD_FALLBACK),
    ]
    outcomes = [_outcome(1, 1, hit=False), _outcome(2, 1, hit=True)]

    board = track_record.summarise(predictions, outcomes, horizons=HORIZONS, min_samples=1, now=NOW)

    assert board["directional"]["overall"]["n"] == 1
    assert board["directional"]["overall"]["hits"] == 0
    assert board["excluded"]["keyword_fallback_predictions"] == 1
    assert board["excluded"]["keyword_fallback_measurements"] == 1


def test_the_market_s_own_direction_is_reported_beside_the_hit_rate():
    """
    A 55% hit rate says nothing until you know what always-bullish scored over
    the same window, and the fallback verdicts belong in that denominator even
    though they are excluded from the rate — it is a fact about the market, not
    about the model.
    """
    predictions = [
        _prediction(1),
        _prediction(2),
        _prediction(3, verdict_source=track_record.KEYWORD_FALLBACK),
    ]
    outcomes = [
        _outcome(1, 1, direction="bullish"),
        _outcome(2, 1, direction="bearish", hit=False),
        _outcome(3, 1, direction="bullish"),
    ]

    board = track_record.summarise(predictions, outcomes, horizons=HORIZONS, min_samples=1, now=NOW)

    observed = board["observed"][0]
    assert (observed["bullish"], observed["bearish"], observed["n"]) == (2, 1, 3)


def test_an_unmeasurable_row_is_counted_but_never_scored():
    predictions = [_prediction(1)]
    outcomes = [_outcome(1, 1, status="unmeasurable", hit=None, direction=None)]

    board = track_record.summarise(predictions, outcomes, horizons=HORIZONS, min_samples=1, now=NOW)

    assert board["totals"]["unmeasurable"] == 1
    assert board["totals"]["measured"] == 0
    assert board["directional"]["overall"]["n"] == 0


def test_pending_counts_the_horizons_that_have_come_due_and_carry_no_row():
    """A verdict old enough for every horizon, with one measured."""
    predictions = [_prediction(1)]
    outcomes = [_outcome(1, 1)]

    board = track_record.summarise(predictions, outcomes, horizons=HORIZONS, min_samples=1, now=NOW)

    assert board["totals"]["pending"] == len(HORIZONS) - 1


# ── Export ───────────────────────────────────────────────────────────────────


def test_an_unresolved_call_still_appears_in_the_export():
    """
    Dropping it would let a reader compute a hit rate over the calls that
    happened to resolve, which is a different and much kinder number.
    """
    rows = track_record.csv_rows([_prediction(1)], [])

    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["horizon_days"] is None


def test_every_export_column_is_declared():
    rows = track_record.csv_rows([_prediction(1)], [_outcome(1, 7)])

    assert set(rows[0]) <= set(track_record.CSV_COLUMNS)
