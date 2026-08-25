"""
Background jobs for the LLM pipelines.

Both the market report and the single-news analysis take longer than an HTTP
request should be held open. Callers start a job, then poll it for the current
stage and, eventually, the finished result. A pipeline that can answer before it
finishes publishes a `partial_result` first.

State is in-process and deliberately so: the app runs as a single uvicorn
instance and a report is cheap to re-run, so surviving a restart is not worth a
persistence layer.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from services.analysis_service import STAGES, generate_market_report

logger = logging.getLogger(__name__)

# Finished jobs stay queryable for a while so a client that reconnects can still
# collect its result, then are dropped.
JOB_RETENTION_SECONDS = 30 * 60

ACTIVE_STATUSES = ("queued", "running")


# Job kinds. The key namespace is shared, so single-flight dedup has to compare
# both — a "daily" report and a news item are never the same run.
KIND_REPORT = "report"
KIND_NEWS = "news"
KIND_CHAT = "chat"
KIND_NOTE = "note"
KIND_POLYMARKET = "polymarket"
# The verdict and the "why was this opened" answer are two runs over the same
# market, started by the same click and keyed by the same slug. Without a
# distinct kind the single-flight lock would dedup one into the other and the
# second click would re-attach to a job answering a different question.
KIND_POLYMARKET_ORIGIN = "polymarket_origin"

# A report is worth re-reading half an hour later; a chat answer is collected by
# the poll that is already running and is dead weight after that. Holding
# thousands of finished turns would also mean holding every question asked.
#
# A grounded note is borrowed machinery: `ai_notes` starts one only to take the
# single-flight lock, and reads the finished text back out of its own store
# rather than off the job. So the job is dead weight the moment it settles, and
# it is held just long enough for a poll already in flight to see it finish.
RETENTION_BY_KIND = {KIND_CHAT: 5 * 60, KIND_NOTE: 60}


@dataclass
class Job:
    """
    One background pipeline run.

    `key` is what single-flight dedups on: the timeframe for a report, the news
    id for a news analysis. `stages` travels with the job because the two
    pipelines have different ones, and the UI renders whatever it is given.
    """

    id: str
    key: str
    kind: str = KIND_REPORT
    stages: List[Dict[str, str]] = field(default_factory=list)
    status: str = "queued"  # queued | running | done | error
    stage: Optional[str] = None
    stage_index: int = -1
    started_at: float = field(default_factory=time.monotonic)
    finished_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    # Published mid-run when a pipeline can produce a usable answer before it
    # finishes — the news pipeline shows a verdict while the review stage is
    # still auditing it.
    partial_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    task: Optional[asyncio.Task] = None
    # Steps differ from stages in that nobody declares them up front. A chat
    # turn decides what to run as it runs, so the list grows and individual
    # entries change status in place; `stages` stays empty for those jobs and
    # `steps` stays empty for the pipelines that declare their stages.
    steps: List[Dict[str, Any]] = field(default_factory=list)
    # Who may read this job. A report is public; a chat job id is effectively a
    # bearer token for someone's question and its answer. Never serialised.
    owner_id: Optional[str] = None

    @property
    def timeframe(self) -> str:
        """Back-compat alias: for a report job the key *is* the timeframe."""
        return self.key

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    def elapsed_seconds(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return round(end - self.started_at, 1)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise for the API — `task` and monotonic clocks stay internal."""
        return {
            "job_id": self.id,
            "key": self.key,
            "kind": self.kind,
            # Kept so existing report clients keep reading the field they know.
            "timeframe": self.key,
            "status": self.status,
            "stage": self.stage,
            "stage_index": self.stage_index,
            "stages": self.stages,
            "steps": self.steps,
            "elapsed_seconds": self.elapsed_seconds(),
            "result": self.result,
            "partial_result": self.partial_result,
            "error": self.error,
        }


# A runner receives progress callbacks and returns the finished result.
StageCallback = Callable[[str], None]
PartialCallback = Callable[[Dict[str, Any]], None]
# Upsert by `step["id"]`: one primitive covers both appending a step nobody knew
# about and flipping an existing one from running to done.
StepCallback = Callable[[Dict[str, Any]], None]


@dataclass(frozen=True)
class JobControls:
    """
    The progress handles a runner is given.

    Bundled into one object rather than passed positionally because the set has
    now grown twice; a third callback should not mean editing every runner
    signature in the codebase again.
    """

    on_stage: StageCallback
    on_partial: PartialCallback
    on_step: StepCallback


JobRunner = Callable[[JobControls], Awaitable[Dict[str, Any]]]

