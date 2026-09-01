"""
One fund's equity positions, assembled from KAP and cached hard.

Four upstream calls stand between a fund code and a holdings list — catalogue,
disclosure query, attachment detail, download — plus a PDF parse. That is far
too much to put behind the fund board, so this is **lazy and per fund**: nothing
is fetched until someone opens a fund, and the answer is then good for a day
against a source that publishes once a month.

That laziness is what makes the feature affordable at all. A nightly job over
two thousand funds would be four thousand requests and half a gigabyte against a
host that rate-limits; a reader opening a fund page is three requests, one of
which is already cached for every other fund.

**It never raises and it always says why.** A fund can have no report yet, a
report this parser cannot read, or a report that lists no equity, and those are
three different sentences on the page. Collapsing them into an empty card would
tell a reader the fund holds no stocks, which for two of the three is false.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from services.bist import fund_holdings, kap_fund_client
from services.cache import bist_cache

logger = logging.getLogger(__name__)

# A month's report is a month's report. The day is not about freshness, it is
# about not repeating four calls for every reader who opens the same fund.
TTL_HOLDINGS = 24 * 60 * 60

# Two months, because that is what a late filing costs: a fund that has not
# filed August by October should still show July rather than nothing.
MAX_STALE_HOLDINGS = 60 * 24 * 60 * 60

# The catalogue is two thousand rows for one request and changes when a fund is
# launched or wound up, which is not a daily event.
TTL_CATALOGUE = 24 * 60 * 60

# After a failure, how long before another attempt for the same fund. KAP
# rate-limits, and a reader refreshing a page that failed should not be what
# pushes it over.
TTL_COOLDOWN = 10 * 60

# How far back to look for the newest report. Long enough to cross a late filing
# and a fund that skipped a month; short enough that the query stays small.
LOOKBACK_DAYS = 150

# What a caller is told when there is nothing to draw.
REASON_NO_REPORT = "no_report"
REASON_UNREADABLE = "unreadable"
REASON_UNAVAILABLE = "unavailable"
REASON_NOT_LISTED = "not_listed"
REASON_NO_EQUITY = "no_equity"


@dataclass(frozen=True)
class FundHoldings:
    """One fund's equity book, as its newest monthly filing states it."""

    code: str
    year: int
    period: int
    published: Optional[date]
    late: bool
    layout: str
    holdings: tuple[fund_holdings.Holding, ...]
    total_value: float
    disclosure_url: str


@dataclass(frozen=True)
class HoldingsOutcome:
    """What the page gets: the book, or the reason there isn't one."""

    holdings: Optional[FundHoldings]
    reason: Optional[str]
    stale: bool = False


def _disclosure_url(index: int) -> str:
    return f"{kap_fund_client.KAP_ROOT}/tr/Bildirim/{index}"


async def _catalogue(fund_type: str) -> Optional[dict[str, kap_fund_client.FundRef]]:
    key = f"kapfunds:{fund_type}"
    cached = bist_cache.get(key)
    if cached is not None:
        return cached
    try:
        catalogue = await kap_fund_client.fetch_fund_catalogue(fund_type)
    except (kap_fund_client.KapUnavailable, ValueError) as e:
        logger.warning("KAP fund catalogue unavailable: %s", e)
        return bist_cache.get_with_fallback(key, max_age=MAX_STALE_HOLDINGS)
    bist_cache.set(key, catalogue, TTL_CATALOGUE)
    return catalogue


async def fetch_fund_holdings(code: str, fund_type: str = "YAT") -> HoldingsOutcome:
    """
    The fund's newest readable equity book, or a named reason there is none.

    Walks back through the filings rather than stopping at the newest: a house
    whose August report this parser cannot read filed a July one in the same
    layout, so stopping would turn a parser gap into a permanently empty card
    for that fund. Two attempts, because a third is a coverage problem to fix in
    `fund_holdings` rather than to paper over with requests.
    """
    code = code.strip().upper()
    if not code:
        raise ValueError("fund code is required")

    key = f"holdings:{code}"
    cached = bist_cache.get(key)
    if cached is not None:
        return cached

    def _stale(reason: str) -> HoldingsOutcome:
        previous = bist_cache.get_with_fallback(key, max_age=MAX_STALE_HOLDINGS)
        if previous is None or previous.holdings is None:
            return HoldingsOutcome(holdings=None, reason=reason)
        return HoldingsOutcome(holdings=previous.holdings, reason=None, stale=True)

    cooldown = f"holdings:cooldown:{code}"
    if bist_cache.get(cooldown) is not None:
        return _stale(REASON_UNAVAILABLE)
    bist_cache.set(cooldown, True, TTL_COOLDOWN)

    catalogue = await _catalogue(fund_type)
    if catalogue is None:
        return _stale(REASON_UNAVAILABLE)

    fund = catalogue.get(code)
    if fund is None:
        # Known to TEFAS, absent from KAP's active book. Pension and exchange
        # funds file under their own type, and a fund can be listed on one and
        # not the other; either way there is nothing here to read.
        outcome = HoldingsOutcome(holdings=None, reason=REASON_NOT_LISTED)
        bist_cache.set(key, outcome, TTL_HOLDINGS)
        return outcome

    today = date.today()
    try:
        reports = await kap_fund_client.fetch_portfolio_reports(
            [fund.oid],
            fund_type=fund_type,
            since=today - timedelta(days=LOOKBACK_DAYS),
            until=today,
        )
    except kap_fund_client.KapUnavailable as e:
        logger.warning("KAP portfolio reports unavailable for %s: %s", code, e)
        return _stale(REASON_UNAVAILABLE)

    if not reports:
        outcome = HoldingsOutcome(holdings=None, reason=REASON_NO_REPORT)
        bist_cache.set(key, outcome, TTL_HOLDINGS)
        return outcome

    for report in reports[:2]:
        try:
            attachment = await kap_fund_client.fetch_attachment(report.index)
            if attachment is None or attachment.extension != "pdf":
                continue
            pdf = await kap_fund_client.download_report(attachment.obj_id)
        except kap_fund_client.KapUnavailable as e:
            logger.warning("KAP attachment unavailable for %s/%s: %s", code, report.index, e)
            return _stale(REASON_UNAVAILABLE)

        parsed = fund_holdings.parse_pdf(pdf)
        if parsed is not None and not parsed.holdings:
            # The report was read and the fund holds no stocks. A real answer,
            # and one a bond fund's page should say out loud.
            outcome = HoldingsOutcome(holdings=None, reason=REASON_NO_EQUITY)
            bist_cache.set(key, outcome, TTL_HOLDINGS)
            return outcome

        if parsed is None:
            logger.info(
                "portfolio report unreadable for %s (%s/%s, disclosure %s)",
                code,
                report.year,
                report.period,
                report.index,
            )
            continue

        outcome = HoldingsOutcome(
            holdings=FundHoldings(
                code=code,
                year=report.year,
                period=report.period,
                published=report.published,
                late=report.late,
                layout=parsed.layout,
                holdings=parsed.holdings,
                total_value=parsed.total_value,
                disclosure_url=_disclosure_url(report.index),
            ),
            reason=None,
        )
        bist_cache.set(key, outcome, TTL_HOLDINGS)
        return outcome

    outcome = HoldingsOutcome(holdings=None, reason=REASON_UNREADABLE)
    bist_cache.set(key, outcome, TTL_HOLDINGS)
    return outcome
