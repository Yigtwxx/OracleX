"""
Reads the hand-maintained lists behind the Ownership board.

Both files are edited by people, so both are validated on the way in and a bad
row is dropped with a warning rather than taken on faith. A malformed entity
that reached the board would render as a card with no source and no numbers,
which looks exactly like a real entity we simply have no data for — the two must
not be confusable.

Paths hang off `asset_registry`'s REGISTRY_DIR rather than the working
directory, for the reason spelled out there: CWD-relative paths silently
produced two separate caches depending on where the process was launched from.
"""

import logging
import os
from typing import Any

from services.asset_registry import REGISTRY_DIR, read_json_cache
from services.ownership.providers.base import EntityConfig

logger = logging.getLogger(__name__)

ENTITIES_FILE = os.path.join(REGISTRY_DIR, "ownership_entities.json")

VALID_CATEGORIES = {"institution", "treasury", "politician", "onchain", "central_bank"}

# Holders a company logo would misrepresent: a person in office and a state's
# bank are identified by the country they act for, and their cards keep a flag.
NON_CORPORATE_CATEGORIES = {"politician", "central_bank"}

# Listed companies are drawn by ticker from the same source the rest of the app
# already uses for stock marks, so a treasury card and a quote row show one
# company one way.
STOCK_LOGO_BASE = "https://financialmodelingprep.com/image-stock"
# Everything else — funds, foundations — has no ticker to be drawn by, so the
# icon comes from the site the registry names.
FAVICON_BASE = "https://www.google.com/s2/favicons"


def _coerce_entity(raw: Any) -> EntityConfig | None:
    """One registry row into an EntityConfig, or None if it cannot be trusted."""
    if not isinstance(raw, dict):
        return None

    entity_id = raw.get("id")
    name = raw.get("name")
    category = raw.get("category")

    if not isinstance(entity_id, str) or not entity_id:
        logger.warning("Ownership registry: row without an id — skipped")
        return None
    if not isinstance(name, str) or not name:
        logger.warning("Ownership registry: %s has no name — skipped", entity_id)
        return None
    if category not in VALID_CATEGORIES:
        logger.warning(
            "Ownership registry: %s has unknown category %r — skipped", entity_id, category
        )
        return None

    sources = raw.get("sources")
    if not isinstance(sources, dict) or not sources:
        # An entity nothing can populate would render as a permanently empty
        # card. Better to leave it off the board than to show a hole.
        logger.warning("Ownership registry: %s declares no sources — skipped", entity_id)
        return None

    clean_sources: dict[str, dict[str, Any]] = {}
    for kind, keys in sources.items():
        if isinstance(keys, dict):
            clean_sources[kind] = keys
        else:
            logger.warning(
                "Ownership registry: %s source %r is not an object — dropped", entity_id, kind
            )
    if not clean_sources:
        return None

    order = raw.get("order")
    return EntityConfig(
        id=entity_id,
        name=name,
        subtitle=raw.get("subtitle"),
        category=category,
        country=raw.get("country"),
        coverage_note=raw.get("coverage_note"),
        sources=clean_sources,
        order=order if isinstance(order, int) else 0,
        logo_domain=_clean_str(raw.get("logo_domain")),
        logo_url=_clean_str(raw.get("logo_url")),
    )


def _clean_str(value: Any) -> str | None:
    """A non-empty string, or None for anything else a hand-edited row holds."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _treasury_ticker(config: EntityConfig) -> str | None:
    """
    The listing symbol a treasury row already carries, in FMP's spelling.

    The registry writes CoinGecko's form — "MSTR.US", "3350.T". Only the US
    suffix is dropped: FMP addresses American listings bare and everything else
    by exchange suffix, so stripping the lot would ask it for a symbol that
    resolves somewhere else entirely.
    """
    symbol = _clean_str(config.sources.get("coingecko_treasury", {}).get("symbol"))
    if symbol is None:
        return None
    base, _, suffix = symbol.partition(".")
    if suffix.upper() == "US":
        return base.upper()
    return symbol.upper()


def entity_logo_url(config: EntityConfig) -> str | None:
    """
    The icon for one holder's card, or None when nothing identifies it.

    None is a real answer: the card falls back to a monogram, which says "we
    have no mark for them" rather than borrowing someone else's. Politicians and
    central banks are deliberately excluded — they are read by country, and the
    flag the card shows instead is the honest identifier for a person holding
    office or a state's bank.

    Resolution never fetches anything. A URL that 404s degrades in the browser,
    where the card can fall back on its own; blocking a board build on a favicon
    lookup would let a dead domain hold up every holder's numbers.
    """
    if config.category in NON_CORPORATE_CATEGORIES:
        return None
    if config.logo_url:
        return config.logo_url

    ticker = _treasury_ticker(config)
    if ticker:
        return f"{STOCK_LOGO_BASE}/{ticker}.png"

    if config.logo_domain:
        return f"{FAVICON_BASE}?domain={config.logo_domain}&sz=128"

    return None


def entity_logo_urls() -> dict[str, str]:
    """Every resolvable icon, keyed by entity id, for one pass over the board."""
    resolved: dict[str, str] = {}
    for config in load_entities():
        url = entity_logo_url(config)
        if url:
            resolved[config.id] = url
    return resolved


def load_entities() -> list[EntityConfig]:
    """
    Every tracked entity, in display order.

    Returns an empty list when the file is missing or unreadable. Callers treat
    that as "no board", not as "nobody holds anything" — the distinction is
    enforced upstream in `board.py`.
    """
    payload = read_json_cache(ENTITIES_FILE)
    if not isinstance(payload, dict):
        logger.warning("Ownership registry: %s missing or unreadable", ENTITIES_FILE)
        return []

    rows = payload.get("entities")
    if not isinstance(rows, list):
        logger.warning("Ownership registry: %s has no entities array", ENTITIES_FILE)
        return []

    entities = [e for e in (_coerce_entity(r) for r in rows) if e is not None]

    seen: set[str] = set()
    unique: list[EntityConfig] = []
    for entity in entities:
        if entity.id in seen:
            # Two rows with one id would fight over the same snapshot history.
            logger.warning("Ownership registry: duplicate id %s — later row dropped", entity.id)
            continue
        seen.add(entity.id)
        unique.append(entity)

    unique.sort(key=lambda e: (e.order, e.name))
    return unique


def load_entity(entity_id: str) -> EntityConfig | None:
    """One entity by id, or None when the registry does not list it."""
    return next((e for e in load_entities() if e.id == entity_id), None)
