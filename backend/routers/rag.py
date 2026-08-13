"""
RAG Multi-Agent Router
Handles all RAG agent endpoints: v2 (Core), v3 (Insights), v4 (Reasoning), v5 (Proactive).
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


# ═══════════════════════════════════════════════════════════════════════════════
# RAG v2 — Core (Initialization, Stats, Query)
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/api/rag/initialize")
async def initialize_rag():
    """Initialize RAG 2.0 with historical data (run once)."""
    try:
        from services.rag_v2_service import initialize_rag_v2

        stats = await initialize_rag_v2(symbols=["BTC", "ETH", "SOL"])
        return {"success": True, "stats": stats}
    except Exception as e:
        print(f"Error initializing RAG: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/rag/stats")
async def get_rag_statistics():
    """Get RAG 2.0 statistics."""
    try:
        from services.rag_v2_service import get_rag_stats

        return get_rag_stats()
    except Exception as e:
        return {"status": f"error: {str(e)}", "news_count": 0, "events_count": 0, "prices_count": 0}


@router.get("/api/rag/query")
async def query_rag_context(
    q: str,
    symbol: Optional[str] = None,
    context_type: str = "all",
    asset_type: Optional[str] = None,
):
    """
    Query RAG 2.0 for historical context.

    - q: Query text (e.g., "Bitcoin halving price behavior")
    - symbol: Filter by symbol (BTC, ETH, etc.)
    - context_type: 'all', 'events', 'prices', 'news'
    - asset_type: 'crypto' or 'stock'; keeps the two sides of the catalogue apart
    """
    try:
        from services.rag_v2_service import query_historical_context

        results = query_historical_context(
            query=q,
            symbol=symbol,
            include_events=context_type in ["all", "events"],
            include_prices=context_type in ["all", "prices"],
            include_news=context_type in ["all", "news"],
            k=5,
            asset_type=asset_type,
        )

        return {"query": q, "symbol": symbol, "results": results}
    except Exception as e:
        print(f"Error querying RAG: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# RAG v3 — Insights Agent (Faz 2)
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/rag/insights/{symbol}")
async def get_price_insights(symbol: str):
    """
    Why is this asset rising/falling?
    Correlates price movement with recent news from RAG.
    """
    try:
        from services.rag_v3_service import get_price_movement_reason

        return await get_price_movement_reason(symbol.upper())
    except Exception as e:
        print(f"Error getting insights: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class NewsSimilarityRequest(BaseModel):
    title: str
    summary: str = ""


@router.post("/api/rag/news-similarity")
async def find_news_similarity(request: NewsSimilarityRequest):
    """
    Find similar historical news and their price outcomes.
    Returns how similar past events affected prices.
    """
    try:
        from services.rag_v3_service import find_historical_news_similarity

        return await find_historical_news_similarity(request.title, request.summary)
    except Exception as e:
        print(f"Error finding news similarity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/rag/event-at-date")
async def get_event_at_date(symbol: str = "BTC", date: str = ""):
    """
    Find the most significant event near a specific date.
    Used for chart tooltip overlays.
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    try:
        from services.rag_v3_service import get_event_at_date as _get_event

        return await _get_event(symbol.upper(), date)
    except Exception as e:
        print(f"Error getting event at date: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# RAG v4 — Reasoning Agent (Faz 3)
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/rag/compare/{symbol_a}/{symbol_b}")
async def compare_two_assets(symbol_a: str, symbol_b: str):
    """
    Compare two crypto assets.
    Returns price data, events, sentiment, and patterns for both.
    """
    try:
        from services.rag_v4_service import compare_assets

        return await compare_assets(symbol_a.upper(), symbol_b.upper())
    except Exception as e:
        print(f"Error comparing assets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ScenarioRequest(BaseModel):
    scenario: str
    symbol: str = "BTC"


@router.post("/api/rag/scenario")
async def simulate_scenario_endpoint(request: ScenarioRequest):
    """
    Simulate a scenario based on historical data.
    Example: "What if Bitcoin ETF is rejected?"
    """
    try:
        from services.rag_v4_service import simulate_scenario

        return await simulate_scenario(request.scenario, request.symbol.upper())
    except Exception as e:
        print(f"Error simulating scenario: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# RAG v5 — Proactive Agent (Faz 4)
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/rag/daily-brief")
async def get_daily_brief():
    """
    Generate a comprehensive daily market briefing.
    Covers overnight movers, top news, events, and sentiment.
    """
    try:
        from services.rag_v5_service import generate_daily_brief

        return await generate_daily_brief()
    except Exception as e:
        print(f"Error generating daily brief: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/rag/anomalies")
async def detect_market_anomalies():
    """
    Detect price-news divergence anomalies.
    Flags symbols where price movement doesn't match news sentiment.
    """
    try:
        from services.rag_v5_service import detect_anomalies

        return await detect_anomalies()
    except Exception as e:
        print(f"Error detecting anomalies: {e}")
        raise HTTPException(status_code=500, detail=str(e))
