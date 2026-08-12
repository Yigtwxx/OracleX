"""
Community service errors.

The service layer raises these; `routers/community.py` is the only place that
knows about HTTP status codes. This replaces the previous pattern, where every
function swallowed its exception and returned `[]`/`None` — and `toggle_like`
went as far as returning `{"error": ...}` with a 200, telling the client the
write had succeeded when it had not.

Reads may still degrade to an empty list. Writes must not lie.
"""


class CommunityError(Exception):
    """Base class for every failure the community service reports."""


class NotFound(CommunityError):
    """The post or comment does not exist."""


class NotOwner(CommunityError):
    """
    The caller is authenticated but does not own the row.

    Worth stating explicitly: the backend connects with the service-role key and
    therefore bypasses row-level security, so this check is the only thing
    standing between one user and another user's posts.
    """


class InvalidRequest(CommunityError):
    """The request is well-formed but not acceptable (bad URL, bad file, ...)."""


class UpstreamFailure(CommunityError):
    """A dependency (Postgres, Storage, a remote page) failed."""
