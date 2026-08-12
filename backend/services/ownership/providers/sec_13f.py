"""
Institutional equity portfolios, from SEC Form 13F-HR.

This is the richest source on the board and the one most easily misread, so two
things are stated on every line it produces.

The value is *as filed*. A 13F reports what a position was worth at the quarter
end, in whole dollars, and that is the number carried through — `value_basis` is
`reported`. Re-pricing the share count against today's quote would produce a
figure no filing contains and no reader could check against anything.

The coverage is partial by law. A 13F lists US-listed long equity and options
held by managers over $100m. It does not show cash, bonds, foreign listings,
short positions or anything held outside the US. A bar built from it fills to
100% of a slice of a portfolio, never of a fortune, which is why every entity
using this source carries a `coverage_note` saying so.

Deltas come from the filings themselves rather than from our snapshot history:
two consecutive 13Fs are a quarter-over-quarter comparison already, so a holder
added today shows real NEW/ADD/TRIM/EXIT immediately instead of waiting a
quarter for us to accumulate a second observation of our own.
"""

import logging
from datetime import UTC, date, datetime
from typing import Any
from xml.etree import ElementTree

from models.ownership import Move, Position, SourceRef
from services.ownership.providers import sec_client
from services.ownership.providers.base import EntityConfig, ProviderResult
from services.ownership.providers.cusip import resolve_tickers

logger = logging.getLogger(__name__)

KIND = "sec_13f"

# Relative change below which two share counts are the same position. Matches
# the snapshot store's threshold so the two never disagree about what moved.
CHANGE_EPSILON = 0.0005
# Positions kept per filer. Berkshire files ~40; the largest filers file
# thousands, and a detail pane is not improved by row four thousand.
MAX_POSITIONS = 250


def _text(node: Any, *path: str) -> str | None:
    """Read a nested tag, ignoring whichever namespace the filer used."""
    current = node
    for tag in path:
        found = None
        for child in current:
            if child.tag.rsplit("}", 1)[-1] == tag:
                found = child
                break
        if found is None:
            return None
        current = found
    return (current.text or "").strip() or None


def _quarter_label(period: str) -> str:
    """`2026-03-31` into `13F Q1 2026`, which is what the badge shows."""
    try:
        when = date.fromisoformat(period)
    except ValueError:
        return "13F"
    return f"13F Q{(when.month - 1) // 3 + 1} {when.year}"


def _parse_info_table(xml: str) -> dict[str, dict[str, Any]]:
    """
    One filing's holdings, keyed by CUSIP.

    Aggregated rather than listed: a filer reports the same security once per
    internal manager, so Berkshire's ninety rows are twenty-nine positions. A
    table that showed the rows would count the same holding several times.
    """
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as e:
        raise sec_client.SecUnavailable(f"information table is not valid XML: {e}") from e

    holdings: dict[str, dict[str, Any]] = {}
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "infoTable":
            continue

        cusip = _text(node, "cusip")
        issuer = _text(node, "nameOfIssuer")
        if not cusip or not issuer:
            continue

        # Options are reported alongside the shares of the same issuer. Folding
        # them into one line would present a call position as stock ownership.
        if (_text(node, "putCall") or "").upper() in {"PUT", "CALL"}:
            continue

        try:
            value = float(_text(node, "value") or 0)
            shares = float(_text(node, "shrsOrPrnAmt", "sshPrnamt") or 0)
        except ValueError:
            continue

        entry = holdings.setdefault(
            cusip,
            {"issuer": issuer, "value": 0.0, "shares": 0.0, "class": _text(node, "titleOfClass")},
        )
        entry["value"] += value
        entry["shares"] += shares

    _rescale_thousands(holdings)
    return holdings


