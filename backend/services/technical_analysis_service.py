"""
Technical Analysis Service — support/resistance, RSI, trend and targets.

Everything here is computed from OKX OHLCV candles (`services.okx_market`).
Binance used to be the source but is unreachable from some of the networks this
runs on, which meant every call quietly degraded to a placeholder payload.

Nothing is invented. When the candles are missing or too short, the function
returns `None` and the caller reports the gap — a level that came out of a
formula applied to no data reads exactly like a real level once it reaches the
UI or an LLM prompt, which is the failure this module is written to avoid.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from services.okx_market import fetch_candles, fetch_ticker_24h

logger = logging.getLogger(__name__)

# Candles pulled per timeframe. 4h is the primary read; 1h is the fallback for
# pairs listed too recently to have 4h history.
CANDLE_LIMIT = 100
# Below this many candles the indicators are not meaningful, so no analysis is
# produced at all.
MIN_CANDLES = 20
# 4h is preferred only when it carries at least this much history.
MIN_PRIMARY_CANDLES = 50


def calculate_atr(candles: List[Dict[str, Any]], period: int = 14) -> Optional[float]:
    """
    Average True Range — the volatility input for target ranges.

    Returns None when there are not enough candles to compute one; callers must
    treat that as "no volatility estimate", not as zero volatility.
    """
    if len(candles) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return sum(true_ranges) / len(true_ranges) if true_ranges else None

    # Calculate ATR using smoothed average
    atr = sum(true_ranges[:period]) / period
    for i in range(period, len(true_ranges)):
        atr = (atr * (period - 1) + true_ranges[i]) / period

    return atr


def calculate_pivot_points(high: float, low: float, close: float) -> Dict[str, float]:
    """
    Calculate classic pivot points.
    """
    pivot = (high + low + close) / 3

    s1 = (2 * pivot) - high
    s2 = pivot - (high - low)
    s3 = low - 2 * (high - pivot)

    r1 = (2 * pivot) - low
    r2 = pivot + (high - low)
    r3 = high + 2 * (pivot - low)

    return {"pivot": pivot, "s1": s1, "s2": s2, "s3": s3, "r1": r1, "r2": r2, "r3": r3}


def find_significant_levels(
    candles: List[Dict[str, Any]], current_price: float, num_levels: int = 3
) -> Tuple[List[float], List[float]]:
    """
    Find significant support and resistance levels from price action.
    Uses local highs/lows with volume weighting.
    """
    if len(candles) < MIN_CANDLES:
        return [], []

    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c["volume"] for c in candles]

    # Find local extremes (where price reversed)
    potential_resistances = []
    potential_supports = []

    for i in range(2, len(candles) - 2):
        # High volume increases significance
        volume_weight = volumes[i] / (sum(volumes) / len(volumes)) if sum(volumes) > 0 else 1.0
        if volume_weight <= 0:
            volume_weight = 1.0

        # Look for swing highs (local maxima)
        if highs[i] >= max(highs[i - 2 : i]) and highs[i] >= max(highs[i + 1 : i + 3]):
            if highs[i] > current_price:
                potential_resistances.append((highs[i], volume_weight))

        # Look for swing lows (local minima)
        if lows[i] <= min(lows[i - 2 : i]) and lows[i] <= min(lows[i + 1 : i + 3]):
            if lows[i] < current_price:
                potential_supports.append((lows[i], volume_weight))

    # Sort by proximity to current price and volume weight
    potential_resistances.sort(key=lambda x: (x[0] - current_price) / x[1])
    potential_supports.sort(key=lambda x: (current_price - x[0]) / x[1])

    # Get unique levels (cluster similar prices)
    def cluster_levels(levels: List[Tuple[float, float]], threshold: float = 0.005) -> List[float]:
        if not levels:
            return []
        clustered = []
        for price, _ in levels:
            # Check if this price is close to an existing cluster
            is_new = True
            for existing in clustered:
                if abs(price - existing) / existing < threshold:
                    is_new = False
                    break
            if is_new:
                clustered.append(price)
            if len(clustered) >= num_levels:
                break
        return clustered

    resistances = cluster_levels(potential_resistances)
    supports = cluster_levels(potential_supports)

    return supports, resistances


def calculate_rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """
    Relative Strength Index.

    Returns None below `period + 1` closes. A "neutral 50" would be a reading
    the market never produced.
    """
    if len(closes) < period + 1:
        return None

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    gains = [c if c > 0 else 0 for c in changes]
    losses = [-c if c < 0 else 0 for c in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return round(rsi, 2)


def get_rsi_signal(rsi: Optional[float]) -> Optional[str]:
    """Interpret RSI value as a signal, or None when there is no RSI."""
    if rsi is None:
        return None
    if rsi >= 70:
        return "Overbought"
    elif rsi <= 30:
        return "Oversold"
    elif rsi >= 60:
        return "Bullish Momentum"
    elif rsi <= 40:
        return "Bearish Momentum"
    else:
        return "Neutral"


def calculate_trend(
    closes: List[float], short_period: int = 10, long_period: int = 30
) -> Optional[str]:
    """
    Determine trend using EMA crossover, or None below `long_period` closes.
    """
    if len(closes) < long_period:
        return None

    def ema(data: List[float], period: int) -> float:
        multiplier = 2 / (period + 1)
        ema_val = sum(data[:period]) / period
        for price in data[period:]:
            ema_val = (price - ema_val) * multiplier + ema_val
        return ema_val

    short_ema = ema(closes, short_period)
    long_ema = ema(closes, long_period)

    if short_ema > long_ema * 1.01:
        return "bullish"
    elif short_ema < long_ema * 0.99:
        return "bearish"
    else:
        return "neutral"


def format_price(price: float) -> str:
    """Format price with appropriate precision."""
    if price >= 10000:
        return f"${price:,.0f}"
    elif price >= 1000:
        return f"${price:,.2f}"
    elif price >= 1:
        return f"${price:.4f}"
    elif price >= 0.01:
        return f"${price:.5f}"
    else:
        return f"${price:.8f}"


def calculate_target_price(
    current_price: float,
    atr: Optional[float],
    trend: Optional[str],
    rsi: Optional[float],
    supports: List[float],
    resistances: List[float],
) -> Optional[str]:
    """
    Project a target range from ATR, trend and the nearest key level.

    Returns None unless all three inputs exist. The previous version substituted
    2% of spot for a missing ATR, which turned "we could not measure volatility"
    into a concrete-looking price range.
    """
    if atr is None or atr <= 0 or trend is None or rsi is None:
        return None

    # Base multiplier based on trend strength
    if trend == "bullish":
        multiplier = 1.5 if rsi < 60 else 1.0  # Less upside if already overbought
    elif trend == "bearish":
        multiplier = -1.5 if rsi > 40 else -1.0  # Less downside if already oversold
    else:
        multiplier = 0.5 if rsi > 50 else -0.5

    # Calculate targets
    if multiplier > 0:
        # Bullish target: aim for next resistance or ATR-based
        base_target = current_price + (atr * multiplier)
        if resistances:
            # Use resistance if it's within reasonable range
            nearest_resistance = resistances[0]
            if nearest_resistance < base_target * 1.5:
                target_low = current_price + (atr * 0.5)
                target_high = nearest_resistance
            else:
                target_low = current_price + (atr * 0.5)
                target_high = base_target
        else:
            target_low = current_price + (atr * 0.5)
            target_high = base_target
    else:
        # Bearish target: aim for next support or ATR-based
        base_target = current_price + (atr * multiplier)
        if supports:
            nearest_support = supports[0]
            if nearest_support > base_target * 0.5:
                target_low = nearest_support
                target_high = current_price - (atr * 0.5)
            else:
                target_low = base_target
                target_high = current_price - (atr * 0.5)
        else:
            target_low = base_target
            target_high = current_price - (atr * 0.5)

    # Ensure proper ordering
    if target_low > target_high:
        target_low, target_high = target_high, target_low

    return f"{format_price(target_low)} - {format_price(target_high)}"


async def get_technical_analysis(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Complete technical analysis for a symbol, or None when it cannot be computed.

    Args:
        symbol: TradingView format symbol (e.g., BINANCE:BTCUSDT, NASDAQ:AAPL).
            The exchange prefix is only a hint about asset class — the data
            itself always comes from OKX.

    Returns:
        The computed levels, or None for stocks and for any crypto pair OKX has
        too little history on. Callers must treat None as "no levels exist for
        this asset" and never substitute their own.
    """
    parts = symbol.split(":")
    exchange = parts[0] if len(parts) > 1 else ""
    clean_symbol = parts[-1]

    is_crypto = exchange.upper() in ("BINANCE", "OKX") or clean_symbol.endswith("USDT")
    if is_crypto:
        return await get_crypto_analysis(clean_symbol)
    return await get_stock_analysis(clean_symbol)


