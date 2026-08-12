"""
CUSIP to ticker, because a 13F does not carry one.

A filing identifies a holding by CUSIP and issuer name — `037833100`, `APPLE
INC` — and never by ticker. Without a mapping, the board cannot link a position
to anything else in the app, and "who else holds AAPL" has nothing to match on.

SEC publishes a FIGI column in its own bulk data, but it is populated for about
5% of rows, so it cannot be the answer. OpenFIGI's mapping endpoint is keyless
and answers in batches of ten, rate-limited to roughly 25 requests a minute.

Resolution is therefore best-effort and cached forever. A CUSIP is permanent:
once `037833100` is known to be AAPL, that never changes, so the cache never
expires and a lookup is paid at most once in the lifetime of the deployment. A
CUSIP that cannot be resolved is remembered as unresolvable too — otherwise
every refresh would re-ask the same failing questions and spend the whole quota
on them.

Failure here is cosmetic by design: an unresolved position keeps its issuer
name and simply has no symbol. Nothing downstream treats a missing ticker as a
missing holding.
"""

import asyncio
import logging
import os
from typing import Any

import httpx

from services.asset_registry import REGISTRY_DIR, read_json_cache, write_json_cache

logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join(REGISTRY_DIR, "cusip_tickers.json")
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"

# OpenFIGI's keyless limits: 10 jobs per request, ~25 requests per minute.
BATCH_SIZE = 10
BATCH_PAUSE_SECONDS = 2.5
REQUEST_TIMEOUT = 20.0
# Ceiling per refresh. The cache makes this a first-run cost; the limit stops a
# thousand-position filer from monopolising the quota in one go.
MAX_BATCHES_PER_RUN = 12

# Sentinel for "asked, and OpenFIGI has no answer". Distinct from absent, which
# means "not asked yet".
UNRESOLVED = ""

_lock = asyncio.Lock()
_cache: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _cache
    if _cache is None:
        stored = read_json_cache(CACHE_FILE)
        _cache = stored if isinstance(stored, dict) else {}
    return _cache


def _persist() -> None:
    if _cache is not None:
        write_json_cache(CACHE_FILE, _cache)


async def _map_batch(client: httpx.AsyncClient, cusips: list[str]) -> dict[str, str]:
    jobs = [{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in cusips]
    response = await client.post(OPENFIGI_URL, json=jobs)
    if response.status_code == 429:
        raise RuntimeError("rate limited")
    response.raise_for_status()

    payload: list[dict[str, Any]] = response.json()
    resolved: dict[str, str] = {}
    for cusip, result in zip(cusips, payload, strict=False):
        entries = result.get("data") if isinstance(result, dict) else None
        ticker = entries[0].get("ticker") if entries else None
        resolved[cusip] = ticker or UNRESOLVED
    return resolved


async def resolve_tickers(cusips: list[str]) -> dict[str, str]:
    """
    Tickers for those CUSIPs we can resolve, skipping the ones we cannot.

    Returns only successful mappings — a caller reading `tickers.get(cusip)`
    gets None for anything unknown, which is exactly what an absent symbol
    should look like.
    """
    cache = _load()
    unknown = [c for c in dict.fromkeys(cusips) if c not in cache]

    if unknown:
        async with _lock:
            # Another entity's lookup may have filled these while we queued.
            unknown = [c for c in unknown if c not in cache]
            await _resolve_missing(unknown, cache)

    return {c: cache[c] for c in cusips if cache.get(c)}


async def _resolve_missing(unknown: list[str], cache: dict[str, str]) -> None:
    if not unknown:
        return

    batches = [unknown[i : i + BATCH_SIZE] for i in range(0, len(unknown), BATCH_SIZE)]
    if len(batches) > MAX_BATCHES_PER_RUN:
        logger.info(
            "CUSIP mapping: %d unresolved, doing %d batches this run and the rest tomorrow",
            len(unknown),
            MAX_BATCHES_PER_RUN,
        )
        batches = batches[:MAX_BATCHES_PER_RUN]

    resolved_any = False
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for index, batch in enumerate(batches):
            try:
                cache.update(await _map_batch(client, batch))
                resolved_any = True
            except Exception as e:
                # Cosmetic failure: the positions still render under their
                # issuer names. Stop asking rather than burn the rest of the
                # quota against whatever is refusing us.
                logger.info("CUSIP mapping stopped after %d batches: %s", index, e)
                break
            if index < len(batches) - 1:
                await asyncio.sleep(BATCH_PAUSE_SECONDS)

    if resolved_any:
        _persist()
