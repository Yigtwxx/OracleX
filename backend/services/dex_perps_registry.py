"""
Reads the hand-maintained venue list behind the DEX Perps board.

Three panels, two providers, and no shared identifier between them: DefiLlama
names Hyperliquid's open interest `Hyperliquid Perps` and its TVL
`Hyperliquid HLP`, while CoinGecko calls the same venue `hyperliquid`. This
file is where those become one row on a chart.

It also collapses what a reader thinks of as one exchange but a provider splits
across versions or chains — `GMX V1 Perps` + `GMX V2 Perps`, `KiloEx (BSC)` +
`KiloEx (Base)` + `KiloEx (opBnb)`. Hence the list-valued fields: a venue's
figure is the sum over its aliases.

The file is edited by people, so a row that cannot be trusted is dropped with a
warning rather than taken on faith, following `ownership/registry.py`. Its path
hangs off `asset_registry.REGISTRY_DIR` for the reason spelled out there:
CWD-relative paths silently resolved to different files depending on where the
process was launched from.
"""

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from services.asset_registry import REGISTRY_DIR, read_json_cache

logger = logging.getLogger(__name__)

DEX_PERP_VENUES_FILE = os.path.join(REGISTRY_DIR, "dex_perp_venues.json")


@dataclass(frozen=True)
class VenueRecord:
    """One venue and the names each provider knows it by."""

    slug: str
    name: str
    llama_oi: tuple[str, ...] = ()
    llama_tvl: tuple[str, ...] = ()
    coingecko_ids: tuple[str, ...] = ()


def _names(raw: Any) -> tuple[str, ...]:
    """A list-valued alias field, keeping only non-empty strings."""
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str) and item)


def _coerce(raw: Any) -> VenueRecord | None:
    """One registry row into a VenueRecord, or None if it cannot be trusted."""
    if not isinstance(raw, dict):
        logger.warning("DEX perp registry: row is not an object — skipped")
        return None

    slug = raw.get("slug")
    name = raw.get("name")

    if not isinstance(slug, str) or not slug:
        logger.warning("DEX perp registry: row without a slug — skipped")
        return None
    if not isinstance(name, str) or not name:
        logger.warning("DEX perp registry: %s has no name — skipped", slug)
        return None

    return VenueRecord(
        slug=slug,
        name=name,
        llama_oi=_names(raw.get("llama_oi")),
        llama_tvl=_names(raw.get("llama_tvl")),
        coingecko_ids=_names(raw.get("coingecko_ids")),
    )


@lru_cache(maxsize=1)
def load_venues() -> tuple[VenueRecord, ...]:
    """Every usable row in the registry, in file order."""
    payload = read_json_cache(DEX_PERP_VENUES_FILE)
    rows = payload.get("venues") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        if payload is not None:
            logger.warning("DEX perp registry: no `venues` list at %s", DEX_PERP_VENUES_FILE)
        return ()

    venues: list[VenueRecord] = []
    seen: set[str] = set()
    for raw in rows:
        venue = _coerce(raw)
        if venue is None:
            continue
        if venue.slug in seen:
            # First wins rather than last: a duplicate is an editing accident,
            # and silently preferring the later row would make which one is
            # live depend on where in the file it happens to sit.
            logger.warning("DEX perp registry: duplicate slug %s — skipped", venue.slug)
            continue
        seen.add(venue.slug)
        venues.append(venue)

    return tuple(venues)


def _index(field: str) -> dict[str, VenueRecord]:
    return {alias: venue for venue in load_venues() for alias in getattr(venue, field)}


def by_llama_oi_name() -> dict[str, VenueRecord]:
    """DefiLlama open-interest protocol name → venue."""
    return _index("llama_oi")


def by_llama_tvl_name() -> dict[str, VenueRecord]:
    """DefiLlama protocol name → venue, for the TVL dimension."""
    return _index("llama_tvl")


def by_coingecko_id() -> dict[str, VenueRecord]:
    """CoinGecko derivatives-exchange id → venue. Membership means "is a DEX"."""
    return _index("coingecko_ids")
