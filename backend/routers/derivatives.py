"""
Derivatives Router.

Open interest against price, per venue and aggregated — the input the
liquidation map models from, finally visible on its own.
"""

from typing import Literal

from fastapi import APIRouter, Query
from services.dex_perps_service import get_dex_perps
from services.open_interest_service import get_open_interest

router = APIRouter()


@router.get("/api/derivatives/open-interest/{symbol}")
async def open_interest(
    symbol: str,
    interval: Literal["1h", "4h", "1d"] = "1d",
    limit: int = Query(400, ge=20, le=2000),
):
    """
    Open interest per exchange, aligned index-for-index with price candles.

    `source` says which provider answered: `coinalyze` reaches back years on the
    daily series, `venues` is the exchanges' own ~30-day statistics endpoints.
    The returned `interval` reports what was actually served, which can be
    coarser than the one asked for when a provider does not publish it.
    """
    return await get_open_interest(symbol, interval, limit)


@router.get("/api/derivatives/dex-perps")
async def dex_perps() -> dict:
    """
    On-chain perpetual venues ranked by open interest, 24h volume and TVL.

    Three independent rankings rather than one table: `sources` names the
    provider behind each, and `stale` marks a panel replaying its last good rows
    because that provider is down. An empty panel with an `unavailable` source
    is a missing measurement, never a venue holding nothing.
    """
    return await get_dex_perps()
