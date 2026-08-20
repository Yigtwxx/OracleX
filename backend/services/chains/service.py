"""
The Chains board: every chain read in parallel, priced, and assembled.

The composition rule here is the same one the home board uses, and it is the
reason this module exists rather than the router calling eight adapters: a chain
that could not be read must cost its own row and nothing else. Eight independent
networks behind eight independent providers will not all be up at once, and a
board that 503s because TronGrid blinked would be down most days.

So every adapter is gathered with `return_exceptions=True`, and a failure is
recorded on that chain as `error` with `blocks: []`. The UI renders such a row as
unreachable — visibly different from a quiet chain, which is the distinction the
whole board turns on.

Prices are fetched once for the set of coins fees are denominated in, not once
per chain: five of the eight rows settle in ETH.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Optional

from services.cache import ServiceCache
from services.chains import bitcoin, evm, flows, history, solana, tron
from services.chains.registry import (
    BTC_TRANSFER_VBYTES,
    CHAINS,
    FEE_SYMBOLS,
    Chain,
)
from services.price_service import get_current_price

logger = logging.getLogger(__name__)

chains_cache = ServiceCache(maxsize=16)

# Ten seconds. The fastest chain here produces four blocks a second, so no cache
# window makes the board look live on Arbitrum's terms — but ten seconds is
# under one Ethereum block and a sixtieth of a Bitcoin one, which is the cadence
# a reader actually perceives. The pulse ring animates against the server's own
# timestamp between refreshes, so the page keeps moving while this sits still.
CACHE_SECONDS = 10

# How stale a replayed board may be before it is withheld. Two minutes is about
# ten Bitcoin-block-widths of tolerance and twelve Ethereum ones: past it the
# heights on the cards are wrong in a way a reader would notice.
MAX_STALE_SECONDS = 120

# Exchange flow is a daily figure from a daily-publishing feed, so it is cached
# far longer than the board around it — polling it on the board's cadence would
# re-fetch a number that changes once a day, three hundred and sixty times an
# hour.
FLOWS_CACHE_SECONDS = 30 * 60

# Satoshis in one bitcoin.
SATS_PER_BTC = 100_000_000


async def _fetch_one(chain: Chain) -> dict[str, Any]:
    """Dispatch a chain to its family's adapter."""
    if chain.family == "evm":
        return await evm.fetch_evm(chain)
    if chain.family == "bitcoin":
        return await bitcoin.fetch_bitcoin(chain.target_block_seconds)
    if chain.family == "solana":
        return await solana.fetch_solana(chain.rpc_urls, chain.target_block_seconds)
    if chain.family == "tron":
        return await tron.fetch_tron()
    raise ValueError(f"no adapter for family {chain.family!r}")


async def _fetch_prices() -> dict[str, Optional[float]]:
    """
    Spot price for every coin a fee on this board is denominated in.

    Asked for as `BTCUSDT` rather than `BTC`, and that suffix is load-bearing:
    `price_service.is_crypto_symbol` routes on an exchange prefix or a USDT
    suffix, and a bare ticker has neither — so it is sent to the *equity* lookup
    instead. "BTC" is a listed US ticker (a spot-bitcoin trust), so the bare form
    resolves without error to about $28, and "ETH" and "TRX" to funds of their
    own. Nothing raises; the fees simply come out four orders of magnitude wrong.

    Failures are per coin: without a price the affected rows lose their currency
    figure and keep their native one, which is still the comparison the FeeRacer
    is for between two chains that settle in the same coin.
    """
    results = await asyncio.gather(
        *(get_current_price(f"{symbol}USDT") for symbol in FEE_SYMBOLS),
        return_exceptions=True,
    )
    prices: dict[str, Optional[float]] = {}
    for symbol, result in zip(FEE_SYMBOLS, results):
        if isinstance(result, BaseException):
            logger.warning("[Chains] price for %s unavailable: %s", symbol, result)
            prices[symbol] = None
        else:
            prices[symbol] = result
    return prices


