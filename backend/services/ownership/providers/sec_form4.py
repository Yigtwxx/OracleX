"""
Insider buys and sells, from SEC Form 4.

The single most important thing in this file is the transaction-code filter, and
it is the thing an unwary implementation gets wrong. A Form 4 reports every
change in an insider's holdings, and most of them are not trades: `M` is an
option or RSU settling, `F` is shares withheld to cover the tax on that
settlement, `A` is a grant, `G` is a gift. Reading the filing without filtering
produces a feed announcing that executives are buying and selling constantly,
when what actually happened is that a vesting schedule ran.

Only `P` (open-market purchase) and `S` (open-market sale) are decisions. Those
are what this provider publishes; everything else is counted and reported as a
number in the entity's issue list, so the omission is visible rather than silent.

Form 4 is filed within two business days, so unlike a 13F this is close to
current — `occurred_at` and `reported_at` are usually a day or two apart rather
than a quarter and a half.
"""

import logging
import re
from datetime import UTC, date, datetime
from typing import Any
from xml.etree import ElementTree

from models.ownership import Move, Position, SourceRef
from services.ownership.providers import sec_client
from services.ownership.providers.base import EntityConfig, ProviderResult

logger = logging.getLogger(__name__)

KIND = "sec_form4"

# The only two codes that represent a decision to buy or sell on the market.
# Everything else is compensation mechanics.
TRADE_CODES = {"P": "buy", "S": "sell"}

# Filings read per entity per refresh. Insiders at an active issuer file in
# bursts, so this is a window rather than a count of events.
MAX_FILINGS = 20


def _text(node: Any, *path: str) -> str | None:
    current = node
    for tag in path:
        found = next((c for c in current if c.tag.rsplit("}", 1)[-1] == tag), None)
        if found is None:
            return None
        current = found
    return (current.text or "").strip() or None


def _number(raw: str | None) -> float | None:
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _owner_matches(root: Any, wanted_cik: str | None, wanted_name: str | None) -> bool:
    """
    Whether this filing belongs to the person we are tracking.

    An issuer's Form 4 stream carries every insider at the company. Without this
    check, a card for one person would fill with everybody else's trades.
    """
    if not wanted_cik and not wanted_name:
        return True

    for owner in root.iter():
        if owner.tag.rsplit("}", 1)[-1] != "reportingOwnerId":
            continue
        cik = (_text(owner, "rptOwnerCik") or "").lstrip("0")
        name = (_text(owner, "rptOwnerName") or "").upper()
        if wanted_cik and cik == str(wanted_cik).lstrip("0"):
            return True
        if wanted_name and wanted_name.upper() in name:
            return True
    return False


