"""
Exchanges Router (CCXT)
Handles multi-exchange price comparison, ticker data, and arbitrage detection.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/api/exchanges")
async def get_exchanges():
    """
    Get list of supported exchanges for multi-exchange price comparison.

    Returns list of exchange IDs that can be used with other endpoints.
    Supports 100+ exchanges via CCXT library.
    """
    try:
        from services.ccxt_service import get_supported_exchanges, get_exchange_info

        exchanges = get_supported_exchanges()
        return {
            "exchanges": [
                {"id": ex, **(get_exchange_info(ex) or {"name": ex.capitalize()})}
                for ex in exchanges
            ],
            "total": len(exchanges),
        }
    except Exception as e:
        print(f"Error getting exchanges: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/exchanges/all")
async def get_all_exchanges():
    """
    Get list of ALL 100+ exchanges supported by CCXT.
    Use with caution - not all may be reliable or available.
    """
    try:
        from services.ccxt_service import get_all_ccxt_exchanges

        exchanges = get_all_ccxt_exchanges()
        return {"exchanges": exchanges, "total": len(exchanges)}
    except Exception as e:
        print(f"Error getting all exchanges: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/exchanges/{exchange_id}/ticker/{base}/{quote}")
async def get_exchange_ticker(exchange_id: str, base: str, quote: str):
    """
    Get ticker data from a specific exchange.

    Args:
        exchange_id: Exchange ID (e.g., 'binance', 'kraken', 'coinbasepro')
        base: Base currency (e.g., 'BTC')
        quote: Quote currency (e.g., 'USDT')

    Example: /api/exchanges/binance/ticker/BTC/USDT
    """
    try:
        from services.ccxt_service import fetch_ticker, get_supported_exchanges

        symbol = f"{base.upper()}/{quote.upper()}"

        if exchange_id not in get_supported_exchanges():
            raise HTTPException(
                status_code=400,
                detail=f"Exchange '{exchange_id}' not supported. Use /api/exchanges to see available exchanges.",
            )

        result = await fetch_ticker(exchange_id, symbol)

        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Could not fetch {symbol} from {exchange_id}. Symbol may not be available.",
            )

        return result
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching ticker: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/multi-exchange/prices/{base}/{quote}")
async def get_multi_exchange_prices(base: str, quote: str, exchanges: Optional[str] = None):
    """
    Get prices for a trading pair from multiple exchanges simultaneously.

    Args:
        base: Base currency (e.g., 'BTC')
        quote: Quote currency (e.g., 'USDT')
        exchanges: Comma-separated list of exchange IDs (optional, defaults to all supported)

    Example: /api/multi-exchange/prices/BTC/USDT?exchanges=binance,kraken,coinbasepro

    Returns prices sorted from lowest to highest.
    """
    try:
        from services.ccxt_service import fetch_multi_exchange_prices

        symbol = f"{base.upper()}/{quote.upper()}"
        exchange_list = exchanges.split(",") if exchanges else None

        results = await fetch_multi_exchange_prices(symbol, exchange_list)

        return {
            "symbol": symbol,
            "prices": results,
            "exchanges_queried": len(exchange_list) if exchange_list else 8,
            "exchanges_responded": len(results),
            "lowest_price": results[0] if results else None,
            "highest_price": results[-1] if results else None,
        }
    except Exception as e:
        print(f"Error fetching multi-exchange prices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/arbitrage/{base}/{quote}")
async def get_arbitrage_opportunity(
    base: str, quote: str, min_spread: float = 0.5, exchanges: Optional[str] = None
):
    """
    Detect arbitrage opportunities for a trading pair across exchanges.

    Args:
        base: Base currency (e.g., 'BTC')
        quote: Quote currency (e.g., 'USDT')
        min_spread: Minimum spread percentage to flag as opportunity (default: 0.5%)
        exchanges: Comma-separated list of exchange IDs (optional)

    Example: /api/arbitrage/BTC/USDT?min_spread=0.3

    Returns:
        - has_opportunity: Whether an arbitrage opportunity exists
        - spread_percent: Price difference as percentage
        - buy_exchange: Where to buy (lowest price)
        - sell_exchange: Where to sell (highest price)
        - potential_profit_per_unit: Profit potential per unit traded
    """
    try:
        from services.ccxt_service import detect_arbitrage_opportunities

        symbol = f"{base.upper()}/{quote.upper()}"
        exchange_list = exchanges.split(",") if exchanges else None

        result = await detect_arbitrage_opportunities(symbol, min_spread, exchange_list)
        return result
    except Exception as e:
        print(f"Error detecting arbitrage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/arbitrage/scan")
async def scan_arbitrage_opportunities(
    min_spread: float = 0.5, symbols: Optional[str] = None, exchanges: Optional[str] = None
):
    """
    Scan multiple trading pairs for arbitrage opportunities.

    Args:
        min_spread: Minimum spread percentage to flag (default: 0.5%)
        symbols: Comma-separated trading pairs (e.g., 'BTC/USDT,ETH/USDT')
        exchanges: Comma-separated exchange IDs

    Example: /api/arbitrage/scan?min_spread=0.3&symbols=BTC/USDT,ETH/USDT,SOL/USDT

    Returns all pairs sorted by spread percentage (highest first).
    """
    try:
        from services.ccxt_service import scan_all_arbitrage_opportunities

        symbol_list = symbols.split(",") if symbols else None
        exchange_list = exchanges.split(",") if exchanges else None

        results = await scan_all_arbitrage_opportunities(
            symbols=symbol_list, min_spread_percent=min_spread, exchanges=exchange_list
        )

        opportunities = [r for r in results if r.get("has_opportunity")]

        return {
            "total_scanned": len(results),
            "opportunities_found": len(opportunities),
            "min_spread_threshold": min_spread,
            "opportunities": opportunities,
            "all_results": results,
        }
    except Exception as e:
        print(f"Error scanning arbitrage: {e}")
        raise HTTPException(status_code=500, detail=str(e))