def _price_the_fee(chain: Chain, snapshot: dict[str, Any], price: Optional[float]) -> None:
    """
    Add the currency figure for a simple transfer, in place.

    Bitcoin is the one chain whose adapter cannot do this itself: its fee arrives
    per virtual byte, and turning that into a transfer cost needs the size of the
    transaction a wallet would actually broadcast — a fact that belongs to the
    registry, not to mempool.space.
    """
    fee = snapshot.get("fee")
    if not isinstance(fee, dict):
        return

    if chain.family == "bitcoin" and fee.get("transfer_native") is None:
        sat_vb = fee.get("half_hour_sat_vb")
        if isinstance(sat_vb, (int, float)):
            # The half-hour tier, not the fastest: it is what an ordinary send
            # uses, and the fastest tier prices urgency rather than the network.
            fee["transfer_native"] = sat_vb * BTC_TRANSFER_VBYTES / SATS_PER_BTC

    native = fee.get("transfer_native")
    fee["transfer_usd"] = (
        round(native * price, 6) if isinstance(native, (int, float)) and price else None
    )


def _empty_row(chain: Chain, error: str) -> dict[str, Any]:
    """
    A chain that could not be read.

    Every reading is None and `error` carries why. Deliberately not a row of
    zeros: a zero fee and a zero block time are readings, and this row has none.
    """
    return {
        "key": chain.key,
        "name": chain.name,
        "symbol": chain.symbol,
        "family": chain.family,
        "target_block_seconds": chain.target_block_seconds,
        "explorer_block_url": chain.explorer_block_url,
        "hash_height_prefix_chars": chain.hash_height_prefix_chars,
        "height": None,
        "last_block_at": None,
        "block_time_seconds": None,
        "cadence_span_seconds": None,
        "tx_count": None,
        "load": None,
        "fee": None,
        "blocks": [],
        "error": error,
    }


async def _fetch_flows_cached() -> dict[str, Any]:
    cached = chains_cache.get("flows")
    if cached is not None:
        return cached
    result = await flows.fetch_flows()
    # Only a result that actually carried something is cached. Caching an
    # outage for half an hour would turn one bad minute into a blank strip for
    # the rest of it.
    if result.get("assets"):
        chains_cache.set("flows", result, FLOWS_CACHE_SECONDS)
    return result


async def fetch_board() -> dict[str, Any]:
    """
    The whole Chains board.

    Never raises. A refresh in which every single chain failed still returns a
    board — of eight unreachable rows — because that is a true and useful thing
    to render, and a 503 would leave the page unable to say which providers are
    down.
    """
    cached = chains_cache.get("board")
    if cached is not None:
        return cached

    snapshots, prices, flow_strip = await asyncio.gather(
        asyncio.gather(*(_fetch_one(chain) for chain in CHAINS), return_exceptions=True),
        _fetch_prices(),
        _fetch_flows_cached(),
    )

    rows: list[dict[str, Any]] = []
    for chain, snapshot in zip(CHAINS, snapshots):
        if isinstance(snapshot, BaseException):
            logger.warning("[Chains] %s unreadable: %s", chain.key, snapshot)
            rows.append(_empty_row(chain, str(snapshot) or snapshot.__class__.__name__))
            continue

        _price_the_fee(chain, snapshot, prices.get(chain.symbol))
        rows.append(
            {
                "key": chain.key,
                "name": chain.name,
                "symbol": chain.symbol,
                "family": chain.family,
                "target_block_seconds": chain.target_block_seconds,
                "explorer_block_url": chain.explorer_block_url,
                "hash_height_prefix_chars": chain.hash_height_prefix_chars,
                "error": None,
                **snapshot,
            }
        )

    board = {
        "chains": rows,
        "flows": flow_strip,
        "prices": prices,
        "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
        "stale": False,
    }

    # Only cached when at least one chain answered. A board of eight failures is
    # returned to this caller but not held, so the next poll ten seconds later
    # retries rather than replaying the outage.
    #
    # The same condition gates the history sample, for the same reason: an outage
    # is not an observation of the network, and letting one into the baseline
    # would manufacture a spike on the next successful read. `record` throttles
    # itself to one sample a quarter of an hour and never raises.
    if any(row["error"] is None for row in rows):
        chains_cache.set("board", board, CACHE_SECONDS)
        await history.record(board)
    return board


def stale_board() -> Optional[dict[str, Any]]:
    """The last good board, flagged as stale, if recent enough to still serve."""
    stale = chains_cache.get_with_fallback("board", max_age=MAX_STALE_SECONDS)
    return None if stale is None else {**stale, "stale": True}