def analyse_candles(
    candles: List[Dict[str, Any]], current_price: float, timeframe: str
) -> Optional[Dict[str, Any]]:
    """
    Compute every level from an OHLCV series. Asset-class agnostic.

    Crypto and equities reach this with the same candle shape, so the indicators
    are computed once rather than duplicated per source.
    """
    if len(candles) < MIN_CANDLES:
        return None

    atr = calculate_atr(candles, 14)

    # Pivots from the most recent stretch of candles.
    recent = candles[-min(24, len(candles)) :]
    high_period = max(c["high"] for c in recent)
    low_period = min(c["low"] for c in recent)
    pivots = calculate_pivot_points(high_period, low_period, candles[-1]["close"])

    # Combine pivot and swing levels, keeping only the ones on the correct side
    # of spot. However many survive is however many are reported — the list is
    # never padded out to a fixed length with invented levels.
    swing_supports, swing_resistances = find_significant_levels(candles, current_price, 3)
    supports = sorted(
        {s for s in [pivots["s1"], pivots["s2"], *swing_supports] if s < current_price},
        reverse=True,
    )[:2]
    resistances = sorted(
        {r for r in [pivots["r1"], pivots["r2"], *swing_resistances] if r > current_price}
    )[:2]

    closes = [c["close"] for c in candles]
    rsi = calculate_rsi(closes, 14)
    trend = calculate_trend(closes, 10, 30)

    return {
        "current_price": current_price,
        "support_levels": [format_price(s) for s in supports],
        "resistance_levels": [format_price(r) for r in resistances],
        "rsi_signal": get_rsi_signal(rsi),
        "rsi_value": rsi,
        "pivot_point": format_price(pivots["pivot"]),
        "target_price": calculate_target_price(
            current_price, atr, trend, rsi, supports, resistances
        ),
        "atr": atr,
        "trend": trend,
        "timeframe": timeframe,
    }


