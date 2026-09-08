"""
Track Record Router — what the terminal predicted, and what happened next.

Public and unauthenticated, which is the one thing about this router worth
arguing for. Every other user-facing surface here is scoped to a caller by
`get_current_user`; a record of the terminal's own accuracy that only its owner
could read would be a private note, not a record. There is nothing per-user in
these tables to protect, and the whole point of publishing the number is that
somebody who has not signed up can check it.

Routes:

    GET  summary        hit rate per horizon, with n and the base rate beside it
    GET  predictions    the individual calls, newest first, paged
    GET  export.csv     the whole record, one row per (call, horizon)

The router shapes and does not compute: everything the numbers mean lives in
`services/track_record`, including the refusal to print a rate over too few
samples.
"""

import csv
import io
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services import track_record
from services.track_record import TrackRecordError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/track-record", tags=["track-record"])

# A ceiling on one page of calls. The board itself is small, but the parameter
# is caller-controlled and an unbounded page is an unbounded response.
MAX_PAGE = 200


class HorizonBucket(BaseModel):
    """One horizon's scored calls. `hit_rate` is null below the sample floor."""

    horizon_days: int
    n: int
    hits: int
    hit_rate: Optional[float] = None


class PredictionOutcome(BaseModel):
    horizon_days: Optional[int] = None
    status: Optional[str] = None
    price_change_pct: Optional[float] = None
    measured_direction: Optional[str] = None
    hit: Optional[bool] = None


class PredictionItem(BaseModel):
    news_id: Optional[str] = None
    pipeline_version: Optional[str] = None
    symbol: Optional[str] = None
    asset_type: Optional[str] = None
    predicted_direction: Optional[str] = None
    confidence: Optional[float] = None
    materiality: Optional[str] = None
    model: Optional[str] = None
    verdict_source: Optional[str] = None
    predicted_at: Optional[str] = None
    published_at: Optional[str] = None
    outcomes: List[PredictionOutcome] = []


class PredictionsResponse(BaseModel):
    items: List[PredictionItem]
    total: int
    limit: int
    offset: int


def _unavailable(exc: Exception) -> HTTPException:
    """
    503 rather than 500, and never the upstream's own words.

    The record is a database read with no fallback worth serving: a page that
    rendered zeros because the query failed would be a claim about the model's
    accuracy, which is precisely the thing this feature exists not to invent.
    """
    logger.error("Track record unavailable: %s", exc)
    return HTTPException(status_code=503, detail="The track record is temporarily unavailable.")


@router.get("/summary")
async def get_summary() -> Dict[str, Any]:
    """Hit rate per horizon, the base rate beside it, and what was excluded."""
    try:
        return await track_record.summary()
    except TrackRecordError as exc:
        raise _unavailable(exc) from exc


@router.get("/predictions", response_model=PredictionsResponse)
async def get_predictions(
    limit: int = Query(50, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """The individual calls, newest first, resolved or not."""
    try:
        return await track_record.list_predictions(limit=limit, offset=offset)
    except TrackRecordError as exc:
        raise _unavailable(exc) from exc


@router.get("/export.csv")
async def export_csv() -> StreamingResponse:
    """
    The whole record as CSV — the "exportable" half of an append-only record.

    Streamed rather than assembled into a string: the row count grows without
    bound over the life of an install, and this is the one route that returns
    all of it.
    """
    try:
        rows = await track_record.export_rows()
    except TrackRecordError as exc:
        raise _unavailable(exc) from exc

    def _stream() -> Any:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(track_record.CSV_COLUMNS))
        writer.writeheader()
        yield buffer.getvalue()
        for row in rows:
            buffer.seek(0)
            buffer.truncate(0)
            writer.writerow({key: row.get(key) for key in track_record.CSV_COLUMNS})
            yield buffer.getvalue()

    return StreamingResponse(
        _stream(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="oracle-x-track-record.csv"'},
    )
