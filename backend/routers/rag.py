"""
RAG Multi-Agent Router
Handles all RAG agent endpoints: v2 (Core), v3 (Insights), v4 (Reasoning), v5 (Proactive).

Two conventions here that the rest of this file used to break, both for the
same underlying reason: this surface has no frontend caller. It is read by the
MCP server and the agent skills, so a failure produces no blank panel anyone
notices — which makes the log line and the status code the only signals there
are.

So every handler reports through `logger` rather than `print`. `print` writes
straight to stdout and bypasses the `LOG_LEVEL` handler `main.py` configures,
which meant a total RAG outage left no line at the configured level anywhere.

And no handler returns `str(e)` to the caller. A ChromaDB or embedding error
carries paths and host detail that a caller has no business seeing, and the
exception text is in the log for whoever is actually debugging it.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from dependencies.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter()

# Every RAG path ends at the same vector store, so a failure is the same
# failure: the store is unreachable or the embedding model will not load. 503
# rather than 500 — this is an upstream that may be back shortly, and it is
# what the rest of the codebase answers for the same situation.
_UNAVAILABLE = HTTPException(status_code=503, detail="The RAG index is unavailable right now")


# ═══════════════════════════════════════════════════════════════════════════════
# RAG v2 — Core (Initialization, Stats, Query)
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/api/rag/initialize", dependencies=[Depends(require_admin)])
async def initialize_rag():
    """
    Initialize RAG 2.0 with historical data (run once).

    Admin-only, and it was the one expensive rebuild in the codebase that was
    not. This embeds the whole historical corpus: it pins the embedding model
    and holds the event loop for as long as that takes, so an open endpoint was
    a way for any unauthenticated caller to keep the terminal busy by asking
    twice. Its siblings — `/api/admin/ownership/refresh`, the BIST board
    rebuild — have been behind `require_admin` since they were written, and the
    radar scan is rate-limited; this is the same reasoning applied to the same
    shape of operation.
    """
    try:
        from services.rag_v2_service import initialize_rag_v2

        stats = await initialize_rag_v2(symbols=["BTC", "ETH", "SOL"])
        return {"success": True, "stats": stats}
    except Exception as e:
        logger.error("RAG initialize failed: %s", e)
        raise _UNAVAILABLE from e


@router.get("/api/rag/stats")
async def get_rag_statistics():
    """Get RAG 2.0 statistics."""
    try:
        from services.rag_v2_service import get_rag_stats

        return get_rag_stats()
    except Exception as e:
        # Not a 200 with zeroes. `agent-skill/oracle-x-api/references/recipes.md`
        # tells an agent to call this "when a query comes back thin", so an
        # unreachable store answering `news_count: 0` reads as "the corpus is
        # legitimately empty" — the agent then reports a confident absence of
        # evidence rather than an outage it could have retried.
        logger.error("RAG stats failed: %s", e)
        raise _UNAVAILABLE from e


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
        logger.error("Error querying RAG: %s", e)
        raise _UNAVAILABLE from e


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
        logger.error("Error getting insights: %s", e)
        raise _UNAVAILABLE from e


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
        logger.error("Error finding news similarity: %s", e)
        raise _UNAVAILABLE from e


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
        logger.error("Error getting event at date: %s", e)
        raise _UNAVAILABLE from e


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
        logger.error("Error comparing assets: %s", e)
        raise _UNAVAILABLE from e


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
        logger.error("Error simulating scenario: %s", e)
        raise _UNAVAILABLE from e


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
        logger.error("Error generating daily brief: %s", e)
        raise _UNAVAILABLE from e


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
        logger.error("Error detecting anomalies: %s", e)
        raise _UNAVAILABLE from e
