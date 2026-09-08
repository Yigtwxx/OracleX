"""
Track record — what the terminal said, and what the price actually did.

The pieces for this existed for a long time and were never joined.
`rag_outcomes` could measure an event's aftermath across six horizons,
`news_analysis_store` kept every verdict on disk with an `outcome` field waiting
to be filled, and its docstring described the job that would fill it. That job
was never written: `record_outcome()` and `pending_outcomes()` had no callers,
and every stored analysis carried a null outcome from the day it was made. This
module is that job, plus the reading side that turns its rows into a figure.

Three things about the design are deliberate and would each be tempting to
"simplify" into something that reads better and means less.

**The horizons are measured from the verdict, not from the headline.** Measuring
from `published_at` would credit the model for whatever the price did between
the article landing and the analysis running — a move no reader could have acted
on, because the call did not yet exist. `predicted_at` is the baseline anchor;
`published_at` is stored beside it so the lag stays visible.

One residue of that is worth stating plainly rather than hiding, because it is
the weakest joint in the measurement: `summarize_outcome` truncates the event
instant to midnight UTC, so the baseline is the last close *before the day the
verdict was made*. A call made at three in the afternoon is therefore measured
from the previous close and carries that session's earlier move with it. The
alternative — shifting every event date forward a day — would buy a stricter
baseline by making every horizon label wrong by one, which is a worse trade. The
page says which baseline it used.

**Ingest is pulled from the store, not pushed from the analysis.** `_persist`
in `news_analysis_service` stays untouched. A database round-trip on the
analysis hot path would be paid on every reply for a figure nobody reads in real
time, and pulling means the analyses already sitting on disk are picked up on
the first pass instead of the record starting empty.

**Nothing is ever rewritten.** A row per (verdict × horizon), written once, when
that horizon first becomes measurable. A track record you can update is not
evidence of anything.
"""

import logging
from datetime import datetime, timedelta, UTC
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from config import settings
from services import news_analysis_store
from services.db import SupabaseOps
from services.rag_outcomes import measure_event_outcome
from services.rag_scoring import BEARISH, BULLISH, NEUTRAL_DIRECTION, direction_from_pct

logger = logging.getLogger(__name__)

PREDICTIONS_TABLE = "predictions"
OUTCOMES_TABLE = "prediction_outcomes"

# The two verdicts that make a falsifiable claim about direction. "Neutral" is
# scored too, but never in the same bucket — see `summarise`.
DIRECTIONAL: Tuple[str, str] = (BULLISH, BEARISH)
VERDICTS: Tuple[str, str, str] = (BULLISH, BEARISH, NEUTRAL_DIRECTION)

STATUS_MEASURED = "measured"
STATUS_UNMEASURABLE = "unmeasurable"

# A verdict whose `source` says this came from a word count over the headline
# because no model was reachable. Recorded, but never counted as something the
# model said.
KEYWORD_FALLBACK = "keyword-fallback"

# A horizon's target session has to have closed before it can be read. Without
# this the newest bar is the one still forming, and the measurement is about a
# shorter window than its label claims.
SETTLE_DAYS = 1

# Confidence bands the summary reports. Open at the top: a model that returns
# exactly 1.0 belongs in the last bucket rather than in none of them.
CONFIDENCE_BUCKETS: Tuple[Tuple[str, float, float], ...] = (
    ("low", 0.0, 0.4),
    ("medium", 0.4, 0.6),
    ("high", 0.6, 0.8),
    ("very-high", 0.8, 1.01),
)

# A ceiling so one query cannot pull an unbounded history into memory. Far past
# what a single-worker install produces in a year.
MAX_ROWS = 20000


class TrackRecordError(Exception):
    """An upstream failure reaching the track record's tables."""


_ops = SupabaseOps(domain="track_record", wrap=TrackRecordError)


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers. No I/O, so the scoring rules can be tested directly rather than
# through a database — which is where a hit rate computed off the wrong
# denominator would otherwise hide.
# ─────────────────────────────────────────────────────────────────────────────


