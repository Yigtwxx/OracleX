import asyncio
import json
import logging
import os
import httpx
import websockets
from datetime import datetime, timedelta
from typing import Dict, List
from collections import deque

from services import asset_registry
from services.okx_market import fetch_candles as fetch_okx_candles

# Configure logging
logger = logging.getLogger(__name__)

# Constants
OKX_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
OKX_INSTRUMENTS_URL = "https://www.okx.com/api/v5/public/instruments"
OKX_LIQUIDATIONS_URL = "https://www.okx.com/api/v5/public/liquidation-orders"
# OKX instCategory: "1" crypto, "3" tokenised equities, "4" commodities.
CRYPTO_INST_CATEGORY = "1"
# How many underlyings to backfill history for — one REST call each.
BACKFILL_SYMBOL_COUNT = 8
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DATA_FILE = os.path.join(DATA_DIR, "liquidations.json")
MAX_HISTORY_LEN = 10000  # Increased for persistence
SAVE_INTERVAL = 60  # Save to disk every 60 seconds
# Anything older than this is history, not a live feed — see load_data().
MAX_AGE_HOURS = 24

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)


class LiquidationService:
    def __init__(self):
        self.liquidations = deque(maxlen=MAX_HISTORY_LEN)
        self.running = False
        self.task = None
        self.save_task = None
        self._lock = asyncio.Lock()
        # instId → contract value, needed to convert contract counts into coins.
        self.contract_values: Dict[str, float] = {}
        self.load_data()

    def load_data(self):
        """
        Load persisted liquidation data from disk, skipping stale events.

        The feed is presented as live, so events older than MAX_AGE_HOURS are
        dropped rather than replayed — otherwise an outage leaves the widget
        showing months-old liquidations as if they had just happened.
        """
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE) as f:
                    data = json.load(f)
                    # Convert timestamps back to logic if needed, but JSON is simple
                    # We might need to parse 'received_at' back to datetime if we use it for logic
                    # For simplicty, we store timestamps as simple floats/iso strings in JSON
                    # and re-parse them when loading.

                    cutoff_ms = (datetime.now() - timedelta(hours=MAX_AGE_HOURS)).timestamp() * 1000
                    loaded_count = 0
                    skipped_count = 0
                    for item in data:
                        if (item.get("timestamp") or 0) < cutoff_ms:
                            skipped_count += 1
                            continue
                        # Parse received_at string back to datetime
                        if isinstance(item.get("received_at"), str):
                            item["received_at"] = datetime.fromisoformat(item["received_at"])
                        self.liquidations.append(item)
                        loaded_count += 1

                    logger.info(
                        f"Loaded {loaded_count} liquidation events from disk "
                        f"({skipped_count} older than {MAX_AGE_HOURS}h skipped)."
                    )
        except Exception as e:
            logger.error(f"Failed to load liquidation data: {e}")

    async def _load_contract_values(self):
        """
        Map each OKX crypto swap instrument to its contract value.

        OKX reports liquidation size in contracts, so `sz` has to be multiplied
        by `ctVal` (0.01 BTC for BTC-USDT-SWAP) to get a coin amount.

        Only `instCategory == "1"` (crypto) is kept. OKX also lists tokenised
        equities (AAPL, NVDA…) and commodities (XAU, CL…) as swaps, and without
        this filter they surface in the crypto liquidation feed. Instruments
        missing from this map are skipped by _parse_instruments.
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(OKX_INSTRUMENTS_URL, params={"instType": "SWAP"})
                response.raise_for_status()
                payload = response.json()

            if payload.get("code") != "0":
                logger.warning(f"OKX instruments returned code {payload.get('code')}")
                return

            values = {}
            for instrument in payload.get("data") or []:
                if instrument.get("instCategory") != CRYPTO_INST_CATEGORY:
                    continue
                try:
                    values[instrument["instId"]] = float(instrument["ctVal"])
                except (KeyError, TypeError, ValueError):
                    continue

            self.contract_values = values
            logger.info(f"Loaded contract values for {len(values)} OKX crypto instruments.")
            await self._drop_non_crypto()
        except Exception as e:
            logger.error(f"Failed to load OKX contract values: {e}")

    async def _drop_non_crypto(self):
        """
        Discard stored events for instruments that are not crypto.

        load_data() runs in the constructor, before the instrument catalogue is
        available, so a disk cache written before the instCategory filter existed
        can still carry tokenised equities into the feed.
        """
        known = {
            inst_id.replace("-USDT-SWAP", "") + "USDT"
            for inst_id in self.contract_values
            if inst_id.endswith("-USDT-SWAP")
        }
        if not known:
            return

        async with self._lock:
            kept = [event for event in self.liquidations if event["symbol"] in known]
            dropped = len(self.liquidations) - len(kept)
            if dropped:
                self.liquidations.clear()
                self.liquidations.extend(kept)
                logger.info(f"Dropped {dropped} non-crypto liquidation events.")

    async def save_data_loop(self):
        """Periodically save data to disk."""
        while self.running:
            await asyncio.sleep(SAVE_INTERVAL)
            await self.save_data()

    async def save_data(self):
        """Save current liquidations to disk."""
        try:
            async with self._lock:
                data_to_save = list(self.liquidations)

            # Convert datetime objects to string for JSON serialization
            serializable_data = []
            for item in data_to_save:
                item_copy = item.copy()
                if isinstance(item_copy.get("received_at"), datetime):
                    item_copy["received_at"] = item_copy["received_at"].isoformat()
                serializable_data.append(item_copy)

            # Sort by timestamp to ensure order
            serializable_data.sort(key=lambda x: x["timestamp"])

            # Write to temp file then rename for atomic write
            temp_file = f"{DATA_FILE}.tmp"
            with open(temp_file, "w") as f:
                json.dump(serializable_data, f)
            os.replace(temp_file, DATA_FILE)
            logger.info(f"Saved {len(serializable_data)} events to disk.")

        except Exception as e:
            logger.error(f"Failed to save liquidation data: {e}")

    async def start(self):
        """Start the WebSocket listener in the background."""
        if self.running:
            return

        self.running = True
        self.task = asyncio.create_task(self._connect_and_listen())
        self.save_task = asyncio.create_task(self.save_data_loop())
        logger.info("Liquidation service started.")

    async def stop(self):
        """Stop the WebSocket listener."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        if self.save_task:
            self.save_task.cancel()
            try:
                await self.save_task
            except asyncio.CancelledError:
                pass

        # Final save
        await self.save_data()
        logger.info("Liquidation service stopped.")

    async def _connect_and_listen(self):
        """Connect to the OKX WebSocket and listen for liquidation events."""
        if not self.contract_values:
            await self._load_contract_values()
            await self._backfill_history()

        while self.running:
            ws = None
            try:
                ws = await websockets.connect(
                    OKX_WS_URL, ping_interval=20, ping_timeout=10, close_timeout=5
                )
                await ws.send(
                    json.dumps(
                        {
                            "op": "subscribe",
                            "args": [{"channel": "liquidation-orders", "instType": "SWAP"}],
                        }
                    )
                )
                logger.info(f"Connected to OKX Liquidation Stream: {OKX_WS_URL}")

                while self.running:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=20)
                    except TimeoutError:
                        # OKX drops idle connections after 30s — keep it alive.
                        await ws.send("ping")
                        continue
                    except asyncio.CancelledError:
                        break

                    if message == "pong":
                        continue

                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        continue

                    await self._process_message(data)

            except asyncio.CancelledError:
                logger.info("WebSocket listener cancelled.")
                break
            except websockets.exceptions.ConnectionClosed:
                if self.running:
                    logger.warning("WebSocket connection closed. Reconnecting in 5s...")
                    await asyncio.sleep(5)
            except Exception as e:
                if self.running:
                    logger.error(f"Error in liquidation listener: {e}")
                    await asyncio.sleep(5)
            finally:
                if ws:
                    try:
                        await ws.close()
                    except Exception:
                        pass

    def _parse_instruments(self, instruments: List[Dict], min_timestamp: float = 0) -> List[Dict]:
        """
        Convert OKX `liquidation-orders` payloads into stored events.

        The WebSocket channel and the historical REST endpoint return the same
        `instId` + `details[]` shape, so both feed through here. The stored shape
        is kept identical to the previous Binance one so every consumer (feed,
        heatmap, levels) keeps working: `side` stays exchange style, where SELL
        means a long was liquidated and BUY means a short was.
        """
        now = datetime.now()
        events = []

        for instrument in instruments:
            inst_id = instrument.get("instId") or ""
            if not inst_id.endswith("-USDT-SWAP"):
                continue

            # ETH-USDT-SWAP → ETHUSDT, matching the previous symbol format.
            symbol = inst_id.replace("-USDT-SWAP", "") + "USDT"
            contract_value = self.contract_values.get(inst_id)
            if not contract_value:
                continue

            for detail in instrument.get("details") or []:
                try:
                    price = float(detail["bkPx"])
                    contracts = float(detail["sz"])
                    timestamp = int(detail["ts"])
                except (KeyError, TypeError, ValueError):
                    continue

                if timestamp < min_timestamp:
                    continue

                events.append(
                    {
                        "symbol": symbol,
                        # A liquidated long is a forced sell, and vice versa.
                        "side": "SELL" if detail.get("posSide") == "long" else "BUY",
                        "amount_usd": contracts * contract_value * price,
                        "price": price,
                        "timestamp": timestamp,  # ms timestamp
                        "received_at": now,
                    }
                )

        return events

    async def _process_message(self, data: dict):
        """Process an incoming OKX `liquidation-orders` WebSocket message."""
        try:
            if data.get("arg", {}).get("channel") != "liquidation-orders":
                return  # subscribe ack, error frame, or another channel

            events = self._parse_instruments(data.get("data") or [])
            if not events:
                return

            async with self._lock:
                self.liquidations.extend(events)

        except Exception as e:
            logger.error(f"Error processing liquidation message: {e}")

    async def _backfill_history(self):
        """
        Seed the feed with recent liquidations from the OKX REST endpoint.

        The WebSocket only delivers events from the moment it connects, so
        without this a fresh start shows an empty feed for minutes. Runs once,
        before the socket opens, and is bounded by the same MAX_AGE_HOURS window
        as the disk cache.
        """
        try:
            symbols = await asset_registry.get_top_perp_symbols(BACKFILL_SYMBOL_COUNT)
            cutoff_ms = (datetime.now() - timedelta(hours=MAX_AGE_HOURS)).timestamp() * 1000

            async with httpx.AsyncClient(timeout=15.0) as client:
                responses = await asyncio.gather(
                    *[
                        client.get(
                            OKX_LIQUIDATIONS_URL,
                            params={
                                "instType": "SWAP",
                                "uly": f"{symbol}-USDT",
                                "state": "filled",
                            },
                        )
                        for symbol in symbols
                    ],
                    return_exceptions=True,
                )

            instruments = []
            for symbol, response in zip(symbols, responses):
                if isinstance(response, BaseException):
                    logger.warning(f"Liquidation backfill failed for {symbol}: {response}")
                    continue
                if response.status_code != 200:
                    continue
                instruments.extend(response.json().get("data") or [])

            events = self._parse_instruments(instruments, min_timestamp=cutoff_ms)
            if not events:
                return

            async with self._lock:
                seen = {(e["symbol"], e["timestamp"], e["price"]) for e in self.liquidations}
                fresh = [e for e in events if (e["symbol"], e["timestamp"], e["price"]) not in seen]
                merged = sorted(list(self.liquidations) + fresh, key=lambda e: e["timestamp"])
                self.liquidations.clear()
                self.liquidations.extend(merged)

            logger.info(f"Backfilled {len(fresh)} historical liquidation events.")
        except Exception as e:
            logger.error(f"Liquidation backfill failed: {e}")

    async def get_heatmap_data(self, time_window_seconds: int = 3600) -> List[Dict]:
        """Get aggregated liquidation data for the heatmap widget."""
        async with self._lock:
            now = datetime.now()
            cutoff = now - timedelta(seconds=time_window_seconds)

            agg: Dict[str, Dict] = {}
            current_data = list(self.liquidations)

            for event in current_data:
                # Ensure received_at is datetime (it should be if loaded correctly, but safety check)
                received_at = event["received_at"]
                if isinstance(received_at, str):
                    received_at = datetime.fromisoformat(received_at)

                if received_at < cutoff:
                    continue

                symbol = event["symbol"]
                amount = event["amount_usd"]
                side = event["side"]

                if symbol not in agg:
                    agg[symbol] = {
                        "symbol": symbol,
                        "total_usd": 0.0,
                        "long_usd": 0.0,
                        "short_usd": 0.0,
                        "count": 0,
                    }

                agg[symbol]["total_usd"] += amount
                agg[symbol]["count"] += 1

                if side == "SELL":
                    agg[symbol]["long_usd"] += amount
                else:
                    agg[symbol]["short_usd"] += amount

            result = []
            for symbol, data in agg.items():
                if data["total_usd"] < 1000:
                    continue

                result.append(
                    {
                        "symbol": symbol,
                        "value": round(data["total_usd"], 2),
                        "long_liq": round(data["long_usd"], 2),
                        "short_liq": round(data["short_usd"], 2),
                        "count": data["count"],
                    }
                )

            result.sort(key=lambda x: x["value"], reverse=True)
            return result[:50]

    async def get_liquidation_history(self, symbol: str) -> List[Dict]:
        """Get all stored liquidation history for a specific symbol."""
        # Clean symbol format if needed (TradingView "BINANCE:BTCUSDT" -> "BTCUSDT")
        clean_symbol = symbol.split(":")[-1]

        async with self._lock:
            # Filter liquidations for this symbol
            history = [
                {
                    "price": event["price"],
                    "amount_usd": event["amount_usd"],
                    "side": event["side"],
                    "timestamp": event["timestamp"],
                }
                for event in self.liquidations
                if event["symbol"] == clean_symbol
            ]

            # Sort by timestamp
            history.sort(key=lambda x: x["timestamp"])
            return history

    async def get_liquidation_levels(
        self,
        symbol: str,
        price_min: float,
        price_max: float,
        num_bins: int = 100,
    ) -> Dict:
        """
        Group the liquidations that actually happened into price bins.

        Each stored event is placed at the price it was liquidated at, so this
        is a histogram of observed liquidations — not modelled levels. For the
        forward-looking estimate see `liquidation_map_service.get_liquidation_map`.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            price_min: Minimum price for binning
            price_max: Maximum price for binning
            num_bins: Number of price bins (default 100)

        Returns:
            Dictionary with:
            - levels: Array of {price, long_liq, short_liq, total}
            - max_value: Maximum liquidation value (for normalization)
            - bin_size: Size of each price bin
        """
        clean_symbol = symbol.split(":")[-1]

        # Calculate bin size
        price_range = price_max - price_min
        bin_size = price_range / num_bins

        if bin_size <= 0:
            return {"levels": [], "max_value": 0, "bin_size": 0}

        # Initialize bins
        bins = {}
        for i in range(num_bins):
            bin_price = price_min + (i + 0.5) * bin_size  # Use mid-point of bin
            bins[i] = {
                "price": round(bin_price, 2),
                "long_liq": 0.0,
                "short_liq": 0.0,
                "total": 0.0,
            }

        async with self._lock:
            # Process all liquidations for this symbol
            for event in self.liquidations:
                if event["symbol"] != clean_symbol:
                    continue

                liq_price = event["price"]
                amount = event["amount_usd"]
                side = event["side"]

                bin_index = int((liq_price - price_min) / bin_size)
                if not 0 <= bin_index < num_bins:
                    continue

                # A SELL liquidation closes a long, a BUY closes a short.
                side_key = "long_liq" if side == "SELL" else "short_liq"
                bins[bin_index][side_key] += amount
                bins[bin_index]["total"] += amount

        # Convert to list and find max value
        levels = list(bins.values())
        max_value = max((b["total"] for b in levels), default=0)

        # Filter out empty bins for efficiency
        levels = [b for b in levels if b["total"] > 0]

        # Sort by price
        levels.sort(key=lambda x: x["price"])

        return {
            "levels": levels,
            "max_value": round(max_value, 2),
            "bin_size": round(bin_size, 2),
            "price_min": round(price_min, 2),
            "price_max": round(price_max, 2),
        }

    async def fetch_candles(
        self, symbol: str, interval: str = "1h", limit: int = 168
    ) -> List[Dict]:
        """
        Fetch OHLCV candles for the OKX perpetual behind `symbol`.

        Thin wrapper over `okx_market.fetch_candles`, kept as a method because
        the chart router and the liquidation map both reach the candles through
        this service. Default: 1h interval, 168 candles (1 week).
        """
        return await fetch_okx_candles(symbol, interval=interval, limit=limit)


# Global instance
liquidation_service = LiquidationService()
