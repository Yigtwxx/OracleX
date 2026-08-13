"""
CCXT Multi-Exchange Service
Connects to 100+ exchanges via CCXT library for price comparison and arbitrage detection.

Supported exchanges include: Binance, Coinbase Pro, Kraken, OKX, KuCoin, Bybit, Gate.io, Huobi
"""

import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any
import ccxt.async_support as ccxt
from services.health_registry import health

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Default exchanges to query for arbitrage detection
DEFAULT_EXCHANGES = [
    "binance",
    "okx",
    "coinbasepro",
    "kraken",
    "kucoin",
    "bybit",
    "gateio",
    "huobi",
]

# Trading pairs to monitor for arbitrage
DEFAULT_PAIRS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "BNB/USDT",
    "ADA/USDT",
    "DOGE/USDT",
    "AVAX/USDT",
]

# Cache settings
CACHE_TTL_SECONDS = 15  # 15 second cache to avoid rate limits
EXCHANGE_LIST_CACHE_TTL = 3600  # 1 hour for exchange list

# ═══════════════════════════════════════════════════════════════════════════════
# CACHE
# ═══════════════════════════════════════════════════════════════════════════════

_price_cache: Dict[str, Dict] = {}
_exchange_list_cache: Dict[str, Any] = {"data": None, "timestamp": None}

# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


def _is_cache_valid(cache_key: str, ttl: int = CACHE_TTL_SECONDS) -> bool:
    """Check if cached data is still valid."""
    if cache_key not in _price_cache:
        return False
    cached = _price_cache[cache_key]
    if not cached.get("timestamp"):
        return False
    elapsed = (datetime.now() - cached["timestamp"]).total_seconds()
    return elapsed < ttl


def _get_exchange_instance(exchange_id: str) -> Optional[ccxt.Exchange]:
    """
    Create a CCXT exchange instance.
    Uses public API (no authentication required for price data).
    """
    try:
        exchange_class = getattr(ccxt, exchange_id, None)
        if exchange_class is None:
            return None

        exchange = exchange_class(
            {
                "enableRateLimit": True,  # Respect rate limits
                "timeout": 10000,  # 10 second timeout
            }
        )
        return exchange
    except Exception as e:
        logger.error(f"Failed to create exchange instance for {exchange_id}: {e}")
        return None


async def _close_exchange(exchange: ccxt.Exchange):
    """Safely close exchange connection."""
    try:
        await exchange.close()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════


def get_supported_exchanges() -> List[str]:
    """
    Get list of all supported exchanges via CCXT.
    Returns a curated list of major, reliable exchanges.
    """
    return DEFAULT_EXCHANGES.copy()


def get_all_ccxt_exchanges() -> List[str]:
    """
    Get list of ALL exchanges supported by CCXT (100+).
    Use with caution - not all exchanges may be reliable.
    """
    return ccxt.exchanges


