"""
A rolling baseline for the chain board's own readings.

Nothing in this application remembers what a chain looked like an hour ago.
`ServiceCache.set` replaces its fallback slot with the value it just wrote, so
after a successful refresh there is exactly zero retained history — which makes
"this fee is unusual" a sentence the board could not previously support at any
level of rigour. This module keeps enough of one to say it.

## The sampling bias, and what is done about it

Samples are taken on the request path, so the board is only sampled while
somebody has the page open. A plain seven-day median over that is not a baseline:
gas prices are strongly diurnal, browsing is diurnal too, and the two correlate.
A median built mostly from European evenings would flag a normal Asian morning as
an anomaly — a number that looks authoritative and is not, which is precisely
what `flows.py` refuses to ship.

So a reading is never compared against the whole window. It is compared against
the same hour of day on other days, and when that band is too thin the answer is
"not enough history", not a guess. That removes the diurnal term entirely at the
cost of a longer warm-up, and the warm-up is visible rather than silent: every
baseline reports how many samples across how many days it was built from.

The exchange-flow detectors in `anomaly.py` do not depend on any of this — they
run off Coin Metrics' own thirty-day dailies and work on a cold start — so the
page is useful from the first load and gets sharper as this fills in.

## Cost

One sample per chain per fifteen minutes, seven days deep: 672 rows a chain,
eight chains, well under a megabyte of JSON. At most four writes an hour no
matter how many tabs are open, each one atomic and off the event loop.
"""

import asyncio
import json
import logging
import os
import statistics
import threading
import time
from datetime import UTC, datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

STORE_FILE = "data/chain_metrics.json"
STORE_VERSION = 1

# One sample a quarter of an hour. The board's own cache is ten seconds, so
# without this gate a busy page would write the store hundreds of times an hour
# to record readings that had barely moved.
SAMPLE_INTERVAL_SECONDS = 900

RETENTION_SECONDS = 7 * 24 * 3600
MAX_SAMPLES_PER_CHAIN = 700

# Readings sampled per chain. Deliberately short: these are the ones with a
# meaningful baseline, and every extra field is seven days of disk.
METRICS = ("fee_native", "fee_usd", "load_percent", "block_time_seconds", "backlog_blocks")

# Hours either side of the current hour that count as the same time of day. A
# three-hour band is wide enough to fill at a realistic visit rate and narrow
# enough that the diurnal shape inside it is flat.
HOUR_BAND = 1

# A baseline needs this many readings, drawn from this many separate days. The
# day count is the important half: fifteen samples from one long session is one
# observation of one afternoon, not a baseline.
MIN_BAND_SAMPLES = 5
MIN_BAND_DAYS = 3

_lock = threading.Lock()
_samples: Optional[dict[str, list[dict[str, Any]]]] = None
_last_sample_at: float = 0.0


def _load() -> dict[str, list[dict[str, Any]]]:
    """Caller holds the lock."""
    global _samples
    if _samples is not None:
        return _samples

    _samples = {}
    if not os.path.exists(STORE_FILE):
        return _samples

    try:
        with open(STORE_FILE) as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        # Losing the baseline is a real cost — a day of warm-up — so it is logged
        # rather than swallowed the way a cache miss would be.
        logger.warning("[Chains] metric history unreadable, starting empty: %s", e)
        return _samples

    if isinstance(payload, dict) and payload.get("version") == STORE_VERSION:
        chains = payload.get("chains")
        if isinstance(chains, dict):
            _samples = {key: list(rows) for key, rows in chains.items() if isinstance(rows, list)}
    return _samples


def _write(payload: dict[str, Any]) -> None:
    """
    Replace the store atomically.

    A half-written file reads back as a JSON error, which discards seven days of
    baseline and restarts the warm-up with no signal. `os.replace` is atomic on
    every platform this runs on, so a crash mid-write leaves the old file intact.
    """
    directory = os.path.dirname(STORE_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)

    tmp = f"{STORE_FILE}.tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    os.replace(tmp, STORE_FILE)