_jobs: Dict[str, Job] = {}
_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    """
    Lazily build the lock so it binds to the running loop.

    On Python 3.9 `asyncio.Lock()` captures the current event loop at
    construction; creating it at import time would bind it to whatever loop
    existed before the server started.
    """
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def _prune() -> None:
    """Drop finished jobs past their retention window."""
    now = time.monotonic()
    expired = [
        job_id
        for job_id, job in _jobs.items()
        if job.finished_at is not None
        and now - job.finished_at > RETENTION_BY_KIND.get(job.kind, JOB_RETENTION_SECONDS)
    ]
    for job_id in expired:
        del _jobs[job_id]


async def _run(job: Job, runner: JobRunner) -> None:
    """Execute the pipeline, recording progress on the job as it advances."""
    stage_index = {stage["key"]: i for i, stage in enumerate(job.stages)}

    def on_stage(key: str) -> None:
        job.stage = key
        job.stage_index = stage_index.get(key, job.stage_index)

    def on_partial(result: Dict[str, Any]) -> None:
        job.partial_result = result

    def on_step(step: Dict[str, Any]) -> None:
        """Upsert by id, so a step can be announced and then updated in place."""
        step_id = step.get("id")
        for index, existing in enumerate(job.steps):
            if existing.get("id") == step_id:
                job.steps[index] = step
                return
        job.steps.append(step)

    job.status = "running"
    try:
        job.result = await runner(JobControls(on_stage, on_partial, on_step))
        job.status = "done"
        job.stage_index = len(job.stages)
    except asyncio.CancelledError:
        job.status = "error"
        job.error = f"{job.kind.capitalize()} generation was cancelled."
        raise
    except Exception as e:  # noqa: BLE001 — the real message is what the UI shows
        logger.exception("%s job failed for key '%s'", job.kind, job.key)
        job.status = "error"
        job.error = str(e) or e.__class__.__name__
    finally:
        job.finished_at = time.monotonic()


async def start(
    key: str,
    kind: str,
    stages: List[Dict[str, str]],
    runner: JobRunner,
    *,
    owner_id: Optional[str] = None,
) -> Job:
    """
    Start a job, or return the one already running for this (kind, key).

    Single-flight matters for the pipelines: a refreshed page, a double-clicked
    button or a second click on the same headline must not fan out into several
    concurrent LLM runs, and all of those callers want the same artifact.

    A chat turn never does. Two identical questions are two questions, and
    merging them would silently drop a message — so chat passes a key that
    cannot collide and the loop below is a no-op for it.
    """
    async with _get_lock():
        _prune()

        for job in _jobs.values():
            if job.kind == kind and job.key == key and job.is_active:
                logger.info("Reusing in-flight %s job %s for '%s'", kind, job.id, key)
                return job

        job = Job(id=uuid.uuid4().hex, key=key, kind=kind, stages=list(stages), owner_id=owner_id)
        _jobs[job.id] = job
        job.task = asyncio.create_task(_run(job, runner))
        return job


async def start_job(timeframe: str, user_id: Optional[str] = None) -> Job:
    """Start (or re-attach to) the market report job for this horizon."""

    async def runner(controls: JobControls) -> Dict[str, Any]:
        return await generate_market_report(timeframe, user_id=user_id, on_stage=controls.on_stage)

    return await start(timeframe, KIND_REPORT, STAGES, runner)


async def get_job(job_id: str) -> Optional[Job]:
    async with _get_lock():
        _prune()
        return _jobs.get(job_id)


async def cancel_job(job_id: str) -> Optional[Job]:
    """
    Stop an in-flight job, returning it once it has actually settled.

    Awaited rather than fired and forgotten so the caller's response already
    reflects the final state — a client that polls the active list right after
    cancelling must not still see the run it just stopped.
    """
    async with _get_lock():
        _prune()
        job = _jobs.get(job_id)

    if job is None:
        return None
    if not job.is_active or job.task is None:
        return job

    job.task.cancel()
    try:
        await job.task
    except asyncio.CancelledError:
        # Expected: this is our own cancellation landing, not the caller's.
        pass
    except Exception:  # noqa: BLE001 — `_run` already recorded it on the job
        pass

    # A cancellation that lands before the task's first line leaves `_run`
    # never having run at all — so its `finally`, which is what stamps
    # `finished_at`, never runs either. The job then stays `queued` forever:
    # `is_active` keeps reporting it to `active_jobs`, and `_prune` skips it
    # because pruning is keyed on `finished_at`. It is a small leak and a
    # confusing one, and it is exactly the case a user pressing stop the moment
    # they see the spinner produces.
    if job.finished_at is None:
        job.status = "error"
        job.error = f"{job.kind.capitalize()} generation was cancelled."
        job.finished_at = time.monotonic()

    return job


async def active_jobs() -> List[Job]:
    """In-flight jobs — lets a returning client re-attach to a running report."""
    async with _get_lock():
        _prune()
        return [job for job in _jobs.values() if job.is_active]
