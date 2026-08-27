"""
The DEX Perps board: which on-chain venue carries the leverage.

The open-interest board next door answers *how much* exposure exists and the
liquidation views answer *where the book sits*. Neither says which exchange is
holding it, and on-chain venues are the half of that answer that can actually
be checked — a perpetual DEX publishes its open interest on-chain, where a
centralised venue self-reports it.

Three panels, deliberately not one table:

* **Open interest** and **TVL** come from DefiLlama, which is the only free
  source that covers every venue rather than the subset one aggregator lists.
* **Volume** comes from CoinGecko. DefiLlama's perpetual volume dimension went
  behind a paid plan, and a panel that quietly disappeared would be worse than
  one drawn from a second provider that names itself.

They are three independent rankings and are never joined: CoinGecko does not
list every protocol DefiLlama covers, and a venue whose collateral sits in a
bridge has a TVL that means something different from its open interest. Joining
them into one row would imply a completeness none of the three has.
"""

import asyncio
import logging
import re
import time
from typing import Any

from services import coingecko, http_client, price_service
from services.cache import ServiceCache
from services.dex_perps_registry import (
    VenueRecord,
    by_coingecko_id,
    by_llama_oi_name,
    by_llama_tvl_name,
)

logger = logging.getLogger(__name__)

LLAMA_OPEN_INTEREST_URL = "https://api.llama.fi/overview/open-interest"
LLAMA_PROTOCOLS_URL = "https://api.llama.fi/protocols"
COINGECKO_DERIVATIVES_PATH = "/derivatives/exchanges"

# The board asks a market-wide question, so the chart series are excluded rather
# than the totals — asking for them would only lengthen the response.
LLAMA_OI_PARAMS = {
    "excludeTotalDataChart": "true",
    "excludeTotalDataChartBreakdown": "true",
}

# DefiLlama tags every protocol with a category, and only these name a venue you
# can hold a perpetual position on. Filtering by category rather than by a
# hand-written exclusion list means a new prediction market needs no code change.
#
# The two excluded categories are excluded for different reasons.
# `Prediction Market` (Kalshi, Polymarket) is not perpetual futures at all.
# `Interface` is a front-end routing orders to a venue already in the list —
# tradeXYZ reports billions on Hyperliquid L1, every dollar of it already
# counted under Hyperliquid Perps, so listing both double-counts the same book.
ALLOWED_CATEGORIES: frozenset[str] = frozenset(
    {"Derivatives", "Interest Rate Derivatives", "Synthetics"}
)

# TVL is narrower than open interest on purpose: an interest-rate or synthetics
# venue can genuinely report open interest on a position, but its TVL is
# collateral backing something that is not a perpetual — admitting it here
# would draw synthetic-debt or rate protocols as on-chain perp venues. Live
# data crossed this line: Alchemix V3, a synthetics protocol with no perpetual
# product, ranked inside the TVL top 15 under the wider filter.
TVL_ALLOWED_CATEGORIES: frozenset[str] = frozenset({"Derivatives"})

# CoinGecko quotes derivatives volume in BTC.
BTC_SYMBOL = "BTCUSDT"

CACHE_TTL_SECONDS = 120
# How old a replayed panel may be. An hour is long enough to ride out a provider
# outage and short enough that nobody reads yesterday's ranking as today's.
#
# This has to be measured from the panel's own last successful fetch, not from
# the whole-board cache entry: the frontend polls every two minutes, well inside
# CACHE_TTL_SECONDS, and ServiceCache.set() re-stamps one shared timestamp for
# the entire assembled board on every write — including a board that is only
# replaying a dead panel. Bounding staleness against that shared timestamp would
# mean the ceiling never fires as long as *something* on the board keeps
# succeeding, which defeats the point of having one. `_last_good` below tracks
# each panel's own clock instead.
STALE_MAX_AGE_SECONDS = 3_600

CACHE_KEY = "dex_perps"
_cache = ServiceCache(maxsize=8)

# Panel key -> (rows, time.time() written), updated only when that panel's own
# fetcher succeeds this cycle. This is what STALE_MAX_AGE_SECONDS is actually
# measured against — see the comment on that constant.
_last_good: dict[str, tuple[list[dict[str, Any]], float]] = {}

SOURCE_UNAVAILABLE = "unavailable"
SOURCE_DEFILLAMA = "defillama"
SOURCE_COINGECKO = "coingecko"


class DexPerpsSourceError(RuntimeError):
    """A panel's provider could not be turned into rows this refresh."""


