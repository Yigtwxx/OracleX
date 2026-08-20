"""
Watchlist Router
Handles watchlist CRUD operations.

Every endpoint here requires a verified caller. It did not used to: all three
were open, and the store behind them was one shared file with no `user_id` in
it, so any client could read and delete every account's lists. Fixing the store
without closing the endpoints would have moved the leak rather than removed it.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dependencies.auth import AuthUser, get_current_user
from utils import log_warning

router = APIRouter()


class WatchlistItem(BaseModel):
    symbol: str
    type: str  # "STOCK" or "CRYPTO"


class CreateWatchlistRequest(BaseModel):
    name: str
    items: List[WatchlistItem]


@router.get("/api/home/watchlist")
async def get_watchlists_endpoint(user: AuthUser = Depends(get_current_user)):
    from services.watchlist_service import get_watchlists

    try:
        return await get_watchlists(user.id)
    except Exception as e:
        log_warning(f"Watchlist read failed: {e}")
        raise HTTPException(status_code=503, detail="Watchlists are unavailable right now")


@router.post("/api/home/watchlist")
async def create_watchlist_endpoint(
    request: CreateWatchlistRequest, user: AuthUser = Depends(get_current_user)
):
    from services.watchlist_service import create_watchlist

    items = [{"symbol": item.symbol, "type": item.type} for item in request.items]
    try:
        return await create_watchlist(user.id, request.name, items)
    except Exception as e:
        log_warning(f"Watchlist create failed: {e}")
        raise HTTPException(status_code=503, detail="The watchlist could not be created")


@router.delete("/api/home/watchlist/{list_id}")
async def delete_watchlist_endpoint(list_id: str, user: AuthUser = Depends(get_current_user)):
    """
    Delete one of the caller's watchlists.

    The service scopes the delete by `user_id` as well as by id — the backend
    holds the service-role key, so a delete without that filter would take any
    list whose id was guessed. 404 is never returned for someone else's list
    because the query simply matches nothing.
    """
    from services.watchlist_service import delete_watchlist

    try:
        return await delete_watchlist(user.id, list_id)
    except Exception as e:
        log_warning(f"Watchlist delete failed: {e}")
        raise HTTPException(status_code=503, detail="The watchlist could not be deleted")
