"""
Public-company crypto treasuries, from CoinGecko's `companies/public_treasury`.

One request per coin serves every entity that holds it. That is not an
optimisation, it is the constraint the provider is built around: the endpoint is
free and keyless, but an unauthenticated client is rate-limited to roughly five
requests before it answers 429 with `retry-after: 59`. Eight entities across two
coins asked individually would be sixteen requests and would fail most of the
way through, so the coin table is fetched once and cached, and every entity is
looked up inside it.

The same limit is why nothing here may be called from a request handler. The
daily refresh fills the cache; the router only ever reads a board that was built
earlier.

Matching is on the exchange symbol, not the company name. CoinGecko's names
carry editorial suffixes that change without notice — "Forum Markets (formerly
ETHZilla)", "ProCap Financial (formerly ProCap BTC)" — while the ticker does not.

CoinGecko publishes no as-of date for these holdings: the figure is whatever the
company last disclosed, which may be a quarter old. So `as_of` stays None and
only `retrieved_at` is set, and the UI says "retrieved" rather than implying the
holding was counted today.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from models.ownership import Position, SourceRef
from services import coingecko
from services.cache import ownership_cache
from services.ownership.providers.base import EntityConfig, ProviderResult

logger = logging.getLogger(__name__)

KIND = "coingecko_treasury"

# Shorter than the interval the live refresh runs on, or that job would spend
# its whole existence re-reading a cached table and the board would only ever
# reprice once a day. Three requests every quarter of an hour is well inside a
# keyless quota; six hours of cache was not a rate-limit decision, it was a
# same-day-rerun one, and the live job is the same-day re-run.
COIN_TABLE_TTL_SECONDS = 15 * 60
# How old a fallback table may be before we stop serving it: past this the
# figures stop being "yesterday's" and start being unattributable.
COIN_TABLE_MAX_FALLBACK_AGE = 14 * 24 * 60 * 60

# CoinGecko coin id -> how the position is labelled. Only coins the endpoint
# actually serves; it 404s on anything else.
COIN_META: dict[str, tuple[str, str]] = {
    "bitcoin": ("BTC", "Bitcoin"),
    "ethereum": ("ETH", "Ethereum"),
    "solana": ("SOL", "Solana"),
}


# Entities are refreshed four at a time, and two of them wanting different coins
# fire two requests in the same instant. Against a keyless quota of roughly five
# requests that burst is most of the budget, so coin fetches are serialised and
# spaced: one at a time, with a gap between distinct coins.
_FETCH_LOCK = asyncio.Lock()
_SPACING_SECONDS = 2.5


def _cache_key(coin: str) -> str:
    return f"treasury_table:{coin}"


async def _coin_table(coin: str) -> dict[str, dict[str, Any]] | None:
    """
    Every company holding `coin`, keyed by exchange symbol.

    Returns None when the table could not be fetched and no usable fallback
    survives — the caller turns that into a failed ProviderResult rather than an
    entity with no positions.
    """
    key = _cache_key(coin)
    cached = ownership_cache.get(key)
    if cached is not None:
        return cached

    async with _FETCH_LOCK:
        # Re-check inside the lock: while we waited, whoever held it may have
        # been fetching the very table we want.
        cached = ownership_cache.get(key)
        if cached is not None:
            return cached
        return await _fetch_coin_table(coin, key)


async def _fetch_coin_table(coin: str, key: str) -> dict[str, dict[str, Any]] | None:
    """Fetch one coin's table. Called only while holding `_FETCH_LOCK`."""
    try:
        payload = await coingecko.get_json(f"/companies/public_treasury/{coin}")
    except Exception as e:
        stale = ownership_cache.get_with_fallback(key, max_age=COIN_TABLE_MAX_FALLBACK_AGE)
        if stale is not None:
            age_hours = (ownership_cache.get_fallback_age(key) or 0) / 3600
            logger.warning(
                "CoinGecko treasury/%s unavailable (%s) — replaying table from %.1fh ago",
                coin,
                e,
                age_hours,
            )
            return stale
        logger.warning("CoinGecko treasury/%s unavailable and no fallback: %s", coin, e)
        return None

    companies = payload.get("companies") if isinstance(payload, dict) else None
    if not isinstance(companies, list) or not companies:
        # A 200 with nothing in it is a schema change, not an empty world. Do
        # not cache it — that would poison the fallback with an empty table.
        logger.warning("CoinGecko treasury/%s returned no companies — treating as failure", coin)
        return None

    table = {
        str(c["symbol"]).upper(): c for c in companies if isinstance(c, dict) and c.get("symbol")
    }
    ownership_cache.set(key, table, COIN_TABLE_TTL_SECONDS)
    # Held while still inside the lock, so the next coin cannot start until the
    # gap has passed. Costs a few seconds once a day and is the difference
    # between three coins landing and two of them getting a 429.
    await asyncio.sleep(_SPACING_SECONDS)
    return table