async def fetch_ticker(exchange_id: str, symbol: str) -> Optional[Dict]:
    """
    Fetch ticker data from a specific exchange.

    Args:
        exchange_id: CCXT exchange ID (e.g., 'binance', 'kraken')
        symbol: Trading pair (e.g., 'BTC/USDT')

    Returns:
        Ticker data with price, volume, etc.
    """
    cache_key = f"{exchange_id}:{symbol}"

    # Check cache
    if _is_cache_valid(cache_key):
        return _price_cache[cache_key]["data"]

    exchange = _get_exchange_instance(exchange_id)
    if not exchange:
        return None

    try:
        ticker = await exchange.fetch_ticker(symbol)

        result = {
            "exchange": exchange_id,
            "symbol": symbol,
            "price": ticker.get("last") or ticker.get("close"),
            "bid": ticker.get("bid"),
            "ask": ticker.get("ask"),
            "high": ticker.get("high"),
            "low": ticker.get("low"),
            "volume": ticker.get("baseVolume"),
            "quoteVolume": ticker.get("quoteVolume"),
            "change_24h": ticker.get("percentage"),
            "timestamp": datetime.now().isoformat(),
        }

        # Update cache
        _price_cache[cache_key] = {"data": result, "timestamp": datetime.now()}

        health.record("prices_crypto", ok=True)
        return result

    except ccxt.BadSymbol:
        # A symbol this exchange does not list is an answer, not an outage —
        # recording it as a failure would paint the badge red for a typo.
        logger.info(f"Symbol {symbol} not found on {exchange_id}")
        return None
    except ccxt.NetworkError as e:
        health.record("prices_crypto", ok=False, error=e)
        logger.error(f"Network error fetching {symbol} from {exchange_id}: {e}")
        return None
    except ccxt.ExchangeError as e:
        health.record("prices_crypto", ok=False, error=e)
        logger.error(f"Exchange error fetching {symbol} from {exchange_id}: {e}")
        return None
    except Exception as e:
        health.record("prices_crypto", ok=False, error=e)
        logger.error(f"Unexpected error fetching {symbol} from {exchange_id}: {e}")
        return None
    finally:
        await _close_exchange(exchange)


async def fetch_multi_exchange_prices(
    symbol: str, exchanges: Optional[List[str]] = None
) -> List[Dict]:
    """
    Fetch prices for a symbol from multiple exchanges simultaneously.

    Args:
        symbol: Trading pair (e.g., 'BTC/USDT')
        exchanges: List of exchange IDs (defaults to DEFAULT_EXCHANGES)

    Returns:
        List of ticker data from each exchange
    """
    if exchanges is None:
        exchanges = DEFAULT_EXCHANGES

    # Fetch from all exchanges concurrently
    tasks = [fetch_ticker(ex, symbol) for ex in exchanges]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter successful results
    valid_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Error fetching from {exchanges[i]}: {result}")
            continue
        if result and result.get("price"):
            valid_results.append(result)

    # Sort by price (ascending)
    valid_results.sort(key=lambda x: x.get("price", 0))

    return valid_results


async def detect_arbitrage_opportunities(
    symbol: str, min_spread_percent: float = 0.5, exchanges: Optional[List[str]] = None
) -> Dict:
    """
    Detect arbitrage opportunities for a symbol across exchanges.

    Args:
        symbol: Trading pair (e.g., 'BTC/USDT')
        min_spread_percent: Minimum spread % to consider an opportunity (default 0.5%)
        exchanges: List of exchange IDs to check

    Returns:
        Arbitrage analysis with opportunity details
    """
    prices = await fetch_multi_exchange_prices(symbol, exchanges)

    if len(prices) < 2:
        return {
            "symbol": symbol,
            "has_opportunity": False,
            "message": "Not enough exchange data available",
            "exchanges_checked": len(prices),
            "timestamp": datetime.now().isoformat(),
        }

    # Find lowest and highest prices
    lowest = prices[0]  # Already sorted ascending
    highest = prices[-1]

    lowest_price = lowest.get("price", 0)
    highest_price = highest.get("price", 0)

    if lowest_price <= 0:
        return {
            "symbol": symbol,
            "has_opportunity": False,
            "message": "Invalid price data",
            "timestamp": datetime.now().isoformat(),
        }

    # Calculate spread
    spread_amount = highest_price - lowest_price
    spread_percent = (spread_amount / lowest_price) * 100

    has_opportunity = spread_percent >= min_spread_percent

    return {
        "symbol": symbol,
        "has_opportunity": has_opportunity,
        "spread_percent": round(spread_percent, 4),
        "spread_amount": round(spread_amount, 6),
        "buy_exchange": lowest.get("exchange"),
        "buy_price": lowest_price,
        "sell_exchange": highest.get("exchange"),
        "sell_price": highest_price,
        "potential_profit_per_unit": round(spread_amount, 6),
        "exchanges_checked": len(prices),
        "all_prices": [
            {
                "exchange": p.get("exchange"),
                "price": p.get("price"),
                "bid": p.get("bid"),
                "ask": p.get("ask"),
            }
            for p in prices
        ],
        "timestamp": datetime.now().isoformat(),
    }


