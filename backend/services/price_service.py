"""
Spot price resolution for a single symbol, crypto or equity.

Extracted from `routers/market.py` so the news pipeline can resolve a price
server-side instead of the browser making a separate round-trip before it can
even start the analysis. One implementation, two callers.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def is_crypto_symbol(symbol: str) -> bool:
    """
    Whether a symbol should be priced from a crypto venue.

    The exchange prefix is the reliable signal; the USDT suffix catches
    unprefixed pairs that reach us from the news attribution path.
    """
    clean = symbol.split(":")[-1].upper()
    exchange = symbol.split(":")[0].upper() if ":" in symbol else ""
    return exchange in ("BINANCE", "OKX") or clean.endswith("USDT")


async def resolve_price(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Current price for `symbol`, or None when no upstream could answer.

    Never a placeholder: a caller that gets None must say the price is
    unavailable rather than analyse against an invented number.
    """
    if not symbol or not symbol.strip():
        return None

    from services.okx_market import fetch_ticker_24h
    from services.stock_market_service import get_stock_context_data

    clean = symbol.split(":")[-1].upper()

    try:
        if is_crypto_symbol(symbol):
            ticker = await fetch_ticker_24h(clean)
            if ticker and ticker.get("price"):
                return {"symbol": symbol, "price": ticker["price"], "source": "OKX"}
        else:
            data = await get_stock_context_data(clean)
            if data and data.get("price"):
                return {"symbol": symbol, "price": data["price"], "source": "Yahoo Finance"}
    except Exception as e:  # noqa: BLE001 — the caller decides what a gap means
        logger.warning("Price lookup for %s failed: %s", symbol, e)

    return None


async def get_current_price(symbol: str) -> Optional[float]:
    """Just the number, for callers that have nowhere to show the source."""
    resolved = await resolve_price(symbol)
    return resolved["price"] if resolved else None
