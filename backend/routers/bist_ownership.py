"""
`/api/bist/ownership/*` — who holds the XU100.

Its own module rather than more of `routers/bist.py`, which is already past
fifteen hundred lines, and its own Pydantic models rather than the hand-built
dicts the rest of that realm returns: this surface mirrors `/api/ownership`,
and a reader moving between the two should meet the same shapes.

The status codes carry the same meaning as on the global board. A board that
has not been built is a 503, never an empty list — an empty grid reads as
"nobody holds anything", which is the one claim this page must never make by
accident. An unknown entity is a 404. A ticker outside the XU100 is a 404 too,
with a message that says why, because "not covered" and "nobody above 5%" are
different answers and the panel has to be able to tell them apart.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from dependencies.auth import AuthUser, get_optional_user, require_admin
from models.bist_ownership import AssetOwners, EntityDetail, Move, OwnershipBoard
from services.bist.ownership import board as board_service
from services.bist.ownership.note import build_ownership_facts, ownership_note
from services.bist.ownership.errors import (
    BistOwnershipError,
    BoardUnavailable,
    EntityNotFound,
    TickerNotCovered,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bist/ownership", tags=["bist", "ownership"])

admin_router = APIRouter(
    prefix="/api/admin/bist/ownership",
    tags=["bist", "ownership", "admin"],
    dependencies=[Depends(require_admin)],
)


def _http_error(error: BistOwnershipError) -> HTTPException:
    if isinstance(error, (EntityNotFound, TickerNotCovered)):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, BoardUnavailable):
        return HTTPException(status_code=503, detail=str(error))
    return HTTPException(status_code=503, detail="BIST ownership board is unavailable right now")


@router.get("/board", response_model=OwnershipBoard)
async def get_bist_ownership_board():
    """Every tracked holder with its XU100 stakes, valued at the latest market cap."""
    try:
        return await board_service.get_board()
    except BistOwnershipError as error:
        raise _http_error(error) from error


@router.get("/moves", response_model=list[Move])
async def get_bist_ownership_moves(
    limit: int = Query(20, ge=1, le=100),
    ticker: str | None = Query(None, description="Bare code or BIST:CODE"),
):
    """Ownership-shaped KAP filings, newest first. The one route allowed to be empty."""
    return await board_service.get_moves(limit=limit, ticker=ticker)


@router.get("/note")
async def get_bist_ownership_note(user: AuthUser | None = Depends(get_optional_user)):
    """
    What the whole board says, narrated.

    Its own route rather than a field on `/board`, for the reason every note on
    this realm is: the board is read on every visit and the paragraph is written
    once a day, so folding them together would hold the grid behind a model run.
    `facts` is null when the board is missing or too thin, and the note then
    says `insufficient_data` rather than describing an index nobody holds.
    """
    facts = await build_ownership_facts()
    return {"facts": facts, "note": await ownership_note(facts, user.id if user else None)}


@router.get("/entities/{entity_id}", response_model=EntityDetail)
async def get_bist_ownership_entity(entity_id: str):
    """One holder: every stake, the filings on those companies, and the sources."""
    try:
        return await board_service.get_entity(entity_id)
    except BistOwnershipError as error:
        raise _http_error(error) from error


@router.get("/assets/{ticker}", response_model=AssetOwners)
async def get_bist_asset_owners(ticker: str):
    """
    Who holds one company.

    Every ≥5% holder from the card, tracked or not; the registry funds whose
    latest report names the ticker; and the ownership-shaped filings on the
    KAP tape. 404 outside the XU100 rather than an empty holder list.
    """
    try:
        return await board_service.get_asset_owners(ticker)
    except BistOwnershipError as error:
        raise _http_error(error) from error


@admin_router.post("/refresh")
async def refresh_bist_ownership():
    """Rebuild the board now. Several minutes: a hundred megabyte-sized cards, sequentially."""
    try:
        report = await board_service.refresh_board()
    except BistOwnershipError as error:
        raise _http_error(error) from error
    return {
        "tickers_total": report.tickers_total,
        "tickers_ok": report.tickers_ok,
        "tickers_failed": report.tickers_failed,
        "tickers_carried": report.tickers_carried,
        "funds_total": report.funds_total,
        "funds_ok": report.funds_ok,
        "funds_failed": report.funds_failed,
        "duration_seconds": round(report.duration_seconds, 1),
    }