def _rescale_thousands(holdings: dict[str, dict[str, Any]]) -> None:
    """
    Put a filing reported in thousands back into dollars, in place.

    The `value` column was reported in thousands until the 2023 rewrite and in
    whole dollars after it, and the table carries no marker saying which. Filers
    who never updated their software still file the old way — Duquesne's Q1 2026
    table prices 3.06m shares of Natera at $612,691, which read as dollars makes
    Druckenmiller's book worth $2.9m instead of $2.9bn.

    Decided on the implied share price, since that is the one quantity with a
    known plausible range: value/shares comes out in cents for a thousands-scaled
    filing and in dollars otherwise. The median rather than the mean, so one
    misreported row cannot flip the whole filing, and a threshold of $1 because
    a portfolio whose *typical* holding trades under a dollar is not a portfolio
    a 13F filer has.
    """
    prices = sorted(
        entry["value"] / entry["shares"]
        for entry in holdings.values()
        if entry["shares"] > 0 and entry["value"] > 0
    )
    if not prices:
        return

    median = prices[len(prices) // 2]
    if median >= 1.0:
        return

    logger.info("13F table looks reported in thousands (median implied price %.4f)", median)
    for entry in holdings.values():
        entry["value"] *= 1000.0


def _relative_change(before: float, after: float) -> float | None:
    if before == 0:
        return None
    return (after - before) / before


def _build_positions(
    current: dict[str, dict[str, Any]],
    previous: dict[str, dict[str, Any]],
    tickers: dict[str, str],
    source: SourceRef,
) -> list[Position]:
    total = sum(entry["value"] for entry in current.values())
    positions: list[Position] = []

    for cusip, entry in current.items():
        before = previous.get(cusip)
        delta_shares = entry["shares"] - before["shares"] if before else None
        delta_value = entry["value"] - before["value"] if before else None
        delta_pct = _relative_change(before["shares"], entry["shares"]) if before else None

        positions.append(
            Position(
                key=cusip,
                label=entry["issuer"].title(),
                symbol=tickers.get(cusip),
                asset_class="equity",
                quantity=entry["shares"],
                quantity_unit="shares",
                value_usd=entry["value"],
                # As filed, at the quarter end. Not our arithmetic.
                value_basis="reported",
                weight_pct=(entry["value"] / total * 100.0) if total else None,
                delta_quantity=delta_shares,
                delta_value_usd=delta_value,
                # A brand-new position has no percentage change from nothing;
                # None reads as "no baseline", which is what NEW means.
                delta_pct=delta_pct * 100.0 if delta_pct is not None else None,
                source=source,
                note=None if before else "New this quarter",
            )
        )

    positions.sort(key=lambda p: -(p.value_usd or 0.0))
    return positions[:MAX_POSITIONS]


def _build_moves(
    entity: EntityConfig,
    current: dict[str, dict[str, Any]],
    previous: dict[str, dict[str, Any]],
    tickers: dict[str, str],
    period: date,
    filed_at: date,
    source: SourceRef,
) -> list[Move]:
    moves: list[Move] = []

    for cusip in set(current) | set(previous):
        now = current.get(cusip)
        before = previous.get(cusip)

        if now and not before:
            kind, delta_shares, delta_value, entry = "new", now["shares"], now["value"], now
        elif before and not now:
            kind, delta_shares, delta_value, entry = (
                "exit",
                -before["shares"],
                -before["value"],
                before,
            )
        elif now and before:
            change = _relative_change(before["shares"], now["shares"])
            if change is None or abs(change) <= CHANGE_EPSILON:
                continue
            kind = "add" if change > 0 else "trim"
            delta_shares = now["shares"] - before["shares"]
            delta_value = now["value"] - before["value"]
            entry = now
        else:
            continue

        label = entry["issuer"].title()
        symbol = tickers.get(cusip)
        verb = {
            "new": "opened a position in",
            "exit": "exited",
            "add": "added to",
            "trim": "trimmed",
        }[kind]

        moves.append(
            Move(
                # Keyed on the period rather than on today, so re-reading the
                # same filing for the next ninety days yields the same id.
                id=f"13f-{entity.id}-{cusip}-{period.isoformat()}-{kind}",
                entity_id=entity.id,
                entity_name=entity.name,
                category=entity.category,  # type: ignore[arg-type]
                kind=kind,  # type: ignore[arg-type]
                asset_label=label,
                asset_symbol=symbol,
                asset_class="equity",
                quantity_delta=delta_shares,
                value_usd_delta=delta_value,
                pct_delta=None,
                # What it describes versus when it became public — for a 13F
                # these are up to 45 days apart, and the UI shows both.
                occurred_at=period,
                reported_at=filed_at,
                headline=f"{entity.name} {verb} {label} — {abs(delta_shares):,.0f} shares",
                source=source,
            )
        )

    moves.sort(key=lambda m: -abs(m.value_usd_delta or 0.0))
    return moves


class Sec13FProvider:
    """US-listed long equity, as filed quarterly on Form 13F-HR."""

    kind: str = KIND
    # Two filings plus an index page, all paced. Generous but bounded.
    timeout: float = 90.0

    async def fetch(self, entity: EntityConfig) -> ProviderResult:
        config = entity.sources.get(KIND)
        if not config:
            return ProviderResult.skipped(KIND)

        cik = config.get("cik")
        if not cik:
            return ProviderResult.failed(KIND, "registry entry needs a `cik`")

        if not sec_client.is_enabled():
            # Not a failure of SEC's, and not something a retry fixes.
            return ProviderResult.failed(
                KIND, "SEC_USER_AGENT is not set — EDGAR requires a contact address"
            )

        try:
            filings = await sec_client.recent_filings(str(cik), "13F-HR", limit=2)
        except Exception as e:
            return ProviderResult.failed(KIND, f"could not list filings: {e}")

        if not filings:
            return ProviderResult.failed(KIND, "no 13F-HR filings found for this CIK")

        try:
            current = await self._holdings(str(cik), filings[0])
        except Exception as e:
            return ProviderResult.failed(KIND, str(e))

        if not current:
            # A 200 that parsed to nothing is a schema change, not an empty
            # portfolio — a filer with no holdings would not be filing.
            return ProviderResult.failed(KIND, "information table parsed to no holdings")

        previous: dict[str, dict[str, Any]] = {}
        if len(filings) > 1:
            try:
                previous = await self._holdings(str(cik), filings[1])
            except Exception as e:
                # Deltas are a nice-to-have; the portfolio is the point.
                logger.info("%s: previous 13F unavailable (%s) — no quarter deltas", entity.id, e)

        period = _parse_date(filings[0]["period"]) or date.today()
        filed_at = _parse_date(filings[0]["filed_at"]) or period
        accession = filings[0]["accession"]

        source = SourceRef(
            kind=KIND,
            label=_quarter_label(filings[0]["period"]),
            url=f"{sec_client.archive_dir(str(cik), accession)}/{accession}-index.htm",
            as_of=period,
            retrieved_at=datetime.now(UTC),
        )

        tickers = await resolve_tickers(list(current))
        positions = _build_positions(current, previous, tickers, source)
        moves = (
            _build_moves(entity, current, previous, tickers, period, filed_at, source)
            if previous
            else []
        )

        return ProviderResult(
            kind=KIND,
            ok=True,
            positions=positions,
            moves=moves,
            as_of=datetime.now(UTC),
            error=None
            if previous
            else "No previous filing — quarter-over-quarter changes unavailable",
        )

    async def _holdings(self, cik: str, filing: dict[str, str]) -> dict[str, dict[str, Any]]:
        accession = filing["accession"]
        url = await sec_client.find_document(cik, accession, "INFORMATION TABLE")
        if not url:
            raise sec_client.SecUnavailable(f"no information table in filing {accession}")
        return _parse_info_table(await sec_client.get_text(url))


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None