def _position(coin: str, row: dict[str, Any], retrieved_at: datetime) -> Position | None:
    """One company's holding of one coin, or None when the row is unusable."""
    symbol, name = COIN_META.get(coin, (coin.upper(), coin.title()))

    quantity = row.get("total_holdings")
    if not isinstance(quantity, (int, float)) or quantity <= 0:
        return None

    value = row.get("total_current_value_usd")
    has_value = isinstance(value, (int, float)) and value > 0

    return Position(
        key=coin,
        label=name,
        symbol=symbol,
        asset_class="crypto",
        quantity=float(quantity),
        quantity_unit=symbol,
        value_usd=float(value) if has_value else None,
        # CoinGecko multiplies the disclosed coin count by a live price. Nobody
        # filed this dollar figure, so it is marked, not reported.
        value_basis="marked" if has_value else "unknown",
        price_usd=float(value) / float(quantity) if has_value else None,
        priced_at=retrieved_at if has_value else None,
        source=SourceRef(
            kind=KIND,
            label="CoinGecko public treasury",
            url=f"https://www.coingecko.com/en/public-companies-{coin}",
            # Deliberately absent: the endpoint does not say which disclosure
            # the coin count came from, and inventing today's date would claim
            # a freshness the number does not have.
            as_of=None,
            retrieved_at=retrieved_at,
        ),
    )


class CoinGeckoTreasuryProvider:
    """Corporate crypto treasuries. One request per coin, shared by all entities."""

    kind: str = KIND
    timeout: float = 30.0

    async def fetch(self, entity: EntityConfig) -> ProviderResult:
        config = entity.sources.get(KIND)
        if not config:
            return ProviderResult.skipped(KIND)

        symbol = str(config.get("symbol", "")).upper()
        coins = config.get("coins") or []
        if not symbol or not isinstance(coins, list) or not coins:
            return ProviderResult.failed(KIND, "registry entry needs `symbol` and `coins`")

        retrieved_at = datetime.now(UTC)
        positions: list[Position] = []
        failures: list[str] = []

        for coin in coins:
            table = await _coin_table(str(coin))
            if table is None:
                failures.append(f"{coin}: table unavailable")
                continue
            row = table.get(symbol)
            if row is None:
                # The company dropped off CoinGecko's list, or the ticker moved.
                # Not a source outage — worth a note, not a failure.
                failures.append(f"{coin}: {symbol} not listed")
                continue
            position = _position(str(coin), row, retrieved_at)
            if position is not None:
                positions.append(position)

        if not positions:
            return ProviderResult.failed(KIND, "; ".join(failures) or "no holdings found")

        return ProviderResult(
            kind=KIND,
            ok=True,
            positions=positions,
            as_of=retrieved_at,
            # Partial success still reports what went missing, so the detail
            # view can explain a card that shows BTC but not ETH.
            error="; ".join(failures) or None,
        )
