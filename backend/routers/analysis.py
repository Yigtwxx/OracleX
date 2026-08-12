"""
Analysis & Notes Router
Handles AI market reports and user notes.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from dependencies.auth import AuthUser, get_optional_user

router = APIRouter()

VALID_TIMEFRAMES = ("daily", "weekly", "monthly")


class NoteRequest(BaseModel):
    title: str
    content: str


def _validate_timeframe(timeframe: str) -> None:
    if timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(status_code=400, detail="Invalid timeframe")


@router.get("/api/analysis/reports")
async def get_report_summaries():
    """
    Freshness metadata for every timeframe.

    Read-only and cheap — this is what the Analysis page loads on mount, so it
    must never trigger generation.
    """
    from services.analysis_service import get_report_summaries as summaries

    return summaries()


@router.get("/api/analysis/report/{timeframe}")
async def get_analysis_report(timeframe: str):
    """
    Return the stored report for a timeframe, or an empty one if none exists.

    Generation is explicitly job-driven; opening the page must not start it.
    """
    _validate_timeframe(timeframe)
    from services.analysis_service import get_report

    return get_report(timeframe)


@router.post("/api/analysis/jobs/{timeframe}", status_code=status.HTTP_202_ACCEPTED)
async def start_analysis_job(
    timeframe: str,
    response: Response,
    user: Optional[AuthUser] = Depends(get_optional_user),
):
    """
    Start generating a report in the background.

    If a job for this timeframe is already in flight, its id is returned rather
    than starting a second run.
    """
    _validate_timeframe(timeframe)
    from services.analysis_jobs import start_job

    job = await start_job(timeframe, user_id=user.id if user else None)
    if not job.is_active:
        # Already finished (retention window) — the client can read it straight away.
        response.status_code = status.HTTP_200_OK
    return job.to_dict()


@router.get("/api/analysis/active-jobs")
async def get_active_analysis_jobs():
    """
    Report jobs currently in flight.

    The job id lives in page state, so leaving the Analysis tab loses it while
    the run keeps going server-side. This lets a returning client rediscover
    what it started — which horizon is generating, and how far along it is —
    without holding the id anywhere.
    """
    from services.analysis_jobs import KIND_REPORT, active_jobs

    return [job.to_dict() for job in await active_jobs() if job.kind == KIND_REPORT]


@router.get("/api/analysis/jobs/{job_id}")
async def get_analysis_job(job_id: str):
    """Poll a report job for its current stage and, once done, its result."""
    from services.analysis_jobs import get_job

    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return job.to_dict()


@router.delete("/api/analysis/jobs/{job_id}")
async def cancel_analysis_job(job_id: str):
    """
    Stop a running report.

    Generation costs minutes of LLM time, so a run started by mistake — or on
    the wrong horizon — needs a way out that is not waiting for it to finish.
    Returns the settled job, so the caller sees the outcome it asked for.
    """
    from services.analysis_jobs import KIND_REPORT, cancel_job, get_job

    job = await get_job(job_id)
    if job is None or job.kind != KIND_REPORT:
        raise HTTPException(status_code=404, detail="Job not found or expired")

    cancelled = await cancel_job(job_id)
    if cancelled is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return cancelled.to_dict()


@router.get("/api/analysis/notes")
async def get_notes():
    """Get all user notes."""
    try:
        from services.analysis_service import get_user_notes

        return get_user_notes()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/analysis/notes")
async def create_note(request: NoteRequest):
    """Create a new user note."""
    try:
        from services.analysis_service import add_user_note

        return add_user_note(request.title, request.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/analysis/notes/{note_id}")
async def delete_note(note_id: str):
    """Delete a user note."""
    try:
        from services.analysis_service import delete_user_note

        return delete_user_note(note_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
