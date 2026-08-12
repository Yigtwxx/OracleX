"""
Who counts as an admin.

One line, in its own module, because two callers need it and neither may import
the other: `dependencies/auth.py` guards the routes, and `services/admin/users.py`
flags the admin's own row in the user list. This module imports nothing but the
settings, so it cannot be part of an import cycle.

The *verified* half of the check lives in `dependencies/auth.py` — this function
only answers "is this address on the list".
"""

from typing import Optional

from config import settings


def is_admin_email(email: Optional[str]) -> bool:
    """
    True when `email` appears in ADMIN_EMAILS, compared case-insensitively.

    `settings.admin_emails` is read on every call rather than cached at import:
    tests monkeypatch it, and caching would mean a restart to change who is an
    admin.
    """
    if not email:
        return False
    return email.strip().lower() in settings.admin_emails
