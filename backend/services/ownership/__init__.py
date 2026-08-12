"""
Ownership — who holds what, and what they bought or sold.

Public filings, public APIs and a small hand-maintained list, assembled once a
day into one board. The package is laid out so that each source is isolated
behind a provider: one of them failing costs its own entities their freshness
and nothing else.

Import surface is deliberately narrow — the router should not need to know
which module assembles what.
"""

from services.ownership.board import get_board, get_entity_detail, get_moves
from services.ownership.errors import BoardUnavailable, EntityNotFound, OwnershipError
from services.ownership.refresh import ensure_board, refresh_ownership

__all__ = [
    "BoardUnavailable",
    "EntityNotFound",
    "OwnershipError",
    "ensure_board",
    "get_board",
    "get_entity_detail",
    "get_moves",
    "refresh_ownership",
]
