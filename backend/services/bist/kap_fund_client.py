"""
KAP's fund API — the only public source for what a fund actually owns.

`tefas_client` answers *how much* of a fund is equity. Only KAP answers *which
equities*, and it does so once a month in an attachment to a disclosure called
"Portföy Dağılım Raporu". This module gets to that attachment.

**This is a different KAP from `kap_service`.** That one reads the disclosure
tape by walking sequential `/tr/Bildirim/<index>` pages, because when it was
written the query surface was a React Server Component app with no JSON to call.
The *fund* surface does have one, on the same host, and it is properly
queryable — so the note in `kap_service` about KAP having no usable public API
is true of the tape and not of this. Four calls stand between a fund code and a
PDF:

1. `/tr/api/fund/criteria/{type}/{state}` — the whole book in one response,
   mapping fund code to the `fundOid` everything else is keyed on.
2. `/tr/api/disclosure/funds/byCriteria` — disclosures for a set of funds,
   filtered by subject. Takes hundreds of oids at once, which is what makes a
   batch refresh cheap even though the reports themselves are not.
3. `/tr/api/notification/attachment-detail/{index}` — the attachment's `objId`.
4. `/tr/api/file/download/{objId}` — the bytes.

Two things about step 4 that cost an afternoon to find. It answers
`content-type: application/pdf` and does not send a PDF: the body is a **Java
serialised `byte[]`**, with the file starting 27 bytes in behind an `ac ed 00 05`
stream header. And the wrapper is undocumented, so the unwrapping here looks for
the PDF's own markers rather than trusting the offset — if MKK ever serves the
file plainly, that keeps working.

Everything goes through the `*_kap` helpers in `services/http_client`, which
hold the primed cookie jar the bot-protection layer requires and put the host on
the health badge.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from services.http_client import KAP_ROOT, get_bytes_kap, get_json_kap, post_json_kap

logger = logging.getLogger(__name__)

CATALOGUE_ENDPOINT = f"{KAP_ROOT}/tr/api/fund/criteria"
DISCLOSURE_ENDPOINT = f"{KAP_ROOT}/tr/api/disclosure/funds/byCriteria"
ATTACHMENT_ENDPOINT = f"{KAP_ROOT}/tr/api/notification/attachment-detail"
DOWNLOAD_ENDPOINT = f"{KAP_ROOT}/tr/api/file/download"

# KAP's own identifier for the monthly portfolio breakdown. Opaque, and the only
# way to ask for it — the endpoint filters on this and not on a title.
PORTFOLIO_REPORT_SUBJECT = "8aca490d502e34b801502e380044002b"

# TEFAS and KAP name the three books differently. TEFAS's codes are what the
# rest of this codebase carries, so the translation lives at this boundary.
KAP_FUND_TYPES = {"YAT": "YF", "EMK": "EYF", "BYF": "BYF"}

# `Y` is the active book. Wound-up funds are a separate list and nothing on this
# board wants them: a fund that no longer exists has no current holdings.
ACTIVE = "Y"


class KapUnavailable(RuntimeError):
    """KAP did not answer, or answered with something unusable."""


@dataclass(frozen=True)
class FundRef:
    """A fund as KAP identifies it."""

    code: str
    oid: str
    name: str


@dataclass(frozen=True)
class PortfolioReport:
    """One monthly portfolio disclosure, before its attachment is fetched."""

    fund_code: str
    index: int
    year: int
    period: int
    """Calendar month the report covers, 1-12."""
    published: Optional[date]
    late: bool
    """KAP's own flag. Worth carrying: a late filing is the commonest reason a
    fund's newest report is two months old rather than one."""


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _parse_published(raw: Any) -> Optional[date]:
    """`"10.08.2026 10:36:08"` — KAP's only date format on this surface."""
    text = _text(raw)
    if not text:
        return None
    try:
        return datetime.strptime(text.split(" ")[0], "%d.%m.%Y").date()
    except ValueError:
        return None


async def fetch_fund_catalogue(fund_type: str = "YAT") -> dict[str, FundRef]:
    """
    Every active fund of one book, keyed by its TEFAS code.

    One request for two thousand funds, which is why the oid lookup is a lookup
    and not a slug derived from the fund's name — KAP's permalinks are built
    from titles and a title can be renamed.
    """
    kap_type = KAP_FUND_TYPES.get(fund_type)
    if kap_type is None:
        raise ValueError(f"fund_type must be one of {sorted(KAP_FUND_TYPES)}, got {fund_type!r}")

    try:
        rows = await get_json_kap(f"{CATALOGUE_ENDPOINT}/{kap_type}/{ACTIVE}")
    except Exception as e:  # noqa: BLE001 — transport, status and decode all mean the same here
        raise KapUnavailable(f"KAP fund catalogue unavailable: {e}") from e

    if not isinstance(rows, list) or not rows:
        raise KapUnavailable("KAP returned no funds")

    catalogue: dict[str, FundRef] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = _text(row.get("fundCode")).upper()
        oid = _text(row.get("fundOid"))
        if not code or not oid:
            continue
        catalogue[code] = FundRef(
            code=code, oid=oid, name=_text(row.get("fundName")) or _text(row.get("title"))
        )
    if not catalogue:
        raise KapUnavailable("KAP fund catalogue carried no usable rows")
    return catalogue


