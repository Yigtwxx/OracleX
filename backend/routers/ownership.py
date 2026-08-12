"""
Ownership Router
Serves the "who holds what" board: tracked entities, their reported positions
and, from a later phase, the moves between them.

`BoardUnavailable` surfaces as a 503 rather than an empty board, for the same
reason the macro and home routers do it: a page handed `[]` renders the outage
as the claim that Strategy holds no bitcoin and Berkshire owns nothing.

An entity that exists in the registry but has no data yet is the opposite case —
that is a real answer, and it is served as 200 with `has_data: false`.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from dependencies.auth import require_admin
from models.ownership import EntityDetail, Move, OwnershipBoard
from services.ownership import consensus
from services.ownership import (
    EntityNotFound,
    OwnershipError,
    get_board,
    get_entity_detail,
    get_moves,
    refresh_ownership,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ownership", tags=["ownership"])

# Separate object so the whole thing sits behind require_admin, matching the
# admin.session_router / admin.router pair.
admin_router = APIRouter(
    prefix="/api/admin/ownership",
    tags=["ownership", "admin"],
    dependencies=[Depends(require_admin)],
)


def _http_error(error: OwnershipError) -> HTTPException:
    """Map a service error onto a status code. The only place that knows both."""
    if isinstance(error, EntityNotFound):
        return HTTPException(status_code=404, detail=str(error))
    return HTTPException(
        status_code=503,
        detail="The ownership board is unavailable right now",
    )


@router.get("/board", response_model=OwnershipBoard)
async def get_ownership_board():
    """Every tracked entity with its allocation and source badge."""
    try:
        return get_board()
    except OwnershipError as error:
        raise _http_error(error) from error


@router.get("/entities/{entity_id}", response_model=EntityDetail)
async def get_ownership_entity(entity_id: str):
    """One entity's full position list."""
    try:
        return get_entity_detail(entity_id)
    except OwnershipError as error:
        raise _http_error(error) from error


@router.get("/moves", response_model=list[Move])
async def get_ownership_moves(
    limit: int = Query(30, ge=1, le=100),
    category: str | None = None,
    entity_id: str | None = None,
):
    """
    Recent buys, sells and transfers across every tracked holder.

    The one endpoint here allowed to answer with an empty list: a quiet period
    genuinely has no moves, and saying so is a real answer rather than an
    outage dressed up as data.
    """
    try:
        return get_moves(limit=limit, category=category, entity_id=entity_id)
    except OwnershipError as error:
        raise _http_error(error) from error


@router.get("/consensus")
async def get_ownership_consensus():
    """What the tracked holders agree on: most held, most bought, most sold."""
    try:
        return consensus.consensus()
    except OwnershipError as error:
        raise _http_error(error) from error


@router.get("/assets/{symbol}")
async def get_asset_owners(symbol: str):
    """
    Every tracked holder of one asset.

    An empty list is a real answer here — nobody we follow holds it — so this
    is a 200 rather than a 404.
    """
    try:
        return {"symbol": symbol.upper(), "owners": consensus.asset_owners(symbol)}
    except OwnershipError as error:
        raise _http_error(error) from error


@router.get("/watchlist-overlap")
async def get_watchlist_overlap():
    """
    Which watched symbols the tracked holders also hold.

    Answers 200 with an empty list rather than an error when there is no
    watchlist or no overlap: the panel hides itself, and a failure here should
    never be what breaks the page.
    """
    try:
        return {"overlap": await consensus.watchlist_overlap()}
    except OwnershipError:
        return {"overlap": []}


@admin_router.post("/refresh")
async def refresh_ownership_board():
    """
    Rebuild the board now instead of waiting for the daily job.

    Admin-only because the sources behind it are rate-limited: an open endpoint
    here would be a way for anyone to spend the day's request budget.
    """
    report = await refresh_ownership()
    return {
        "entities_total": report.entities_total,
        "entities_ok": report.entities_ok,
        "sources_failed": report.sources_failed,
        "health": [s.model_dump(mode="json") for s in report.health],
    }
