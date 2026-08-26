"""
The SMTP transport, and nothing else.

One function sends one message. What that message *says* belongs to
`alarm_email_service`; what it looks like belongs to `templates/email/`. Keeping
the three apart is what lets the composition be unit-tested without a relay and
the relay be swapped without touching a template.

## Why stdlib `smtplib` and not `aiosmtplib`

The send is blocking, so it runs in a worker thread through `asyncio.to_thread`.
That is a real cost — one thread per outbound message — but alarm mail is
bounded to `ALARM_EMAIL_HOURLY_LIMIT` per address and arrives in ones, not in
campaigns. Paying a thread for it is cheaper than adding a dependency to
`requirements-base.txt`, which is the file this project treats as the definition
of what it needs to run.

## Why the headers below are not decoration

Sending mail is easy; having it arrive in an inbox rather than a spam folder is
the actual problem, and most of it is decided before the body is read:

  * **`From` must be the authenticated account.** SPF and DKIM authenticate the
    sending domain, and every major provider now checks the alignment between
    that domain and the one in `From`. Gmail's submission relay simply rewrites
    a mismatched From; other relays reject it outright. `sender_address()`
    therefore falls back to `SMTP_USER` and logs when the two differ.
  * **A plaintext alternative is mandatory.** An HTML-only message is one of the
    oldest and strongest spam signals there is, and it is also the version a
    watch or a screen reader gets. Every send here carries both parts.
  * **`List-Unsubscribe` (with `One-Click`).** Gmail and Yahoo have required it
    since 2024 for bulk senders and weigh it for everyone else. It costs two
    headers and is the single cheapest deliverability win available.
  * **A real `Message-ID` and `Date`.** Some relays add them, some do not, and a
    message missing either scores badly at the receiver.
"""

import asyncio
import logging
import smtplib
import ssl
import time
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from config import settings
from services import mail_settings_service
from services.health_registry import health

logger = logging.getLogger(__name__)

_HEALTH_CATEGORY = "notifications"


class EmailNotConfigured(RuntimeError):
    """Raised when a send is attempted with no relay configured."""


def is_configured() -> bool:
    """Whether a send can be attempted at all."""
    return mail_settings_service.is_configured()


def sender_address() -> str:
    """
    The address messages are sent from.

    `from_address` wins when set, but the authenticated account is the safer
    default and the one that keeps SPF/DKIM aligned — see the module docstring.
    """
    return mail_settings_service.resolved().sender


def _sender_domain() -> str:
    address = sender_address()
    _, _, domain = address.partition("@")
    return domain or "localhost"


def _build_message(
    *,
    config: mail_settings_service.MailSettings,
    to: str,
    subject: str,
    html: str,
    text: str,
    unsubscribe_mailto: str | None,
) -> EmailMessage:
    message = EmailMessage()

    local, _, domain = config.sender.partition("@")
    message["From"] = Address(config.from_name, local, domain)
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=_sender_domain())

    if config.reply_to:
        message["Reply-To"] = config.reply_to

    # Tells a filter this is triggered mail rather than a campaign, and stops
    # well-behaved autoresponders from replying to it.
    message["Auto-Submitted"] = "auto-generated"
    message["X-Auto-Response-Suppress"] = "All"

    if unsubscribe_mailto:
        # `mailto:` rather than a URL on purpose: an unsubscribe endpoint that
        # acts on a GET is a link any scanner can fire, and the address list
        # lives in the reader's own browser here — there is no server-side list
        # for a URL to remove them from.
        message["List-Unsubscribe"] = f"<mailto:{unsubscribe_mailto}?subject=unsubscribe>"
        message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    # Order matters: `set_content` writes the plaintext body, then
    # `add_alternative` promotes the message to multipart/alternative with the
    # HTML as the preferred part. Doing it the other way round buries the text.
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    return message


def _send_blocking(config: mail_settings_service.MailSettings, message: EmailMessage) -> None:
    """The actual SMTP conversation. Runs off the event loop."""
    timeout = settings.SMTP_TIMEOUT

    if config.ssl:
        context = ssl.create_default_context()
        client: smtplib.SMTP = smtplib.SMTP_SSL(
            config.host, config.port, timeout=timeout, context=context
        )
    else:
        client = smtplib.SMTP(config.host, config.port, timeout=timeout)

    try:
        client.ehlo()
        if config.starttls and not config.ssl:
            client.starttls(context=ssl.create_default_context())
            # Required by RFC 3207: the capability list from before the upgrade
            # is not trustworthy, and some relays only advertise AUTH after it.
            client.ehlo()
        if config.user:
            client.login(config.user, config.password)
        client.send_message(message)
    finally:
        try:
            client.quit()
        except Exception:  # noqa: BLE001 - the message is already delivered
            client.close()


async def send_html(
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    unsubscribe_mailto: str | None = None,
) -> None:
    """
    Send one message, or raise.

    Every outcome is reported to the health registry, so a relay that starts
    refusing logins shows up on `/api/system/health` instead of only in a log
    line nobody is reading.
    """
    config = mail_settings_service.resolved()
    if not config.configured:
        raise EmailNotConfigured(
            "Outbound mail is not configured: set an SMTP host and account, either in "
            "backend/.env or from the Alarm Center's email panel."
        )

    message = _build_message(
        config=config,
        to=to,
        subject=subject,
        html=html,
        text=text,
        unsubscribe_mailto=unsubscribe_mailto,
    )

    started = time.monotonic()
    try:
        await asyncio.to_thread(_send_blocking, config, message)
    except Exception as error:
        health.record(_HEALTH_CATEGORY, ok=False, error=error)
        # The recipient is deliberately absent from the log line. Failures are
        # noisy and log aggregators are not a place to accumulate addresses.
        logger.warning("SMTP send failed via %s: %s", config.host, error)
        raise
    else:
        health.record(
            _HEALTH_CATEGORY,
            ok=True,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
