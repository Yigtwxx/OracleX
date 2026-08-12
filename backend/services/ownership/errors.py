"""
The one error family the ownership router translates into status codes.

Services raise these; `routers/ownership.py` owns the mapping. Keeping the HTTP
vocabulary out of the service layer is what lets the same functions be called
from the scheduler, where there is no request to fail.
"""


class OwnershipError(Exception):
    """Base for anything the ownership router knows how to answer with."""


class EntityNotFound(OwnershipError):
    """No entity with this id exists in the registry. A 404, not an outage."""


class BoardUnavailable(OwnershipError):
    """
    No board could be produced — not from memory, not from disk.

    Distinct from "the board is empty", which never happens: an empty grid is
    the claim that nobody holds anything, and that is not a claim an outage
    entitles us to make.
    """
