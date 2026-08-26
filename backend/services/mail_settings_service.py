"""
The SMTP relay's configuration, from the environment *or* from the admin panel.

## Why this exists at all

Every other secret in this app is environment-only, on the reasoning stated in
CLAUDE.md: a request can write the database and cannot write the environment.
That reasoning still holds for `ADMIN_EMAILS`, which decides who is trusted, and
it is not being weakened here.

It does not hold for an SMTP relay. Adminship is the gate, not the payload — a
caller who can already reach this code is already trusted, and making them SSH
in to add four lines to a `.env` buys nothing beyond the friction. So the relay
is configurable at runtime by an admin, and this module is the one place that
decides what "configured" currently means.

## Resolution order

    file (admin panel)  →  environment  →  unset

The file wins because it is the more recent statement of intent: an admin who
typed a host into the panel expects that host to be used, not a stale one from a
`.env` written months ago. An empty field in the file is *absence*, not an
override with the empty string, so setting only a password in the panel keeps
the host from `.env`.

## What is stored, and how

`backend/data/mail_settings.json`, written 0600 and gitignored. The password is
encrypted through `services/secret_box` — the same Fernet box the per-user LLM
keys use, for the same reason: a file on disk is a file that gets copied into a
backup, and a plaintext app password there is a compromised mailbox.

`token_secret` is stored in the clear next to it, and that is deliberate rather
than an oversight. It signs the confirmation tokens in `alarm_email_service`,
whose entire power is "may cause alarm mail to be sent to an address that
already confirmed itself". Losing it costs a nuisance; losing the mailbox
password costs the mailbox. Encrypting the second and not the first reflects
that difference instead of implying both are equally grave.

It is also generated on first use if the environment sets none, which is what
makes the panel work end to end without anyone editing a file.
"""

import json
import logging
import os
import secrets
import threading
from dataclasses import dataclass, replace
from typing import Any

from config import settings
from services import secret_box

logger = logging.getLogger(__name__)

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORE_PATH = os.path.join(_BACKEND_DIR, "data", "mail_settings.json")

# One process, several workers under uvicorn --reload; the write is a
# read-modify-write and two admins saving at once would otherwise interleave.
_lock = threading.Lock()

# Fields an admin may set. Kept as a tuple rather than inferred from the
# dataclass so adding an internal field to `MailSettings` cannot silently make
# it writable over HTTP.
EDITABLE_FIELDS: tuple[str, ...] = (
    "host",
    "port",
    "user",
    "ssl",
    "starttls",
    "from_address",
    "from_name",
    "reply_to",
)


@dataclass(frozen=True)
class MailSettings:
    """The relay as it will actually be dialled."""

    host: str
    port: int
    user: str
    password: str
    ssl: bool
    starttls: bool
    from_address: str
    from_name: str
    reply_to: str

    @property
    def sender(self) -> str:
        """
        Who the message is from.

        Falls back to the authenticated user, because that is the address SPF
        and DKIM will authenticate and the only one Gmail's relay will not
        rewrite. See the docstring in `services/email_delivery`.
        """
        return (self.from_address or self.user).strip()

    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender)


class MailSettingsError(RuntimeError):
    """A refusal the router turns into a 4xx with this message."""


# ── The file ────────────────────────────────────────────────────────────────


def _read_file() -> dict[str, Any]:
    """The stored overrides, or `{}` — a missing or corrupt file is not an error."""
    try:
        with open(_STORE_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as error:
        # Falling back to the environment is the right failure here: the relay
        # keeps working on whatever `.env` says instead of the feature going
        # dark because one file was truncated by a bad shutdown.
        logger.warning("mail settings file unreadable, falling back to env: %s", error)
        return {}
    return data if isinstance(data, dict) else {}


def _write_file(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_STORE_PATH), exist_ok=True)
    temporary = f"{_STORE_PATH}.tmp"
    # 0600 before any content is written, not after: a chmod that follows the
    # write leaves a window where the password is world-readable.
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    # Atomic replace, so a crash mid-write leaves the previous file intact
    # rather than a half-parsed one.
    os.replace(temporary, _STORE_PATH)


# ── Resolution ──────────────────────────────────────────────────────────────


def _from_env() -> MailSettings:
    return MailSettings(
        host=settings.SMTP_HOST.strip(),
        port=settings.SMTP_PORT,
        user=settings.SMTP_USER.strip(),
        password=settings.SMTP_PASSWORD,
        ssl=settings.SMTP_SSL,
        starttls=settings.SMTP_STARTTLS,
        from_address=settings.SMTP_FROM.strip(),
        from_name=settings.SMTP_FROM_NAME.strip(),
        reply_to=settings.SMTP_REPLY_TO.strip(),
    )


