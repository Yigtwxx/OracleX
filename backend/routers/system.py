"""
System Router
Reports how far the backend has got through its startup warm-up.
"""

from fastapi import APIRouter

from services.health_registry import health
from services.readiness import readiness

router = APIRouter()


@router.get("/api/system/health")
async def system_health():
    """
    Per-category health of every upstream the app reads, for the LIVE badge.

    Passive: it reports what the last real call to each provider did, and makes
    no request of its own. That means it is cheap enough for the frontend's
    ten-second poll, and it costs no upstream rate limit.

    Public, so `detail` carries only a short failure class — never a URL, a host
    or an upstream's own error body.
    """
    return health.snapshot()


@router.get("/api/system/readiness")
async def system_readiness():
    """
    Startup progress, polled by the frontend's boot gate.

    `ready` turns true once every required step has succeeded and every optional
    one has settled, or once the warm-up deadline passes — whichever comes
    first. `degraded` says the screen opened without everything working, and
    `blocked` says a required step failed and waiting will not help.

    Cheap by design: it reads in-memory state and performs no I/O, because the
    frontend polls it twice a second while the splash is up.
    """
    return readiness.snapshot()
