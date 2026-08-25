"""
The country table behind the elections board: identity, and market relevance.

Hand-maintained rather than derived, and that is the point. The obvious move was
to reuse `services/polymarket/geography.py`, which already knows ~180 countries —
but its patterns are built for prose search over market questions, not for
canonicalising a calendar, and they get this job wrong in ways that would be
invisible on the board:

    countries_in("South Sudan general election")  -> ["Sudan"]
    countries_in("Equatorial Guinea …")           -> ["Guinea"]
    countries_in("DR Congo …")                    -> ["Congo"]
    countries_in("Georgian parliamentary …")      -> []      # AMBIGUOUS, no aliases
    countries_in("U.S.")                          -> []

Three of those are the *wrong country*, not a miss, which is the failure this
terminal is least willing to ship. Changing `geography.py` to suit a calendar
would change what the Polymarket map shades, so the calendar brings its own
table instead and leaves that module alone.

Identity (`iso2`, `flag`) is required per row; market relevance (`tier`,
`tickers`, `note`) is optional and deliberately sparse. An unlisted country
still reaches the board — under a white flag, with no tickers. A guessed ticker
would be the plausible-wrong-number this codebase declines everywhere else.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "registry" / "elections.json"
)

# An alias is matched with word boundaries against a market question, so a short
# one is a false-positive generator: "us", "in" and "no" are all ISO codes and
# all English words. Four is the shortest length at which a country phrase is
# plausibly unambiguous, and the rejection is logged rather than silent so a
# seed edit that trips it gets noticed.
MIN_ALIAS_LENGTH = 4

TIERS = ("major", "watch")


@dataclass(frozen=True)
class CountryEntry:
    """What the board knows about a country beyond the date it votes."""

    iso2: str | None
    flag: str
    # "major" and "watch" order the board and drive the default filter. None
    # means the country is known but not tracked — it lists, it does not lead.
    tier: str | None = None
    tickers: tuple[str, ...] = ()
    # Phrases that mean this country and nothing else, used to reach a
    # Polymarket market. The only route for the countries `geography.py`
    # cannot name at all.
    aliases: tuple[str, ...] = ()
    note: str | None = None
    reviewed: str | None = None


UNKNOWN_COUNTRY = CountryEntry(iso2=None, flag="🏳️")


@dataclass
class Registry:
    """The loaded table, plus the lookup that must never raise."""

    entries: dict[str, CountryEntry] = field(default_factory=dict)

    def get(self, country: str) -> CountryEntry:
        """The entry for a country, or a blank one. Never a KeyError."""
        return self.entries.get(country.strip(), UNKNOWN_COUNTRY)

    def alias_index(self) -> dict[str, tuple[str, ...]]:
        """Country -> its alias phrases, for the countries that have any."""
        return {name: entry.aliases for name, entry in self.entries.items() if entry.aliases}


def load_registry(path: Path | None = None) -> Registry:
    """
    The country table, or an empty one.

    Returns rather than raises on a broken file, following
    `streamer_service.load_registry`: a seed that will not parse should cost the
    board its flags and its tickers, not its dates. The dates are the product.
    """
    source = path or REGISTRY_PATH
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        logger.error("Elections registry unreadable (%s): %s", source, error)
        return Registry()

    if not isinstance(raw, dict):
        logger.error("Elections registry is not an object: %s", source)
        return Registry()

    entries: dict[str, CountryEntry] = {}
    for name, row in raw.items():
        # Keys beginning with an underscore are the file's own documentation.
        if name.startswith("_") or not isinstance(row, dict):
            continue
        entry = _entry(name, row)
        if entry is not None:
            entries[name.strip()] = entry

    logger.info(
        "Elections registry: %d countries, %d tracked",
        len(entries),
        sum(1 for e in entries.values() if e.tier),
    )
    return Registry(entries)


def _entry(name: str, row: dict) -> CountryEntry | None:
    flag = row.get("flag")
    if not isinstance(flag, str) or not flag:
        # Identity is the one thing this file exists to supply. A row without it
        # is worse than no row: the board would show a country as tracked and
        # then render it identically to an untracked one.
        logger.error("Elections registry row %r has no flag; skipped", name)
        return None

    iso2 = row.get("iso2")
    if iso2 is not None and not (isinstance(iso2, str) and len(iso2) == 2 and iso2.isupper()):
        logger.error("Elections registry row %r has a malformed iso2 %r; skipped", name, iso2)
        return None

    tier = row.get("tier")
    if tier is not None and tier not in TIERS:
        logger.error("Elections registry row %r has an unknown tier %r; untracked", name, tier)
        tier = None

    aliases = []
    for alias in row.get("aliases") or ():
        if not isinstance(alias, str):
            continue
        cleaned = alias.strip().lower()
        if len(cleaned) < MIN_ALIAS_LENGTH:
            logger.error("Elections registry row %r: alias %r is too short; dropped", name, alias)
            continue
        aliases.append(cleaned)

    tickers = tuple(t for t in (row.get("tickers") or ()) if isinstance(t, str) and t.strip())

    return CountryEntry(
        iso2=iso2,
        flag=flag,
        tier=tier,
        tickers=tickers,
        aliases=tuple(aliases),
        note=row.get("note") or None,
        reviewed=row.get("reviewed") or None,
    )
