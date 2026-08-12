"""
Admin service.

Adminship itself is not here and not in the database: it is the ADMIN_EMAILS
environment variable, checked in `dependencies/auth.py`. The backend holds the
service-role key and bypasses RLS, so anything stored in a table is one bug away
from being self-grantable, while an environment variable cannot be written by a
request.

Each module owns one thing:

    identity    is this email on the admin list (imported by dependencies/auth)
    bans        suspension lookup + TTL cache, on the hot path of every request
    users       the user list, plan changes, suspensions
    moderation  removing someone else's post or comment, and the content browser
    audit       the action trail
    errors      the exception types the router translates into status codes
    _db         this package's binding of services/db.py

`bans` deliberately imports nothing but `_db`: `dependencies/auth.py` asks it
about every authenticated request, and it must not drag the rest of the package
onto that path.
"""

from . import audit, bans, identity, moderation, users
from .audit import AuditActor
from .errors import (
    AdminError,
    InvalidRequest,
    NotFound,
    ProtectedTarget,
    UpstreamFailure,
)

__all__ = [
    "audit",
    "bans",
    "identity",
    "moderation",
    "users",
    "AuditActor",
    "AdminError",
    "InvalidRequest",
    "NotFound",
    "ProtectedTarget",
    "UpstreamFailure",
]