def _prune(rows: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
    cutoff = now - RETENTION_SECONDS
    kept = [row for row in rows if row.get("t", 0) >= cutoff]
    return kept[-MAX_SAMPLES_PER_CHAIN:]


def _reading(row: dict[str, Any]) -> dict[str, Any]:
    """The sampled subset of one chain row, flattened out of its nested blocks."""
    fee = row.get("fee") or {}
    load = row.get("load") or {}
    mempool = row.get("mempool") or {}
    return {
        "fee_native": fee.get("transfer_native"),
        "fee_usd": fee.get("transfer_usd"),
        "load_percent": load.get("percent"),
        "block_time_seconds": row.get("block_time_seconds"),
        "backlog_blocks": mempool.get("backlog_blocks"),
    }


def _sample(board: dict[str, Any], now: float) -> None:
    """Append one reading per readable chain. Caller holds the lock."""
    store = _load()

    for row in board.get("chains") or []:
        key = row.get("key")
        # A row that failed carries blank readings, and a blank is not a low fee.
        # Letting one unreachable poll into the median would drag the baseline
        # down and manufacture a spike on the next successful read.
        if not key or row.get("error"):
            continue

        reading = _reading(row)
        if all(value is None for value in reading.values()):
            continue

        rows = store.setdefault(key, [])
        rows.append({"t": now, **reading})
        store[key] = _prune(rows, now)


async def record(board: dict[str, Any]) -> None:
    """
    Sample this board, at most once every `SAMPLE_INTERVAL_SECONDS`.

    Never raises: `fetch_board` is documented as never raising, and a baseline is
    a nice-to-have on a page that renders without it. The write goes to a thread
    because this sits on the request path of the fastest-refreshing page in the
    application, and a synchronous `json.dump` there would stall the event loop
    for every other caller.
    """
    global _last_sample_at

    try:
        now = time.time()
        with _lock:
            if now - _last_sample_at < SAMPLE_INTERVAL_SECONDS:
                return
            _last_sample_at = now
            _sample(board, now)
            payload = {"version": STORE_VERSION, "chains": _load()}
            snapshot = json.loads(json.dumps(payload))

        await asyncio.to_thread(_write, snapshot)
    except Exception as e:  # noqa: BLE001 — the board outranks its own history
        logger.warning("[Chains] could not record metric history: %s", e)


def series(chain_key: str, metric: str) -> list[tuple[float, float]]:
    """Every retained `(timestamp, value)` for one reading, oldest first."""
    with _lock:
        rows = list(_load().get(chain_key) or [])
    return [
        (row["t"], float(row[metric]))
        for row in rows
        if isinstance(row.get(metric), (int, float)) and row.get("t")
    ]


def _hour_of(timestamp: float) -> int:
    return datetime.fromtimestamp(timestamp, UTC).hour


def _in_band(hour: int, target: int) -> bool:
    """Whether `hour` sits within `HOUR_BAND` of `target`, wrapping at midnight."""
    distance = abs(hour - target)
    return min(distance, 24 - distance) <= HOUR_BAND


def baseline(chain_key: str, metric: str, *, now: Optional[float] = None) -> Optional[dict]:
    """
    What this reading normally looks like at this time of day, or None.

    None means "not enough history to judge", and callers must treat it as
    exactly that rather than as "normal". The median and MAD are robust
    statistics on purpose: chain fees are heavy-tailed, and one congested
    afternoon inside the window would drag a mean far enough that the threshold
    either never fires again or fires constantly.
    """
    at = time.time() if now is None else now
    target = _hour_of(at)

    band = [
        (timestamp, value)
        for timestamp, value in series(chain_key, metric)
        if _in_band(_hour_of(timestamp), target) and timestamp < at
    ]
    if len(band) < MIN_BAND_SAMPLES:
        return None

    days = {datetime.fromtimestamp(t, UTC).date() for t, _ in band}
    if len(days) < MIN_BAND_DAYS:
        return None

    values = [value for _, value in band]
    median = statistics.median(values)
    mad = statistics.median([abs(value - median) for value in values])

    return {
        "median": median,
        "mad": mad,
        "samples": len(values),
        "days": len(days),
        "hour_utc": target,
        "band_hours": HOUR_BAND,
    }


def coverage() -> dict[str, int]:
    """How many samples are retained per chain. For the payload's honesty block."""
    with _lock:
        return {key: len(rows) for key, rows in _load().items()}


def reset_state() -> None:
    """Drop the in-memory view and the sampling gate. For tests."""
    global _samples, _last_sample_at
    with _lock:
        _samples = None
        _last_sample_at = 0.0
