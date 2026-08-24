"""
Polymarket Router
Serves the prediction-market board, one market's facts, and the bet analysis.

Two conventions from the rest of the API are load-bearing here.

`UpstreamUnavailable` is a 503 rather than an empty board, for the reason the
macro router gives: a page handed `[]` renders an outage as the claim that
nobody is betting on anything. An unresolvable slug is a 404 rather than a blank
market, for the reason `/api/price` gives: declining to answer is honest and a
market card with no odds is not.

The detail endpoint deliberately does no AI work at all. That is what makes an
honest refusal affordable — the facts, the drift and the holder concentration
are all reachable without a model, so when no verdict can be written the page is
still worth looking at and the refusal reads as a statement about the evidence
rather than as a broken page.
"""

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status

from config import settings
from dependencies.auth import AuthUser, get_optional_user
from services.polymarket.facts import MarketUnavailable
from services.polymarket.service import UpstreamUnavailable, get_board, get_market_facts

logger = logging.getLogger(__name__)

router = APIRouter()

# Slugs arrive from the client and are pasted into an outbound query string.
# `url_guard` cannot help: the host is one of ours, so nothing it checks is in
# question. Polymarket's own slugs are lowercase, digits and hyphens, and
# anything else is either a typo or an attempt to steer the upstream request.
_SLUG = re.compile(r"^[a-z0-9-]{1,120}$")


def _validated(slug: str) -> str:
    if not _SLUG.fullmatch(slug):
        raise HTTPException(status_code=404, detail=f"No market matches {slug!r}")
    return slug


@router.get("/api/polymarket/board")
async def get_polymarket_board():
    """
    Active prediction markets by 24-hour volume.

    Carries its own `stale` flag and age so the UI can say how old the odds are
    instead of implying they are live.
    """
    try:
        return await get_board()
    except UpstreamUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/api/polymarket/map")
async def get_polymarket_map():
    """
    Three geographic layers, each labelled with what it actually is.

    None of them is "where the money came from" — that cannot be built from
    Polymarket's data and the payload says so per layer rather than leaving the
    reader to assume. See `services/polymarket/map_service`.
    """
    from services.polymarket.map_service import build_map

    try:
        return await build_map()
    except UpstreamUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/api/polymarket/markets/{slug}")
async def get_polymarket_market(slug: str):
    """
    One market's facts and microstructure. No model is consulted.

    404 when the slug resolves to nothing — never a placeholder market.
    """
    key = _validated(slug)
    try:
        resolved = await get_market_facts(key)
    except MarketUnavailable as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:  # noqa: BLE001
        logger.warning("Polymarket market fetch failed for %s: %s", key, error)
        raise HTTPException(status_code=503, detail="Polymarket is unreachable") from error

    if resolved is None:
        raise HTTPException(status_code=404, detail=f"No market matches {slug!r}")

    facts, micro, _raw = resolved
    return {
        "facts": facts.model_dump(mode="json"),
        "microstructure": micro.model_dump(mode="json"),
    }


def _require_ai() -> None:
    if not settings.USE_AI:
        raise HTTPException(
            status_code=503,
            detail="AI analysis is currently unavailable. The LLM service is not enabled.",
        )


@router.post(
    "/api/polymarket/markets/{slug}/analysis/jobs",
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_polymarket_analysis(
    slug: str,
    response: Response,
    user: Optional[AuthUser] = Depends(get_optional_user),
):
    """
    Start the bet analysis for one market, or re-attach to the running one.

    202 for a fresh run, 200 when an identical job is already in flight — a
    double-clicked Analysis button must not pay for two pipelines.

    The job may well end in a refusal rather than a verdict, and that is a
    successful run: the pipeline declines when the evidence it could gather does
    not support a judgement, and says which searches came back empty.
    """
    _require_ai()
    key = _validated(slug)

    from services.polymarket.analysis import start_analysis_job

    try:
        resolved = await get_market_facts(key, include_trades=False)
    except MarketUnavailable as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    if resolved is None:
        raise HTTPException(status_code=404, detail=f"No market matches {slug!r}")

    _facts, _micro, raw = resolved
    job = await start_analysis_job(raw, user_id=user.id if user else None)
    if not job.is_active:
        response.status_code = status.HTTP_200_OK
    return job.to_dict()


@router.get("/api/polymarket/analysis/jobs/{job_id}")
async def get_polymarket_analysis_job(job_id: str):
    """Poll a running analysis. 404 once the job has aged out of retention."""
    from services.analysis_jobs import get_job

    job = await get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Analysis job not found or expired")
    return job.to_dict()
