"""
Auth Router — the checks that run *before* Supabase sees a sign-up.

Authentication itself happens entirely in the browser against Supabase GoTrue;
this backend only verifies the resulting token (`dependencies/auth.py`). The one
thing the browser cannot do is decide whether an address is worth accepting, so
that lives here.

There is exactly one endpoint, because the sign-up form asks exactly one
question: *can I use this address?* Splitting it into "is it deliverable" and
"is it taken" would double the surface a stranger can probe for no gain.

## The enumeration trade-off, stated plainly

Answering `registered: true` tells an anonymous caller that an address has an
account here. That is a deliberate choice: the alternative — Supabase's silent
"check your email" for a duplicate sign-up — leaves a real user staring at an
inbox that will never receive anything, which is the failure this endpoint
exists to remove.

Two things keep the cost bounded:

  * The registration lookup runs *only* after the address passes syntax, the
    disposable-domain list and a real DNS answer. An attacker cannot use this as
    a cheap oracle over a generated list; every probe has to name a plausible
    address at a domain that genuinely accepts mail.
  * `RateLimit` caps a source address at 10 attempts per 10 minutes.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from dependencies.rate_limit import RateLimit
from services import auth_service, email_guard

logger = logging.getLogger(__name__)

router = APIRouter()

# Module scope, not per-request: a fresh limiter on every call would carry no
# history and permit everything.
_precheck_limit = RateLimit(name="email-precheck", limit=10, window_seconds=600)


class EmailPrecheckRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class EmailPrecheckResponse(BaseModel):
    """
    A verdict, not an error.

    `deliverable=False` still comes back with a 200 — the form reads the body
    and renders `message` under the email field. Reserving non-2xx for things
    that actually went wrong keeps "this address is a throwaway" from looking
    like an outage in the logs.
    """

    deliverable: bool
    registered: bool
    reason: str
    message: str


@router.post(
    "/api/auth/email/precheck",
    response_model=EmailPrecheckResponse,
    dependencies=[Depends(_precheck_limit)],
)
async def precheck_email(data: EmailPrecheckRequest) -> EmailPrecheckResponse:
    """Check an address for deliverability, then for an existing account."""
    verdict = await email_guard.check_deliverable(data.email)

    if not verdict.ok:
        return EmailPrecheckResponse(
            deliverable=False,
            registered=False,
            reason=verdict.reason,
            message=verdict.message,
        )

    try:
        registered = await auth_service.is_email_registered(email_guard.normalize(data.email))
    except auth_service.AuthServiceError:
        # The address itself is fine; we just could not check for a duplicate.
        # 503 rather than a fabricated "not registered", so the form knows to
        # fall through to Supabase and let its own duplicate error decide.
        raise HTTPException(status_code=503, detail="Sign-up checks are unavailable right now.")

    if registered:
        return EmailPrecheckResponse(
            deliverable=True,
            registered=True,
            reason="registered",
            message="This email is already registered — sign in instead.",
        )

    return EmailPrecheckResponse(
        deliverable=True,
        registered=False,
        reason=verdict.reason,
        message="",
    )