async def scan_all_arbitrage_opportunities(
    symbols: Optional[List[str]] = None,
    min_spread_percent: float = 0.5,
    exchanges: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Scan multiple trading pairs for arbitrage opportunities.

    Args:
        symbols: List of trading pairs to check (defaults to DEFAULT_PAIRS)
        min_spread_percent: Minimum spread to flag as opportunity
        exchanges: Exchanges to check

    Returns:
        List of arbitrage analyses, sorted by spread (highest first)
    """
    if symbols is None:
        symbols = DEFAULT_PAIRS

    # Check all symbols concurrently
    tasks = [
        detect_arbitrage_opportunities(symbol, min_spread_percent, exchanges) for symbol in symbols
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter and sort by spread
    valid_results = []
    for result in results:
        if isinstance(result, Exception):
            continue
        if result:
            valid_results.append(result)

    # Sort by spread percentage (highest first)
    valid_results.sort(key=lambda x: x.get("spread_percent", 0), reverse=True)

    return valid_results


async def get_exchange_markets(exchange_id: str) -> List[str]:
    """
    Get list of available trading pairs on an exchange.

    Args:
        exchange_id: CCXT exchange ID

    Returns:
        List of trading pair symbols
    """
    exchange = _get_exchange_instance(exchange_id)
    if not exchange:
        return []

    try:
        await exchange.load_markets()
        return list(exchange.symbols)
    except Exception as e:
        logger.error(f"Error loading markets for {exchange_id}: {e}")
        return []
    finally:
        await _close_exchange(exchange)


# ═══════════════════════════════════════════════════════════════════════════════
# EXCHANGE INFO
# ═══════════════════════════════════════════════════════════════════════════════

EXCHANGE_INFO = {
    "binance": {
        "name": "Binance",
        "logo": "https://cryptologos.cc/logos/binance-coin-bnb-logo.png",
        "region": "Global",
        "url": "https://www.binance.com",
    },
    "coinbasepro": {
        "name": "Coinbase Pro",
        "logo": "https://cryptologos.cc/logos/usd-coin-usdc-logo.png",
        "region": "US",
        "url": "https://pro.coinbase.com",
    },
    "kraken": {
        "name": "Kraken",
        "logo": "https://www.kraken.com/favicon.ico",
        "region": "US/EU",
        "url": "https://www.kraken.com",
    },
    "okx": {
        "name": "OKX",
        "logo": "https://static.okx.com/cdn/assets/imgs/221/73F0BB32A0D5B1C7.png",
        "region": "Global",
        "url": "https://www.okx.com",
    },
    "kucoin": {
        "name": "KuCoin",
        "logo": "https://assets.staticimg.com/cms/media/1lB3PkckFDyfxz6VudCEACBeRRBi6sQQ7DDjz0yWM.svg",
        "region": "Global",
        "url": "https://www.kucoin.com",
    },
    "bybit": {
        "name": "Bybit",
        "logo": "https://www.bybit.com/favicon.ico",
        "region": "Global",
        "url": "https://www.bybit.com",
    },
    "gateio": {
        "name": "Gate.io",
        "logo": "https://www.gate.io/favicon.ico",
        "region": "Global",
        "url": "https://www.gate.io",
    },
    "huobi": {
        "name": "Huobi",
        "logo": "https://www.huobi.com/favicon.ico",
        "region": "Asia",
        "url": "https://www.huobi.com",
    },
}


def get_exchange_info(exchange_id: str) -> Optional[Dict]:
    """Get metadata about an exchange."""
    return EXCHANGE_INFO.get(exchange_id)
