"""
Social service errors.

Same contract the community package established: the service layer raises,
`routers/social.py` is the only place that knows about status codes, and a
failed write never comes back as a 200.
"""


class SocialError(Exception):
    """Base class for every failure the social service reports."""


class NotFound(SocialError):
    """The conversation or member does not exist."""


class NotAParticipant(SocialError):
    """
    The caller is authenticated but is not one of the two people in this thread.

    The backend connects with the service-role key and bypasses row-level
    security, so this check is the only thing standing between one member and
    somebody else's private messages.
    """


class NotEligible(SocialError):
    """
    The caller may not send this message.

    Carries the machine-readable reasons so the UI can say *which* requirement
    is unmet rather than a flat refusal.
    """

    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__("Not eligible to send messages")
        self.reasons = reasons


class InvalidRequest(SocialError):
    """The request is well-formed but not acceptable (empty body, self-DM, ...)."""


class UpstreamFailure(SocialError):
    """A dependency (Postgres) failed."""
