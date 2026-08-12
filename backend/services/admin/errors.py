"""
The admin service's exception types.

Mirrors `services/community/errors.py`: the service raises these, and
`routers/admin.py` is the only place that knows which status code each one
becomes.
"""


class AdminError(Exception):
    """Base for every failure the admin service raises deliberately."""


class NotFound(AdminError):
    """The user, post or comment named by the request does not exist."""


class InvalidRequest(AdminError):
    """The request is well-formed but asks for something the service refuses."""


class ProtectedTarget(AdminError):
    """
    The target is one the admin is not allowed to act on — themselves, or
    another admin account.

    Its own type rather than an `InvalidRequest` because it maps to 409 and
    because banning the admin account is unrecoverable through the API: the ban
    is enforced in `get_current_user`, so it would lock the unban route away
    along with everything else.
    """


class UpstreamFailure(AdminError):
    """Supabase refused or was unreachable."""
