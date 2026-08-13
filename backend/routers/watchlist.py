"""
Watchlist Router
Handles watchlist CRUD operations.
"""

from typing import List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class WatchlistItem(BaseModel):
    symbol: str
    type: str  # "STOCK" or "CRYPTO"


class CreateWatchlistRequest(BaseModel):
    name: str
    items: List[WatchlistItem]


@router.get("/api/home/watchlist")
async def get_watchlists_endpoint():
    try:
        from services.watchlist_service import get_watchlists

        return await get_watchlists()
    except Exception as e:
        print(f"Error getting watchlists: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/home/watchlist")
async def create_watchlist_endpoint(request: CreateWatchlistRequest):
    try:
        from services.watchlist_service import create_watchlist

        # Convert Pydantic models to dicts
        items_dict = [{"symbol": item.symbol, "type": item.type} for item in request.items]
        return await create_watchlist(request.name, items_dict)
    except Exception as e:
        print(f"Error creating watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/home/watchlist/{list_id}")
async def delete_watchlist_endpoint(list_id: str):
    try:
        from services.watchlist_service import delete_watchlist

        return await delete_watchlist(list_id)
    except Exception as e:
        print(f"Error deleting watchlist: {e}")
        raise HTTPException(status_code=500, detail=str(e))