async def get_crypto_analysis(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Technical analysis for a crypto pair from OKX candles.

    4h is the primary timeframe; a pair without enough 4h history falls back to
    1h. Below `MIN_CANDLES` on both, this returns None.
    """
    try:
        timeframe = "4h"
        candles = await fetch_candles(symbol, "4h", CANDLE_LIMIT, spot=True)
        if len(candles) < MIN_PRIMARY_CANDLES:
            hourly = await fetch_candles(symbol, "1h", CANDLE_LIMIT, spot=True)
            if len(hourly) > len(candles):
                candles, timeframe = hourly, "1h"

        if len(candles) < MIN_CANDLES:
            logger.info("Not enough OKX candles for %s — no analysis produced.", symbol)
            return None

        # Prefer the live ticker; the last close comes from the same series and
        # is a real observation too, so it is a legitimate stand-in.
        ticker = await fetch_ticker_24h(symbol)
        current_price = ticker["price"] if ticker else candles[-1]["close"]

        return analyse_candles(candles, current_price, timeframe)

    except Exception as e:
        logger.error("Crypto analysis error for %s: %s", symbol, e)
        return None


async def get_stock_analysis(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Technical analysis for an equity or index from Yahoo Finance daily bars.

    Equities used to get no levels at all here, which meant the news panel and
    the chat prompt reported a gap for every stock. Yahoo publishes the daily
    history for free, so the same indicators now run on real equity data.
    """
    try:
        from services.stock_market_service import fetch_stock_candles

        candles = await fetch_stock_candles(symbol)
        if len(candles) < MIN_CANDLES:
            logger.info("Not enough Yahoo bars for %s — no analysis produced.", symbol)
            return None

        return analyse_candles(candles, candles[-1]["close"], "1d")

    except Exception as e:
        logger.error("Stock analysis error for %s: %s", symbol, e)
        return None
