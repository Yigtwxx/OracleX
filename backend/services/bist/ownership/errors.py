"""Errors the BIST ownership service raises. The router maps them; nothing else knows both."""


class BistOwnershipError(RuntimeError):
    """Base class, so a router can catch the family in one clause."""


class BoardUnavailable(BistOwnershipError):
    """No stored board and none could be built. Never rendered as an empty list."""


class EntityNotFound(BistOwnershipError):
    """The id names no registry entity."""


class TickerNotCovered(BistOwnershipError):
    """The ticker is outside the universe the board was built over."""
