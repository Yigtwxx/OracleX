"""HTTP access to an Oracle-X instance, with the failure modes kept apart.

Three outcomes have to stay distinguishable all the way up to the tool result,
because a model cannot recover from them the same way:

  * the instance is not there            → nothing will work; say so and stop
  * the instance declined                → a real answer: no data for that input
  * the instance answered                → data

Collapsing the middle case into an error is what makes an agent retry a symbol
that will never resolve; collapsing it into an empty result is what makes one
report "no liquidations" when it never asked the right question.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"

# Market reads are served from the backend's own cache and answer quickly.
# LLM-backed work is not done inline — it goes through the job endpoints — so
# no tool here needs a minutes-long timeout.
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


class OracleXError(RuntimeError):
    """The instance could not answer. Never raised when it answers 'no'."""


class InstanceUnreachable(OracleXError):
    """Nothing is listening. Every other tool will fail the same way."""


class NotFound(OracleXError):
    """The instance has no data for that request.

    Oracle-X refuses to emit a placeholder price or a placeholder technical
    payload, so a 404 is a deliberate answer rather than a fault. Tools
    surface it as text the model can pass on, not as a retryable error.
    """


class AuthRequired(OracleXError):
    """The endpoint is scoped to a signed-in user and no usable token exists."""


def base_url() -> str:
    return os.environ.get("ORACLE_X_URL", DEFAULT_BASE_URL).rstrip("/")


def token() -> str | None:
    return os.environ.get("ORACLE_X_TOKEN") or None


def _auth_headers() -> dict[str, str]:
    value = token()
    if not value:
        raise AuthRequired(
            "This needs a signed-in user. Set ORACLE_X_TOKEN to a Supabase "
            "access token in the MCP server's environment."
        )
    return {"Authorization": f"Bearer {value}"}


async def request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    authenticated: bool = False,
) -> Any:
    """Call one endpoint and return the decoded JSON."""
    headers = _auth_headers() if authenticated else {}
    url = f"{base_url()}{path}"

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.request(method, url, params=params, json=json, headers=headers)
    except httpx.ConnectError as exc:
        raise InstanceUnreachable(
            f"No Oracle-X instance answering at {base_url()}. Start the "
            "terminal, or point ORACLE_X_URL at the right host."
        ) from exc
    except httpx.TimeoutException as exc:
        raise OracleXError(f"{path} timed out against {base_url()}.") from exc

    return _decode(response, path)


def _decode(response: httpx.Response, path: str) -> Any:
    if response.status_code == 404:
        raise NotFound(f"The instance has no data for {path}.")
    if response.status_code == 401:
        raise AuthRequired(f"{path}: ORACLE_X_TOKEN is missing or expired.")
    if response.status_code == 403:
        raise AuthRequired(f"{path}: this account is not permitted.")
    if response.status_code == 422:
        # FastAPI's validation error — a required parameter the caller did not
        # know about. Pass the detail through: retrying the same call cannot
        # help, and the body says exactly what is missing.
        raise OracleXError(f"{path} rejected the parameters: {response.text[:300]}")
    if response.status_code == 503:
        raise OracleXError(
            f"{path}: the upstream this endpoint depends on is not answering "
            "right now. Other categories may still be healthy — check the "
            "instance health."
        )
    if response.status_code >= 400:
        raise OracleXError(f"{path}: HTTP {response.status_code}")

    return response.json()


async def get(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    authenticated: bool = False,
) -> Any:
    return await request("GET", path, params=params, authenticated=authenticated)


async def post(
    path: str,
    json: dict[str, Any] | None = None,
    *,
    authenticated: bool = False,
) -> Any:
    return await request("POST", path, json=json, authenticated=authenticated)
