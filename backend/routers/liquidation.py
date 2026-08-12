"""
Liquidation Router
Handles liquidation heatmap, history, levels, and market candles.
"""

from fastapi import APIRouter, Query
from services.liquidation_map_service import get_liquidation_map
from services.liquidation_service import liquidation_service

router = APIRouter()


@router.get("/api/liquidations/heatmap")
async def get_liquidation_heatmap():
    """
    Get live liquidation heatmap data.
    Aggregated from the real-time OKX liquidation-orders WebSocket stream.
    """
    return await liquidation_service.get_heatmap_data()


@router.get("/api/liquidations/history/{symbol}")
async def get_liquidation_history(symbol: str):
    """
    Get all stored liquidation history for a specific symbol.
    Start building your heat profile from this data.
    """
    return await liquidation_service.get_liquidation_history(symbol)


@router.get("/api/liquidations/levels/{symbol}")
async def get_liquidation_levels(
    symbol: str, price_min: float, price_max: float, num_bins: int = 100
):
    """
    Get observed liquidations grouped into price bins.
    A histogram of liquidations that happened, not modelled levels —
    for the forward-looking estimate use /api/liquidations/map/{symbol}.
    """
    return await liquidation_service.get_liquidation_levels(
        symbol=symbol, price_min=price_min, price_max=price_max, num_bins=num_bins
    )


@router.get("/api/liquidations/map/{symbol}")
async def get_liquidation_map_route(
    symbol: str,
    interval: str = "1h",
    columns: int = Query(160, ge=20, le=280),
    bins: int = Query(120, ge=20, le=200),
):
    """
    Get the modelled liquidation heatmap (Coinglass-style) for a symbol.

    These are *estimated* liquidation levels derived from open interest, volume
    and the long/short ratio — not observed liquidations. See
    `services/liquidation_map_service` for the model and its assumptions.
    """
    return await get_liquidation_map(symbol, interval=interval, columns=columns, bins=bins)


@router.get("/api/market/candles/{symbol}")
async def get_market_candles(symbol: str, interval: str = "1h", limit: int = 168):
    """
    Get OHLCV candles for chart backfilling.
    Default: 1h interval, 168 candles (1 week).
    """
    return await liquidation_service.fetch_candles(symbol, interval, limit)
