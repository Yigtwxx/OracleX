"""
Alarm Router — the mail channel for alarms the browser evaluates.

Everything about *whether* an alarm fired stays in the frontend
(`hooks/useAlarmEngine.ts`, `lib/alarms/evaluate.ts`), which is where the market
data already is. This router exists only because a browser cannot send mail.

Routes, each answering one question the Alarm Center asks:

    GET  status         can this feature work at all on this deployment?
    POST request-code   send a confirmation code to an address
    POST confirm        exchange a code for the token the browser then keeps
    POST notify         an alarm fired — mail it

    GET  smtp           what relay is configured?          (admin)
    PUT  smtp           point it at a different one        (admin)
    DEL  smtp           forget it and fall back to .env    (admin)
    POST smtp/test      prove the relay actually works     (admin)

The four SMTP routes are behind `require_admin` because the relay is one
deployment-wide account, not a per-user preference: the caller is configuring
where *everyone's* alarm mail comes from and typing a mailbox password to do it.
`get_current_user` refuses an unsigned caller before the admin check is reached,
so the 401/403 split falls out of the dependency chain.

`notify` is the one worth being careful about, and the reasoning behind its
token is in `services/alarm_email_service`. The per-IP limits here are a second
line in front of the per-address ones there: an attacker with no token cannot
get past `token_valid`, but they can still make this process do DNS lookups and
open SMTP connections, and these caps bound that.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from dependencies.auth import AuthUser, require_admin
from dependencies.rate_limit import RateLimit
from services import alarm_email_service, email_guard, mail_settings_service
from services.alarm_email_service import AlarmEmailError, AlarmMailPayload, TooManyRequests
from services.email_delivery import EmailNotConfigured

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alarms", tags=["alarms"])

# Module scope: a limiter constructed per request carries no history.
_code_limit = RateLimit(name="alarm-email-code", limit=6, window_seconds=600)
_confirm_limit = RateLimit(name="alarm-email-confirm", limit=15, window_seconds=600)
# Generous, because one browser with several alarms on a busy source legitimately
# reaches here often — and the real ceiling is the per-address hourly cap.
_notify_limit = RateLimit(name="alarm-email-notify", limit=60, window_seconds=3600)


class EmailStatusResponse(BaseModel):
    """
    Whether the deployment can send mail.

    A fact about configuration, not about the caller, so it needs no auth and no
    limit. The frontend renders the confirmation form on `enabled: true` and an
    explanation otherwise, rather than offering a button that answers 503.
    """

    enabled: bool


class RequestCodeRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ConfirmRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=4, max_length=12)


class ConfirmResponse(BaseModel):
    """`email` is echoed normalized — the browser stores what the backend will verify."""

    email: str
    token: str


class NotifyRequest(BaseModel):
    """
    One fired alarm.

    Every field is a display string the frontend has already rendered for the
    toast, rather than an alarm id the backend would have to resolve. That is
    deliberate: the alarm lives in localStorage and this process has never seen
    it, so re-deriving the text here would mean duplicating `lib/alarms/describe`
    in Python and letting the two drift.

    `fired_at_label` is formatted in the browser for the same reason — it is the
    only place that knows the reader's timezone.
    """

    email: str = Field(min_length=3, max_length=254)
    token: str = Field(min_length=8, max_length=128)
    event_id: str = Field(min_length=1, max_length=128)
    source_label: str = Field(min_length=1, max_length=200)
    subject_line: str = Field(min_length=1, max_length=200)
    observed: str = Field(min_length=1, max_length=200)
    rule: str = Field(min_length=1, max_length=200)
    fired_at_label: str = Field(min_length=1, max_length=200)
    tone: str = Field(default="accent", pattern="^(up|down|warn|accent)$")
    trigger_count: int | None = Field(default=None, ge=0, le=1_000_000)
    # The two sentences the message leads with. Optional, so a tab left open
    # across a deploy that predates them still sends a coherent alarm rather
    # than 422ing on every fire.
    headline: str = Field(default="", max_length=200)
    lead: str = Field(default="", max_length=200)
    # Threshold alarms only; absent for a state change, a keyword or a countdown.
    threshold: str | None = Field(default=None, max_length=200)
    distance: str | None = Field(default=None, max_length=200)


class NotifyResponse(BaseModel):
    """`sent: false` means it was a duplicate already delivered, not a failure."""

    sent: bool


@router.get("/email/status", response_model=EmailStatusResponse)
async def email_status() -> EmailStatusResponse:
    """Can this deployment send alarm mail?"""
    return EmailStatusResponse(enabled=alarm_email_service.is_enabled())


@router.post("/email/request-code", dependencies=[Depends(_code_limit)])
async def request_code(data: RequestCodeRequest) -> dict[str, bool]:
    """Mail a confirmation code to the address."""
    try:
        await alarm_email_service.request_code(data.email)
    except TooManyRequests as error:
        raise HTTPException(status_code=429, detail=str(error)) from error
    except EmailNotConfigured as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except AlarmEmailError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        # The address is never echoed into the log or the response. What the
        # user needs is "it did not send"; what an operator needs is in the
        # warning `email_delivery` already logged.
        logger.warning("Alarm confirmation code could not be sent: %s", error)
        raise HTTPException(
            status_code=502, detail="The confirmation email could not be sent. Try again shortly."
        ) from error
    return {"sent": True}


@router.post(
    "/email/confirm", response_model=ConfirmResponse, dependencies=[Depends(_confirm_limit)]
)
async def confirm(data: ConfirmRequest) -> ConfirmResponse:
    """Exchange a code for the token `notify` requires."""
    try:
        token = alarm_email_service.confirm_code(data.email, data.code)
    except TooManyRequests as error:
        raise HTTPException(status_code=429, detail=str(error)) from error
    except AlarmEmailError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    # `normalize`, not `.lower()` — the local part of an address is case-sensitive
    # per RFC 5321 and the token is signed over the normalized form. Lowercasing
    # the whole thing here would hand back a token that never validates again.
    return ConfirmResponse(email=email_guard.normalize(data.email), token=token)


@router.post("/email/notify", response_model=NotifyResponse, dependencies=[Depends(_notify_limit)])
async def notify(data: NotifyRequest) -> NotifyResponse:
    """Mail one fired alarm to a confirmed address."""
    payload = AlarmMailPayload(
        event_id=data.event_id,
        source_label=data.source_label,
        subject_line=data.subject_line,
        observed=data.observed,
        rule=data.rule,
        fired_at_label=data.fired_at_label,
        tone=data.tone,  # type: ignore[arg-type]  # constrained by the field pattern
        trigger_count=data.trigger_count,
        headline=data.headline,
        lead=data.lead,
        threshold=data.threshold,
        distance=data.distance,
    )
    try:
        sent = await alarm_email_service.send_alarm(data.email, data.token, payload)
    except TooManyRequests as error:
        raise HTTPException(status_code=429, detail=str(error)) from error
    except EmailNotConfigured as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except AlarmEmailError as error:
        # 403 rather than 400: the one thing that reaches here is a token this
        # backend did not issue, and the frontend clears its stored address on
        # exactly that status.
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception as error:
        logger.warning("Alarm mail could not be sent: %s", error)
        raise HTTPException(status_code=502, detail="The alarm email could not be sent.") from error
    return NotifyResponse(sent=sent)


# ── SMTP configuration (admin) ──────────────────────────────────────────────


class SmtpSettingsResponse(BaseModel):
    """
    The relay as it stands.

    `has_password` rather than the password or any part of it: the panel needs
    to know whether one is stored so it can label the field "leave blank to
    keep", and it needs nothing else. `source` says whether these values came
    from the panel or from `.env`, so an admin editing a deployment they did not
    set up can tell which they are about to override.
    """

    host: str
    port: int
    user: str
    ssl: bool
    starttls: bool
    from_address: str
    from_name: str
    reply_to: str
    has_password: bool
    sender: str
    configured: bool
    source: str


class SmtpSettingsRequest(BaseModel):
    """
    One save from the panel.

    Every field is optional and `None` means "not part of this change" rather
    than "set to empty". That is what makes the password field work: the panel
    never receives the stored one, so an edit that leaves it blank has to be
    able to say "leave it alone" — which `None` does and `""` cannot, since an
    empty string is how the password is deleted.
    """

    host: str | None = Field(default=None, max_length=253)
    port: int | None = Field(default=None, ge=1, le=65535)
    user: str | None = Field(default=None, max_length=254)
    password: str | None = Field(default=None, max_length=512)
    ssl: bool | None = None
    starttls: bool | None = None
    from_address: str | None = Field(default=None, max_length=254)
    from_name: str | None = Field(default=None, max_length=120)
    reply_to: str | None = Field(default=None, max_length=254)


class SmtpTestRequest(BaseModel):
    """Where to send the probe. Defaults to the admin's own address."""

    to: str | None = Field(default=None, max_length=254)


