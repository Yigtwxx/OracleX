"""
Takasbank's declared Price Scan Range, per underlying.

**This module is the reason the VİOP map is worth drawing.** The crypto
liquidation map has to invent how leverage is distributed across its users —
`LEVERAGE_TIERS` in `services/liquidation_map_service.py` is ten made-up
weights, and it is that model's weakest joint, because no exchange publishes
what leverage its users chose. Here the clearing house publishes one number that
binds everyone, per underlying, every day. So a cohort gets one band, and that
band sits where a published parameter says it sits. Nothing is distributed and
nothing is assumed.

**What the PSR is, and what it is not.** It is the price move Takasbank
collateralises against under the BISTECH margin method — a one-day, 99%
confidence scan range, expressed as a percentage of contract value. A position
whose price moves by the PSR has exhausted the scan risk its initial margin was
sized for.

It is **not** a margin-call trigger. Takasbank does not publish a maintenance
margin rate for VİOP: the CCP procedure (31.07.2026) leaves the level to a
General Letter in article 39/3, and 39/4 states maintenance is not applied at
end of day. The "75% of initial" figure that circulates appears only in an
undated guide. So the call price cannot be computed, is not computed here, and
must not be claimed anywhere it is drawn.

**Two filters that are not optional.** The file carries a portfolio per broker
alongside the ones per underlying, and rights-issue portfolios beside the main
contract. Without `setlMeth == "DELIV"` and dropping a `pfCode` ending in `_C`,
THYAO reads 14.0 instead of its actual 13.4 — a plausible wrong number, arrived
at silently.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from io import BytesIO
from typing import Optional

from services.cache import bist_cache
from services.http_client import get_bytes

logger = logging.getLogger(__name__)

# Named for the payload and the page: the reader is told which host the number
# came from, because "a published rate" is only a claim if its source is stated.
PSR_SOURCE_HOST = "wwwdata.takasbank.com.tr"

# The live parameter directory. Not `takasbank.com.tr`, which sits behind a
# bot-protection layer, and not `wwwdata.takasbank.com.tr/viop/SPAN/`, which is
# a legacy archive frozen on 03.03.2017 — both are dead ends that look alive.
DIRECTORY_URL = "https://wwwdata.takasbank.com.tr/pardosya/Prod/{day}/"

# End-of-day, run 001. The intraday files revise the parameter through the
# session — nine to sixteen runs a day — so they are not a snapshot anything can
# be pinned to. The end-of-day file is the one fixed point.
EOD_PATTERN = re.compile(r"TAKASEOD_[A-Z0-9_-]*-(\d{6})-001\.zip")

# Rights-issue portfolios shadow the main contract with a different scan rate.
RIGHTS_SUFFIX = "_C"

# Physically settled single-stock futures. The file also holds cash-settled
# broker collateral portfolios under the same element name.
DELIVERY_METHOD = "DELIV"

# The archive is about two megabytes and expands to roughly seventy. Only the
# compressed body crosses the network; the expansion is streamed.
MAX_ARCHIVE_BYTES = 12_000_000
MAX_LISTING_BYTES = 2_000_000

TTL_PSR = 6 * 60 * 60
MAX_STALE_PSR = 7 * 24 * 60 * 60

# How many days back to look for a published file before giving up. Covers a
# long weekend plus a public holiday.
MAX_LOOKBACK_DAYS = 6

SCHEMA_VERSION = 1
CACHE_KEY = "takasbank_psr"

PSR_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "takasbank_psr.json",
)


class PsrUnavailable(RuntimeError):
    """No scan range could be read, and no recent enough copy survives."""


@dataclass(frozen=True)
class UnderlyingPsr:
    """One underlying's declared scan range."""

    underlying: str
    psr: float
    """Fraction of contract value, e.g. 0.134 for THYAO's 13.4%."""
    contract_value: Optional[float]
    multiplier: Optional[int]
    """`cvf` — shares per contract, straight from the clearing house. An
    independent check on the figure the bulletin derives for itself."""


@dataclass
class PsrSnapshot:
    rates: dict[str, UnderlyingPsr]
    as_of: str
    """The file's own `pointInTime` date, not when we fetched it."""
    run: str
    created: str
    source_file: str
    stored_at: float

    def get(self, underlying: str) -> Optional[UnderlyingPsr]:
        return self.rates.get(underlying.strip().upper())


def _text(element: ET.Element, path: str) -> Optional[str]:
    found = element.findtext(path)
    return found.strip() if isinstance(found, str) else None


def _number(raw: Optional[str]) -> Optional[float]:
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return None if value != value else value


