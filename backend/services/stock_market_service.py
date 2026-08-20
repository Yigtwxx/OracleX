"""Stock Market Overview service using httpx for NASDAQ stocks."""

import hashlib
import logging
import httpx
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import quote
import asyncio

from services import asset_registry
from services.asset_registry import GLOBAL_INDICES
from services.cache import market_cache
from services.http_client import get_json_impersonated
from services.series import downsample

logger = logging.getLogger(__name__)

CACHE_DURATION_SECONDS = 120  # 2 minutes
FEAR_GREED_CACHE_DURATION = 600  # 10 minutes

# How many NASDAQ stocks the overview page ranks. The tickers themselves come
# from asset_registry, so a stock climbing into the top ranks appears on its own.
# All 250 are quoted from the exchange screener in a single request, which is
# what makes this count affordable.
NASDAQ_TOP_COUNT = 250

# yfinance costs one request per ticker, so it only enriches the head of the
# list, where a fresher intraday price is actually worth the latency. The rest
# of the table keeps its screener quote.
YF_ENRICH_COUNT = 30


# Daily bars pulled for equity technical analysis. Six months comfortably covers
# the 30-period trend window and the 14-period ATR/RSI even across market holidays.
CANDLE_RANGE = "6mo"
CANDLE_CACHE_DURATION = 900  # 15 minutes — daily bars only change once a day

# Windows over past sessions are settled history: what NVDA did in January 2025
# is not going to change. Cached for a day so re-indexing the event catalogue
# does not re-fetch the same years of bars.
HISTORY_WINDOW_CACHE_DURATION = 86400  # 24 hours


# The overview table's "Last 7 Days" column. Yahoo's spark endpoint is the only
# batched source of recent closes, which is what makes a series for all 250 rows
# affordable: 13 requests instead of 250. It rejects anything above 20 symbols
# with a 400, so the universe is chunked to that ceiling.
SPARKLINE_BATCH_SIZE = 20
SPARKLINE_RANGE = "7d"

# Hourly rather than daily bars. The daily series carries only ~5 points over a
# week and leaves the current session null until it closes, which draws as a
# flat stub; hourly gives the line a real shape and ends on the live price.
SPARKLINE_INTERVAL = "1h"

# Longer than the overview's own TTL: a week-long line does not visibly change
# in two minutes, so this spares Yahoo four fetches out of five.
SPARKLINE_CACHE_DURATION = 600  # 10 minutes


def get_stock_logo(symbol: str) -> str:
    """Get logo URL for a stock symbol (delegates to the shared registry)."""
    return asset_registry.build_stock_logo_url(symbol)


