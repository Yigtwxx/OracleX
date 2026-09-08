"""
Validation for a base URL a *reader* supplied.

The server's own `OLLAMA_BASE_URL` and `LLM_BASE_URL` are operator settings and
are not checked here: whoever writes the environment already runs the process,
so `http://localhost:11434` is exactly right for them.

A value arriving from a request is different. Accepting it unchecked would let
any signed-in reader make the server fetch an address of their choosing —
`http://169.254.169.254/` for cloud instance credentials, or anything on the
private network the container sits in. That is a server-side request forgery
whether or not the response is ever legible to them.

The rule is narrow enough to state in one line: a *reader's* endpoint must be
one the public internet can reach. That costs nothing real, because the whole
point of the field is to name a machine the server is not already next to — a
reader self-hosting the whole stack sets the environment variable instead and
never sees this field. A hostname is resolved before the decision, so
`ollama.internal` pointing at 10.x does not slip past a check on the text.
"""

import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse

# Long enough for a tunnel hostname with a path prefix, short enough that the
# column and the log line stay sane.
MAX_LENGTH = 400


class InvalidBaseURL(ValueError):
    """The supplied endpoint is malformed or is not publicly reachable."""


def _resolved_addresses(host: str) -> list[ipaddress._BaseAddress]:
    """
    Every address `host` resolves to.

    All of them are checked, not just the first: a name that answers with one
    public and one private address would otherwise pass here and connect to the
    private one.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise InvalidBaseURL(f"'{host}' does not resolve.") from e

    addresses = []
    for info in infos:
        try:
            addresses.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    if not addresses:
        raise InvalidBaseURL(f"'{host}' does not resolve to an IP address.")
    return addresses


def _is_public(address: ipaddress._BaseAddress) -> bool:
    """
    Whether the server may dial this address on a reader's say-so.

    `is_global` alone is not enough: it answers True for some addresses Python
    does not classify as private but which are still not somewhere a request
    should be sent, so the specific families are named as well.
    """
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def validate(raw: Optional[str]) -> str:
    """
    Normalise a reader-supplied base URL, or raise `InvalidBaseURL`.

    Returns "" for a blank value, which every caller reads as "use the server's
    setting" rather than as an endpoint.
    """
    if raw is None:
        return ""

    url = raw.strip().rstrip("/")
    if not url:
        return ""

    if len(url) > MAX_LENGTH:
        raise InvalidBaseURL(f"That endpoint is longer than {MAX_LENGTH} characters.")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise InvalidBaseURL("The endpoint must start with http:// or https://.")
    if not parsed.hostname:
        raise InvalidBaseURL("The endpoint has no host.")
    # Credentials in the URL would be logged by anything that prints it, and no
    # legitimate Ollama or OpenAI-compatible endpoint needs them.
    if parsed.username or parsed.password:
        raise InvalidBaseURL("Put credentials in the API key field, not in the URL.")

    for address in _resolved_addresses(parsed.hostname):
        if not _is_public(address):
            raise InvalidBaseURL(
                "That address is not reachable from the public internet, so this "
                "server cannot call it. Expose your machine through a tunnel and "
                "use the address it gives you."
            )

    return url
