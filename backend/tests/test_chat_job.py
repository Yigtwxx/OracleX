"""
Running a chat turn as a job.

Three things separate a chat job from the report and news jobs it shares
machinery with, and each is asserted here: it must never be deduped, it must
not be readable by anyone but its owner, and its steps arrive one at a time
rather than being declared up front.
"""

import asyncio

import pytest

from services import analysis_jobs, chat_service, chat_tools
from services.chat_service import QueryFocus


@pytest.fixture(autouse=True)
def _clean_jobs():
    analysis_jobs._jobs.clear()
    yield
    analysis_jobs._jobs.clear()


async def _settle(job):
    if job.task:
        await asyncio.gather(job.task, return_exceptions=True)
    return job


# ── single-flight is defeated, deliberately ──────────────────────────────────


async def test_two_identical_chat_turns_get_two_jobs():
    """
    Two callers asking for the daily report want the same artifact. Two chat
    turns never are, even with identical text — keying on anything stable would
    silently merge a double-tap into one answer and drop a message.
    """

    async def runner(_controls):
        return {"response": "ok"}

    a = await analysis_jobs.start("k-a", analysis_jobs.KIND_CHAT, [], runner)
    b = await analysis_jobs.start("k-b", analysis_jobs.KIND_CHAT, [], runner)
    await _settle(a)
    await _settle(b)

    assert a.id != b.id


async def test_report_jobs_still_dedupe():
    """The behaviour chat opts out of has to keep working for everyone else."""
    started = []

    async def runner(_controls):
        started.append(1)
        await asyncio.sleep(0.05)
        return {"ok": True}

    first = await analysis_jobs.start("daily", analysis_jobs.KIND_REPORT, [], runner)
    second = await analysis_jobs.start("daily", analysis_jobs.KIND_REPORT, [], runner)

    assert first.id == second.id
    await _settle(first)
    assert len(started) == 1


# ── steps ────────────────────────────────────────────────────────────────────


async def test_steps_are_upserted_by_id_not_appended():
    """A step is announced when it starts and updated when it ends."""

    async def runner(controls):
        controls.on_step({"id": "0", "tool": "web_search", "status": "running"})
        controls.on_step({"id": "0", "tool": "web_search", "status": "done"})
        controls.on_step({"id": "1", "tool": "read_page", "status": "running"})
        return {"ok": True}

    job = await _settle(await analysis_jobs.start("k", analysis_jobs.KIND_CHAT, [], runner))

    assert [s["id"] for s in job.steps] == ["0", "1"]
    assert job.steps[0]["status"] == "done"


async def test_a_report_job_serialises_an_empty_step_list():
    """
    Back-compat. `useAnalysisJob` and the report UI read the same payload, and
    a missing key would break them where an empty list does not.
    """

    async def runner(_controls):
        return {"ok": True}

    job = await _settle(await analysis_jobs.start("daily", analysis_jobs.KIND_REPORT, [], runner))

    assert job.to_dict()["steps"] == []


async def test_owner_id_is_not_serialised():
    """It is an access-control field, not something to hand back to a client."""

    async def runner(_controls):
        return {"ok": True}

    job = await _settle(
        await analysis_jobs.start("k", analysis_jobs.KIND_CHAT, [], runner, owner_id="user-1")
    )

    assert job.owner_id == "user-1"
    assert "owner_id" not in job.to_dict()


def test_chat_jobs_are_retained_more_briefly_than_reports():
    """A chat answer is collected by the poll already running; a report is not."""
    chat = analysis_jobs.RETENTION_BY_KIND.get(analysis_jobs.KIND_CHAT)

    assert chat is not None
    assert chat < analysis_jobs.JOB_RETENTION_SECONDS


# ── the executor ─────────────────────────────────────────────────────────────


def _plan(*names):
    return [chat_tools.PlannedStep(n, {}) for n in names]


@pytest.fixture
def fake_tools(monkeypatch):
    """Replace the registry with tools whose behaviour the test dictates."""

    def install(**behaviours):
        registry = {}
        for name, (delay, result) in behaviours.items():

            async def run(_ctx, _delay=delay, _result=result, **_kwargs):
                if _delay:
                    await asyncio.sleep(_delay)
                if isinstance(_result, Exception):
                    raise _result
                return _result

            registry[name] = chat_tools.Tool(
                name=name,
                description=f"{name} description",
                args=(),
                run=run,
                timeout=5.0,
                label=f"Running {name}",
                priority=50,
            )
        monkeypatch.setattr(chat_tools, "REGISTRY", registry)
        return registry

    return install


def _ctx(message="what is going on"):
    return chat_tools.ToolContext(message=message, focus=QueryFocus(symbols=("BTC",)))


async def test_steps_are_reported_running_then_settled_in_plan_order(fake_tools):
    fake_tools(
        a=(0, chat_tools.ToolResult(block="A")),
        b=(0, chat_tools.ToolResult(block="B")),
    )
    seen = []

    await chat_service.run_plan(
        _ctx(), _plan("a", "b"), lambda s: seen.append((s["id"], s["status"]))
    )

    assert seen == [("0", "running"), ("0", "done"), ("1", "running"), ("1", "done")]


