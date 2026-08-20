"""
TRON, read through TronGrid's public HTTP API.

One call does the whole job: `getblockbylatestnum` returns the last N blocks
with their headers and transaction lists, so the stream, the height and the
cadence all come out of a single request. Nothing else on the board is that
cheap to read.

Two things TRON does not have, and which are therefore reported as absent rather
than as zero:

- **No block-fullness ceiling that means anything to a reader.** TRON meters
  execution in Energy and bandwidth against per-account daily allowances, not
  against a per-block gas limit, so there is no "this block was 74% full".
- **No fee on an ordinary transfer.** A TRX transfer is paid for out of the
  free bandwidth every account is granted daily, which is why the chain shows
  five hundred transactions a block and a fee of nothing. The board reports zero
  here as a measured fact with a note, not as a missing reading — this is the one
  place on the whole board where zero is the true answer.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from services.http_client import post_json

logger = logging.getLogger(__name__)

TRONGRID_API = "https://api.trongrid.io"
API_TIMEOUT = 10.0

# Blocks pulled per refresh. Matches the EVM stream length so the two render at
# the same width.
STREAM_BLOCKS = 10


async def fetch_tron() -> dict[str, Any]:
    """
    TRON's current state: the last blocks, their transaction counts, and the
    cadence measured across them.

    Raises if TronGrid did not answer or returned nothing usable — there is no
    second endpoint to fall back to, and an empty block list would render as a
    halted chain.
    """
    raw = await post_json(
        f"{TRONGRID_API}/wallet/getblockbylatestnum",
        payload={"num": STREAM_BLOCKS},
        timeout=API_TIMEOUT,
    )

    entries = raw.get("block") if isinstance(raw, dict) else None
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("TronGrid returned no blocks")

    blocks: list[dict[str, Any]] = []
    for entry in entries:
        header = (entry or {}).get("block_header", {}).get("raw_data", {})
        number = header.get("number")
        timestamp = header.get("timestamp")
        if not isinstance(number, int):
            continue
        blocks.append(
            {
                "height": number,
                # TRON's `blockID` is not an opaque digest: its first eight bytes
                # are the block number, so the leading zeros are an artefact of
                # zero-padding a small height into 64 hex characters rather than
                # anything the chain worked for. Stripping them leaves the
                # height in hex followed by the digest proper.
                "hash": (entry or {}).get("blockID"),
                # Already milliseconds upstream, unlike every other chain here,
                # which reports whole seconds.
                "timestamp_ms": timestamp if isinstance(timestamp, int) else None,
                "tx_count": len(entry.get("transactions") or []),
                # See the module docstring: there is no ceiling to fill.
                "fill_percent": None,
            }
        )

    if not blocks:
        raise RuntimeError("TronGrid returned no readable block headers")

    blocks.sort(key=lambda b: b["height"], reverse=True)

    block_time: Optional[float] = None
    span_seconds: Optional[int] = None
    if len(blocks) >= 2 and blocks[0]["timestamp_ms"] and blocks[-1]["timestamp_ms"]:
        span_ms = blocks[0]["timestamp_ms"] - blocks[-1]["timestamp_ms"]
        gaps = len(blocks) - 1
        if span_ms > 0 and gaps > 0:
            block_time = round(span_ms / 1000 / gaps, 2)
            span_seconds = int(span_ms / 1000)

    return {
        "height": blocks[0]["height"],
        "last_block_at": blocks[0]["timestamp_ms"],
        "block_time_seconds": block_time,
        "cadence_span_seconds": span_seconds,
        "tx_count": blocks[0]["tx_count"],
        "load": None,
        "fee": {
            "transfer_native": 0.0,
            "is_fixed": True,
            # Distinguishes "measured as free" from "could not be measured", and
            # is what the UI prints instead of a currency figure.
            "free_reason": "covered by the daily bandwidth allowance",
        },
        "blocks": blocks,
    }
