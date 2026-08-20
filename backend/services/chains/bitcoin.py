"""
Bitcoin, read through mempool.space.

The one chain on the board whose interesting numbers are not about the last
block. Ethereum's story is told by fullness and fee; Bitcoin's is told by the
backlog waiting to get in, the difficulty retarget it is halfway through, and
the halving it is counting down to. All four come from mempool.space, free and
keyless, which the app already depends on for the home board.

Congestion here deliberately is not "how full was the last block". Bitcoin
blocks are always full — a miner takes the top 1M vB of the mempool whatever
that is worth — so fullness is 100% on a dead network and 100% on a frantic
one. The measure that separates them is how many blocks deep the queue is, and
that is what `load` reports.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from services.http_client import get_json

logger = logging.getLogger(__name__)

MEMPOOL_API = "https://mempool.space/api"
API_TIMEOUT = 8.0

# Virtual bytes a miner can take in one block: the 4M weight-unit consensus
# limit works out to 1M vB. Used to express the raw mempool as a depth in
# blocks, which is the only unit in which "42 million vB" means anything.
BLOCK_VBYTES = 1_000_000

# Where the queue-depth reading saturates. Six blocks is about an hour of
# backlog: past that the difference between "very congested" and "even more
# congested" stops changing what anyone would do, so the bar tops out and the
# fee number carries the rest of the story.
BACKLOG_SATURATION_BLOCKS = 6.0

# The floor a transaction has to clear to be competing for space at all.
# Bitcoin Core's default minimum relay fee, and the fallback for the threshold
# below when the fee recommendation could not be read.
MIN_RELAY_SAT_VB = 1.0

# Blocks between halvings, fixed by consensus.
HALVING_INTERVAL = 210_000


def _first_float(payload: Any, *keys: str) -> Optional[float]:
    """The first key present on a dict, as a float, or None."""
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


async def _get(path: str) -> Any:
    return await get_json(f"{MEMPOOL_API}{path}", timeout=API_TIMEOUT)


async def fetch_bitcoin(target_block_seconds: float) -> dict[str, Any]:
    """
    Bitcoin's current state: recent blocks, the mempool backlog, fees, and the
    two countdowns the chain runs on.

    The five upstream calls are independent, so they go out together and each is
    allowed to fail on its own. Only the block list is load-bearing: without it
    there is no height and no cadence, and the caller is told the chain could not
    be read. The rest degrade to None, which the board renders as an unmeasured
    reading rather than a zero.
    """
    (
        blocks_raw,
        mempool_raw,
        fees_raw,
        difficulty_raw,
        hashrate_raw,
        projected_raw,
    ) = await asyncio.gather(
        _get("/blocks"),
        _get("/mempool"),
        _get("/v1/fees/recommended"),
        _get("/v1/difficulty-adjustment"),
        _get("/v1/mining/hashrate/3d"),
        _get("/v1/fees/mempool-blocks"),
        return_exceptions=True,
    )

    if isinstance(blocks_raw, BaseException) or not isinstance(blocks_raw, list) or not blocks_raw:
        raise RuntimeError("mempool.space did not return a block list") from (
            blocks_raw if isinstance(blocks_raw, BaseException) else None
        )

    for name, value in (
        ("mempool", mempool_raw),
        ("fees", fees_raw),
        ("difficulty", difficulty_raw),
        ("hashrate", hashrate_raw),
        ("projected blocks", projected_raw),
    ):
        if isinstance(value, BaseException):
            logger.warning("[Chains] bitcoin %s unavailable: %s", name, value)

    mempool = mempool_raw if isinstance(mempool_raw, dict) else {}
    fees = fees_raw if isinstance(fees_raw, dict) else {}
    difficulty = difficulty_raw if isinstance(difficulty_raw, dict) else {}
    hashrate = hashrate_raw if isinstance(hashrate_raw, dict) else {}
    projected = projected_raw if isinstance(projected_raw, list) else []

    # ── Blocks and cadence ───────────────────────────────────────────────────
    blocks: list[dict[str, Any]] = []
    for entry in blocks_raw:
        if not isinstance(entry, dict) or "height" not in entry:
            continue
        weight = entry.get("weight")
        blocks.append(
            {
                "height": entry["height"],
                # mempool.space calls the block hash `id`. Its leading zeros are
                # not padding — they are the proof of work, and they vary block
                # to block, which is why the UI counts them rather than only
                # stripping them.
                "hash": entry.get("id"),
                "timestamp_ms": (
                    entry["timestamp"] * 1000 if isinstance(entry.get("timestamp"), int) else None
                ),
                "tx_count": entry.get("tx_count"),
                # Weight against the 4M-unit consensus limit, which is the real
                # ceiling a Bitcoin block fills — `size` in bytes has no fixed
                # limit to divide by since SegWit.
                "fill_percent": (
                    round(weight / 4_000_000 * 100, 2) if isinstance(weight, int) else None
                ),
                "size_bytes": entry.get("size"),
            }
        )
    blocks.sort(key=lambda b: b["height"], reverse=True)

    height = blocks[0]["height"]
    last_block_at = blocks[0]["timestamp_ms"]

    # Averaged across the returned window rather than taken between the last two
    # blocks. Bitcoin's interval is a Poisson process — consecutive blocks land
    # forty seconds apart about as often as they land forty minutes apart — so a
    # single gap says nothing about the chain's rate.
    block_time: Optional[float] = None
    if len(blocks) >= 2 and blocks[0]["timestamp_ms"] and blocks[-1]["timestamp_ms"]:
        span_ms = blocks[0]["timestamp_ms"] - blocks[-1]["timestamp_ms"]
        gaps = len(blocks) - 1
        if span_ms > 0 and gaps > 0:
            block_time = round(span_ms / 1000 / gaps, 1)

    # ── Backlog ──────────────────────────────────────────────────────────────
    #
    # Measured against the projected blocks a miner would actually build, not
    # against the raw mempool, and the difference is not academic. A recent
    # reading had 42M vB queued — forty-two blocks deep — while the fee
    # recommendation sat at 1 sat/vB across every tier, meaning anything paying
    # the floor cleared within the hour. Dividing the raw size by the block
    # limit reported that quiet chain as 100% congested.
    #
    # The reason is that the mempool retains transactions that are not competing
    # for anything: in that same reading, 35 of the 42 blocks were a single
    # 0.13 sat/vB pile that will not confirm at any foreseeable price. Counting
    # only the projected blocks whose median fee clears the economy tier drops
    # that pile and leaves the one block that was genuinely contested.
    mempool_vsize = mempool.get("vsize") if isinstance(mempool.get("vsize"), int) else None
    raw_backlog_blocks = (
        round(mempool_vsize / BLOCK_VBYTES, 2) if mempool_vsize is not None else None
    )

    # The economy tier is mempool.space's own "cheapest that still confirms".
    # Anything below it is queued, not competing.
    threshold = _first_float(fees, "economyFee", "minimumFee") or MIN_RELAY_SAT_VB

    backlog_blocks: Optional[float] = None
    load: Optional[dict[str, Any]] = None
    if projected:
        contested = 0
        for block in projected:
            median = block.get("medianFee") if isinstance(block, dict) else None
            if isinstance(median, (int, float)) and median >= threshold:
                contested += 1
        backlog_blocks = float(contested)
        load = {
            "percent": round(min(backlog_blocks / BACKLOG_SATURATION_BLOCKS, 1.0) * 100, 1),
            "basis": "fee_contested_backlog",
        }

    # ── Halving ──────────────────────────────────────────────────────────────
    halving_height = (height // HALVING_INTERVAL + 1) * HALVING_INTERVAL
    halving_remaining = halving_height - height
    halving_at_ms: Optional[int] = None
    if last_block_at is not None:
        halving_at_ms = last_block_at + int(halving_remaining * target_block_seconds * 1000)

    retarget_at = difficulty.get("estimatedRetargetDate")

    return {
        "height": height,
        "last_block_at": last_block_at,
        "block_time_seconds": block_time,
        "cadence_span_seconds": (
            int((blocks[0]["timestamp_ms"] - blocks[-1]["timestamp_ms"]) / 1000)
            if len(blocks) >= 2 and blocks[0]["timestamp_ms"] and blocks[-1]["timestamp_ms"]
            else None
        ),
        "tx_count": blocks[0]["tx_count"],
        "load": load,
        "fee": {
            # sat/vB, the unit Bitcoin fees are actually quoted in. Converted to
            # a currency figure by the service, which is the only place that
            # knows the coin's price.
            "fastest_sat_vb": _first_float(fees, "fastestFee"),
            "half_hour_sat_vb": _first_float(fees, "halfHourFee"),
            "hour_sat_vb": _first_float(fees, "hourFee"),
            "economy_sat_vb": _first_float(fees, "economyFee"),
        },
        "mempool": {
            "tx_count": mempool.get("count"),
            "vsize": mempool_vsize,
            #: Blocks deep in transactions that are actually bidding for space.
            "backlog_blocks": backlog_blocks,
            #: Blocks deep counting everything queued, dust included. Reported
            #: alongside rather than instead, because the gap between the two is
            #: itself the interesting number — see the comment above.
            "raw_backlog_blocks": raw_backlog_blocks,
            "contested_fee_threshold_sat_vb": threshold,
            "total_fee_sat": mempool.get("total_fee"),
        },
        "economics": {
            "hashrate": _first_float(hashrate, "currentHashrate"),
            "difficulty": _first_float(hashrate, "currentDifficulty")
            or _first_float(difficulty, "previousRetarget"),
            "difficulty_change_percent": _first_float(difficulty, "difficultyChange"),
            "difficulty_progress_percent": _first_float(difficulty, "progressPercent"),
            "difficulty_retarget_at": int(retarget_at)
            if isinstance(retarget_at, (int, float))
            else None,
            "difficulty_blocks_remaining": difficulty.get("remainingBlocks"),
            "halving_height": halving_height,
            "halving_blocks_remaining": halving_remaining,
            "halving_estimated_at": halving_at_ms,
        },
        "blocks": blocks,
    }
