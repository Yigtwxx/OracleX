"""
Solana, read through its public JSON-RPC node.

The chain that fits the board least well, and the reasons are worth stating
because they decide what this returns:

- **There is no mempool.** Transactions are forwarded straight to the leader,
  so there is no queue to measure and no backlog to report. `load` is derived
  from slot production instead.
- **There is no gas market for a plain transfer.** A one-signature transaction
  costs 5,000 lamports whatever the network is doing. Priority fees exist, but
  they are optional and are not what a transfer pays, so the fee reported here
  is a constant and the board says so rather than implying a live quote.
- **Slots are not blocks.** A slot is a turn its leader may skip, so
  `absoluteSlot` runs ahead of `blockHeight`. Skipped slots are the useful
  signal: they are what a struggling Solana looks like.

**The stream is bucketed, and that is not a compromise.** Ten individual slots
span four seconds — no window at all next to Ethereum's two minutes. So the
stream covers `STREAM_SLOTS` scheduled slots and groups them into ten buckets of
equal width, each bar standing for about eight seconds. The bar's height is then
the share of that bucket's slots that actually produced a block, which is the
closest thing Solana has to the block-fullness bar the EVM chains draw: work
done against capacity offered.

**Skips are counted, not inferred, and the difference was a real bug.** The
first version of this module derived the skip rate from
`getRecentPerformanceSamples`, comparing slots produced against the number the
nominal 400ms cadence allows for. That measured almost nothing but cadence
drift: Solana's real slot time sits around 413ms, and 0.4/0.413 is 0.968, so a
network skipping nothing at all reported 3.2% skipped — permanently, and the
load bar was built on it. `getBlocksWithLimit` returns exactly the slots in a
range that produced a block, so the shortfall against the range is the skip
count itself. It is one call, and it is the same call the stream needs.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from services.chains.registry import LAMPORTS_PER_SOL, SOLANA_LAMPORTS_PER_SIGNATURE
from services.http_client import post_json

logger = logging.getLogger(__name__)

RPC_TIMEOUT = 12.0

# How many one-minute samples to average throughput over. Five smooths out the
# burst a single popular mint causes without hiding a sustained slowdown.
PERFORMANCE_SAMPLES = 5

# The stream's window, in scheduled slots, and how it is divided.
#
# Ten buckets because that is what the other chains draw, so the strip keeps the
# same shape whichever chain is selected. Ten slots to a bucket because the UI
# renders each bar as one segment per slot, lit where a block was produced —
# ten segments is the most a 40px-wide column can show and still be counted by
# eye, and it makes the grouping self-evident rather than something the caption
# has to explain.
#
# The result covers 100 scheduled slots, about forty seconds. Shorter than
# Ethereum's two minutes, but the same order of magnitude — which is the point,
# since ten raw slots would have been four seconds.
STREAM_BUCKETS = 10
SLOTS_PER_BUCKET = 10
STREAM_SLOTS = STREAM_BUCKETS * SLOTS_PER_BUCKET

# Read from a little behind the head. The most recent slots have not been
# confirmed yet, so including them would count "not finished" as "skipped" and
# show a permanent dip at the newest end of every stream.
CONFIRMATION_LAG_SLOTS = 40

# Where the skipped-slot reading saturates. Solana skips a fraction of a percent
# in normal operation, and past a fifth of its slots the network is visibly
# degraded — so that is where the bar tops out.
SKIP_SATURATION_PERCENT = 20.0


async def _rpc(url: str, method: str, params: list[Any]) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    response = await post_json(url, payload=payload, timeout=RPC_TIMEOUT)
    if isinstance(response, dict) and "error" in response:
        raise RuntimeError(f"solana {method}: {response['error']}")
    return response.get("result") if isinstance(response, dict) else None


async def _block_meta(url: str, slots: list[int]) -> dict[int, dict[str, Any]]:
    """
    `blockTime` and `blockhash` for each of `slots`, as one batch.

    `transactionDetails: "none"` is what keeps this affordable. The same call
    asking for signatures — the only way the RPC will report a transaction
    count — returns 130KB for a single slot, so ten of them would move 1.3MB
    every refresh to learn ten array lengths. At "none" a slot is 232 bytes.
    That is why the buckets carry no transaction count: it is not that Solana
    hides it, it is that the only route to it costs four orders of magnitude
    more than the number is worth.
    """
    if not slots:
        return {}

    batch = [
        {
            "jsonrpc": "2.0",
            "id": index,
            "method": "getBlock",
            "params": [
                slot,
                {
                    "transactionDetails": "none",
                    "rewards": False,
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        }
        for index, slot in enumerate(slots)
    ]

    response = await post_json(url, payload=batch, timeout=RPC_TIMEOUT)
    if not isinstance(response, list):
        return {}

    meta: dict[int, dict[str, Any]] = {}
    for entry in response:
        if not isinstance(entry, dict):
            continue
        result = entry.get("result")
        index = entry.get("id")
        if isinstance(result, dict) and isinstance(index, int) and 0 <= index < len(slots):
            block_time = result.get("blockTime")
            meta[slots[index]] = {
                "time": block_time if isinstance(block_time, int) else None,
                "hash": result.get("blockhash"),
            }
    return meta


async def fetch_solana(rpc_urls: tuple[str, ...], target_block_seconds: float) -> dict[str, Any]:
    """
    Solana's current state: slot height, epoch progress, throughput, the share
    of slots the network is dropping, and the bucketed production stream.

    Epoch info is load-bearing — without it there is no height. Everything else
    degrades on its own: a failed stream leaves the card its cadence and
    throughput rather than costing Solana its row.
    """
    last_error: Optional[BaseException] = None

    for url in rpc_urls:
        epoch_raw, samples_raw = await asyncio.gather(
            _rpc(url, "getEpochInfo", []),
            _rpc(url, "getRecentPerformanceSamples", [PERFORMANCE_SAMPLES]),
            return_exceptions=True,
        )

        if isinstance(epoch_raw, BaseException) or not isinstance(epoch_raw, dict):
            last_error = (
                epoch_raw
                if isinstance(epoch_raw, BaseException)
                else RuntimeError("solana returned no epoch info")
            )
            logger.warning("[Chains] solana epoch info unavailable (%s): %s", url, last_error)
            continue

        if isinstance(samples_raw, BaseException):
            logger.warning("[Chains] solana performance samples unavailable: %s", samples_raw)
            samples_raw = []

        blocks: list[dict[str, Any]] = []
        skipped_percent: Optional[float] = None
        head_slot = epoch_raw.get("absoluteSlot")

        # Every endpoint gets its own turn at the stream, not just the one that
        # answered for the epoch. The stream is two further calls against a
        # rate-limited public node, so it is the part that fails first — and it
        # failing is not a reason to leave the card without a load bar when
        # another node would have served it.
        if isinstance(head_slot, int):
            for stream_url in rpc_urls:
                try:
                    blocks, skipped_percent = await _fetch_stream(stream_url, head_slot)
                except Exception as e:  # noqa: BLE001 — the stream is not load-bearing
                    logger.warning(
                        "[Chains] solana slot stream unavailable (%s): %s", stream_url, e
                    )
                    continue
                if blocks:
                    break

        return _build(
            epoch_raw,
            samples_raw if isinstance(samples_raw, list) else [],
            blocks,
            skipped_percent,
            target_block_seconds,
        )

    raise last_error or RuntimeError("no Solana RPC endpoint answered")


async def _fetch_stream(url: str, head_slot: int) -> tuple[list[dict[str, Any]], Optional[float]]:
    """
    The bucketed production stream, and the true skip rate over its window.

    Returns buckets newest-first, matching every other chain's stream.
    """
    end_slot = head_slot - CONFIRMATION_LAG_SLOTS
    start_slot = end_slot - STREAM_SLOTS + 1
    if start_slot < 0:
        return [], None

    produced = await _rpc(url, "getBlocksWithLimit", [start_slot, STREAM_SLOTS])
    if not isinstance(produced, list) or not produced:
        return [], None

    produced_set = set(produced)
    # Against the range that was *scheduled*, not against the slots that came
    # back — dividing the returned list by itself would always be 100%.
    skipped_percent = round((1 - len(produced_set) / STREAM_SLOTS) * 100, 3)

    # One bucket per SLOTS_PER_BUCKET consecutive scheduled slots, oldest first
    # while they are being built, then reversed.
    buckets: list[dict[str, Any]] = []
    for index in range(STREAM_BUCKETS):
        bucket_start = start_slot + index * SLOTS_PER_BUCKET
        bucket_slots = range(bucket_start, bucket_start + SLOTS_PER_BUCKET)
        hits = [slot for slot in bucket_slots if slot in produced_set]
        buckets.append(
            {
                # The newest slot that actually produced a block, so the label
                # links to something that exists. Falls back to the scheduled
                # end of the bucket when every slot in it was skipped.
                "height": hits[-1] if hits else bucket_start + SLOTS_PER_BUCKET - 1,
                "hash": None,
                "timestamp_ms": None,
                # Not available at any sane cost — see `_block_times`.
                "tx_count": None,
                "fill_percent": round(len(hits) / SLOTS_PER_BUCKET * 100, 1),
                "slots_produced": len(hits),
                "slots_scheduled": SLOTS_PER_BUCKET,
            }
        )

    # Real timestamps and hashes for the buckets, rather than interpolating from
    # the cadence. Ten slots at 232 bytes each is a batch worth sending.
    #
    # The hash belongs to the slot the bucket is *labelled* by — its newest
    # produced slot — not to the group, which has no hash of its own. That is
    # the same slot the column links to, so the two agree.
    meta = await _block_meta(url, [bucket["height"] for bucket in buckets])
    for bucket in buckets:
        entry = meta.get(bucket["height"])
        if entry is None:
            continue
        if entry["time"] is not None:
            bucket["timestamp_ms"] = entry["time"] * 1000
        bucket["hash"] = entry["hash"]

    buckets.reverse()
    return buckets, skipped_percent


def _build(
    epoch: dict[str, Any],
    samples: list[Any],
    blocks: list[dict[str, Any]],
    skipped_percent: Optional[float],
    target_block_seconds: float,
) -> dict[str, Any]:
    absolute_slot = epoch.get("absoluteSlot")
    block_height = epoch.get("blockHeight")
    slot_index = epoch.get("slotIndex")
    slots_in_epoch = epoch.get("slotsInEpoch")

    # ── Throughput and cadence, from the samples ─────────────────────────────
    #
    # The samples are still the right source for these two: they report slots
    # and transactions over a known period, which is exactly a rate. It was only
    # the *skip* rate they could not support, because that needs the schedule
    # rather than the clock.
    total_txs = 0
    total_non_vote = 0
    total_slots = 0
    total_seconds = 0
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        period = sample.get("samplePeriodSecs")
        slots = sample.get("numSlots")
        if not isinstance(period, int) or not isinstance(slots, int) or period <= 0:
            continue
        total_seconds += period
        total_slots += slots
        if isinstance(sample.get("numTransactions"), int):
            total_txs += sample["numTransactions"]
        if isinstance(sample.get("numNonVoteTransactions"), int):
            total_non_vote += sample["numNonVoteTransactions"]

    tps: Optional[float] = None
    non_vote_tps: Optional[float] = None
    slot_time: Optional[float] = None

    if total_seconds > 0:
        tps = round(total_txs / total_seconds, 1)
        non_vote_tps = round(total_non_vote / total_seconds, 1)
        if total_slots > 0:
            slot_time = round(total_seconds / total_slots, 3)

    load: Optional[dict[str, Any]] = None
    if skipped_percent is not None:
        load = {
            "percent": round(min(skipped_percent / SKIP_SATURATION_PERCENT, 1.0) * 100, 1),
            "basis": "skipped_slots",
        }

    # ── Epoch ────────────────────────────────────────────────────────────────
    epoch_progress: Optional[float] = None
    epoch_ends_at: Optional[int] = None
    if isinstance(slot_index, int) and isinstance(slots_in_epoch, int) and slots_in_epoch > 0:
        epoch_progress = round(slot_index / slots_in_epoch * 100, 2)
        remaining = slots_in_epoch - slot_index
        # Projected on the cadence actually observed, not the nominal 400ms.
        # Solana's real slot time runs consistently above target, so the nominal
        # figure would put every epoch boundary hours early.
        pace = slot_time or target_block_seconds
        epoch_ends_at = int((time.time() + remaining * pace) * 1000)

    return {
        # The slot, not `blockHeight`: it is what every Solana explorer shows and
        # what the chain's own cadence is measured in.
        "height": absolute_slot,
        # The head slot is not dated — only the stream's buckets are, and the
        # head is deliberately ahead of them by the confirmation lag. A card
        # cannot count up from an instant it does not have, which is why
        # Solana's shows its block rate instead.
        "last_block_at": None,
        "block_time_seconds": slot_time,
        "cadence_span_seconds": total_seconds or None,
        "tx_count": None,
        "load": load,
        "fee": {
            "transfer_native": SOLANA_LAMPORTS_PER_SIGNATURE / LAMPORTS_PER_SOL,
            # Named so the UI can say the number is a protocol constant rather
            # than a live quote. Nothing else on the board is fixed like this.
            "is_fixed": True,
        },
        "throughput": {
            "tps": tps,
            # What the board shows by default. Vote transactions are consensus
            # traffic, not user activity, and they are roughly half of Solana's
            # headline TPS — quoting the total invites a comparison with
            # Ethereum's that is not measuring the same thing.
            "non_vote_tps": non_vote_tps,
            "skipped_slot_percent": skipped_percent,
        },
        "economics": {
            "epoch": epoch.get("epoch"),
            "epoch_progress_percent": epoch_progress,
            "epoch_ends_at": epoch_ends_at,
            "block_height": block_height,
        },
        "blocks": blocks,
        # Tells the UI the stream's rows are groups rather than single blocks,
        # so it can label them as such instead of implying twenty slots are one.
        "stream_bucket_slots": SLOTS_PER_BUCKET,
    }