def parse_span(payload: bytes) -> PsrSnapshot:
    """
    The underlying → scan range map out of one SPAN archive.

    Streamed with `iterparse` and cleared as it goes: the document expands to
    roughly seventy megabytes and only about fifty rows of it are wanted, so
    holding the tree would cost two orders of magnitude more memory than the
    answer. Measured at about a second.
    """
    archive = zipfile.ZipFile(BytesIO(payload))
    names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
    if not names:
        raise PsrUnavailable("SPAN archive holds no XML")

    rates: dict[str, UnderlyingPsr] = {}
    created = ""
    as_of = ""
    run = ""

    with archive.open(names[0]) as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            tag = element.tag.split("}")[-1]

            if tag == "created" and not created:
                created = (element.text or "").strip()
                continue
            if tag == "pointInTime":
                as_of = _text(element, "date") or as_of
                run = _text(element, "run") or run
                element.clear()
                continue
            if tag != "futPf":
                continue

            code = (_text(element, "pfCode") or "").upper()
            settlement_method = _text(element, "setlMeth")
            scan = _number(_text(element, ".//scanRate/priceScanPct"))
            contract_value = _number(_text(element, ".//fut/val"))
            cvf = _number(_text(element, ".//fut/cvf"))
            element.clear()

            if not code or code.endswith(RIGHTS_SUFFIX):
                continue
            if settlement_method != DELIVERY_METHOD:
                continue
            if scan is None or scan <= 0:
                continue

            rates[code] = UnderlyingPsr(
                underlying=code,
                psr=scan / 100.0,
                contract_value=contract_value,
                multiplier=int(cvf) if cvf else None,
            )

    if not rates:
        raise PsrUnavailable("SPAN archive yielded no scan ranges")

    return PsrSnapshot(
        rates=rates,
        as_of=as_of,
        run=run,
        created=created,
        source_file=names[0],
        stored_at=time.time(),
    )


def _read_psr_file() -> Optional[PsrSnapshot]:
    try:
        with open(PSR_FILE) as handle:
            payload = json.load(handle)
        if int(payload.get("schema_version", 0)) != SCHEMA_VERSION:
            return None
        if time.time() - float(payload["stored_at"]) > MAX_STALE_PSR:
            return None
        return PsrSnapshot(
            rates={key: UnderlyingPsr(**value) for key, value in payload["rates"].items()},
            as_of=payload["as_of"],
            run=payload["run"],
            created=payload["created"],
            source_file=payload["source_file"],
            stored_at=float(payload["stored_at"]),
        )
    except FileNotFoundError:
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("Takasbank PSR cache unreadable, ignoring it: %s", e)
        return None


def _write_psr_file(snapshot: PsrSnapshot) -> None:
    try:
        os.makedirs(os.path.dirname(PSR_FILE), exist_ok=True)
        temp = f"{PSR_FILE}.tmp"
        with open(temp, "w") as handle:
            json.dump(
                {
                    "schema_version": SCHEMA_VERSION,
                    "stored_at": snapshot.stored_at,
                    "as_of": snapshot.as_of,
                    "run": snapshot.run,
                    "created": snapshot.created,
                    "source_file": snapshot.source_file,
                    "rates": {key: asdict(value) for key, value in snapshot.rates.items()},
                },
                handle,
            )
        os.replace(temp, PSR_FILE)
    except Exception as e:  # noqa: BLE001
        logger.warning("Takasbank PSR cache could not be written: %s", e)


async def _latest_eod_url() -> Optional[str]:
    """The newest end-of-day archive within the lookback window, or None."""
    for step in range(MAX_LOOKBACK_DAYS):
        day = date.today() - timedelta(days=step)
        if day.weekday() >= 5:
            continue
        url = DIRECTORY_URL.format(day=day.strftime("%y%m%d"))
        try:
            listing = await get_bytes(url, timeout=30.0, max_bytes=MAX_LISTING_BYTES)
        except Exception as e:  # noqa: BLE001
            logger.debug("Takasbank listing for %s unavailable: %s", day, e)
            continue
        names = EOD_PATTERN.findall(listing.decode("utf-8", errors="replace"))
        if not names:
            continue
        return f"{url}TAKASEOD_-CCP__-BI-_____-{day.strftime('%y%m%d')}-001.zip"
    return None


async def fetch_psr() -> PsrSnapshot:
    """
    The current scan ranges, from cache, disk, or the clearing house.

    A stale copy is served rather than nothing: the parameter moves slowly and
    a band drawn from last week's figure with its date on the screen is more
    honest than a page that refuses to render. It is only a hard failure when
    there is no copy at all — the distance the band sits at is a published
    number, and there is no version of this map that invents one.
    """
    cached = bist_cache.get(CACHE_KEY)
    if cached is not None:
        return cached

    on_disk = await asyncio.to_thread(_read_psr_file)
    if on_disk is not None and time.time() - on_disk.stored_at < TTL_PSR:
        bist_cache.set(CACHE_KEY, on_disk, TTL_PSR)
        return on_disk

    try:
        url = await _latest_eod_url()
        if url is None:
            raise PsrUnavailable("no end-of-day parameter file published in the lookback window")
        payload = await get_bytes(url, timeout=120.0, max_bytes=MAX_ARCHIVE_BYTES)
        # The archive expands to seventy megabytes and takes about a second to
        # walk. That is a second the event loop would spend answering nothing.
        snapshot = await asyncio.to_thread(parse_span, payload)
        snapshot.source_file = url.rsplit("/", 1)[-1]
    except Exception as e:  # noqa: BLE001
        if on_disk is not None:
            logger.warning("Takasbank PSR unreadable, serving the copy on disk: %s", e)
            bist_cache.set(CACHE_KEY, on_disk, TTL_PSR)
            return on_disk
        raise PsrUnavailable(f"Takasbank scan ranges unavailable: {e}") from e

    await asyncio.to_thread(_write_psr_file, snapshot)
    bist_cache.set(CACHE_KEY, snapshot, TTL_PSR)
    return snapshot
