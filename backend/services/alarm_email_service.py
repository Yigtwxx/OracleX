"""
Alarm mail: confirming an address, then mailing that address when one fires.

## The shape of the problem

The alarm engine runs in the browser (`frontend/hooks/useAlarmEngine.ts`). It
knows a rule broke; it cannot send mail. So the browser asks this backend to,
and that request is the whole security question here — an endpoint that takes an
address and a body and sends mail is an open relay, and an open relay attached
to a real mailbox loses that mailbox.

Three things close it, and none of them is optional:

  1. **The address proves itself first.** A six-digit code is mailed to it and
     has to come back. Until it does, nothing else is sent there.
  2. **The browser holds a token it cannot forge.** Confirming returns
     `HMAC(ALARM_EMAIL_SECRET, address)`. `send_alarm` recomputes it and
     compares in constant time, so possession of the token *is* proof that this
     address was confirmed at some point — which is exactly the claim being
     made. It is bound to the address and useless for any other.
  3. **The body is composed here, not there.** The caller supplies fields —
     a subject, a reading, a rule — that are rendered into a fixed template
     with autoescaping on. There is no path from the request to arbitrary HTML,
     so the worst a stolen token buys is alarm-shaped mail to its own address,
     capped at `ALARM_EMAIL_HOURLY_LIMIT` an hour.

The token deliberately carries no expiry. It stands for "this mailbox agreed to
receive these", which does not become false with time; rotating
`ALARM_EMAIL_SECRET` invalidates every one at once, and the frontend treats a
rejected token as "confirm again" rather than as an error.

## Why the code lives in memory

`TTLCache`, not the database. A confirmation code is valid for ten minutes and
is worthless afterwards, so persisting it buys nothing but a migration — and the
failure mode of losing them on restart is that the user asks for another one.
The same reasoning the rate limiter in `dependencies/rate_limit.py` already
applies to its counters.
"""

import hashlib
import hmac
import logging
import os
import secrets
import time
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from typing import Literal

from cachetools import TTLCache
from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import settings
from services import email_delivery, email_guard, mail_settings_service
from services.email_delivery import EmailNotConfigured

logger = logging.getLogger(__name__)

Tone = Literal["up", "down", "warn", "accent"]

_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates"
)

# `select_autoescape` rather than `autoescape=True` so the choice is legible:
# these templates are HTML and every value rendered into them — a symbol, a
# rule, a timestamp the browser formatted — arrives from a request.
_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(("html",)),
    trim_blocks=True,
    lstrip_blocks=True,
)

# Codes awaiting confirmation, and how many guesses each has left. Sized to bound
# memory rather than to express a policy: an address that is not in here is
# simply one whose code expired.
_MAX_PENDING = 5_000
_pending: TTLCache = TTLCache(maxsize=_MAX_PENDING, ttl=settings.ALARM_EMAIL_CODE_TTL_SECONDS)

# How often one address may ask for a fresh code, and how often one confirmed
# address may be mailed. Both are sliding windows of timestamps, not counters —
# a counter with a TTL resets the whole window on every write.
_CODE_REQUEST_WINDOW_S = 600
_CODE_REQUEST_LIMIT = 3
_code_requests: TTLCache = TTLCache(maxsize=_MAX_PENDING, ttl=_CODE_REQUEST_WINDOW_S)

_SEND_WINDOW_S = 3600
_sends: TTLCache = TTLCache(maxsize=_MAX_PENDING, ttl=_SEND_WINDOW_S)

# Trigger ids already mailed. The browser retries a failed request and a second
# tab runs its own copy of the engine, so the same fired alarm can arrive twice;
# without this the reader gets two identical messages.
_seen_events: TTLCache = TTLCache(maxsize=_MAX_PENDING, ttl=_SEND_WINDOW_S)

# Caps on what a caller may put in a message. Not validation of meaning — the
# strings are opaque here — only a bound on what gets rendered into a template
# and read by a spam filter.
MAX_FIELD_LENGTH = 200


class AlarmEmailError(RuntimeError):
    """A refusal the router turns into a 4xx with this message."""


class TooManyRequests(AlarmEmailError):
    """A rate limit was hit. Separate so the router can answer 429."""


