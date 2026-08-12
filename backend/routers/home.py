"""
Home Router
Handles Home page widget endpoints: funding rates, liquidations, on-chain data,
macro calendar, whale trades.

Every handler lets `UpstreamUnavailable` surface as a 503. An outage must not be
returned as an empty list or a payload of zeros — the widgets render those as
real readings ("no events this week", "0 Gwei / Low cost").
"""

from fastapi import APIRouter, HTTPException

from services.home_service import (
    UpstreamUnavailable,
    fetch_funding_rates,
    fetch_liquidations,
    fetch_macro_calendar,
    fetch_onchain_data,
)
from services.onchain_service import fetch_whale_trades

router = APIRouter()


def _unavailable(error: UpstreamUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail=str(error))


@router.get("/api/home/funding-rates")
async def get_funding_rates():
    """Get real-time funding rates for the core OKX perpetuals, plus any outlier."""
    try:
        return await fetch_funding_rates()
    except UpstreamUnavailable as e:
        raise _unavailable(e) from e


@router.get("/api/home/liquidations")
async def get_liquidations():
    """Get recent liquidations from the OKX liquidation-orders stream."""
    try:
        return await fetch_liquidations()
    except UpstreamUnavailable as e:
        raise _unavailable(e) from e


@router.get("/api/home/onchain")
async def get_onchain_data():
    """
    Get on-chain stats.

    This one never 503s: it is a composite of four independent sources and each
    metric reports its own availability as null, so a partial outage still
    carries the metrics that did resolve.
    """
    return await fetch_onchain_data()


@router.get("/api/home/macro-calendar")
async def get_macro_calendar():
    """Get US Economic Calendar (ForexFactory)."""
    try:
        return await fetch_macro_calendar()
    except UpstreamUnavailable as e:
        raise _unavailable(e) from e


@router.get("/api/onchain/whales")
async def get_whale_trades():
    """Get whale trade activity from OKX public trades."""
    return await fetch_whale_trades()