async def test_a_tool_that_raises_is_reported_failed_and_the_turn_continues(fake_tools):
    fake_tools(
        boom=(0, RuntimeError("upstream is down")),
        after=(0, chat_tools.ToolResult(block="still here")),
    )

    outcomes = await chat_service.run_plan(_ctx(), _plan("boom", "after"))

    assert [o.status for o in outcomes] == ["failed", "done"]


async def test_a_tool_that_finds_nothing_is_empty_not_failed(fake_tools):
    """
    The distinction the answer depends on: "searched and found nothing" is a
    gap to report, "was never consulted" is silence.
    """
    fake_tools(quiet=(0, chat_tools.ToolResult(ok=True, block="", detail="no results")))

    outcomes = await chat_service.run_plan(_ctx(), _plan("quiet"))

    assert outcomes[0].status == "empty"


async def test_an_unknown_tool_name_fails_that_step_alone(fake_tools):
    fake_tools(real=(0, chat_tools.ToolResult(block="A")))

    outcomes = await chat_service.run_plan(_ctx(), _plan("imaginary", "real"))

    assert [o.status for o in outcomes] == ["failed", "done"]


async def test_the_phase_budget_skips_the_rest_rather_than_starving_the_answer(fake_tools):
    """
    Checked before each step, not around the loop: the point is that the answer
    still gets its own budget, so what runs out is the evidence, not the reply.
    """
    # The first step eats almost the whole budget, leaving less than
    # MIN_STEP_BUDGET — the point at which starting another step would only
    # produce a step that times out immediately.
    fake_tools(
        slow=(1.2, chat_tools.ToolResult(block="A")),
        never=(0, chat_tools.ToolResult(block="B")),
        also_never=(0, chat_tools.ToolResult(block="C")),
    )

    outcomes = await chat_service.run_plan(_ctx(), _plan("slow", "never", "also_never"), budget=2.0)

    assert outcomes[0].status == "done"
    assert [o.status for o in outcomes[1:]] == ["skipped", "skipped"]
    assert "ran out of time" in outcomes[1].result.detail


async def test_a_skipped_step_is_still_reported_to_the_ui(fake_tools):
    fake_tools(slow=(1.2, chat_tools.ToolResult(block="A")), never=(0, chat_tools.ToolResult()))
    seen = []

    await chat_service.run_plan(
        _ctx(), _plan("slow", "never"), lambda s: seen.append((s["id"], s["status"])), budget=2.0
    )

    assert ("1", "skipped") in seen
    # A skipped step never announces itself as running — it did not run.
    assert ("1", "running") not in seen


async def test_the_snapshot_is_always_the_first_step(fake_tools):
    """No plan gets to omit the one source everything else is outranked by."""
    focus = QueryFocus(symbols=("BTC",))
    plan = [chat_tools.PlannedStep(chat_tools.PINNED_TOOL, {})] + chat_tools.heuristic_plan(
        "how is BTC", focus
    )

    assert plan[0].tool == chat_tools.PINNED_TOOL
    assert chat_tools.PINNED_TOOL not in [s.tool for s in plan[1:]]


# ── stopping a turn ──────────────────────────────────────────────────────────


async def test_a_running_turn_can_be_cancelled():
    """
    A turn can spend minutes gathering evidence. A question asked by mistake
    needs a way out that is not waiting for it to finish.
    """
    started = asyncio.Event()

    async def runner(_controls):
        started.set()
        await asyncio.sleep(30)
        return {"response": "never"}

    job = await analysis_jobs.start("k", analysis_jobs.KIND_CHAT, [], runner, owner_id="user-1")
    await started.wait()
    assert job.is_active

    cancelled = await analysis_jobs.cancel_job(job.id)

    assert cancelled is not None
    assert not cancelled.is_active
    assert cancelled.status == "error"


async def test_cancelling_settles_before_it_returns():
    """
    Awaited rather than fired and forgotten: a client that polls right after
    cancelling must not still see the run it just stopped.
    """

    async def runner(_controls):
        await asyncio.sleep(30)

    job = await analysis_jobs.start("k", analysis_jobs.KIND_CHAT, [], runner)
    cancelled = await analysis_jobs.cancel_job(job.id)

    assert cancelled.finished_at is not None
    assert job.id not in {j.id for j in await analysis_jobs.active_jobs()}


async def test_cancelling_a_finished_turn_is_not_an_error():
    """The poll and the stop button race; losing that race must be harmless."""

    async def runner(_controls):
        return {"response": "done already"}

    job = await _settle(await analysis_jobs.start("k", analysis_jobs.KIND_CHAT, [], runner))
    cancelled = await analysis_jobs.cancel_job(job.id)

    assert cancelled is not None
    assert cancelled.status == "done"


async def test_cancelling_an_unknown_turn_returns_none():
    assert await analysis_jobs.cancel_job("does-not-exist") is None
