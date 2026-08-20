"""
One adapter for every EVM chain on the board: Ethereum, Base, Arbitrum, OP and
BNB Chain.

They differ in cadence by a factor of fifty and in fee by four orders of
magnitude, but they answer the same five JSON-RPC methods, so the differences
belong in `registry.Chain` rather than in five near-identical modules.

Three things here are not obvious:

1. **One round trip per chain.** Everything the board needs — the recent blocks
   it streams, the anchor block it measures cadence against, the gas price and
   the rollup's L1 fee — goes out as a single JSON-RPC *batch*. A naive port
   would issue fourteen requests per chain and eighty per refresh.

2. **Cadence is measured over a fixed span of time, not a fixed count of
   blocks.** Block timestamps are whole seconds, so on Arbitrum — four blocks a
   second — consecutive blocks differ by 0 or 1, and averaging ten of them
   yields a number that is wrong by a factor of four. The anchor is therefore
   chosen so the span is about a minute on every chain, which is 5 blocks back
   on Ethereum and 240 on Arbitrum.

3. **Fullness is reported only where a ceiling is real.** See `registry`.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from services.chains.registry import EVM_TRANSFER_GAS, Chain
from services.http_client import post_json

logger = logging.getLogger(__name__)

RPC_TIMEOUT = 8.0

# How many recent blocks the board streams. Ten is what fills the strip at the
# width the panel is drawn; asking for more would cost nothing extra in round
# trips but would push a payload nobody renders.
STREAM_BLOCKS = 10

# The span cadence is averaged over. A minute is long enough that the whole-
# second timestamp resolution rounds out even on a four-blocks-a-second chain,
# and short enough that a cadence that has just changed shows up on this refresh
# rather than two refreshes later.
CADENCE_SPAN_SECONDS = 60.0

# Ceiling on how far back the anchor may sit. Without it the span rule would ask
# Arbitrum for a block 240 back — which is correct — but any future chain with a
# 50ms cadence would silently start requesting blocks a thousand deep.
MAX_CADENCE_LOOKBACK = 400

# OP-stack predeploy that prices posting a transaction's data to Ethereum, and
# the selector for `getL1Fee(bytes)`.
L1_GAS_ORACLE = "0x420000000000000000000000000000000000000F"
L1_FEE_SELECTOR = "0x49948e0e"

# Bytes of a serialized native-transfer envelope, which is what the oracle
# prices. The exact payload does not matter — the oracle charges by calldata
# size and zero/non-zero byte mix — but the *size* does, so this is a realistic
# one rather than a round number.
TRANSFER_ENVELOPE_BYTES = 110


def _hex_to_int(value: Any) -> Optional[int]:
    """Parse a JSON-RPC quantity, or None when the node omitted or nulled it."""
    if not isinstance(value, str):
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def _encode_l1_fee_call() -> str:
    """
    ABI-encode `getL1Fee(bytes)` for a transfer-sized payload.

    Hand-rolled rather than pulled in with `eth-abi`: this is the only ABI call
    in the codebase, and its argument is one dynamic `bytes` — a head holding
    the offset, then the length, then the payload padded to a 32-byte boundary.
    A dependency for eleven lines would be the larger cost.
    """
    payload = b"\x02" + b"\xab" * (TRANSFER_ENVELOPE_BYTES - 1)
    padding = (32 - len(payload) % 32) % 32
    return L1_FEE_SELECTOR + f"{32:064x}" + f"{len(payload):064x}" + payload.hex() + "00" * padding


def _cadence_lookback(chain: Chain) -> int:
    """How many blocks back the cadence anchor sits, for a ~60s span."""
    blocks = round(CADENCE_SPAN_SECONDS / max(chain.target_block_seconds, 0.01))
    return max(2, min(blocks, MAX_CADENCE_LOOKBACK))


def _block_request(request_id: int, number: int | str) -> dict[str, Any]:
    tag = number if isinstance(number, str) else hex(number)
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "eth_getBlockByNumber",
        # False: hashes rather than full transaction objects. A busy Ethereum
        # block carries several hundred transactions, and the board only ever
        # counts them — asking for the objects would multiply the payload by
        # roughly a thousand to learn a length.
        "params": [tag, False],
    }


async def _rpc_batch(chain: Chain, requests: list[dict[str, Any]]) -> dict[int, Any]:
    """
    Send one JSON-RPC batch, trying each configured endpoint in turn.

    Returns results keyed by request id, with entries missing for any call the
    node answered with an error. A partial answer is deliberately allowed
    through: `eth_call` against the L1 oracle fails on chains that have no such
    predeploy, and losing the fee should not cost the whole chain its row.
    """
    last_error: Optional[BaseException] = None

    for url in chain.rpc_urls:
        try:
            raw = await post_json(url, payload=requests, timeout=RPC_TIMEOUT)
        except Exception as e:  # noqa: BLE001 — every endpoint gets its turn
            logger.warning("[Chains] %s RPC unreachable (%s): %s", chain.key, url, e)
            last_error = e
            continue

        if not isinstance(raw, list):
            logger.warning("[Chains] %s returned a non-batch response from %s", chain.key, url)
            continue

        results: dict[int, Any] = {}
        for entry in raw:
            if not isinstance(entry, dict) or "result" not in entry:
                continue
            results[entry.get("id")] = entry["result"]

        # An endpoint that answered nothing usable is treated as a failure so
        # the next one still gets a turn, rather than returning an empty dict
        # that the caller would read as "this chain has no blocks".
        if results:
            return results

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"no RPC endpoint answered for {chain.key}")


def _fill_percent(
    chain: Chain, gas_used: Optional[int], gas_limit: Optional[int]
) -> Optional[float]:
    """
    How full a block is, or None where that question has no answer.

    None on Arbitrum by design — see `registry`. Also None when either quantity
    is missing, rather than treating an absent `gasUsed` as an empty block.
    """
    if not chain.gas_ceiling or gas_used is None or not gas_limit:
        return None
    return round(gas_used / gas_limit * 100, 2)


async def fetch_evm(chain: Chain) -> dict[str, Any]:
    """
    One EVM chain's current state, in a single round trip.

    Raises if no endpoint answered. Individual readings inside the payload come
    back as None when the node did not report them; nothing is defaulted to zero,
    because a zero fee and an unmeasured fee render identically and mean the
    opposite things.
    """
    lookback = _cadence_lookback(chain)

    # Ids are assigned by role so the response can be taken apart without
    # depending on the order the node chose to answer in — JSON-RPC explicitly
    # allows a batch to come back shuffled.
    ID_GAS_PRICE = 1
    ID_L1_FEE = 2
    ID_ANCHOR = 3
    ID_STREAM_BASE = 100

    requests: list[dict[str, Any]] = [
        {"jsonrpc": "2.0", "id": ID_GAS_PRICE, "method": "eth_gasPrice", "params": []},
        _block_request(ID_STREAM_BASE, "latest"),
    ]
    if chain.l1_data_fee:
        requests.append(
            {
                "jsonrpc": "2.0",
                "id": ID_L1_FEE,
                "method": "eth_call",
                "params": [{"to": L1_GAS_ORACLE, "data": _encode_l1_fee_call()}, "latest"],
            }
        )

    # The head's height is not known until the batch comes back, so the stream
    # and the anchor need a second one. Two round trips per chain rather than
    # one is the price of not hardcoding a height; `eth_blockNumber` first would
    # have cost the same.
    head = await _rpc_batch(chain, requests)
    latest = head.get(ID_STREAM_BASE)
    if not isinstance(latest, dict):
        raise RuntimeError(f"{chain.key} did not return a head block")

    height = _hex_to_int(latest.get("number"))
    if height is None:
        raise RuntimeError(f"{chain.key} head block carries no height")

    follow_up = [_block_request(ID_ANCHOR, max(height - lookback, 0))]
    for offset in range(1, STREAM_BLOCKS):
        follow_up.append(_block_request(ID_STREAM_BASE + offset, height - offset))
    rest = await _rpc_batch(chain, follow_up)

    # ── Cadence ──────────────────────────────────────────────────────────────
    head_ts = _hex_to_int(latest.get("timestamp"))
    anchor = rest.get(ID_ANCHOR)
    anchor_ts = _hex_to_int(anchor.get("timestamp")) if isinstance(anchor, dict) else None
    anchor_height = _hex_to_int(anchor.get("number")) if isinstance(anchor, dict) else None

    block_time: Optional[float] = None
    span_seconds: Optional[int] = None
    if head_ts is not None and anchor_ts is not None and anchor_height is not None:
        blocks_apart = height - anchor_height
        span_seconds = head_ts - anchor_ts
        if blocks_apart > 0 and span_seconds > 0:
            block_time = round(span_seconds / blocks_apart, 3)

    # ── The stream ───────────────────────────────────────────────────────────
    blocks: list[dict[str, Any]] = []
    burn_wei_total = 0
    burn_samples = 0
    for offset in range(STREAM_BLOCKS):
        raw = latest if offset == 0 else rest.get(ID_STREAM_BASE + offset)
        if not isinstance(raw, dict):
            continue
        number = _hex_to_int(raw.get("number"))
        timestamp = _hex_to_int(raw.get("timestamp"))
        gas_used = _hex_to_int(raw.get("gasUsed"))
        gas_limit = _hex_to_int(raw.get("gasLimit"))
        base_fee = _hex_to_int(raw.get("baseFeePerGas"))
        if number is None:
            continue

        if base_fee is not None and gas_used is not None:
            burn_wei_total += base_fee * gas_used
            burn_samples += 1

        blocks.append(
            {
                "height": number,
                # Already in hand from the batch — the header carries it, so the
                # strip labels its columns with the block's own identity at no
                # extra call.
                "hash": raw.get("hash"),
                "timestamp_ms": timestamp * 1000 if timestamp is not None else None,
                "tx_count": len(raw.get("transactions") or []),
                "fill_percent": _fill_percent(chain, gas_used, gas_limit),
                "gas_used": gas_used,
                "gas_limit": gas_limit,
            }
        )

    blocks.sort(key=lambda b: b["height"], reverse=True)

    # ── Fees ─────────────────────────────────────────────────────────────────
    gas_price_wei = _hex_to_int(head.get(ID_GAS_PRICE))
    base_fee_wei = _hex_to_int(latest.get("baseFeePerGas"))
    l1_fee_wei = _hex_to_int(head.get(ID_L1_FEE)) if chain.l1_data_fee else None

    transfer_wei: Optional[int] = None
    if gas_price_wei is not None:
        transfer_wei = gas_price_wei * EVM_TRANSFER_GAS
        # The rollups' execution fee is the smaller half of the bill whenever
        # Ethereum is busy. Leaving it out would have shown Base and OP as an
        # order of magnitude cheaper than they are.
        if l1_fee_wei is not None:
            transfer_wei += l1_fee_wei

    # Burn is a rate, so it needs a cadence to be expressed per day. Reported as
    # None rather than extrapolated from the target when the chain's own cadence
    # could not be measured.
    burn_native_per_day: Optional[float] = None
    if burn_samples and block_time and block_time > 0:
        mean_burn_wei = burn_wei_total / burn_samples
        burn_native_per_day = mean_burn_wei / 1e18 * (86_400 / block_time)

    return {
        "height": height,
        "last_block_at": head_ts * 1000 if head_ts is not None else None,
        "block_time_seconds": block_time,
        "cadence_span_seconds": span_seconds,
        "tx_count": blocks[0]["tx_count"] if blocks else None,
        "load": (
            {"percent": blocks[0]["fill_percent"], "basis": "block_fullness"}
            if blocks and blocks[0]["fill_percent"] is not None
            else None
        ),
        "fee": {
            "gas_price_gwei": gas_price_wei / 1e9 if gas_price_wei is not None else None,
            "base_fee_gwei": base_fee_wei / 1e9 if base_fee_wei is not None else None,
            "l1_data_fee_native": l1_fee_wei / 1e18 if l1_fee_wei is not None else None,
            "transfer_native": transfer_wei / 1e18 if transfer_wei is not None else None,
        },
        "burn_native_per_day": burn_native_per_day,
        "blocks": blocks,
    }
