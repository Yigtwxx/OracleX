"""
Market Router
Handles Fear & Greed Index, market overview (crypto + NASDAQ), global indices, and heatmap data.
"""

import logging

from fastapi import APIRouter, HTTPException

from models.schemas import FearGreedData, HeatmapData, MarketOverview
from services.fear_greed_service import fetch_fear_greed_index
from services.heatmap_service import fetch_heatmap_data
from services.macro_board_service import fetch_macro_indices
from services.market_overview_service import fetch_market_overview
from services.stock_market_service import fetch_nasdaq_overview

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/fear-greed", response_model=FearGreedData)
async def get_fear_greed():
    """
    Get Crypto Fear & Greed Index from alternative.me API.

    Values: 0-25 Extreme Fear, 26-46 Fear, 47-54 Neutral, 55-75 Greed, 76-100 Extreme Greed
    """
    data = await fetch_fear_greed_index()
    if data is None:
        raise HTTPException(status_code=503, detail="Fear & Greed Index is temporarily unavailable")
    return FearGreedData(**data)


@router.get("/api/price/{symbol}")
async def get_symbol_price(symbol: str):
    """
    Current price for one symbol, crypto or equity.

    Exists so the browser does not call an exchange directly: the frontend used
    to fetch Binance from the page, which fails outright on the networks where
    Binance is blocked and also leaves the browser with no fallback. Routing it
    through the backend reuses whichever upstream actually answers.

    404 when no price could be resolved — never a placeholder number.
    """
    from services.price_service import resolve_price

    resolved = await resolve_price(symbol)
    if resolved:
        return resolved

    raise HTTPException(status_code=404, detail=f"No price available for {symbol}")


@router.get("/api/market-overview", response_model=MarketOverview)
async def get_market_overview():
    """
    Get market overview with top coin prices and global stats.

    Covers the top `TOP_COINS_COUNT` coins by market cap, resolved live from
    CoinGecko — no fixed symbol list.
    """
    data = await fetch_market_overview()
    return MarketOverview(**data)


@router.get("/api/nasdaq-overview", response_model=MarketOverview)
async def get_nasdaq_overview():
    """
    Get NASDAQ stock market overview with top stocks and Fear & Greed index.

    Covers the top `NASDAQ_TOP_COUNT` NASDAQ listings by market cap, resolved
    live from the exchange screener — no fixed symbol list.
    """
    data = await fetch_nasdaq_overview()
    return MarketOverview(**data)


@router.get("/api/market/indices")
async def get_market_indices():
    """
    Global market indices (S&P 500, NASDAQ, Nikkei, FTSE, DAX, DXY, BIST, …).

    Served from the macro board rather than its own fetch. This used to run an
    uncached, plainly-headered request per index on every call — which Yahoo
    rate-limits — and produced numbers that disagreed with the macro page by
    minutes. Sharing the board's cache fixes both, and the response shape is
    unchanged so the ticker did not have to move.

    An empty list on a total outage, not a 503: this feeds a decorative ticker
    strip that is allowed to render nothing.
    """
    try:
        return await fetch_macro_indices()
    except Exception as error:  # noqa: BLE001 — the ticker degrades to empty
        logger.warning("Global indices unavailable: %s", error)
        return []


@router.get("/api/heatmap/data", response_model=HeatmapData)
async def get_heatmap_data(limit: int = 50, include_pegged: bool = False):
    """
    Multi-metric heatmap board: price change, volume, turnover, developer.

    Answers 503 rather than an empty board when the data cannot be produced —
    a blank grid served with a 200 is indistinguishable from a market where
    nothing is listed, and the snapshot builder downstream cannot tell them
    apart either. A board recovered from the stale cache comes back as a normal
    200 carrying `stale: true` and its age.

    `include_pegged` brings back stablecoins and wrapped assets, which are
    filtered out by default: they read a flat ~0.00% every day and take the
    largest tiles on the board while saying nothing about the market.
    """
    data = await fetch_heatmap_data(
        limit=max(10, min(limit, 100)),
        include_pegged=include_pegged,
    )
    if data is None:
        raise HTTPException(status_code=503, detail="Heatmap data is temporarily unavailable")
    return HeatmapData(**data)


@router.get("/api/asset-detail/{symbol}")
async def get_asset_detail(symbol: str, type: str = "crypto"):
    """
    Get detailed asset information.

    - **crypto**: CoinGecko data (description, categories, links, ATH/ATL, supply)
    - **stock/nasdaq**: Yahoo Finance data (company info, sector, P/E, 52-week range)
    """
    from services.asset_detail_service import fetch_asset_detail

    data = await fetch_asset_detail(symbol, type)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Asset '{symbol}' not found")
    return data