@router.get("/email/smtp", response_model=SmtpSettingsResponse)
async def read_smtp(_: AuthUser = Depends(require_admin)) -> SmtpSettingsResponse:
    """The relay currently in force, without its password."""
    return SmtpSettingsResponse(**mail_settings_service.public_view())


@router.put("/email/smtp", response_model=SmtpSettingsResponse)
async def write_smtp(
    data: SmtpSettingsRequest, _: AuthUser = Depends(require_admin)
) -> SmtpSettingsResponse:
    """Point the relay somewhere else."""
    payload = data.model_dump(exclude_none=True)
    password = payload.pop("password", None)
    fields = {
        key: value.strip() if isinstance(value, str) else value for key, value in payload.items()
    }

    try:
        mail_settings_service.save(fields, password)
    except mail_settings_service.MailSettingsError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.warning("SMTP settings could not be written: %s", error)
        raise HTTPException(status_code=500, detail="Settings could not be saved.") from error

    return SmtpSettingsResponse(**mail_settings_service.public_view())


@router.delete("/email/smtp", response_model=SmtpSettingsResponse)
async def delete_smtp(_: AuthUser = Depends(require_admin)) -> SmtpSettingsResponse:
    """Forget the panel's overrides and fall back to the environment."""
    mail_settings_service.clear()
    return SmtpSettingsResponse(**mail_settings_service.public_view())


@router.post("/email/smtp/test")
async def test_smtp(
    data: SmtpTestRequest, admin: AuthUser = Depends(require_admin)
) -> dict[str, bool]:
    """
    Send one message through the relay as it is configured right now.

    Worth its own route rather than leaving the admin to find out from the first
    real alarm: almost every SMTP misconfiguration — wrong port, an account
    password where an app password was needed, TLS on the wrong side — fails at
    authentication, which this surfaces in a second with the relay's own words.
    """
    recipient = (data.to or admin.email or "").strip()
    if not recipient:
        raise HTTPException(status_code=400, detail="No address to send the test to.")

    try:
        await alarm_email_service.send_relay_test(recipient)
    except EmailNotConfigured as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        # The relay's own message is the useful part here and the caller is an
        # admin, so unlike every other route on this router it is passed through
        # rather than replaced with something generic.
        raise HTTPException(status_code=502, detail=f"{type(error).__name__}: {error}") from error
    return {"sent": True}
