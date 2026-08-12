"""
The one question about sign-up the backend can answer that the browser cannot.

Supabase's client-side `signUp` deliberately refuses to say whether an address
is already taken: with email confirmation on it returns success and an
obfuscated user for a duplicate, which is good against enumeration and terrible
for the person who typed their own address and is now waiting for an email that
will never arrive. This module holds the service-role lookup that lets the
sign-up form say so plainly instead.

Why `profiles` and not GoTrue: `auth.admin.list_users()` in supabase-py v2 takes
no email filter, so asking it this question means paging the entire user table.
`profiles.email` is written by the `handle_new_user()` trigger
(`001_initial_schema.sql`) at the moment the auth row is inserted, which makes
it a faithful mirror — and migration 011 adds the `lower(email)` index this
lookup needs plus a backfill for the rows an older bug left with a NULL email.
"""

import logging

from services.db import SupabaseOps

logger = logging.getLogger(__name__)

TABLE = "profiles"


class AuthServiceError(Exception):
    """The registration lookup could not be completed."""


_ops = SupabaseOps(domain="auth", wrap=AuthServiceError)


async def is_email_registered(email: str) -> bool:
    """
    Whether an account already exists for `email`.

    Raises `AuthServiceError` when the lookup itself fails. That is deliberate:
    silently returning False would tell the caller "this address is free" on the
    strength of a database outage, and the sign-up that follows would fail with
    a much worse message.
    """
    address = email.strip()
    if not address:
        return False

    rows = await _ops.table_op(
        # `ilike` with no wildcard is an exact, case-insensitive match — which is
        # what the addresses need, since GoTrue folds the domain and users type
        # whatever they type.
        lambda client: client.table(TABLE).select("id").ilike("email", address).limit(1).execute(),
        what="look up email registration",
    )
    return bool(rows)
