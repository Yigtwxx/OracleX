"""
Tests for report job scheduling and the read paths that must never generate.

The regression these guard is the Analysis page opening straight into a failed
report: reads used to trigger a synchronous LLM run, so a slow or unavailable
provider surfaced as a fake "unavailable" report body.
"""

import asyncio

import pytest

from services import analysis_jobs, analysis_service


@pytest.fixture(autouse=True)
def clear_jobs():
    """Job state and its lock are module-level, so isolate each test from the last."""
    analysis_jobs._jobs.clear()
    analysis_jobs._lock = None
    yield
    analysis_jobs._jobs.clear()
    analysis_jobs._lock = None


@pytest.fixture
async def slow_report(monkeypatch):
    """
    A report pipeline that runs long enough to observe an in-flight job.

    Async so the events bind to the test's own event loop.
    """
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_generate(timeframe, user_id=None, on_stage=None):
        if on_stage:
            on_stage("collecting")
        started.set()
        await release.wait()
        return {
            "content": f"{timeframe} report",
            "timestamp": "2026-01-01T00:00:00",
            "stale": False,
        }

    monkeypatch.setattr(analysis_jobs, "generate_market_report", fake_generate)
    return started, release


async def test_start_job_same_timeframe_twice_returns_same_job(slow_report):
    started, release = slow_report

    first = await analysis_jobs.start_job("daily")
    await started.wait()
    second = await analysis_jobs.start_job("daily")

    assert second.id == first.id, "A second request must join the in-flight job, not start another"

    release.set()
    await first.task


async def test_start_job_different_timeframes_run_independently(slow_report):
    started, release = slow_report

    daily = await analysis_jobs.start_job("daily")
    await started.wait()
    weekly = await analysis_jobs.start_job("weekly")

    assert daily.id != weekly.id, "Different horizons are separate jobs"

    release.set()
    await asyncio.gather(daily.task, weekly.task)


async def test_job_reports_stage_progress_then_result(slow_report):
    started, release = slow_report

    job = await analysis_jobs.start_job("daily")
    await started.wait()

    assert job.status == "running", f"Expected running, got {job.status}"
    assert job.stage == "collecting", f"Expected the collecting stage, got {job.stage}"

    release.set()
    await job.task

    assert job.status == "done", f"Expected done, got {job.status}"
    assert job.result["content"] == "daily report", (
        "The finished report must be attached to the job"
    )


async def test_job_failure_records_real_error_message(monkeypatch):
    async def failing(timeframe, user_id=None, on_stage=None):
        raise RuntimeError("no LLM provider could serve it")

    monkeypatch.setattr(analysis_jobs, "generate_market_report", failing)

    job = await analysis_jobs.start_job("daily")
    await job.task

    assert job.status == "error", f"Expected error, got {job.status}"
    assert "no LLM provider" in job.error, (
        f"The provider error must survive to the client: {job.error}"
    )
    assert job.result is None, "A failed job must not carry a fabricated report"


async def test_active_jobs_lists_in_flight_report_then_drops_it(slow_report):
    """
    What lets a returning page find the run it started.

    The job id only lives in page state, so leaving the Analysis tab loses it
    while the run continues; this listing is how the page rediscovers it.
    """
    started, release = slow_report

    job = await analysis_jobs.start_job("daily")
    await started.wait()

    active = await analysis_jobs.active_jobs()
    assert [j.id for j in active] == [job.id], (
        f"The running report must be listed, got {[j.id for j in active]}"
    )

    release.set()
    await job.task

    assert await analysis_jobs.active_jobs() == [], "A finished job is no longer in flight"


async def test_cancel_job_stops_the_run_and_clears_it_from_active(slow_report):
    started, _ = slow_report

    job = await analysis_jobs.start_job("daily")
    await started.wait()

    cancelled = await analysis_jobs.cancel_job(job.id)

    assert cancelled is not None and cancelled.id == job.id, "Cancel must return the job it stopped"
    assert cancelled.status == "error", f"Expected a settled job, got {cancelled.status}"
    assert "cancelled" in (cancelled.error or "").lower(), (
        f"The reason must say it was cancelled, got {cancelled.error!r}"
    )
    assert cancelled.result is None, "A cancelled run must not carry a report"
    assert await analysis_jobs.active_jobs() == [], (
        "A cancelled job must be gone from the active list by the time cancel returns"
    )


async def test_cancel_job_unknown_id_returns_none():
    assert await analysis_jobs.cancel_job("does-not-exist") is None, (
        "Cancelling an expired job must not resolve to something"
    )


async def test_get_job_unknown_id_returns_none():
    assert await analysis_jobs.get_job("does-not-exist") is None, "Unknown ids must not resolve"


def test_get_report_with_no_stored_report_does_not_generate(monkeypatch, tmp_path):
    """The core regression: reading a report must never call an LLM."""
    monkeypatch.setattr(analysis_service, "REPORTS_FILE", str(tmp_path / "reports.json"))

    def explode(*args, **kwargs):
        raise AssertionError("get_report must not trigger generation")

    monkeypatch.setattr(analysis_service, "generate_market_report", explode)

    report = analysis_service.get_report("daily")

    assert report["content"] is None, f"Expected an empty report, got {report['content']!r}"
    assert report["stale"] is True, "A missing report is stale by definition"


def test_get_report_summaries_covers_every_timeframe(monkeypatch, tmp_path):
    monkeypatch.setattr(analysis_service, "REPORTS_FILE", str(tmp_path / "reports.json"))

    summaries = analysis_service.get_report_summaries()

    assert set(summaries) == {"daily", "weekly", "monthly"}, (
        f"Unexpected horizons: {set(summaries)}"
    )
    assert all(s["generated_at"] is None for s in summaries.values()), (
        "Nothing is stored yet, so no horizon should claim a generation time"
    )