@dataclass(frozen=True)
class AlarmMailPayload:
    """One fired alarm, as much of it as a message needs."""

    event_id: str
    source_label: str
    subject_line: str
    observed: str
    rule: str
    fired_at_label: str
    tone: Tone = "accent"
    trigger_count: int | None = None
    # The two prose lines the message leads with, written by the browser in
    # `lib/alarms/describe.ts`. Optional so a caller that sends neither — an
    # older tab, the relay test — still produces a coherent message rather than
    # a blank headline; `render_alarm` composes a plain one from the parts.
    headline: str = ""
    lead: str = ""
    # Only threshold alarms have these. A state change or a keyword hit has no
    # level to be measured against, and the figures row shrinks accordingly
    # rather than printing an empty column.
    threshold: str | None = None
    distance: str | None = None


# ── Configuration ───────────────────────────────────────────────────────────


def is_enabled() -> bool:
    """
    Whether the feature can work end to end.

    Only the relay is in question. The signing secret used to be the second
    condition, and is not any more: `mail_settings_service.token_secret`
    generates and keeps one when the environment sets none, which is what lets
    an admin turn the whole feature on from the panel without opening a file.
    """
    return email_delivery.is_configured()


def _require_enabled() -> None:
    """
    Raises `EmailNotConfigured`, not `AlarmEmailError`, and the distinction is
    load-bearing: the router answers the first with 503 (this deployment cannot
    send mail) and the second with 4xx (your request was wrong). A missing
    relay reported as a bad token would send the frontend into a confirmation
    loop it can never complete.
    """
    if not email_delivery.is_configured():
        raise EmailNotConfigured("Outbound mail is not configured — set up an SMTP relay first.")


def app_url() -> str:
    """The frontend's public address, for the button in an alarm mail."""
    explicit = settings.APP_PUBLIC_URL.strip()
    if explicit:
        return explicit.rstrip("/")
    first_origin = settings.CORS_ORIGINS.split(",")[0].strip()
    return first_origin.rstrip("/")


# ── Tokens ──────────────────────────────────────────────────────────────────

_TOKEN_CONTEXT = b"oracle-x:alarm-email:v1:"