def _slugify(name: str) -> str:
    """A stable key for a venue the registry does not name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _to_float(value: Any) -> float | None:
    """
    A provider figure as a number, or None when it is not one.

    CoinGecko returns `trade_volume_24h_btc` as a *string*, and DefiLlama
    returns `null` for a protocol that reported nothing this window. Neither is
    an error; both must stop before reaching an axis.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _normalise(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Sum aliases into one row per venue, drop the non-positive, rank descending.

    A venue reporting nothing is dropped rather than drawn as a zero bar: the
    bar would claim a measurement that was never taken, and a zero is not a
    point a log axis can place.
    """
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        slug = row["slug"]
        existing = merged.get(slug)
        if existing is None:
            # `_lead` remembers the largest alias seen so far. Seeded here, not
            # left to default to zero: without it the *second* alias always
            # looks like the bigger one and its change overwrites the first's.
            merged[slug] = {**row, "_lead": row["value_usd"]}
            continue
        existing["value_usd"] += row["value_usd"]
        # The change belongs to the largest alias, which is the one whose
        # movement the summed bar actually follows. Averaging two versions'
        # percentages would report a number neither provider published.
        if row["value_usd"] > existing["_lead"]:
            existing["change_1d_pct"] = row["change_1d_pct"]
            existing["_lead"] = row["value_usd"]
        # Unioned rather than arbitrated like the change above: a venue deployed
        # on two chains is on both of them, and the merged bar's tooltip names
        # them. Keeping only the leading alias's list would drop Ethereum from
        # dYdX and three chains from ApeX — a shorter answer that reads as a
        # complete one.
        if row["chains"]:
            existing["chains"] = sorted({*existing["chains"], *row["chains"]})

    out = [
        {key: value for key, value in row.items() if key != "_lead"}
        for row in merged.values()
        if row["value_usd"] > 0
    ]
    out.sort(key=lambda row: row["value_usd"], reverse=True)
    return out


def _llama_rows(
    protocols: list[Any],
    *,
    index: dict[str, VenueRecord],
    value_key: str,
    categories: frozenset[str],
    change_key: str | None = None,
) -> list[dict[str, Any]]:
    """
    Turn one DefiLlama protocol list into board rows.

    Open interest and TVL are two different dimensions of the same DefiLlama
    `/protocols`-shaped list — same registry-lookup and row-construction,
    differing only in which field holds the value, which (if any) holds its
    daily change, and which category set admits a protocol. See
    `TVL_ALLOWED_CATEGORIES` for why the two panels disagree on that filter.
    """
    rows: list[dict[str, Any]] = []
    for protocol in protocols:
        if not isinstance(protocol, dict):
            continue
        if protocol.get("category") not in categories:
            continue
        name = protocol.get("name")
        value = _to_float(protocol.get(value_key))
        if not isinstance(name, str) or value is None:
            continue

        venue = index.get(name)
        chains = protocol.get("chains")
        rows.append(
            {
                "slug": venue.slug if venue else _slugify(name),
                "name": venue.name if venue else name,
                "value_usd": value,
                "change_1d_pct": _to_float(protocol.get(change_key)) if change_key else None,
                "logo": protocol.get("logo") or "",
                "chains": [c for c in chains if isinstance(c, str)]
                if isinstance(chains, list)
                else [],
            }
        )

    return rows


async def _fetch_open_interest() -> list[dict[str, Any]]:
    """Current open interest per on-chain venue, in USD."""
    payload = await http_client.get_json(LLAMA_OPEN_INTEREST_URL, params=LLAMA_OI_PARAMS)
    protocols = payload.get("protocols") if isinstance(payload, dict) else None
    if not isinstance(protocols, list):
        raise DexPerpsSourceError("DefiLlama open-interest payload carried no protocol list")

    # `total24h` is the *current* open interest on this dimension, not a
    # 24-hour sum — the field name is the dimension API's, not a claim about
    # the window.
    rows = _llama_rows(
        protocols,
        index=by_llama_oi_name(),
        value_key="total24h",
        categories=ALLOWED_CATEGORIES,
        change_key="change_1d",
    )
    return _normalise(rows)


async def _fetch_tvl() -> list[dict[str, Any]]:
    """Value locked in each derivatives protocol, in USD."""
    payload = await http_client.get_json(LLAMA_PROTOCOLS_URL)
    if not isinstance(payload, list):
        raise DexPerpsSourceError("DefiLlama protocols payload was not a list")

    # DefiLlama's protocol list carries a 1d TVL change, but it measures a
    # different quantity from the open-interest change beside it. Left out
    # rather than shown as the same badge — hence no change_key here.
    rows = _llama_rows(
        payload,
        index=by_llama_tvl_name(),
        value_key="tvl",
        categories=TVL_ALLOWED_CATEGORIES,
    )
    return _normalise(rows)


async def _fetch_volume() -> list[dict[str, Any]]:
    """
    24-hour perpetual volume per on-chain venue, in USD.

    CoinGecko's derivatives list carries no flag saying which venue is on-chain,
    so the registry is the allowlist: an id it does not name is a centralised
    exchange and never reaches this panel. A heuristic on the venue name would
    admit a CEX the day it renamed itself.
    """
    payload = await coingecko.get_json(
        COINGECKO_DERIVATIVES_PATH,
        params={"per_page": 100, "page": 1, "order": "open_interest_btc_desc"},
    )
    if not isinstance(payload, list):
        raise DexPerpsSourceError("CoinGecko derivatives payload was not a list")

    btc_price = await price_service.get_current_price(BTC_SYMBOL)
    if not btc_price:
        # Serving BTC-denominated figures under a USD axis would be a wrong
        # number rather than a missing one.
        raise DexPerpsSourceError("no BTC price to convert CoinGecko volume with")

    index = by_coingecko_id()
    if not index:
        # A missing or corrupt registry file (`read_json_cache` returns None
        # for either) makes `load_venues()` come back empty, which would
        # otherwise mean every CoinGecko row misses the allowlist silently —
        # the panel would then render as a measured "no venues" instead of the
        # registry failure it actually is.
        raise DexPerpsSourceError("DEX perp registry has no coingecko_ids entries")

    rows: list[dict[str, Any]] = []
    for exchange in payload:
        if not isinstance(exchange, dict):
            continue
        venue = index.get(exchange.get("id"))
        if venue is None:
            continue
        volume_btc = _to_float(exchange.get("trade_volume_24h_btc"))
        if volume_btc is None:
            continue

        rows.append(
            {
                "slug": venue.slug,
                "name": venue.name,
                "value_usd": volume_btc * btc_price,
                # CoinGecko publishes no 24h change for this figure, and the
                # DefiLlama change beside it measures open interest, not volume.
                "change_1d_pct": None,
                "logo": exchange.get("image") or "",
                # The derivatives list names no chain.
                "chains": [],
            }
        )

    return _normalise(rows)


# Panel key → (fetcher attribute name, provider name). The attribute is looked
# up at call time rather than bound here so a test can patch one fetcher.
_PANELS: tuple[tuple[str, str, str], ...] = (
    ("open_interest", "_fetch_open_interest", SOURCE_DEFILLAMA),
    ("volume_24h", "_fetch_volume", SOURCE_COINGECKO),
    ("tvl", "_fetch_tvl", SOURCE_DEFILLAMA),
)


async def get_dex_perps() -> dict[str, Any]:
    """
    One payload for the three panels, with every key present.

    A provider failure costs its own panel and nothing else: the other two are
    served as normal, and the failed one replays its last good rows as long as
    they are no older than STALE_MAX_AGE_SECONDS, flagged `stale` so the chart
    can say so. Past that ceiling — or with nothing to replay at all — it comes
    back empty and named `unavailable` rather than zero-filled — an empty panel
    reads as a missing measurement, and a zero bar reads as a measured nothing.
    """
    cached = _cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    results = await asyncio.gather(
        *(globals()[attr]() for _, attr, _ in _PANELS),
        return_exceptions=True,
    )

    now = time.time()
    board: dict[str, Any] = {"sources": {}, "stale": {}}
    for (panel, _, provider), result in zip(_PANELS, results):
        if isinstance(result, BaseException):
            logger.warning("DEX perps: %s panel failed (%s)", panel, result)
            last_good = _last_good.get(panel)
            fresh = last_good is not None and (now - last_good[1]) <= STALE_MAX_AGE_SECONDS
            board[panel] = last_good[0] if fresh else []
            board["sources"][panel] = provider if fresh else SOURCE_UNAVAILABLE
            board["stale"][panel] = fresh
            continue
        board[panel] = result
        board["sources"][panel] = provider
        board["stale"][panel] = False
        _last_good[panel] = (result, now)

    board["updated_at"] = int(now)

    # Cached even when a panel is stale: retrying a dead provider every request
    # would turn one outage into a request storm, and the panel already says it
    # is replaying.
    _cache.set(CACHE_KEY, board, ttl=CACHE_TTL_SECONDS)
    return board
