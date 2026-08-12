"""
Whale-trade feed — large taker orders on the most liquid spot pairs.

Sourced from OKX public trades. Binance's `aggTrades` was the original source but
is unreachable from some of the networks this runs on, which left the widget
permanently empty rather than merely quiet.

Two things make OKX usable where a naive port would not be:

1. **Aggregation.** `aggTrades` merged the fills of one taker order server-side;
   OKX publishes raw fills. A $65k BTC market order arrives as eighteen rows of
   a few thousand dollars each, so `okx_market.aggregate_taker_orders` rebuilds
   the orders before anything is compared against the size threshold.
2. **Accumulation.** OKX returns at most 500 fills per pair, which spans roughly
   six minutes — a window that genuinely contains no half-million-dollar order.
   Whales are rare by definition, so qualifying orders are kept in a rolling
   store and the feed reports what has been seen over the retention window,
   the same shape `liquidation_service` uses for its own feed.

Nothing is retained that was not actually observed, and nothing is extrapolated
to fill the gaps between polls.
"""

import logging
from collections import deque
from time import time
from typing import Any, Deque, Dict, List, Set

from services import asset_registry
from services.cache import home_cache
from services.okx_market import (
    OKX_MAX_TRADES,
    aggregate_taker_orders,
    fetch_many_recent_trades,
)

logger = logging.getLogger(__name__)

# Cache configuration
CACHE_DURATION = 10  # 10 seconds (near real-time)

# Whale activity is scanned on the most liquid pairs, resolved live by volume.
TRACKED_PAIR_COUNT = 5

# Minimum size for an order to count as a whale print.
#
# Set against what OKX spot actually prints rather than a round number: over a
# scan window the largest single taker orders on BTC and ETH land around
# $65k-$100k, because the matching engine fills a large order across many
# price levels and the venue is thinner than the derivatives book. The previous
# $500k threshold was carried over from Binance's aggregated feed and matched
# nothing here, so the widget sat empty and looked broken.
#
# The UI reads this number back out of the API response, so the header can
# never disagree with what was actually filtered.
MIN_WHALE_VALUE_USD = 100_000
# How many recent fills each pair is scanned over (OKX caps this at 500).
TRADE_SCAN_DEPTH = OKX_MAX_TRADES
# Newest orders returned in the feed.
FEED_LENGTH = 50
# How long an observed whale order stays in the feed.
RETENTION_SECONDS = 24 * 3600
# Cap on retained orders, so a busy day cannot grow the store without bound.
MAX_RETAINED = 2000

# Observed whale orders, oldest-first, plus the ids already recorded so repeated
# polls over an overlapping window do not double-count the same order.
_whales: Deque[Dict[str, Any]] = deque(maxlen=MAX_RETAINED)
_seen_ids: Set[str] = set()


def _record(symbol: str, orders: List[Dict[str, Any]]) -> None:
    """Add this pair's newly seen whale orders to the rolling store."""
    base = symbol.replace("USDT", "")

    # Oldest-first, so the deque stays chronological and `maxlen` drops the
    # oldest rather than the most recent.
    for order in sorted(orders, key=lambda o: o["timestamp"]):
        if order["value"] < MIN_WHALE_VALUE_USD:
            continue

        key = f"{symbol}:{order['trade_id']}"
        if key in _seen_ids:
            continue

        _seen_ids.add(key)
        _whales.append(
            {
                "id": key,
                "symbol": base,
                "price": order["price"],
                "quantity": order["quantity"],
                "value": order["value"],
                # OKX reports the taker's direction, so this needs no inversion.
                "side": order["side"],
                "timestamp": order["timestamp"],
                "fills": order["fills"],
            }
        )


def _prune() -> None:
    """Drop orders past the retention window, and their dedup entries."""
    cutoff_ms = (time() - RETENTION_SECONDS) * 1000

    while _whales and _whales[0]["timestamp"] < cutoff_ms:
        _seen_ids.discard(_whales.popleft()["id"])

    # `maxlen` can evict without going through `_prune`, so reconcile the id set
    # against what actually survived rather than letting it grow forever.
    if len(_seen_ids) > len(_whales) * 2:
        _seen_ids.clear()
        _seen_ids.update(w["id"] for w in _whales)


async def fetch_whale_trades() -> Dict[str, Any]:
    """
    Whale orders observed over the retention window, newest first.

    `stats` describes the retained orders, not a fixed 24-hour tape: it is what
    this process has actually seen since it started, which is why the window it
    covers is reported alongside the numbers.
    """
    cached = home_cache.get("whale_trades")
    if cached is not None:
        return cached

    try:
        tracked_pairs = await asset_registry.get_top_spot_pairs(TRACKED_PAIR_COUNT)
        by_pair = await fetch_many_recent_trades(tracked_pairs, TRADE_SCAN_DEPTH)

        for symbol, fills in by_pair.items():
            _record(symbol, aggregate_taker_orders(fills))
        _prune()

        whales = sorted(_whales, key=lambda w: w["timestamp"], reverse=True)

        buy_volume = sum(w["value"] for w in whales if w["side"] == "buy")
        sell_volume = sum(w["value"] for w in whales if w["side"] == "sell")
        total_volume = buy_volume + sell_volume

        result = {
            "trades": [{k: v for k, v in w.items() if k != "id"} for w in whales[:FEED_LENGTH]],
            "stats": {
                "observed_volume": total_volume,
                "net_flow": buy_volume - sell_volume,
                # None rather than a neutral 50 when nothing qualified: an empty
                # window says nothing about buy pressure in either direction.
                "buy_pressure_percent": (
                    buy_volume / total_volume * 100 if total_volume > 0 else None
                ),
                "whale_count": len(whales),
                "min_value_usd": MIN_WHALE_VALUE_USD,
                "window_seconds": (int(time() - whales[-1]["timestamp"] / 1000) if whales else 0),
                "pairs_scanned": len(by_pair),
            },
        }

        home_cache.set("whale_trades", result, CACHE_DURATION)
        return result

    except Exception as e:
        logger.error("Error fetching whale trades: %s", e)
        stale = home_cache.get_with_fallback("whale_trades")
        if stale:
            return stale
        return {"trades": [], "stats": {}}
