"""
The one door onto SEC EDGAR, paced so we keep our access to it.

SEC asks for no more than ten requests a second and for a User-Agent naming a
contact address on every single one. It enforces both: a request without the
header is answered 403, and sustained abuse is blocked by IP — which would take
out the whole deployment, not just this feature. So the throttle lives here
rather than at the call sites, because the limit belongs to the host and not to
any one caller: two providers each politely staying under the rate would
together be over it.

`SEC_USER_AGENT` empty disables everything downstream. That is deliberate. A
deployment that has not declared itself should read no filings at all rather
than risk the ban — a missing feature is recoverable, a blocked IP is not.
"""

import asyncio
import logging
import time
from html import unescape
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

# Well under SEC's stated ceiling. This job runs once a day against a handful of
# filers; there is nothing to gain from crowding the limit.
MIN_REQUEST_INTERVAL = 0.15
REQUEST_TIMEOUT = 30.0

_LOCK = asyncio.Lock()
_last_request_at = 0.0


class SecUnavailable(Exception):
    """EDGAR could not be read. Carries why, for the entity's issue list."""


def is_enabled() -> bool:
    """Whether a contact address has been declared. Nothing runs without one."""
    return bool(settings.SEC_USER_AGENT.strip())


def _headers() -> dict[str, str]:
    return {
        "User-Agent": settings.SEC_USER_AGENT.strip(),
        "Accept-Encoding": "gzip, deflate",
    }


async def _paced_get(url: str) -> httpx.Response:
    """One GET, never closer than MIN_REQUEST_INTERVAL to the previous one."""
    global _last_request_at

    async with _LOCK:
        gap = time.monotonic() - _last_request_at
        if gap < MIN_REQUEST_INTERVAL:
            await asyncio.sleep(MIN_REQUEST_INTERVAL - gap)
        _last_request_at = time.monotonic()

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        return await client.get(url, headers=_headers())


async def get_json(url: str) -> Any:
    if not is_enabled():
        raise SecUnavailable("SEC_USER_AGENT is not configured")
    response = await _paced_get(url)
    if response.status_code == 403:
        raise SecUnavailable("SEC returned 403 — check SEC_USER_AGENT")
    response.raise_for_status()
    return response.json()


async def get_text(url: str) -> str:
    if not is_enabled():
        raise SecUnavailable("SEC_USER_AGENT is not configured")
    response = await _paced_get(url)
    if response.status_code == 403:
        raise SecUnavailable("SEC returned 403 — check SEC_USER_AGENT")
    response.raise_for_status()
    return response.text


def pad_cik(cik: str) -> str:
    """EDGAR's submissions endpoint wants the ten-digit, zero-padded form."""
    return str(cik).strip().lstrip("CIK").zfill(10)


def archive_dir(cik: str, accession: str) -> str:
    """The folder a filing's documents live in."""
    return f"{ARCHIVES_BASE}/{int(pad_cik(cik))}/{accession.replace('-', '')}"


async def recent_filings(cik: str, form_type: str, limit: int = 4) -> list[dict[str, str]]:
    """
    The most recent filings of one type, newest first.

    Reads the `recent` block of the submissions JSON, which covers roughly the
    last thousand filings — far more than the four quarters this needs, so the
    older paginated files are deliberately not fetched.
    """
    payload = await get_json(SUBMISSIONS_URL.format(cik=pad_cik(cik)))
    recent = (payload.get("filings") or {}).get("recent") or {}

    forms = recent.get("form") or []
    accessions = recent.get("accessionNumber") or []
    dates = recent.get("filingDate") or []
    report_dates = recent.get("reportDate") or []
    primary = recent.get("primaryDocument") or []

    out: list[dict[str, str]] = []
    for i, form in enumerate(forms):
        if form != form_type:
            continue
        out.append(
            {
                "accession": accessions[i] if i < len(accessions) else "",
                "filed_at": dates[i] if i < len(dates) else "",
                "period": report_dates[i] if i < len(report_dates) else "",
                "primary_document": primary[i] if i < len(primary) else "",
            }
        )
        if len(out) >= limit:
            break
    return out


async def find_document(cik: str, accession: str, type_label: str) -> str | None:
    """
    The URL of the document of a given `<TYPE>` inside a filing.

    The filename cannot be guessed: across filers the 13F information table has
    been `53405.xml`, `123122ainftable.xml` and `form13fInfoTable.xml`. The
    index-headers page is the only thing that reliably maps a document type to
    its filename, so it is read rather than assumed.
    """
    index_url = f"{archive_dir(cik, accession)}/{accession}-index-headers.html"
    try:
        html = await get_text(index_url)
    except Exception as e:
        raise SecUnavailable(f"could not read filing index: {e}") from e

    # The page is SGML rendered inside a <pre>, so its own angle brackets arrive
    # escaped: the document list reads `&lt;TYPE&gt;INFORMATION TABLE`, not
    # `<TYPE>`. Unescaping first is what makes the rest of this a line scan.
    text = unescape(html)

    current_type: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("<TYPE>"):
            current_type = line[len("<TYPE>") :].strip().upper()
        elif line.startswith("<FILENAME>") and current_type == type_label.upper():
            filename = line[len("<FILENAME>") :].strip()
            if filename:
                return f"{archive_dir(cik, accession)}/{filename}"
    return None
