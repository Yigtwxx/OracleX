"""
Chains Router
Serves the Chains tab: one board carrying every chain's cadence, load, fees and
economics, plus the daily exchange-flow strip.

One endpoint rather than several, which is the opposite of what the Live router
does — and for the same reason. There the three payloads had shelf lives an
order of magnitude apart, so folding them together would have pinned all three
to the shortest. Here every reading is a live network measurement on the same
ten-second cache, and the block streams the page renders come out of the very
requests that produced the headline numbers. Splitting them would mean fetching
the same blocks twice.

House rule holds: an outage is never returned as an empty board. Unlike the
other tabs it also does not 503, because this board is eight independent
providers and can be partly right — a chain that failed carries `error` on its
own row while the other seven report normally.
"""

from fastapi import APIRouter, Depends

from dependencies.auth import AuthUser, get_optional_user

from services.chains.anomaly import anomaly_note, detect
from services.chains.service import fetch_board, stale_board

router = APIRouter()


@router.get("/api/chains/board")
async def get_chains_board():
    """
    Every chain's current state: height, cadence, load, fees and economics, with
    the last blocks each one produced.

    `fetch_board` does not raise, so the guard here is for the unexpected rather
    than for upstream failure — and even then it replays the last good board
    before giving up, since a two-minute-old set of heights is far closer to the
    truth than nothing.
    """
    try:
        return await fetch_board()
    except Exception:  # noqa: BLE001 — the board must not take the tab down
        stale = stale_board()
        if stale is not None:
            return stale
        raise


@router.get("/api/chains/anomalies")
async def get_chain_anomalies(user: AuthUser | None = Depends(get_optional_user)):
    """
    What on the board is not normal, and a note explaining why they co-occur.

    A second endpoint, on a router whose docstring argues for one — and for the
    same reason it argues that. The board is folded together because every
    reading on it shares a ten-second cache and comes out of the same requests.
    These do not: they are measured against days of history and the note is held
    for an hour, so folding them in would ship one hourly artifact on all three
    hundred and sixty board polls an hour and pin it to a ten-second cache.

    `anomalies` is computed in Python and is the product; the note is commentary
    on it. An unreachable model costs the sentence, never the detection.
    """
    try:
        board = await fetch_board()
    except Exception:  # noqa: BLE001 — same stance as the board: never take the tab down
        board = stale_board() or {}

    detection = detect(board)
    return {**detection, "note": await anomaly_note(detection, user.id if user else None)}