def issue_token(email: str) -> str:
    """The bearer proof that `email` confirmed a code. Deterministic per address."""
    digest = hmac.new(
        mail_settings_service.token_secret().encode("utf-8"),
        _TOKEN_CONTEXT + email_guard.normalize(email).encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def token_valid(email: str, token: str) -> bool:
    """Constant-time check. False for an empty token, never an error."""
    if not token:
        return False
    return hmac.compare_digest(issue_token(email), token)


# ── Sliding windows ─────────────────────────────────────────────────────────


def _hit(store: TTLCache, key: str, limit: int, window_s: float) -> bool:
    """Record one use of `key`; False once `limit` uses fall inside the window."""
    now = time.monotonic()
    recent = [stamp for stamp in store.get(key, []) if now - stamp < window_s]
    if len(recent) >= limit:
        store[key] = recent
        return False
    recent.append(now)
    store[key] = recent
    return True


# ── Confirmation ────────────────────────────────────────────────────────────


def _new_code() -> str:
    """Six digits, uniformly drawn. `randbelow`, not `randint` — this is a secret."""
    return f"{secrets.randbelow(1_000_000):06d}"


async def request_code(email: str) -> None:
    """
    Mail a fresh confirmation code, or raise.

    Deliverability is checked first through the same guard sign-up uses, so a
    typo is answered immediately instead of by silence from a mailbox that does
    not exist.
    """
    _require_enabled()
    address = email_guard.normalize(email)

    verdict = await email_guard.check_deliverable(address)
    if not verdict.ok:
        raise AlarmEmailError(verdict.message)

    if not _hit(_code_requests, address, _CODE_REQUEST_LIMIT, _CODE_REQUEST_WINDOW_S):
        raise TooManyRequests("Too many codes requested. Try again in a few minutes.")

    code = _new_code()
    _pending[address] = {"code": code, "attempts": 0}

    ttl_minutes = max(1, settings.ALARM_EMAIL_CODE_TTL_SECONDS // 60)
    html = _env.get_template("email/verification.html").render(
        subject="Your Oracle-X confirmation code",
        preheader=f"Your confirmation code: {code}",
        eyebrow="Confirm",
        email=address,
        code=code,
        ttl_minutes=ttl_minutes,
    )
    text = (
        "Oracle-X — confirm your email address\n\n"
        f"Your confirmation code: {code}\n"
        f"It is valid for {ttl_minutes} minutes.\n\n"
        f"Enter it under Alarm Center > Email Alerts and alarm notifications will "
        f"start arriving at {address}.\n\n"
        "If you did not ask for this there is nothing to do — the code expires on "
        "its own, and nothing is ever sent to an address that has not confirmed one.\n"
    )

    await email_delivery.send_html(
        to=address,
        # The code is deliberately not in the subject. It would show on a lock
        # screen, and this one is worth slightly more than a login OTP: it binds
        # an address to a notification channel that then needs no further proof.
        subject="Your Oracle-X confirmation code",
        html=html,
        text=text,
    )


def confirm_code(email: str, code: str) -> str:
    """
    Exchange a code for a token, or raise.

    The entry is dropped on success and on the last failed attempt, so a code is
    good for exactly one confirmation and a guesser gets
    `ALARM_EMAIL_CODE_MAX_ATTEMPTS` tries at a six-digit space, once per code.
    """
    _require_enabled()
    address = email_guard.normalize(email)
    entry = _pending.get(address)
    if entry is None:
        raise AlarmEmailError("That code has expired. Request a new one.")

    entry["attempts"] += 1
    if entry["attempts"] > settings.ALARM_EMAIL_CODE_MAX_ATTEMPTS:
        _pending.pop(address, None)
        raise TooManyRequests("Too many wrong attempts. Request a new code.")

    # Constant-time even here: the codes are short-lived, but a timing oracle on
    # a six-digit space is worth closing for the cost of one function call.
    if not hmac.compare_digest(entry["code"], code.strip()):
        _pending[address] = entry
        remaining = settings.ALARM_EMAIL_CODE_MAX_ATTEMPTS - entry["attempts"]
        raise AlarmEmailError(f"Wrong code. {max(remaining, 0)} attempts left.")

    _pending.pop(address, None)
    return issue_token(address)


# ── Sending ─────────────────────────────────────────────────────────────────


def _clip(value: str) -> str:
    """Bound one caller-supplied string. Escaping is Jinja's job, length is ours."""
    text = " ".join(value.split())
    return text[:MAX_FIELD_LENGTH]


def stats_as_pairs(stats: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    """The figures row without its colours, for the plaintext part."""
    return [(label, value) for label, value, _ in stats]


def render_alarm(payload: AlarmMailPayload) -> tuple[str, str, str]:
    """
    `(subject, html, text)` for one fired alarm.

    Split out of `send_alarm` so the composition — which is the part that can be
    wrong in an interesting way — is testable without a relay.
    """
    source_label = _clip(payload.source_label)
    subject_line = _clip(payload.subject_line)
    observed = _clip(payload.observed)
    rule = _clip(payload.rule)
    fired_at = _clip(payload.fired_at_label)
    threshold = _clip(payload.threshold) if payload.threshold else None
    distance = _clip(payload.distance) if payload.distance else None

    # A sentence, not a label — the design leads with it. Falling back to one
    # assembled here keeps a caller that sends none from producing a message
    # with an empty first line, which is the only way this template can look
    # broken.
    headline = _clip(payload.headline) or f"{subject_line} is at {observed}."
    lead = _clip(payload.lead) if payload.lead else ""

    tone_colours = {"up": "#22c55e", "down": "#ef4444", "warn": "#f59e0b", "accent": "#2f6feb"}
    # The reading is the fact; the level is what it is being judged against; the
    # distance is the only one that carries a direction, so it is the only one
    # painted. See the note in the template.
    stats: list[tuple[str, str, str]] = [("Observed", observed, "#e8e8ea")]
    if threshold:
        stats.append(("Threshold", threshold, "#9a9aa3"))
    if distance:
        stats.append(("Change", distance, tone_colours[payload.tone]))

    meta: list[tuple[str, str]] = [("Rule", rule), ("Source", source_label), ("Fired at", fired_at)]
    if payload.trigger_count is not None and payload.trigger_count > 1:
        meta.append(("Times fired", str(payload.trigger_count)))

    # The reading leads the subject line for the same reason it leads the body:
    # in an inbox list the value is the whole message, and the rule is context
    # the reader already knows — they wrote it.
    #
    # No emoji. It reads as a marketing blast rather than a machine reporting a
    # number, and several filters score a leading pictograph in the subject the
    # same way — the one thing this message cannot afford.
    subject = f"{subject_line} — {observed}"

    html = _env.get_template("email/alarm.html").render(
        subject=subject,
        preheader=f"{observed} · {rule}",
        eyebrow="Alarm fired",
        eyebrow_color=tone_colours[payload.tone],
        framed=False,
        headline=headline,
        lead=lead,
        stats=stats,
        meta=meta,
        tone=payload.tone,
        app_url=app_url(),
    )

    lines = ["Oracle-X — an alarm fired", "", headline]
    if lead:
        lines += ["", lead]
    lines += [""]
    lines += [f"{label}: {value}" for label, value in stats_as_pairs(stats)]
    lines += [f"{label}: {value}" for label, value in meta]
    url = app_url()
    if url:
        lines += ["", f"Open the terminal: {url}"]
    lines += [
        "",
        "You are receiving this because this address was confirmed for email",
        "alerts in the Oracle-X Alarm Center. To stop them, remove the address",
        "under Alarm Center > Email Alerts.",
        "",
    ]
    return subject, html, "\n".join(lines)


async def send_alarm(email: str, token: str, payload: AlarmMailPayload) -> bool:
    """
    Mail one fired alarm. Returns False when it was a duplicate of one already
    sent, which is a success from the caller's point of view — the reader has
    the message — and must not read as an error.
    """
    _require_enabled()
    address = email_guard.normalize(email)

    if not token_valid(address, token):
        raise AlarmEmailError(
            "This address is not confirmed. Confirm it again in the Alarm Center."
        )

    dedupe_key = f"{address}:{payload.event_id}"
    if dedupe_key in _seen_events:
        return False

    if not _hit(_sends, address, settings.ALARM_EMAIL_HOURLY_LIMIT, _SEND_WINDOW_S):
        raise TooManyRequests(
            "Hourly email limit reached for this address. Try narrowing the alarm rule."
        )

    subject, html, text = render_alarm(payload)
    await email_delivery.send_html(
        to=address,
        subject=subject,
        html=html,
        text=text,
        unsubscribe_mailto=email_delivery.sender_address(),
    )
    # Marked only after a successful send, so a relay failure the browser retries
    # is not silently swallowed as a duplicate.
    _seen_events[dedupe_key] = True
    return True


async def send_relay_test(to: str) -> None:
    """
    Prove the relay works, straight to an admin's own inbox.

    Deliberately does not go through `send_alarm`: there is no confirmed address
    and no token here, and there should not be — the whole point is to test the
    transport before anyone has confirmed anything through it. It is reachable
    only from an admin route for exactly that reason.

    It renders the ordinary alarm template rather than a bare "test" line,
    because half of what an admin is checking is whether the message *arrives
    looking right* — in the inbox rather than in spam, with the colours and the
    button intact.
    """
    _require_enabled()
    address = email_guard.normalize(to)

    subject, html, text = render_alarm(
        AlarmMailPayload(
            event_id="relay-test",
            source_label="Price",
            subject_line="BTCUSDT · Price",
            observed="$72,450.00",
            rule="price rises above $70,000.00",
            fired_at_label="just now",
            tone="up",
            headline="BTCUSDT rose above your $70,000.00 level.",
            lead=(
                "This is a relay test, not a real alarm — the reading below is made up. "
                "If it reached your inbox rather than your spam folder, the relay works."
            ),
            threshold="$70,000.00",
            distance="+3.50%",
        )
    )
    await email_delivery.send_html(
        to=address,
        subject=subject,
        html=html,
        text=text,
        unsubscribe_mailto=email_delivery.sender_address(),
    )


def reset_state() -> None:
    """Forget every pending code and window. For tests."""
    _pending.clear()
    _code_requests.clear()
    _sends.clear()
    _seen_events.clear()
