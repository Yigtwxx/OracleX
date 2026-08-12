"""
Live Router
Handles the Live tab: the event calendar, the broadcast probe, and the headline
tape that runs alongside them.

Three endpoints rather than one board, because their shelf lives differ by an
order of magnitude — the calendar is cached for fifteen minutes, the broadcast
probe for three, and the tape is read straight out of the news cache. Folding
them together would pin all three to the shortest of those.

Same house rule as the rest of the app: `UpstreamUnavailable` surfaces as a 503.
An outage must not be returned as an empty list — "nothing is live" is a claim
about the world, and the tab renders it as one.
"""

from fastapi import APIRouter, HTTPException, Query

from services.home_service import UpstreamUnavailable
from services.live_events_service import fetch_live_events
from services.live_stream_service import probe_all
from services.live_tape_service import fetch_tape
from services.streamer_service import fetch_streamers

router = APIRouter()


def _unavailable(error: UpstreamUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail=str(error))


@router.get("/api/live/events")
async def get_live_events():
    """Scheduled market-moving events, partitioned into live / upcoming / recent."""
    try:
        return await fetch_live_events()
    except UpstreamUnavailable as e:
        raise _unavailable(e) from e


@router.get("/api/live/streams")
async def get_live_streams():
    """Which curated broadcast channels are on air, and where to embed them."""
    try:
        return await probe_all()
    except UpstreamUnavailable as e:
        raise _unavailable(e) from e


@router.get("/api/live/streamers")
async def get_live_streamers():
    """
    Which market commentators are broadcasting, across YouTube and Kick.

    Status only — the rows link out rather than embedding. Probing YouTube is
    expensive, so this is built on demand and cached for ten minutes; nothing
    schedules it.
    """
    try:
        return await fetch_streamers()
    except UpstreamUnavailable as e:
        raise _unavailable(e) from e


@router.get("/api/live/tape")
async def get_live_tape(limit: int = Query(50, ge=1, le=200)):
    """
    Market-moving headlines, newest first.

    Reads the news cache the scheduler already refreshes every two minutes, so
    polling this costs nothing upstream.
    """
    return fetch_tape(limit=limit)
