"""
The contract every ownership source implements.

A provider is handed one entity's config and returns what it could find. It
never raises: a provider that throws takes the whole daily refresh down with it,
and the entire point of this layer is that CoinGecko being rate-limited must not
blank Berkshire. Failure is a value — `ProviderResult.failed(...)` — which is
what lets the board report *which* source broke instead of silently shrinking.

Position and Move construction happens inside the provider, because only the
provider knows what its own SourceRef should say. Nothing downstream is allowed
to invent a label or an `as_of`.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from models.ownership import Move, Position, SourceKind


@dataclass(slots=True)
class EntityConfig:
    """One curated row out of ownership_entities.json."""

    id: str
    name: str
    subtitle: str | None
    category: str
    country: str | None
    coverage_note: str | None
    # Per-source keys, e.g. {"sec_13f": {"cik": "0001067983"}}.
    sources: dict[str, dict[str, Any]]
    order: int = 0
    # Where the card's icon comes from, for holders no ticker identifies —
    # a fund files a 13F but does not trade under a symbol. Resolved to a URL
    # in `registry.entity_logo_url`, never here.
    logo_domain: str | None = None
    # An explicit override, for the entity whose real mark neither its ticker
    # nor its favicon produces.
    logo_url: str | None = None


@dataclass(slots=True)
class ProviderResult:
    """What one provider found for one entity, and whether it worked."""

    kind: SourceKind
    ok: bool
    positions: list[Position] = field(default_factory=list)
    # Moves a source hands us directly — Form 4 lines, on-chain transfers.
    # Snapshot-derived moves are computed later and do not come through here.
    moves: list[Move] = field(default_factory=list)
    as_of: datetime | None = None
    error: str | None = None

    @classmethod
    def failed(cls, kind: SourceKind, message: str) -> "ProviderResult":
        return cls(kind=kind, ok=False, error=message)

    @classmethod
    def skipped(cls, kind: SourceKind) -> "ProviderResult":
        """This entity has no key for this source. Not a failure."""
        return cls(kind=kind, ok=True)


class OwnershipProvider(Protocol):
    """Implemented by every module under `providers/`."""

    kind: SourceKind
    # Seconds this provider gets per entity before the runner cancels it.
    timeout: float

    async def fetch(self, entity: EntityConfig) -> ProviderResult: ...
