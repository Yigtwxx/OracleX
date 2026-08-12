"""
Is this address plausibly real?

Sign-up used to accept anything the browser's `type="email"` let through, so
`a@a.a` and a ten-minute mailbox were as good as a real address. This module is
the check in front of it, in three steps ordered cheapest-first so a typo never
costs a network round-trip:

    syntax      does it parse as an address at all
    disposable  is the domain a known throwaway-mail service
    DNS         does the domain actually accept mail (MX, then A)

None of the three proves the mailbox exists — only the confirmation email
Supabase sends does that, and it stays the final gate. What this buys is an
immediate, specific message at the point of typing rather than a silent failure
the user discovers when no mail arrives.

Deliberately fails open. A resolver outage that blocked every sign-up on the
site would be a far worse failure than letting a handful of dead domains
through, so an unreachable resolver returns `ok=True` with `reason="unresolved"`
and a warning in the log.

DNS is resolved over HTTPS through the existing `httpx` dependency rather than
by adding `dnspython`. The stdlib cannot look up MX records at all, and a real
resolver would answer through the container's `/etc/resolv.conf` — which is a
stub in Docker and behaves differently on a development machine than on the
deployment target. DoH is the same everywhere, is natively async, and can be
tested by patching one function.
"""

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Literal

from cachetools import TTLCache

from config import settings
from services import http_client

logger = logging.getLogger(__name__)

Reason = Literal["ok", "syntax", "disposable", "no_mx", "unresolved"]


@dataclass(frozen=True)
class EmailVerdict:
    """The outcome of one address check. `message` is display-ready."""

    ok: bool
    reason: Reason
    message: str
    domain: str


_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_BLOCKLIST_PATH = os.path.join(
    os.path.dirname(_BACKEND_DIR), "data", "disposable_email_domains.txt"
)

# Pragmatic rather than RFC-complete. The full grammar permits quoted local
# parts and bracketed IP domains, neither of which any real sign-up uses, and
# accepting them here would only widen what the rest of the app has to handle.
_SYNTAX = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
    r"(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)

_MAX_LENGTH = 254

# Two providers, tried in order, so one being down is not an outage here.
_RESOLVERS = (
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
)
_DOH_HEADERS = {"accept": "application/dns-json"}
_DOH_TIMEOUT = 3.0

# NXDOMAIN. The domain does not exist, which is a different answer from "exists
# but has no mail server" and reaches the same verdict by a shorter path.
_NXDOMAIN = 3

# One hour is long enough that a busy sign-up form does not re-resolve
# gmail.com on every submission, and short enough that a newly configured
# domain starts working the same day.
_dns_cache: TTLCache = TTLCache(maxsize=4096, ttl=3600)


def _load_blocklist() -> frozenset[str]:
    """
    Read the disposable-domain list once, at import.

    A missing file is a warning, never a startup failure: the other two checks
    still work, and refusing to boot over a data file would take the whole API
    down with it.
    """
    try:
        with open(_BLOCKLIST_PATH, encoding="utf-8") as handle:
            domains = {
                line.strip().lower()
                for line in handle
                if line.strip() and not line.lstrip().startswith("#")
            }
    except OSError as e:
        logger.warning("email_guard: disposable-domain list unavailable (%s)", e)
        return frozenset()

    logger.info("email_guard: loaded %d disposable domains", len(domains))
    return frozenset(domains)


DISPOSABLE_DOMAINS = _load_blocklist()


def normalize(email: str) -> str:
    """
    Trim the address and lowercase its domain.

    The local part is left alone on purpose: it is case-sensitive per RFC 5321,
    and a few real mail systems still treat it that way. Only the domain half
    is safe to fold, which is also all the comparisons here need.
    """
    email = email.strip()
    if "@" not in email:
        return email
    local, _, domain = email.rpartition("@")
    return f"{local}@{domain.lower()}"


def domain_of(email: str) -> str:
    """The domain half of `email`, lowercased, or `""` if there isn't one."""
    _, _, domain = email.rpartition("@")
    return domain.strip().lower()


def _syntax_ok(email: str) -> bool:
    return len(email) <= _MAX_LENGTH and bool(_SYNTAX.match(email))


def _is_disposable(domain: str) -> bool:
    """
    Whether `domain` — or any parent of it — is on the blocklist.

    Walking the parents is what catches `foo.mailinator.com`: the throwaway
    services hand out unlimited subdomains, so matching the exact string only
    would block the front door and leave every window open.
    """
    if not DISPOSABLE_DOMAINS:
        return False

    labels = domain.split(".")
    for i in range(len(labels) - 1):
        if ".".join(labels[i:]) in DISPOSABLE_DOMAINS:
            return True
    return False


async def _query(resolver: str, domain: str, record: str) -> Any:
    return await http_client.get_json(
        resolver,
        params={"name": domain, "type": record},
        headers=_DOH_HEADERS,
        timeout=_DOH_TIMEOUT,
    )


async def _accepts_mail(domain: str) -> bool | None:
    """
    Whether `domain` has a mail destination.

    Returns True/False for an answer, and None when no resolver could be
    reached — the caller turns that into a fail-open verdict.

    Falling back from MX to A is not a formality: RFC 5321 §5.1 says a host with
    an address record and no MX is still a valid mail destination, and a few
    small domains are configured exactly that way.
    """
    cached = _dns_cache.get(domain)
    if cached is not None:
        return cached

    for resolver in _RESOLVERS:
        try:
            answer = await _query(resolver, domain, "MX")
        except Exception as e:
            logger.debug("email_guard: %s failed for %s (%s)", resolver, domain, type(e).__name__)
            continue

        if not isinstance(answer, dict):
            continue

        if answer.get("Status") == _NXDOMAIN:
            _dns_cache[domain] = False
            return False

        if answer.get("Answer"):
            _dns_cache[domain] = True
            return True

        try:
            fallback = await _query(resolver, domain, "A")
        except Exception:
            # The MX answer was authoritative enough on its own: the domain
            # resolved and simply has no mail exchanger.
            _dns_cache[domain] = False
            return False

        result = bool(isinstance(fallback, dict) and fallback.get("Answer"))
        _dns_cache[domain] = result
        return result

    logger.warning("email_guard: no resolver could be reached for %s", domain)
    return None


async def check_deliverable(email: str) -> EmailVerdict:
    """Run the three checks in order and return the first failure, or `ok`."""
    address = normalize(email)
    domain = domain_of(address)

    if not _syntax_ok(address):
        return EmailVerdict(
            ok=False,
            reason="syntax",
            message="That does not look like an email address.",
            domain=domain,
        )

    if _is_disposable(domain):
        return EmailVerdict(
            ok=False,
            reason="disposable",
            message="Temporary-mail addresses are not accepted. Use an address you can keep.",
            domain=domain,
        )

    if not settings.EMAIL_DNS_CHECK_ENABLED:
        return EmailVerdict(ok=True, reason="ok", message="", domain=domain)

    accepts = await _accepts_mail(domain)
    if accepts is None:
        return EmailVerdict(
            ok=True,
            reason="unresolved",
            message="",
            domain=domain,
        )
    if not accepts:
        return EmailVerdict(
            ok=False,
            reason="no_mx",
            message=f"No mail server is configured for {domain}. Check the spelling.",
            domain=domain,
        )

    return EmailVerdict(ok=True, reason="ok", message="", domain=domain)