def _slug(text: str) -> str:
    """A stable key fragment. Position keys are what snapshot history hangs on."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "unknown"


def _parse_ownership_rows(
    root: Any,
    issuer: str,
    symbol: str | None,
    filed_at: date,
    url: str,
) -> list[dict[str, Any]]:
    """
    Every "and this is what they own now" line in one filing.

    Table I reports, per row, the number of shares held once that row settled —
    including on rows this provider ignores as trades. A grant is not a purchase
    and never appears in the moves feed, but the share count it leaves behind is
    still the filed answer to what the person holds.

    Rows are kept separate by (security, direct/indirect, nature) because that
    is the unit the figure is reported in: shares held directly and shares held
    through a trust are two disclosures, and adding them is only correct if the
    filing happens to report both, which it does not have to.
    """
    rows: list[dict[str, Any]] = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in {"nonDerivativeTransaction", "nonDerivativeHolding"}:
            continue

        shares = _number(
            _text(node, "postTransactionAmounts", "sharesOwnedFollowingTransaction", "value")
        )
        if shares is None:
            continue

        title = _text(node, "securityTitle", "value") or "Common Stock"
        ownership = (_text(node, "ownershipNature", "directOrIndirectOwnership", "value") or "D")[
            :1
        ].upper()
        nature = _text(node, "ownershipNature", "natureOfOwnership", "value")
        occurred = _parse_date(_text(node, "transactionDate", "value")) or filed_at

        rows.append(
            {
                "key": f"form4-{_slug(title)}-{ownership.lower()}"
                + (f"-{_slug(nature)}" if nature else ""),
                "issuer": issuer,
                "symbol": symbol,
                "title": title,
                "ownership": ownership,
                "nature": nature,
                "shares": shares,
                "occurred": occurred,
                "filed_at": filed_at,
                "url": url,
            }
        )
    return rows


def _parse_form4(
    xml: str,
    entity: EntityConfig,
    accession: str,
    filed_at: date,
    url: str,
    wanted_cik: str | None,
    wanted_name: str | None,
) -> tuple[list[Move], int, list[dict[str, Any]]]:
    """Trades in one filing, how many non-trade lines were skipped, and holdings."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return [], 0, []

    if not _owner_matches(root, wanted_cik, wanted_name):
        return [], 0, []

    issuer = _text(root, "issuer", "issuerName") or "Unknown issuer"
    symbol = _text(root, "issuer", "issuerTradingSymbol")
    owner_name = None
    for owner in root.iter():
        if owner.tag.rsplit("}", 1)[-1] == "reportingOwnerId":
            owner_name = _text(owner, "rptOwnerName")
            break

    moves: list[Move] = []
    skipped = 0

    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "nonDerivativeTransaction":
            continue

        code = _text(node, "transactionCoding", "transactionCode")
        if code not in TRADE_CODES:
            skipped += 1
            continue

        shares = _number(_text(node, "transactionAmounts", "transactionShares", "value"))
        if shares is None or shares == 0:
            continue

        # The price can be reported as a footnote reference instead of a value —
        # a blind read of `<value>` raises on those, so it is optional here.
        price = _number(_text(node, "transactionAmounts", "transactionPricePerShare", "value"))
        occurred = _parse_date(_text(node, "transactionDate", "value")) or filed_at

        kind = TRADE_CODES[code]
        signed_shares = shares if kind == "buy" else -shares
        value = shares * price if price is not None else None

        who = owner_name.title() if owner_name else entity.name
        verb = "bought" if kind == "buy" else "sold"
        moves.append(
            Move(
                # Stable across re-reads of the same filing: accession plus the
                # transaction's own date and size.
                id=f"form4-{accession}-{code}-{occurred.isoformat()}-{shares:.0f}",
                entity_id=entity.id,
                entity_name=entity.name,
                category=entity.category,  # type: ignore[arg-type]
                kind=kind,  # type: ignore[arg-type]
                asset_label=issuer.title(),
                asset_symbol=symbol,
                asset_class="equity",
                quantity_delta=signed_shares,
                value_usd_delta=(value if kind == "buy" else -value) if value is not None else None,
                pct_delta=None,
                occurred_at=occurred,
                reported_at=filed_at,
                headline=f"{who} {verb} {shares:,.0f} shares of {symbol or issuer}",
                source=SourceRef(
                    kind=KIND,
                    label=f"Form 4 · {filed_at.isoformat()}",
                    url=url,
                    as_of=occurred,
                    retrieved_at=datetime.now(UTC),
                ),
            )
        )

    return moves, skipped, _parse_ownership_rows(root, issuer, symbol, filed_at, url)


def _holding_positions(
    rows: list[dict[str, Any]],
    prices: dict[str, float],
) -> list[Position]:
    """
    What the filings say the person owns, one position per ownership bucket.

    Never a running total. Summing the transactions in our window would be a
    number nobody filed — the window is a handful of filings, not the position's
    history. What is filed is the share count each row leaves behind, so each
    (security, direct/indirect, nature) bucket takes the count from its own most
    recent row and nothing is added to anything else.

    The share count is the filing's; the dollar value is ours, marked at the
    latest quote. A quote we do not have leaves the value unknown rather than
    dropping the position: "1.3m shares, value unknown" is the true statement,
    and it is more than the card could say before.
    """
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        current = latest.get(row["key"])
        if current is None or (row["occurred"], row["filed_at"]) >= (
            current["occurred"],
            current["filed_at"],
        ):
            latest[row["key"]] = row

    # `natureOfOwnership` is free text, and the same holding is worded
    # differently from one filing to the next — Trump Jr's stake appears as
    # "See Footnote 4" on one Form 4 and as the trust's full name on another.
    # Two buckets of the same security reporting the same share count to the
    # unit are that: one holding described twice. Keeping both doubles it.
    deduped: dict[tuple[str, str, float], dict[str, Any]] = {}
    for row in latest.values():
        signature = (row["title"], row["ownership"], row["shares"])
        current = deduped.get(signature)
        if current is None or (row["occurred"], row["filed_at"]) >= (
            current["occurred"],
            current["filed_at"],
        ):
            deduped[signature] = row

    positions: list[Position] = []
    for row in sorted(deduped.values(), key=lambda r: -r["shares"]):
        symbol = (row["symbol"] or "").upper() or None
        price = prices.get(symbol) if symbol else None
        # An indirect holding is a different disclosure from a direct one and
        # the label has to say so, or two rows of the same stock read as a bug.
        suffix = ""
        if row["ownership"] == "I":
            nature = row["nature"]
            # "See Footnote 4" names nothing; it points at prose we do not
            # render. Printing it puts a dangling cross-reference on the card.
            if nature and re.match(r"^see\s+footnote", nature, re.I):
                nature = None
            suffix = " · indirect" + (f" ({nature})" if nature else "")

        positions.append(
            Position(
                key=row["key"],
                label=f"{row['issuer'].title()}{suffix}",
                symbol=symbol,
                asset_class="equity",
                quantity=row["shares"],
                quantity_unit="shares",
                value_usd=row["shares"] * price if price else None,
                value_basis="marked" if price else "unknown",
                price_usd=price,
                priced_at=datetime.now(UTC) if price else None,
                source=SourceRef(
                    kind=KIND,
                    label=f"Form 4 · {row['filed_at'].isoformat()}",
                    url=row["url"],
                    as_of=row["occurred"],
                    retrieved_at=datetime.now(UTC),
                ),
                note="Shares owned following the most recent reported transaction",
            )
        )
    return positions