def _chart_to_candles(payload: dict) -> list[dict]:
    """
    Convert a Yahoo v8 chart payload into the shared candle dict shape.

    Yahoo returns parallel arrays with `null` in every series for sessions it
    has no data for (holidays, halts). Those rows are dropped rather than
    carried forward or zero-filled.
    """
    try:
        result = payload["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError):
        return []

    candles = []
    for i, ts in enumerate(timestamps):
        try:
            close = quote["close"][i]
            open_ = quote["open"][i]
            high = quote["high"][i]
            low = quote["low"][i]
            volume = quote["volume"][i] or 0
            if None in (close, open_, high, low):
                continue
            candles.append(
                {
                    "time": int(ts),
                    "open": float(open_),
                    "high": float(high),
                    "low": float(low),
                    "close": float(close),
                    "volume": float(volume),
                    "volume_usd": float(volume) * float(close),
                }
            )
        except (KeyError, IndexError, TypeError, ValueError):
            continue

    return candles


def _yfinance_candles(symbol: str, interval: str, period: str = CANDLE_RANGE) -> list[dict]:
    """Same bars via yfinance, used only when the chart endpoint comes back empty."""
    import yfinance as yf

    history = yf.Ticker(symbol).history(period=period, interval=interval)
    if history is None or history.empty:
        return []

    candles = []
    for timestamp, row in history.iterrows():
        try:
            close = float(row["Close"])
            volume = float(row["Volume"])
            candles.append(
                {
                    "time": int(timestamp.timestamp()),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": close,
                    "volume": volume,
                    "volume_usd": volume * close,
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return candles


def _yfinance_candles_between(symbol: str, start_ms: int, end_ms: int, interval: str) -> list[dict]:
    """Same as `_yfinance_candles`, but for an explicit window rather than a period."""
    import yfinance as yf

    history = yf.Ticker(symbol).history(
        start=datetime.utcfromtimestamp(start_ms / 1000).date(),
        end=datetime.utcfromtimestamp(end_ms / 1000).date(),
        interval=interval,
    )
    if history is None or history.empty:
        return []

    candles = []
    for timestamp, row in history.iterrows():
        try:
            close = float(row["Close"])
            volume = float(row["Volume"])
            candles.append(
                {
                    "time": int(timestamp.timestamp()),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": close,
                    "volume": volume,
                    "volume_usd": volume * close,
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return candles


async def fetch_stock_candles_between(
    symbol: str, start_ms: int, end_ms: int, interval: str = "1d"
) -> list[dict]:
    """
    Daily bars inside a fixed date window, oldest-first.

    The equity counterpart to `okx_market.fetch_candles_between`, and the reason
    it exists: `fetch_stock_candles` is pinned to `CANDLE_RANGE` ("6mo"), which
    is right for technical analysis and useless for asking what a 2020 event did
    to a price. Rather than widen that call — every technical-analysis caller
    would start pulling years of bars it does not read — this asks Yahoo for the
    window directly via `period1`/`period2`.

    Same fetch chain and the same candle shape as its sibling, so callers can
    treat crypto and equity history identically. Empty list when Yahoo has no
    data for the window; never a synthesised series.
    """
    if end_ms <= start_ms:
        return []

    period1, period2 = int(start_ms / 1000), int(end_ms / 1000)
    cache_key = f"stock_window_{symbol.upper()}_{interval}_{period1}_{period2}"
    cached = market_cache.get(cache_key)
    if cached is not None:
        return cached

    candles: list[dict] = []
    try:
        payload = await get_json_impersonated(
            # Index tickers carry a caret ("^IXIC"), which has to be escaped to
            # survive the path.
            f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}",
            params={"period1": period1, "period2": period2, "interval": interval},
            timeout=20.0,
        )
        candles = _chart_to_candles(payload)
    except Exception as e:
        logger.warning("Yahoo window unavailable for %s: %s", symbol, e)

    if not candles:
        try:
            candles = await asyncio.to_thread(
                _yfinance_candles_between, symbol, start_ms, end_ms, interval
            )
        except Exception as e:
            logger.warning("yfinance window unavailable for %s: %s", symbol, e)

    if not candles:
        return []

    # A closed window over past sessions does not change, so this is cached for
    # far longer than the rolling `fetch_stock_candles` view.
    market_cache.set(cache_key, candles, HISTORY_WINDOW_CACHE_DURATION)
    return candles


async def fetch_stock_candles(
    symbol: str, interval: str = "1d", range_: str = CANDLE_RANGE
) -> list[dict]:
    """
    OHLCV bars for an equity or index, oldest-first.

    `range_` is Yahoo's period parameter and defaults to `CANDLE_RANGE`, which is
    what a single-timeframe technical read needs. The multi-timeframe read asks
    for two years of daily and weekly bars through the same call rather than a
    second fetcher — Yahoo takes the window as a parameter, and one cache key per
    (symbol, interval, range) keeps the wider request from evicting the narrow one.

    Yahoo's chart endpoint answers "Too Many Requests" to ordinary HTTP clients
    no matter what User-Agent they send — it fingerprints the TLS handshake — so
    this goes through the impersonating client, with yfinance as a second try.

    Returns the same candle shape as `okx_market.fetch_candles`, so the technical
    analysis code path is identical for crypto and equities. Empty list when
    Yahoo has no history — never a synthesised series.
    """
    cache_key = f"stock_candles_{symbol.upper()}_{interval}_{range_}"
    cached = market_cache.get(cache_key)
    if cached is not None:
        return cached

    candles: list[dict] = []
    try:
        payload = await get_json_impersonated(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"range": range_, "interval": interval},
            timeout=20.0,
        )
        candles = _chart_to_candles(payload)
    except Exception as e:
        logger.warning("Yahoo chart unavailable for %s: %s", symbol, e)

    if not candles:
        # yfinance performs its own cookie/crumb handshake and sometimes gets
        # through when the chart endpoint does not. It is synchronous, hence the
        # thread.
        try:
            candles = await asyncio.to_thread(_yfinance_candles, symbol, interval, range_)
        except Exception as e:
            logger.warning("yfinance candles unavailable for %s: %s", symbol, e)

    if not candles:
        stale = market_cache.get_with_fallback(cache_key)
        return stale if stale else []

    market_cache.set(cache_key, candles, CANDLE_CACHE_DURATION)
    return candles


async def fetch_single_stock(client: httpx.AsyncClient, symbol: str) -> Optional[dict]:
    """
    Fetch single stock data from Yahoo Finance v8 chart API.
    Returns real-time price, change, volume and market cap.
    """
    try:
        # v8 chart API (v7 quote API is now deprecated/unauthorized). It answers
        # "Too Many Requests" to ordinary clients regardless of User-Agent, so
        # this goes through the impersonating client. `client` is kept in the
        # signature because every caller passes a shared session.
        data = await get_json_impersonated(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"interval": "1d", "range": "2d"},
            timeout=15.0,
        )

        if data:
            chart = data.get("chart", {})
            results = chart.get("result", [])

            if results:
                meta = results[0].get("meta", {})

                price = meta.get("regularMarketPrice", 0) or 0
                prev_close = (
                    meta.get("chartPreviousClose", 0) or meta.get("previousClose", 0) or price
                )
                change = ((price - prev_close) / prev_close * 100) if prev_close and price else 0
                volume = meta.get("regularMarketVolume", 0) or 0
                high = meta.get("regularMarketDayHigh", 0) or 0
                low = meta.get("regularMarketDayLow", 0) or 0
                fifty_two_week_high = meta.get("fiftyTwoWeekHigh", high) or high
                fifty_two_week_low = meta.get("fiftyTwoWeekLow", low) or low

                # Prefer the registry's name/sector, then whatever Yahoo returned.
                registry_meta = await asset_registry.get_stock_metadata()
                stock_meta = registry_meta.get(symbol) or {
                    "name": meta.get("longName") or meta.get("shortName") or symbol,
                    "sector": "Other",
                }

                # Market cap comes from the NASDAQ screener the registry already
                # holds, so no extra request is needed. Yahoo's v8 chart meta only
                # carries sharesOutstanding, which is the fallback.
                market_cap = stock_meta.get("market_cap") or 0
                if market_cap == 0:
                    shares = meta.get("sharesOutstanding", 0) or 0
                    if shares > 0 and price > 0:
                        market_cap = price * shares

                return {
                    "symbol": symbol,
                    "name": stock_meta["name"],
                    "sector": stock_meta.get("sector", "Other"),
                    "logo": get_stock_logo(symbol),
                    "price": float(price),
                    "change_24h": round(float(change), 2),
                    "volume_24h": float(volume * price) if price else 0,
                    "high_24h": float(high),
                    "low_24h": float(low),
                    "market_cap": float(market_cap),
                    "market_cap_rank": 0,
                    "fifty_two_week_high": float(fifty_two_week_high),
                    "fifty_two_week_low": float(fifty_two_week_low),
                }
    except Exception as e:
        logger.warning("Error fetching %s: %s", symbol, e)

    return None


def get_market_status() -> dict:
    """
    Get current NASDAQ market status (US Eastern Time).
    """
    import pytz  # type: ignore

    try:
        # Define timezones
        tz_ny = pytz.timezone("America/New_York")
        now_ny = datetime.now(tz_ny)

        # Check weekend
        if now_ny.weekday() >= 5:  # 5=Saturday, 6=Sunday
            return {
                "status": "Closed",
                "message": "🔴 Closed (Weekend)",
                "color": "red",
                "next_event": "Opens Mon 09:30 ET",
            }

        # Convert to Minutes from Midnight for easy comparison
        current_minutes = now_ny.hour * 60 + now_ny.minute

        # Market Hours (in minutes)
        # Pre-market: 04:00 (240) - 09:30 (570)
        # Open: 09:30 (570) - 16:00 (960)
        # After-hours: 16:00 (960) - 20:00 (1200)

        pre_market_start = 4 * 60
        open_start = 9 * 60 + 30
        close_start = 16 * 60
        after_hours_end = 20 * 60

        if pre_market_start <= current_minutes < open_start:
            # Pre-market
            minutes_to_open = open_start - current_minutes
            hrs = minutes_to_open // 60
            mins = minutes_to_open % 60
            return {
                "status": "Pre-market",
                "message": f"🟠 Pre-market • Opens in {hrs}h {mins}m",
                "color": "orange",
                "next_event": "Market Opens 09:30 ET",
            }

        elif open_start <= current_minutes < close_start:
            # Market Open
            minutes_to_close = close_start - current_minutes
            hrs = minutes_to_close // 60
            mins = minutes_to_close % 60
            return {
                "status": "Open",
                "message": f"🟢 Market Open • Closes in {hrs}h {mins}m",
                "color": "green",
                "next_event": "Closes 16:00 ET",
            }

        elif close_start <= current_minutes < after_hours_end:
            # After-hours
            return {
                "status": "After-hours",
                "message": "🌙 After-hours",
                "color": "blue",
                "next_event": "Pre-market 04:00 ET",
            }

        else:
            # Closed (Night)
            return {
                "status": "Closed",
                "message": "🔴 Closed",
                "color": "red",
                "next_event": "Pre-market 04:00 ET",
            }

    except Exception as e:
        logger.error("Error determining market status: %s", e)
        return {"status": "Unknown", "message": "--", "color": "gray", "next_event": ""}


def _enrich_one(ticker: Any) -> Optional[dict]:
    """
    Fresher intraday numbers for one ticker, or None if it has nothing better.

    Blocking — each `fast_info` attribute access can hit the network. Only
    `fast_info` is touched: `ticker.info` issues a second, far slower request
    and everything it used to supply here comes from `fast_info` or the
    screener. A `None` field means "no improvement on the screener value".
    """
    fast = ticker.fast_info
    price = fast.last_price
    if not price or price <= 0:
        return None

    prev_close = fast.previous_close
    volume = fast.last_volume or 0

    return {
        "price": float(price),
        "change_24h": float((price - prev_close) / prev_close * 100) if prev_close else None,
        "volume_24h": float(volume) * float(price) if volume else None,
        "high_24h": float(fast.day_high or price),
        "low_24h": float(fast.day_low or price),
        "market_cap": float(fast.market_cap) if fast.market_cap else None,
        "fifty_two_week_high": float(fast.year_high or 0),
        "fifty_two_week_low": float(fast.year_low or 0),
    }


async def _enrich_with_yfinance(symbols: list[str]) -> dict[str, dict]:
    """
    Fresher intraday numbers for `symbols`, keyed by symbol.

    One request per ticker, so they run concurrently on the default executor —
    sequentially this costs ~0.6s each, which alone was most of the endpoint's
    cold-start latency. Symbols that fail are simply absent from the result,
    leaving the caller's screener values in place.
    """
    try:
        import yfinance as yf

        tickers = yf.Tickers(" ".join(symbols))
    except Exception as e:
        logger.warning("yfinance unavailable: %s", e)
        return {}

    resolved = [tickers.tickers.get(symbol) for symbol in symbols]
    results = await asyncio.gather(
        *(
            asyncio.to_thread(_enrich_one, ticker)
            if ticker is not None
            else asyncio.sleep(0, result=None)
            for ticker in resolved
        ),
        # One bad ticker must not cost the others their enrichment.
        return_exceptions=True,
    )

    return {
        symbol: result
        for symbol, result in zip(symbols, results)
        if isinstance(result, dict) and result
    }


def _spark_series(payload: dict) -> dict[str, list[float]]:
    """
    Pull one thinned close series per symbol out of a spark response.

    Yahoo pads the series with `null` for sessions it has no print for (holidays,
    halts, and the current session before it settles). Those are dropped rather
    than carried forward, same as `_chart_to_candles`. A symbol that ends up with
    fewer than two usable closes is left out entirely — one point is not a line.
    """
    series: dict[str, list[float]] = {}

    for item in (payload.get("spark") or {}).get("result") or []:
        symbol = item.get("symbol")
        responses = item.get("response") or []
        if not symbol or not responses:
            continue
        try:
            quote = (responses[0]["indicators"]["quote"] or [{}])[0]
            closes = [float(c) for c in (quote.get("close") or []) if c is not None]
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if len(closes) > 1:
            series[symbol] = downsample(closes)

    return series


async def fetch_stock_sparklines(symbols: list[str]) -> dict[str, list[float]]:
    """
    Seven-day close series for `symbols`, keyed by symbol.

    Symbols Yahoo has no week of history for are simply absent, so the caller
    renders those rows without a chart instead of drawing an invented one. An
    outage yields the last good map if one is still recent, otherwise an empty
    map — never a synthesised series.
    """
    if not symbols:
        return {}

    # Keyed by the exact symbol set: the universe is re-ranked on its own
    # schedule, and a stock that has just climbed into it deserves a fetch
    # rather than ten minutes of blank chart.
    digest = hashlib.blake2s(",".join(sorted(symbols)).encode(), digest_size=8).hexdigest()
    cache_key = f"stock_sparklines_{digest}"
    cached = market_cache.get(cache_key)
    if cached is not None:
        return cached

    batches = [
        symbols[i : i + SPARKLINE_BATCH_SIZE] for i in range(0, len(symbols), SPARKLINE_BATCH_SIZE)
    ]
    payloads = await asyncio.gather(
        *(
            get_json_impersonated(
                "https://query1.finance.yahoo.com/v7/finance/spark",
                params={
                    "symbols": ",".join(batch),
                    "range": SPARKLINE_RANGE,
                    "interval": SPARKLINE_INTERVAL,
                },
                timeout=20.0,
            )
            for batch in batches
        ),
        # One rejected chunk must not cost the other twelve their series.
        return_exceptions=True,
    )

    series: dict[str, list[float]] = {}
    for payload in payloads:
        if isinstance(payload, Exception):
            logger.warning("Yahoo spark batch failed: %s", payload)
            continue
        series.update(_spark_series(payload))

    if not series:
        stale = market_cache.get_with_fallback(cache_key)
        return stale if stale else {}

    market_cache.set(cache_key, series, SPARKLINE_CACHE_DURATION)
    return series


async def fetch_nasdaq_overview() -> dict:
    """
    Fetch NASDAQ stock overview data.

    The exchange screener quotes the whole top-`NASDAQ_TOP_COUNT` in one request,
    so it is the primary source. yfinance then refreshes the head of the list,
    and the Yahoo v8 chart API is the last resort if the screener produced
    nothing at all.
    """
    # Check cache first — always refresh market_status since it's time-dependent
    cached = market_cache.get("stock_overview")
    if cached is not None:
        cached_data = cached.copy()
        cached_data["market_status"] = get_market_status()
        return cached_data

    stocks_data = []
    total_volume = 0
    total_market_cap = 0

    # Top NASDAQ listings by market cap, resolved live from the exchange
    # screener. The ranking and the quotes are independent cache entries, so
    # a cold start resolves them side by side rather than back to back.
    universe, quotes = await asyncio.gather(
        asset_registry.get_stock_universe(NASDAQ_TOP_COUNT),
        asset_registry.get_stock_quotes(),
    )
    nasdaq_stocks = [stock["symbol"] for stock in universe]

    for stock in universe:
        symbol = stock["symbol"]
        quote_row = quotes.get(symbol) or {}
        price = quote_row.get("price", 0.0)
        if price <= 0:
            # No quote and no price to invent — the row is dropped rather than
            # rendered at $0.
            continue

        share_volume = quote_row.get("volume", 0.0)
        stocks_data.append(
            {
                "symbol": symbol,
                "name": stock.get("name", symbol),
                "sector": stock.get("sector", "Other"),
                "logo": get_stock_logo(symbol),
                "price": price,
                "change_24h": quote_row.get("change_pct", 0.0),
                "volume_24h": share_volume * price,
                "high_24h": price,
                "low_24h": price,
                "market_cap": stock.get("market_cap", 0.0),
                "market_cap_rank": 0,
                # The screener carries no 52-week range; only yfinance-enriched
                # rows get one, and 0 reads as "unknown" downstream.
                "fifty_two_week_high": 0.0,
                "fifty_two_week_low": 0.0,
            }
        )

    # Refresh the head of the list with intraday numbers.
    if stocks_data:
        head = [row["symbol"] for row in stocks_data[:YF_ENRICH_COUNT]]
        try:
            enriched = await _enrich_with_yfinance(head)
        except Exception as e:
            logger.warning("yfinance enrichment failed: %s", e)
            enriched = {}

        for row in stocks_data[:YF_ENRICH_COUNT]:
            fresh = enriched.get(row["symbol"])
            if not fresh:
                continue
            # A None means yfinance had nothing better than the screener value.
            row.update({k: v for k, v in fresh.items() if v is not None})

    # Last resort: the screener gave us nothing, so price the head directly.
    if len(stocks_data) < 5:
        logger.warning("Screener quotes unavailable; falling back to Yahoo v8 chart API")
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                # Capped at the enrichment count — 250 parallel Yahoo requests
                # would earn a 429 rather than a table.
                tasks = [
                    fetch_single_stock(client, symbol) for symbol in nasdaq_stocks[:YF_ENRICH_COUNT]
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for result in results:
                    if isinstance(result, dict) and result.get("price", 0) > 0:
                        stocks_data.append(result)
        except Exception as e:
            logger.error("Yahoo Finance v8 fallback also failed: %s", e)

    # Sort and rank all data regardless of source
    if stocks_data:
        stocks_data.sort(key=lambda x: x.get("market_cap", 0), reverse=True)
        for i, stock in enumerate(stocks_data):
            stock["market_cap_rank"] = i + 1

    # The week's shape, for the table's "Last 7 Days" column. Fetched once the
    # row set is final so the fallback path above is covered too.
    if stocks_data:
        try:
            sparklines = await fetch_stock_sparklines([row["symbol"] for row in stocks_data])
        except Exception as e:
            logger.warning("Sparkline fetch failed: %s", e)
            sparklines = {}

        for row in stocks_data:
            series = sparklines.get(row["symbol"]) or []
            row["sparkline"] = series
            # Derived from the series that is actually drawn, so the number and
            # the line can never disagree. None — not 0 — when there is no week
            # of history: a flat week is a reading, an absent one is not.
            row["change_7d"] = (
                round((series[-1] - series[0]) / series[0] * 100, 2)
                if len(series) > 1 and series[0]
                else None
            )

    # Calculate totals
    for stock in stocks_data:
        total_volume += stock.get("volume_24h", 0)
        total_market_cap += stock.get("market_cap", 0)

    # Get Fear & Greed for stocks
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            fear_greed = await fetch_stock_fear_greed(client)
    except Exception as e:
        logger.warning("Error fetching stock fear/greed: %s", e)
        fear_greed = None

    result = {
        "coins": stocks_data,
        "total_volume_24h": total_volume,
        "total_market_cap": total_market_cap,
        "btc_dominance": 0,
        "active_cryptocurrencies": len(stocks_data),
        "fear_greed": fear_greed,
        "timestamp": datetime.now().isoformat(),
        "market_status": get_market_status(),
    }

    market_cache.set("stock_overview", result, CACHE_DURATION_SECONDS)
    return result


async def fetch_stock_fear_greed(client: Optional[httpx.AsyncClient] = None) -> Optional[dict]:
    """
    CNN's Fear & Greed Index for the stock market, or None when unavailable.

    CNN's data host answers 418 to ordinary HTTP clients — it fingerprints the
    TLS handshake, so no User-Agent gets past it — hence the impersonating
    client. `client` is accepted for call-site compatibility and unused.

    A payload missing `score` or `rating` is treated as a failure. It used to
    default to 50/"Neutral", which is a legible reading of the market that CNN
    never published.
    """
    cached = market_cache.get("fear_greed_stock")
    if cached is not None:
        return cached

    try:
        data = await get_json_impersonated(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            timeout=15.0,
        )

        fear_greed_data = (data or {}).get("fear_and_greed") or {}
        score = fear_greed_data.get("score")
        rating = fear_greed_data.get("rating")

        if score is None or rating is None:
            raise ValueError("CNN Fear & Greed payload carries no score/rating")

        result = {
            "value": int(round(float(score))),
            # CNN sends lower-case ratings ("fear", "extreme greed").
            "classification": str(rating).title(),
            "timestamp": fear_greed_data.get("timestamp") or datetime.now().isoformat(),
        }

        market_cache.set("fear_greed_stock", result, FEAR_GREED_CACHE_DURATION)
        return result

    except Exception as e:
        logger.error("Error fetching CNN Fear & Greed: %s", e)

    return market_cache.get_with_fallback("fear_greed_stock")


async def fetch_global_indices() -> list:
    """
    Fetch global market indices data.
    """
    indices_data = []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            tasks = [fetch_single_stock(client, symbol) for symbol in GLOBAL_INDICES.keys()]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, dict):
                    symbol = result["symbol"]
                    meta = GLOBAL_INDICES.get(symbol, {})
                    result["name"] = meta.get("name", result["name"])
                    result["region"] = meta.get("region", "Global")
                    indices_data.append(result)

    except Exception as e:
        logger.error("Error fetching global indices: %s", e)

    # Sort by region/importance (custom order based on dict keys)
    ordered_data = []
    for symbol in GLOBAL_INDICES.keys():
        item = next((i for i in indices_data if i["symbol"] == symbol), None)
        if item:
            ordered_data.append(item)

    return ordered_data


async def is_stock_symbol(symbol: str) -> bool:
    """Check if the symbol is a known stock symbol or tracked index."""
    return await asset_registry.is_known_stock(symbol)


async def get_stock_context_data(symbol: str) -> Optional[Dict]:
    """
    Get formatted stock data for AI context.
    Usage: Chat Service
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            data = await fetch_single_stock(client, symbol)
            if data:
                # Add Fear & Greed for context
                fg = await fetch_stock_fear_greed(client)
                data["fear_greed"] = fg
                return data
    except Exception as e:
        logger.error("Error fetching stock context for %s: %s", symbol, e)
    return None