def _decrypt_password(stored: dict[str, Any]) -> str | None:
    ciphertext = stored.get("password")
    if not ciphertext:
        return None
    try:
        return secret_box.decrypt(ciphertext)
    except secret_box.SecretBoxUnconfigured as error:
        # The secret was rotated or removed. Say so once and fall through to the
        # environment; silently sending with no password would fail at the relay
        # with a far less useful message.
        logger.warning("stored SMTP password could not be decrypted: %s", error)
        return None


def resolved() -> MailSettings:
    """The settings in force right now — file over environment, field by field."""
    current = _from_env()
    stored = _read_file()

    for field in EDITABLE_FIELDS:
        if field not in stored:
            continue
        value = stored[field]
        if isinstance(value, str) and not value.strip() and field != "reply_to":
            # An empty string in the file means "nothing was typed here", which
            # must not blank out a working value from the environment. Reply-To
            # is the exception: clearing it is a real intent.
            continue
        current = replace(current, **{field: value})

    password = _decrypt_password(stored)
    if password:
        current = replace(current, password=password)

    return current


def is_configured() -> bool:
    return resolved().configured


def source() -> str:
    """Where the current settings came from, for the panel to display."""
    stored = _read_file()
    if any(field in stored for field in EDITABLE_FIELDS) or stored.get("password"):
        return "panel"
    return "env" if _from_env().configured else "none"


def public_view() -> dict[str, Any]:
    """
    What the admin panel is shown.

    Never the password, and never its ciphertext — only whether one exists. A
    field the panel cannot read is a field the panel cannot leak.
    """
    current = resolved()
    return {
        "host": current.host,
        "port": current.port,
        "user": current.user,
        "ssl": current.ssl,
        "starttls": current.starttls,
        "from_address": current.from_address,
        "from_name": current.from_name,
        "reply_to": current.reply_to,
        "has_password": bool(current.password),
        "sender": current.sender,
        "configured": current.configured,
        "source": source(),
    }


# ── Writing ─────────────────────────────────────────────────────────────────


def save(fields: dict[str, Any], password: str | None) -> None:
    """
    Persist an admin's changes.

    `password=None` means "leave whatever is stored alone", which is what an
    edit that does not retype the password has to mean — the panel never
    receives the current one, so it cannot send it back.
    """
    unknown = set(fields) - set(EDITABLE_FIELDS)
    if unknown:
        raise MailSettingsError(f"Unknown field(s): {', '.join(sorted(unknown))}")

    if password is not None and not secret_box.is_configured():
        raise MailSettingsError(
            "Set LLM_KEY_ENCRYPTION_SECRET in backend/.env before storing a password — "
            "it is the key this backend encrypts stored secrets with. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )

    with _lock:
        stored = _read_file()
        for field, value in fields.items():
            stored[field] = value
        if password is not None:
            # An empty password is a deletion, not an empty secret to encrypt.
            stored["password"] = secret_box.encrypt(password) if password else ""
        stored.setdefault("token_secret", _new_token_secret())
        _write_file(stored)


def clear() -> None:
    """Forget every override and fall back to the environment."""
    with _lock:
        stored = _read_file()
        # The signing secret survives, so clearing the relay does not invalidate
        # every address a user already confirmed.
        kept = {"token_secret": stored["token_secret"]} if stored.get("token_secret") else {}
        if kept:
            _write_file(kept)
        else:
            try:
                os.remove(_STORE_PATH)
            except FileNotFoundError:
                pass


# ── The token signing secret ────────────────────────────────────────────────


def _new_token_secret() -> str:
    return secrets.token_urlsafe(48)


def token_secret() -> str:
    """
    The key confirmation tokens are signed with.

    Environment first, so a deployment that wants to control it still can and
    rotating it there invalidates every token at once. Otherwise one is
    generated and kept, which is what lets the whole feature be turned on from
    the panel without anyone opening a file.
    """
    from_env = settings.ALARM_EMAIL_SECRET.strip()
    if from_env:
        return from_env

    stored = _read_file()
    existing = stored.get("token_secret")
    if isinstance(existing, str) and existing:
        return existing

    with _lock:
        # Re-read inside the lock: another request may have generated one while
        # this one was waiting, and handing out two different secrets would
        # invalidate the first caller's token the moment it was issued.
        stored = _read_file()
        existing = stored.get("token_secret")
        if isinstance(existing, str) and existing:
            return existing
        generated = _new_token_secret()
        stored["token_secret"] = generated
        _write_file(stored)
        return generated