async def _issuer_prices(symbols: set[str]) -> dict[str, float]:
    """
    Latest quote per issuer symbol, best effort.

    Best effort because the quote table is a NASDAQ screener: an NYSE-listed
    issuer simply is not in it, and that has to end in an unpriced position
    rather than in an exception or an invented price.
    """
    if not symbols:
        return {}
    try:
        from services.asset_registry import get_stock_quotes

        quotes = await get_stock_quotes()
    except Exception as e:  # noqa: BLE001
        logger.info("Form 4: no quotes available for %s (%s)", ", ".join(sorted(symbols)), e)
        return {}

    prices: dict[str, float] = {}
    for symbol in symbols:
        price = (quotes.get(symbol) or {}).get("price")
        if isinstance(price, (int, float)) and price > 0:
            prices[symbol] = float(price)
    return prices


class SecForm4Provider:
    """Open-market insider purchases and sales."""

    kind: str = KIND
    timeout: float = 120.0

    async def fetch(self, entity: EntityConfig) -> ProviderResult:
        config = entity.sources.get(KIND)
        if not config:
            return ProviderResult.skipped(KIND)

        issuer_cik = config.get("issuer_cik")
        if not issuer_cik:
            return ProviderResult.failed(KIND, "registry entry needs an `issuer_cik`")

        if not sec_client.is_enabled():
            return ProviderResult.failed(
                KIND, "SEC_USER_AGENT is not set — EDGAR requires a contact address"
            )

        owner_cik = config.get("owner_cik")
        owner_name = config.get("owner_name")

        # A Form 4 is indexed under both the issuer and the reporting owner, so
        # when we are tracking a person we ask for *their* filings rather than
        # sifting the issuer's stream for them. An active issuer files in bursts
        # and one person's trades fall off the end of that window within days.
        # The documents still live in the issuer's archive folder, which is why
        # the two CIKs are used for different things below.
        listing_cik = str(owner_cik) if owner_cik else str(issuer_cik)

        try:
            filings = await sec_client.recent_filings(listing_cik, "4", limit=MAX_FILINGS)
        except Exception as e:
            return ProviderResult.failed(KIND, f"could not list Form 4 filings: {e}")

        if not filings:
            return ProviderResult(kind=KIND, ok=True, error="no Form 4 filings found")

        moves: list[Move] = []
        holding_rows: list[dict[str, Any]] = []
        skipped_total = 0
        failures = 0

        for filing in filings:
            accession = filing["accession"]
            try:
                # Documents live under the issuer's folder regardless of whose
                # submission list we found the accession in.
                url = await sec_client.find_document(str(issuer_cik), accession, "4")
                if not url:
                    continue
                xml = await sec_client.get_text(url)
            except Exception:
                failures += 1
                continue

            filed_at = _parse_date(filing["filed_at"]) or date.today()
            index_url = (
                f"{sec_client.archive_dir(str(issuer_cik), accession)}/{accession}-index.htm"
            )
            parsed, skipped, rows = _parse_form4(
                xml, entity, accession, filed_at, index_url, owner_cik, owner_name
            )
            moves.extend(parsed)
            holding_rows.extend(rows)
            skipped_total += skipped

        notes: list[str] = []
        if skipped_total:
            # Said out loud, because a filter this aggressive must not be silent.
            notes.append(
                f"{skipped_total} non-trade line(s) skipped — option settlements, "
                "tax withholding and grants are not buys or sells"
            )
        if failures:
            notes.append(f"{failures} filing(s) unreadable")

        moves.sort(key=lambda m: m.reported_at or m.occurred_at, reverse=True)

        # Holdings only when the registry row names a person. An issuer-wide
        # stream is every insider's filings at once, and their personal stakes
        # are not the company's: reading them as positions would put the CEO's
        # shares on the company's balance sheet.
        positions: list[Position] = []
        if owner_cik or owner_name:
            prices = await _issuer_prices(
                {(row["symbol"] or "").upper() for row in holding_rows if row["symbol"]}
            )
            positions = _holding_positions(holding_rows, prices)
            if holding_rows and not prices:
                notes.append("No quote available for the issuer — holdings are shares only")

        return ProviderResult(
            kind=KIND,
            ok=True,
            positions=positions,
            moves=moves,
            as_of=datetime.now(UTC),
            error="; ".join(notes) or None,
        )