def _as_utc(value: Any) -> Optional[datetime]:
    """
    A stored timestamp as an aware UTC datetime, or None if it is not one.

    Everything `news_analysis_store` writes is naive: `analysed_at` and
    `stored_at` are both `datetime.now()`, which is the *server's* zone rather
    than UTC. Stamping those with `tzinfo=UTC` would shift every verdict by the
    host's offset — three hours, here — and on a one-day horizon that is enough
    to read the wrong session as the baseline. `astimezone()` on a naive value
    attaches the local zone, which is the frame they were actually written in.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        # Both separators appear in the store: `stored_at` uses isoformat's "T",
        # while a news item's `published_at` was written with a space.
        try:
            parsed = datetime.fromisoformat(text.replace(" ", "T").replace("Z", "+00:00"))
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(UTC)


def _published_utc(value: Any) -> Optional[datetime]:
    """
    A news item's publication stamp as UTC.

    Not `_as_utc`: `parse_feed_date` returns naive time in `FEED_TZ`, which is
    the wire's frame and not the server's. Reading it as local would be right
    only on a machine that happens to run at UTC+3, and wrong everywhere else by
    the difference.
    """
    if value is None:
        return None

    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC)

    text = value if isinstance(value, datetime) else str(value).strip()
    if not text:
        return None

    from services.news_service import FEED_TZ

    if isinstance(text, datetime):
        parsed: Optional[datetime] = text
    else:
        try:
            parsed = datetime.fromisoformat(text.replace(" ", "T").replace("Z", "+00:00"))
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=FEED_TZ)
    return parsed.astimezone(UTC)


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def prediction_from_entry(entry: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """
    One stored analysis as a `predictions` row, or None when it cannot be scored.

    None is a real answer three times over, and each is a different fact the
    summary reports rather than a row quietly dropped: a verdict that is not one
    of the three directions, an item with no symbol (nothing to measure a price
    against), and one with no usable timestamp (nothing to measure from).
    """
    analysis = entry.get("analysis") or {}
    news = entry.get("news") or {}

    news_id = entry.get("news_id")
    if not news_id:
        return None

    direction = str(analysis.get("sentiment") or "").strip().lower()
    if direction not in VERDICTS:
        return None

    symbol = str(news.get("symbol") or "").strip()
    if not symbol:
        return None

    # `analysed_at` is when the model answered; `stored_at` is when the answer
    # was filed. They differ by milliseconds, and the first is the real one.
    predicted_at = _as_utc(analysis.get("analysed_at")) or _as_utc(entry.get("stored_at"))
    if predicted_at is None:
        return None

    published_at = _published_utc(news.get("published_at"))

    return {
        "news_id": str(news_id),
        "pipeline_version": str(entry.get("pipeline_version") or "unknown"),
        "symbol": symbol,
        "asset_type": str(news.get("asset_type") or "crypto").strip().lower(),
        "predicted_direction": direction,
        "confidence": _as_float(analysis.get("confidence")),
        "materiality": analysis.get("materiality") or None,
        "model": analysis.get("model") or None,
        "verdict_source": analysis.get("source") or None,
        "predicted_at": predicted_at.isoformat(),
        "published_at": published_at.isoformat() if published_at else None,
    }


def reachable_horizons(
    predicted_at: datetime,
    *,
    now: datetime,
    horizons: Sequence[int],
    settle_days: int = SETTLE_DAYS,
) -> List[int]:
    """Horizons whose target session has closed, so they can be read at all."""
    cutoff = now - timedelta(days=settle_days)
    return [days for days in sorted(set(horizons)) if predicted_at + timedelta(days=days) <= cutoff]


def abandoned_horizons(
    predicted_at: datetime,
    *,
    now: datetime,
    horizons: Sequence[int],
    give_up_days: int,
) -> List[int]:
    """
    Horizons old enough that a still-missing measurement is not coming.

    Without this a symbol the venues do not carry back far enough is re-fetched
    on every pass forever, and the price of one unlistable ticker is paid at the
    exchange every hour for the life of the install.
    """
    cutoff = now - timedelta(days=give_up_days)
    return [days for days in sorted(set(horizons)) if predicted_at + timedelta(days=days) <= cutoff]


def measured_row(
    prediction_id: int,
    *,
    horizon_days: int,
    price_change_pct: float,
    predicted_direction: str,
    max_drawdown_pct: Optional[float] = None,
    max_runup_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """One measured horizon, scored against the verdict."""
    measured_direction = direction_from_pct(price_change_pct)
    return {
        "prediction_id": prediction_id,
        "horizon_days": horizon_days,
        "status": STATUS_MEASURED,
        "price_change_pct": round(price_change_pct, 4),
        "measured_direction": measured_direction,
        # Null rather than False when the direction could not be established, so
        # an unreadable measurement never counts against the record.
        "hit": None if measured_direction is None else measured_direction == predicted_direction,
        "max_drawdown_pct": None if max_drawdown_pct is None else round(max_drawdown_pct, 4),
        "max_runup_pct": None if max_runup_pct is None else round(max_runup_pct, 4),
        "measured_at": datetime.now(UTC).isoformat(),
    }


def unmeasurable_row(prediction_id: int, *, horizon_days: int) -> Dict[str, Any]:
    """A horizon closed without a measurement, so it stops being retried."""
    return {
        "prediction_id": prediction_id,
        "horizon_days": horizon_days,
        "status": STATUS_UNMEASURABLE,
        "price_change_pct": None,
        "measured_direction": None,
        "hit": None,
        "max_drawdown_pct": None,
        "max_runup_pct": None,
        "measured_at": datetime.now(UTC).isoformat(),
    }


def _empty_bucket() -> Dict[str, Any]:
    return {"n": 0, "hits": 0, "hit_rate": None}


def _tally(bucket: Dict[str, Any], hit: Optional[bool]) -> None:
    if hit is None:
        return
    bucket["n"] += 1
    if hit:
        bucket["hits"] += 1


def _settle(bucket: Dict[str, Any], min_samples: int) -> Dict[str, Any]:
    """
    Fill in the rate, or refuse to.

    Below the floor the bucket reports its count and nothing else. A five-sample
    bucket moves twenty points per call, and rendering that as a percentage
    invites a reader to treat noise as a measurement — the same reasoning as
    `polymarket/sufficiency`, applied to our own numbers rather than a market's.
    """
    n = bucket["n"]
    bucket["hit_rate"] = round(bucket["hits"] / n, 4) if n >= min_samples else None
    return bucket


def _baseline(
    bucket: Mapping[str, Any], mix: Mapping[str, int], min_samples: int
) -> Dict[str, Any]:
    """
    What the best fixed answer would have scored on the same calls.

    The number a hit rate has to be read against. A model that says "bullish"
    into a market that rose on two thirds of the measured windows has not shown
    anything by being right two thirds of the time, and a page that prints the
    hit rate alone invites exactly that reading. The benchmark is the best
    constant predictor — always-bullish, always-bearish or always-neutral,
    whichever won — because beating the *easiest* alternative is the weakest
    claim worth making.

    Withheld below the sample floor for the same reason the rate is.
    """
    n = bucket["n"]
    if not n:
        return {"baseline_rate": None, "baseline_direction": None}
    direction = max(mix, key=lambda key: mix[key])
    return {
        "baseline_rate": round(mix[direction] / n, 4) if n >= min_samples else None,
        "baseline_direction": direction if mix[direction] else None,
    }


def confidence_bucket(confidence: Optional[float]) -> Optional[str]:
    """Which reported band a confidence falls in, or None when it was not given."""
    if confidence is None:
        return None
    for label, low, high in CONFIDENCE_BUCKETS:
        if low <= confidence < high:
            return label
    return None


def summarise(
    predictions: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    *,
    horizons: Sequence[int],
    min_samples: int,
    now: Optional[datetime] = None,
    settle_days: int = SETTLE_DAYS,
) -> Dict[str, Any]:
    """
    The whole record as one board, computed in Python.

    Grouped in Python rather than SQL for the reason `usage_service` gives: the
    volume is small, and a grouped RPC would be a migration every time a
    breakdown is added.

    Three separations carry the honesty of the number and none of them is
    cosmetic:

    * **Directional and neutral verdicts are never pooled.** "Neutral" hitting
      means the price stayed inside the flat band, which is the easiest of the
      three claims and the one the model reaches for most often. Averaging it
      into the headline would lift the figure with the verdict that risks least.
    * **The measured distribution is reported beside the hit rate.** A 55% hit
      rate says nothing until you know what always-bullish scored over the same
      window, and only one of those two numbers is flattering by default.
    * **Keyword-fallback verdicts are excluded and counted.** A word count over
      a headline is not a thing the model said, and a record that quietly
      contains both is measuring two different systems.
    """
    now = now or datetime.now(UTC)
    horizon_days = sorted(set(horizons))

    by_id = {row["id"]: row for row in predictions if row.get("id") is not None}

    directional: Dict[int, Dict[str, Any]] = {d: _empty_bucket() for d in horizon_days}
    # The measured direction mix over exactly the rows the directional bucket
    # counts. Not `observed`, which spans every measurement: a benchmark has to
    # share its denominator with the number it is a benchmark for, or the
    # comparison is between two different samples and reads as an edge that was
    # never measured.
    directional_mix: Dict[int, Dict[str, int]] = {
        d: {BULLISH: 0, BEARISH: 0, NEUTRAL_DIRECTION: 0} for d in horizon_days
    }
    neutral: Dict[int, Dict[str, Any]] = {d: _empty_bucket() for d in horizon_days}
    observed: Dict[int, Dict[str, int]] = {
        d: {BULLISH: 0, BEARISH: 0, NEUTRAL_DIRECTION: 0} for d in horizon_days
    }
    by_materiality: Dict[str, Dict[str, Any]] = {}
    by_confidence: Dict[str, Dict[str, Any]] = {
        label: _empty_bucket() for label, _, _ in CONFIDENCE_BUCKETS
    }
    overall = _empty_bucket()

    measured = unmeasurable = 0
    excluded_fallback_rows = 0

    for outcome in outcomes:
        prediction = by_id.get(outcome.get("prediction_id"))
        if prediction is None:
            continue

        if outcome.get("status") == STATUS_UNMEASURABLE:
            unmeasurable += 1
            continue
        measured += 1

        days = outcome.get("horizon_days")
        if days in observed:
            direction = outcome.get("measured_direction")
            if direction in observed[days]:
                observed[days][direction] += 1

        if prediction.get("verdict_source") == KEYWORD_FALLBACK:
            excluded_fallback_rows += 1
            continue

        hit = outcome.get("hit")
        predicted = prediction.get("predicted_direction")

        if predicted in DIRECTIONAL:
            if days in directional:
                _tally(directional[days], hit)
                measured_direction = outcome.get("measured_direction")
                if hit is not None and measured_direction in directional_mix[days]:
                    directional_mix[days][measured_direction] += 1
            _tally(overall, hit)

            materiality = prediction.get("materiality") or "unstated"
            _tally(by_materiality.setdefault(materiality, _empty_bucket()), hit)

            band = confidence_bucket(_as_float(prediction.get("confidence")))
            if band is not None:
                _tally(by_confidence[band], hit)
        elif predicted == NEUTRAL_DIRECTION and days in neutral:
            _tally(neutral[days], hit)

    # Every horizon each verdict is old enough to have, minus the ones written.
    expected = 0
    for prediction in predictions:
        predicted_at = _as_utc(prediction.get("predicted_at"))
        if predicted_at is None:
            continue
        expected += len(
            reachable_horizons(
                predicted_at, now=now, horizons=horizon_days, settle_days=settle_days
            )
        )

    scored_predictions = {
        outcome.get("prediction_id") for outcome in outcomes if outcome.get("prediction_id")
    }
    fallback_predictions = sum(
        1 for row in predictions if row.get("verdict_source") == KEYWORD_FALLBACK
    )

    return {
        "generated_at": now.isoformat(),
        "min_samples": min_samples,
        "horizons": horizon_days,
        "totals": {
            "predictions": len(predictions),
            "predictions_scored": len(scored_predictions),
            "measured": measured,
            "unmeasurable": unmeasurable,
            # Horizons already reachable that carry no row yet — the backlog the
            # next scoring pass will work through.
            "pending": max(expected - (measured + unmeasurable), 0),
        },
        "directional": {
            "overall": _settle(overall, min_samples),
            "by_horizon": [
                {
                    "horizon_days": d,
                    **_settle(directional[d], min_samples),
                    **_baseline(directional[d], directional_mix[d], min_samples),
                }
                for d in horizon_days
            ],
        },
        "neutral": {
            "by_horizon": [
                {"horizon_days": d, **_settle(neutral[d], min_samples)} for d in horizon_days
            ],
        },
        # What the market did, regardless of what was predicted. The denominator
        # a hit rate has to be read against.
        "observed": [
            {
                "horizon_days": d,
                "n": sum(observed[d].values()),
                "bullish": observed[d][BULLISH],
                "bearish": observed[d][BEARISH],
                "neutral": observed[d][NEUTRAL_DIRECTION],
            }
            for d in horizon_days
        ],
        "by_materiality": [
            {"materiality": key, **_settle(bucket, min_samples)}
            for key, bucket in sorted(by_materiality.items())
        ],
        "by_confidence": [
            {
                "band": label,
                "from": low,
                "to": min(high, 1.0),
                **_settle(by_confidence[label], min_samples),
            }
            for label, low, high in CONFIDENCE_BUCKETS
        ],
        "excluded": {
            "keyword_fallback_predictions": fallback_predictions,
            "keyword_fallback_measurements": excluded_fallback_rows,
        },
        "pipeline_versions": sorted(
            {str(row.get("pipeline_version")) for row in predictions if row.get("pipeline_version")}
        ),
    }


def csv_rows(
    predictions: Sequence[Mapping[str, Any]], outcomes: Sequence[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    """
    The record flattened to one row per (verdict × horizon), for export.

    Verdicts with no measurement yet are included with empty outcome columns.
    An export that silently drops them would let a reader compute a hit rate
    over the calls that happened to resolve, which is a different and much
    kinder number.
    """
    by_prediction: Dict[Any, List[Mapping[str, Any]]] = {}
    for outcome in outcomes:
        by_prediction.setdefault(outcome.get("prediction_id"), []).append(outcome)

    rows: List[Dict[str, Any]] = []
    for prediction in predictions:
        base = {
            "news_id": prediction.get("news_id"),
            "pipeline_version": prediction.get("pipeline_version"),
            "symbol": prediction.get("symbol"),
            "asset_type": prediction.get("asset_type"),
            "predicted_direction": prediction.get("predicted_direction"),
            "confidence": prediction.get("confidence"),
            "materiality": prediction.get("materiality"),
            "model": prediction.get("model"),
            "verdict_source": prediction.get("verdict_source"),
            "predicted_at": prediction.get("predicted_at"),
            "published_at": prediction.get("published_at"),
        }
        measurements = sorted(
            by_prediction.get(prediction.get("id"), []),
            key=lambda row: row.get("horizon_days") or 0,
        )
        if not measurements:
            rows.append({**base, "horizon_days": None, "status": "pending"})
            continue
        for outcome in measurements:
            rows.append(
                {
                    **base,
                    "horizon_days": outcome.get("horizon_days"),
                    "status": outcome.get("status"),
                    "price_change_pct": outcome.get("price_change_pct"),
                    "measured_direction": outcome.get("measured_direction"),
                    "hit": outcome.get("hit"),
                    "max_drawdown_pct": outcome.get("max_drawdown_pct"),
                    "max_runup_pct": outcome.get("max_runup_pct"),
                    "measured_at": outcome.get("measured_at"),
                }
            )
    return rows


CSV_COLUMNS: Tuple[str, ...] = (
    "news_id",
    "pipeline_version",
    "symbol",
    "asset_type",
    "predicted_direction",
    "confidence",
    "materiality",
    "model",
    "verdict_source",
    "predicted_at",
    "published_at",
    "horizon_days",
    "status",
    "price_change_pct",
    "measured_direction",
    "hit",
    "max_drawdown_pct",
    "max_runup_pct",
    "measured_at",
)

# ─────────────────────────────────────────────────────────────────────────────
# The database side.
# ─────────────────────────────────────────────────────────────────────────────


async def _fetch_predictions() -> List[Dict[str, Any]]:
    rows = await _ops.table_op(
        lambda client: (
            client.table(PREDICTIONS_TABLE)
            .select("*")
            .order("predicted_at", desc=True)
            .limit(MAX_ROWS)
            .execute()
        ),
        what="read predictions",
    )
    return rows or []


async def _fetch_outcomes() -> List[Dict[str, Any]]:
    rows = await _ops.table_op(
        lambda client: client.table(OUTCOMES_TABLE).select("*").limit(MAX_ROWS).execute(),
        what="read outcomes",
    )
    return rows or []


async def _insert_predictions(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not rows:
        return []
    written = await _ops.table_op(
        lambda client: client.table(PREDICTIONS_TABLE).insert(list(rows)).execute(),
        what="insert predictions",
    )
    return written or []


async def _insert_outcomes(rows: Sequence[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    written = await _ops.table_op(
        lambda client: client.table(OUTCOMES_TABLE).insert(list(rows)).execute(),
        what="insert outcomes",
    )
    return len(written or [])


async def ingest() -> int:
    """
    Copy any verdict the store holds and the record does not, and return the count.

    Pulled rather than pushed — see the module docstring. The unique constraint
    on `(news_id, pipeline_version)` is the real guard; this only avoids sending
    rows that are certain to collide, so two passes racing produce a failed
    insert rather than a duplicate record.
    """
    try:
        entries = news_analysis_store.all_entries()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Track record: could not read the analysis store: %s", exc)
        return 0

    candidates: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for entry in entries:
        row = prediction_from_entry(entry)
        if row is not None:
            candidates[(row["news_id"], row["pipeline_version"])] = row

    if not candidates:
        return 0

    existing = {
        (str(row.get("news_id")), str(row.get("pipeline_version")))
        for row in await _fetch_predictions()
    }
    fresh = [row for key, row in candidates.items() if key not in existing]
    written = await _insert_predictions(fresh)
    if written:
        logger.info("Track record: ingested %d new verdicts", len(written))
    return len(written)


async def _score_one(
    prediction: Mapping[str, Any],
    already: Sequence[int],
    *,
    now: datetime,
    horizons: Sequence[int],
) -> List[Dict[str, Any]]:
    """
    Every horizon of one verdict that can be closed on this pass.

    One price fetch serves all of them: `measure_event_outcome` returns the
    whole horizon set from a single candle series, so scoring six horizons costs
    the same request as scoring one.
    """
    predicted_at = _as_utc(prediction.get("predicted_at"))
    if predicted_at is None:
        return []

    prediction_id = prediction["id"]
    pending = [
        days
        for days in reachable_horizons(predicted_at, now=now, horizons=horizons)
        if days not in already
    ]
    if not pending:
        return []

    outcome = await measure_event_outcome(
        str(prediction.get("symbol") or ""),
        predicted_at,
        str(prediction.get("asset_type") or "crypto"),
    )

    direction = str(prediction.get("predicted_direction") or "")
    rows: List[Dict[str, Any]] = []
    give_up = abandoned_horizons(
        predicted_at,
        now=now,
        horizons=pending,
        give_up_days=settings.TRACK_RECORD_GIVE_UP_DAYS,
    )

    for days in pending:
        pct = outcome.horizons.get(days) if outcome is not None else None
        if pct is not None:
            rows.append(
                measured_row(
                    prediction_id,
                    horizon_days=days,
                    price_change_pct=pct,
                    predicted_direction=direction,
                    max_drawdown_pct=outcome.max_drawdown_pct if outcome else None,
                    max_runup_pct=outcome.max_runup_pct if outcome else None,
                )
            )
        elif days in give_up:
            rows.append(unmeasurable_row(prediction_id, horizon_days=days))

    return rows


def _mirror_into_store(prediction: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> None:
    """
    Write the measurement back into the analysis store.

    This is the loop `news_analysis_store`'s docstring promised and never got:
    with it, a stored verdict finally knows what the price did afterwards, which
    is what the news view needs to show a past call beside its outcome. Failing
    here must not fail the scoring pass — the durable record is Postgres, and
    this is a convenience copy.
    """
    measured = {
        row["horizon_days"]: row["price_change_pct"]
        for row in rows
        if row.get("status") == STATUS_MEASURED and row.get("price_change_pct") is not None
    }
    if not measured:
        return

    try:
        news_analysis_store.record_outcome(
            str(prediction.get("news_id")),
            {
                "horizons": {str(days): pct for days, pct in sorted(measured.items())},
                "measured_at": datetime.now(UTC).isoformat(),
                "predicted_direction": prediction.get("predicted_direction"),
                "measured_direction": direction_from_pct(measured[max(measured)]),
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "Track record: could not mirror %s into the store: %s",
            prediction.get("news_id"),
            exc,
        )


async def score_pending(*, now: Optional[datetime] = None) -> Dict[str, int]:
    """
    Ingest new verdicts, then close every horizon that has come due.

    Bounded by `TRACK_RECORD_SCORE_BATCH` verdicts per pass. The measurement
    hits OKX or Yahoo once per verdict, and an unbounded pass over a year of
    history would arrive at both as a burst — the same reasoning that paces the
    heatmap refresh.
    """
    now = now or datetime.now(UTC)
    horizons = settings.rag_outcome_horizons
    ingested = await ingest()

    predictions = await _fetch_predictions()
    outcomes = await _fetch_outcomes()

    scored_by_prediction: Dict[Any, List[int]] = {}
    for outcome in outcomes:
        scored_by_prediction.setdefault(outcome.get("prediction_id"), []).append(
            outcome.get("horizon_days")
        )

    due = [
        prediction
        for prediction in predictions
        if (predicted_at := _as_utc(prediction.get("predicted_at"))) is not None
        and set(reachable_horizons(predicted_at, now=now, horizons=horizons))
        - set(scored_by_prediction.get(prediction.get("id"), []))
    ]
    # Oldest first: a horizon that came due weeks ago is the one at risk of
    # passing the give-up window while newer verdicts are served ahead of it.
    due.sort(key=lambda row: str(row.get("predicted_at") or ""))
    batch = due[: settings.TRACK_RECORD_SCORE_BATCH]

    written = 0
    for prediction in batch:
        try:
            rows = await _score_one(
                prediction,
                scored_by_prediction.get(prediction.get("id"), []),
                now=now,
                horizons=horizons,
            )
        except Exception as exc:  # noqa: BLE001
            # One unreadable symbol must not stop the pass: the rest of the
            # batch is independent of it and will be retried either way.
            logger.warning("Track record: scoring %s failed: %s", prediction.get("news_id"), exc)
            continue

        if not rows:
            continue
        written += await _insert_outcomes(rows)
        _mirror_into_store(prediction, rows)

    if ingested or written:
        logger.info(
            "Track record: %d verdicts ingested, %d horizons closed, %d still due",
            ingested,
            written,
            max(len(due) - len(batch), 0),
        )
    return {"ingested": ingested, "written": written, "due": len(due)}


async def summary() -> Dict[str, Any]:
    """The board the public page renders."""
    predictions = await _fetch_predictions()
    outcomes = await _fetch_outcomes()
    return summarise(
        predictions,
        outcomes,
        horizons=settings.rag_outcome_horizons,
        min_samples=settings.TRACK_RECORD_MIN_SAMPLES,
    )


async def list_predictions(*, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """
    Individual calls, newest first, each with whatever horizons have landed.

    The verdict is served whether or not anything has been measured yet. A list
    that showed only resolved calls would be a different and much kinder record
    than the one the summary is computed from.
    """
    predictions = await _fetch_predictions()
    outcomes = await _fetch_outcomes()

    by_prediction: Dict[Any, List[Mapping[str, Any]]] = {}
    for outcome in outcomes:
        by_prediction.setdefault(outcome.get("prediction_id"), []).append(outcome)

    window = predictions[offset : offset + limit]
    items = [
        {
            **{key: prediction.get(key) for key in CSV_COLUMNS if key in prediction},
            "outcomes": sorted(
                (
                    {
                        "horizon_days": row.get("horizon_days"),
                        "status": row.get("status"),
                        "price_change_pct": row.get("price_change_pct"),
                        "measured_direction": row.get("measured_direction"),
                        "hit": row.get("hit"),
                    }
                    for row in by_prediction.get(prediction.get("id"), [])
                ),
                key=lambda row: row["horizon_days"] or 0,
            ),
        }
        for prediction in window
    ]

    return {"items": items, "total": len(predictions), "limit": limit, "offset": offset}


async def export_rows() -> List[Dict[str, Any]]:
    """The whole record, flattened for CSV."""
    predictions = await _fetch_predictions()
    outcomes = await _fetch_outcomes()
    return csv_rows(predictions, outcomes)
