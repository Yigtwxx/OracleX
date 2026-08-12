"""
Web Search Service - DuckDuckGo Search Integration
Provides real-time web search capability for Oracle AI chat.
"""

import asyncio
import os
from typing import List, Dict, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Cache for search results (5 minute TTL)
_search_cache: Dict[str, tuple] = {}
CACHE_TTL = 300  # 5 minutes

# Budget for a single DuckDuckGo round-trip.
#
# This is the bound that actually decides how long a search may take. The
# library's own default is 5s, which is short enough that a merely slow — not
# broken — backend reads as "no results" and the turn answers without any web
# context at all. The caller's asyncio timeout cannot help here: it fires on
# the coroutine while the underlying thread keeps running, so widening the
# outer bound alone would leak threads rather than buy patience.
#
# Keep this comfortably BELOW the caller's outer budget (chat_service.
# WEB_TIMEOUT), so a stalled search is reported by the library and the thread
# unwinds, instead of being abandoned mid-flight.
SEARCH_TIMEOUT = float(os.environ.get("WEB_SEARCH_TIMEOUT", "15"))


async def search_web(
    query: str, max_results: int = 5, timeout: Optional[float] = None
) -> List[Dict]:
    """
    Search the web using DuckDuckGo.

    Args:
        query: Search query string
        max_results: Maximum number of results to return
        timeout: Per-request budget in seconds; defaults to SEARCH_TIMEOUT

    Returns:
        List of search results with title, snippet, and url
    """
    budget = SEARCH_TIMEOUT if timeout is None else timeout

    # Check cache first
    cache_key = f"{query}:{max_results}"
    if cache_key in _search_cache:
        cached_time, cached_results = _search_cache[cache_key]
        if (datetime.now() - cached_time).total_seconds() < CACHE_TTL:
            return cached_results

    try:
        # Run the sync DuckDuckGo search in a thread pool
        from ddgs import DDGS

        def do_search():
            try:
                ddgs = DDGS(timeout=budget)
                results = ddgs.text(query, max_results=max_results)
                return [
                    {
                        "title": r.get("title", ""),
                        "snippet": r.get("body", ""),
                        "url": r.get("href", ""),
                    }
                    for r in results
                ]
            except Exception as e:
                logger.error(f"DDGS search failed after {budget:.0f}s budget: {e}")
                return []

        results = await asyncio.to_thread(do_search)

        # Only a hit is worth remembering. Caching an empty list would make one
        # timed-out search answer the next five minutes of identical questions
        # with silence — the opposite of what a longer budget is buying.
        if results:
            _search_cache[cache_key] = (datetime.now(), results)

        return results

    except Exception as e:
        logger.error(f"Web search error for '{query}': {e}")
        return []


async def search_crypto_news(symbol: str) -> List[Dict]:
    """
    Search for recent crypto news about a specific symbol.
    """
    query = f"{symbol} cryptocurrency news today {datetime.now().strftime('%B %Y')}"
    return await search_web(query, max_results=3)


async def search_market_analysis(symbol: str) -> List[Dict]:
    """
    Search for market analysis and price predictions.
    """
    query = f"{symbol} price analysis technical analysis {datetime.now().strftime('%B %Y')}"
    return await search_web(query, max_results=3)


async def search_general_finance(query: str) -> List[Dict]:
    """
    Search for general financial information.
    """
    finance_query = f"{query} finance market {datetime.now().strftime('%Y')}"
    return await search_web(finance_query, max_results=4)


def _render_results(heading: str, results: List[Dict], limit: int) -> List[str]:
    """
    Format search hits for a prompt, carrying the source URL through.

    The URL is not decoration: the assistant is required to cite web claims as
    `[Source](url)`, and it can only do that honestly if the link reaches it.
    """
    if not results:
        return []

    lines = [f"\n**{heading}**"]
    for i, r in enumerate(results[:limit], 1):
        url = r.get("url") or ""
        lines.append(f"{i}. {r.get('title', '')}" + (f" — {url}" if url else ""))
        snippet = r.get("snippet") or ""
        if snippet:
            lines.append(f"   → {snippet[:250]}")
    return lines


async def get_enhanced_context(user_message: str, detected_symbol: Optional[str] = None) -> str:
    """
    Build enhanced context from web searches based on user message.

    Returns formatted string with web search results.
    """
    context_parts: List[str] = []

    try:
        # If a specific symbol is detected, search for it
        if detected_symbol:
            news_results, analysis_results = await asyncio.gather(
                search_crypto_news(detected_symbol),
                search_market_analysis(detected_symbol),
            )
            context_parts += _render_results(
                f"{detected_symbol} — recent web headlines", news_results, 3
            )
            context_parts += _render_results(
                f"{detected_symbol} — web analysis", analysis_results, 2
            )
        else:
            # General financial search based on user message
            general_results = await search_general_finance(user_message)
            context_parts += _render_results("Web search results", general_results, 3)

        if context_parts:
            return "\n".join(context_parts)
        return ""

    except Exception as e:
        logger.error(f"Error building enhanced context: {e}")
        return ""
