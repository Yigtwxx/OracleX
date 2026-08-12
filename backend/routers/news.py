"""
News & Analysis Router
Handles news fetching, AI sentiment analysis, technical analysis, and Ollama status.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Response, status


from models.schemas import (
    AnalysisRequest,
    NewsAnalysis,
    NewsItem,
    NewsResponse,
    SentimentAnalysis,
)
from dependencies.auth import AuthUser, get_optional_user
from services import news_analysis_store
from services.news_analysis_service import analyse_news_item, start_analysis_job
from services.news_service import fetch_all_news
from services.technical_analysis_service import get_technical_analysis
from utils import (
    log_header,
    log_step,
    log_success,
    log_warning,
    log_error,
    USE_AI,
    USE_REAL_API,
    get_news_from_cache,
    update_news_cache,
    get_news_cache,
)

router = APIRouter()


@router.get("/api/news", response_model=NewsResponse)
async def get_news(asset_type: Optional[str] = None, limit: int = 20):
    """
    Fetch latest news items.

    Serves data from memory cache (updated by background scheduler).
    If cache is empty (server just started), triggers a fetch.
    """
    # 1. Try to get from cache
    cached_dict = get_news_cache()
    items = list(cached_dict.values())

    # 2. If cache is empty, fetch immediately (fallback)
    if not items and USE_REAL_API:
        log_warning("Cache miss in /api/news - fetching synchronously...")
        try:
            items = await fetch_all_news()
            update_news_cache(items)
        except Exception as e:
            print(f"Error fetching real news: {e}")
            items = []

    # 3. If still empty, return empty list
    if not items:
        items = []

    # 4. Filter by asset type
    if asset_type:
        items = [n for n in items if n.asset_type == asset_type]

    # 5. Sort by date (newest first) just in case
    items.sort(key=lambda x: x.published_at, reverse=True)

    # 6. Pagination
    items = items[:limit]

    return NewsResponse(items=items, total=len(items))


@router.get("/api/news/{news_id}", response_model=NewsItem)
async def get_news_item(news_id: str):
    """Fetch a specific news item by ID."""
    item = get_news_from_cache(news_id)
    if item:
        return item
    raise HTTPException(status_code=404, detail="News item not found")


async def _resolve_news_item(news_id: str):
    """
    Find a news item, refreshing the cache once before giving up.

    The cache is replaced wholesale every ten minutes, so an item the user can
    still see in a stale tab may already be gone from it.
    """
    news_item = get_news_from_cache(news_id)
    if news_item:
        return news_item

    log_warning("News not in cache, fetching fresh data...")
    try:
        update_news_cache(await fetch_all_news())
        news_item = get_news_cache().get(news_id)
        if news_item:
            log_success("Found news in fresh data!")
    except Exception as e:
        log_error(f"Failed to fetch fresh news: {e}")

    if not news_item:
        log_error(f"News item not found: {news_id}")
        raise HTTPException(status_code=404, detail=f"News item not found: {news_id}")
    return news_item


def _require_ai() -> None:
    if not USE_AI:
        raise HTTPException(
            status_code=503,
            detail="AI analysis is currently unavailable. The LLM service is not enabled.",
        )


@router.post("/api/news/{news_id}/analysis/jobs", status_code=status.HTTP_202_ACCEPTED)
async def start_news_analysis(
    news_id: str,
    response: Response,
    current_price: Optional[float] = None,
    user: Optional[AuthUser] = Depends(get_optional_user),
):
    """
    Start the research note for one news item, or re-attach to the running one.

    202 for a fresh run, 200 when an identical job is already in flight — a
    double click must not fan out into two pipelines.
    """
    _require_ai()
    log_header("NEWS ANALYSIS JOB")
    log_step("📰", f"News ID: {news_id}")

    news_item = await _resolve_news_item(news_id)
    job = await start_analysis_job(
        news_item, current_price=current_price, user_id=user.id if user else None
    )
    if not job.is_active:
        response.status_code = status.HTTP_200_OK
    return job.to_dict()


@router.get("/api/news/analysis/jobs/{job_id}")
async def get_news_analysis_job(job_id: str):
    """Poll a running analysis. 404 once the job has aged out of retention."""
    from services.analysis_jobs import get_job

    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Analysis job not found or expired")
    return job.to_dict()


@router.get("/api/news/{news_id}/analysis", response_model=Optional[NewsAnalysis])
async def get_cached_news_analysis(news_id: str):
    """
    The stored note for this item, or null if none was produced under the
    current pipeline.

    Never generates: the caller decides whether to spend the tokens, and this is
    what the panel reads when a headline is opened. "Nobody has analysed this
    yet" is the ordinary answer on a first click, so it is a null body rather
    than a 404 — a 404 here made every first click log a failed request.
    """
    entry = news_analysis_store.get(news_id)
    if not entry:
        return None
    return NewsAnalysis(**entry["analysis"])


@router.post("/api/analyze", response_model=SentimentAnalysis)
async def analyze_news(
    request: AnalysisRequest, user: Optional[AuthUser] = Depends(get_optional_user)
):
    """
    Analyze a news item and wait for the result.

    Deprecated in favour of the job endpoints above, which report progress
    instead of holding the connection open for the whole pipeline. Kept so
    existing clients keep working; it returns the legacy `SentimentAnalysis`
    subset of the same note.
    """
    _require_ai()
    log_header("NEW ANALYSIS REQUEST (legacy blocking endpoint)")
    log_step("📰", f"News ID: {request.news_id}")

    news_item = await _resolve_news_item(request.news_id)
    return await analyse_news_item(
        news_item,
        current_price=request.current_price,
        user_id=user.id if user else None,
    )


@router.get("/api/symbols")
async def get_tracked_symbols():
    """Get list of all tracked symbols."""
    # Return empty list or cached symbols if available
    cached = get_news_cache()
    if cached:
        # Unattributed items carry no symbol and simply aren't tracked.
        symbols = list({item.symbol for item in cached.values() if item.symbol})
        return {"symbols": symbols}
    return {"symbols": []}


@router.get("/api/technical/{symbol}")
async def get_technical_levels(symbol: str):
    """
    Computed technical levels for a crypto pair or an equity.

    Examples: /api/technical/BTCUSDT, /api/technical/BINANCE:ETHUSDT,
    /api/technical/AAPL

    An unprefixed symbol used to be forced through the crypto path with a
    hardcoded "BINANCE:" prefix, which sent tickers like AAPL to the crypto
    branch and read them off OKX's tokenised-equity market instead of the
    exchange the ticker actually trades on. The prefix is now only added when
    the symbol is recognisably a crypto pair.

    404 when no levels could be computed — never a placeholder payload.
    """
    resolved = (
        symbol
        if ":" in symbol
        else (f"BINANCE:{symbol}" if symbol.upper().endswith("USDT") else symbol)
    )

    result = await get_technical_analysis(resolved)
    if result:
        return result
    raise HTTPException(status_code=404, detail="Technical analysis not available for this symbol")