def _disclosure_payload(oids: list[str], fund_type: str, since: date, until: date) -> dict:
    """
    The disclosure query body, in full.

    Every empty list and empty string is sent rather than omitted. The endpoint
    reads the body as a filled-in form and a missing key is not the same as a
    blank one — the same trap `tefas_client._screener_payload` documents.
    """
    return {
        "fromDate": since.isoformat(),
        "toDate": until.isoformat(),
        "fundTypeList": [KAP_FUND_TYPES.get(fund_type, "YF")],
        "mkkMemberOidList": [],
        "fundOidList": oids,
        "passiveFundOidList": [],
        "disclosureClass": "",
        "isLate": "",
        "subjectList": [PORTFOLIO_REPORT_SUBJECT],
        "discIndex": [],
        "fromSrc": False,
        "srcCategory": "",
    }


async def fetch_portfolio_reports(
    oids: list[str], *, fund_type: str = "YAT", since: date, until: date
) -> list[PortfolioReport]:
    """
    Portfolio-report disclosures for a set of funds, newest first per fund.

    Takes a list because the endpoint does: asking for four hundred funds costs
    the same round trip as asking for one, and the caller decides whether it is
    filling a single fund's card or rebuilding a book.
    """
    if not oids:
        return []

    try:
        rows = await post_json_kap(
            DISCLOSURE_ENDPOINT, payload=_disclosure_payload(oids, fund_type, since, until)
        )
    except Exception as e:  # noqa: BLE001
        raise KapUnavailable(f"KAP disclosure query unavailable: {e}") from e

    if not isinstance(rows, list):
        raise KapUnavailable("KAP disclosure query returned an unexpected body")

    reports: list[PortfolioReport] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = _text(row.get("fundCode")).upper()
        try:
            index = int(row.get("disclosureIndex"))
            year = int(row.get("year"))
            period = int(row.get("period"))
        except (TypeError, ValueError):
            continue
        if not code:
            continue
        reports.append(
            PortfolioReport(
                fund_code=code,
                index=index,
                year=year,
                period=period,
                published=_parse_published(row.get("publishDate")),
                late=bool(row.get("isLate")),
            )
        )

    # Newest period first. Sorted on the period the report covers rather than on
    # its publication date: a late filing is published after a newer one and
    # would otherwise displace it.
    reports.sort(key=lambda report: (report.year, report.period), reverse=True)
    return reports


def _walk_attachments(node: Any, found: list[dict]) -> None:
    """The attachment list is nested differently per disclosure class, so it is
    searched for by shape rather than by path."""
    if isinstance(node, dict):
        if node.get("objId") and (node.get("fileName") or node.get("fileExtension")):
            found.append(node)
        for value in node.values():
            _walk_attachments(value, found)
    elif isinstance(node, list):
        for value in node:
            _walk_attachments(value, found)


@dataclass(frozen=True)
class Attachment:
    obj_id: str
    file_name: str
    extension: str


async def fetch_attachment(index: int) -> Optional[Attachment]:
    """
    The disclosure's first attachment, or None when it has none.

    Only the first: a portfolio report has exactly one in every case seen, and a
    second would be a correction whose relationship to the first this module has
    no way to judge.
    """
    try:
        body = await get_json_kap(f"{ATTACHMENT_ENDPOINT}/{index}")
    except Exception as e:  # noqa: BLE001
        raise KapUnavailable(f"KAP attachment detail unavailable for {index}: {e}") from e

    found: list[dict] = []
    _walk_attachments(body, found)
    if not found:
        return None

    first = found[0]
    return Attachment(
        obj_id=_text(first.get("objId")),
        file_name=_text(first.get("fileName")),
        extension=_text(first.get("fileExtension")).lower(),
    )


def unwrap_pdf(raw: bytes) -> Optional[bytes]:
    """
    The PDF inside whatever KAP's download endpoint actually sent.

    The body arrives as a Java serialised `byte[]` — `ac ed 00 05` then a type
    descriptor, with the file 27 bytes in — under a `content-type` of
    `application/pdf`, which is how it goes unnoticed until a parser rejects it.

    Located by the PDF's own markers rather than by that offset. The offset is a
    property of one serialiser's output; `%PDF-` and `%%EOF` are properties of
    the format, and a plainly served file falls out of the same code path.
    """
    start = raw.find(b"%PDF-")
    if start == -1:
        return None
    end = raw.rfind(b"%%EOF")
    if end == -1 or end < start:
        return None
    return raw[start : end + len(b"%%EOF")]


async def download_report(obj_id: str) -> bytes:
    """The attachment's bytes, unwrapped. Raises when it is not a PDF at all."""
    try:
        raw = await get_bytes_kap(f"{DOWNLOAD_ENDPOINT}/{obj_id}")
    except Exception as e:  # noqa: BLE001
        raise KapUnavailable(f"KAP attachment download failed for {obj_id}: {e}") from e

    pdf = unwrap_pdf(raw)
    if pdf is None:
        # Some houses file the report as a spreadsheet. That is a coverage gap
        # rather than a fault, but it is not something this path can read.
        raise KapUnavailable(f"KAP attachment {obj_id} is not a PDF")
    return pdf
