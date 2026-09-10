"""
Tests for which background jobs `start_scheduler` actually registers.

This file exists because of a bug that no other kind of test could have caught.
`services/bist/ownership/board.py` serves its board with `stale` set once the
stored copy passes `BOARD_STALE_AFTER_SECONDS`, and it was written expecting a
nightly rebuild to clear the flag. That rebuild was never added to the
scheduler: `ensure_board()` ran once at boot and `refresh_board()` only behind
the admin button, so every deployment up longer than twenty-six hours served a
permanently stale holdings board. Nothing failed, nothing logged, and the two
sibling jobs for the *global* ownership board made the omission look like a
pair rather than an absence.

A missing job is invisible to every other test in this suite — the service is
tested, the router is tested, and both pass whether or not anything ever calls
them on a timer. The assertion has to be made against the registration itself.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from services import scheduler_service


@pytest.fixture
def registered_jobs(monkeypatch):
    """
    Run `start_scheduler` against a throwaway scheduler and hand back its jobs.

    The module global is replaced rather than the real one reused: these tests
    must not leave jobs on the scheduler the application will start, and a
    second run against a live one would be a no-op anyway because
    `start_scheduler` guards on `scheduler.running`.

    `start` is stubbed because `AsyncIOScheduler.start()` wants a running event
    loop and these are synchronous tests. Everything under test happens in the
    `add_job` calls before it.
    """
    fake = AsyncIOScheduler()
    monkeypatch.setattr(fake, "start", lambda *a, **kw: None)
    monkeypatch.setattr(scheduler_service, "scheduler", fake)

    scheduler_service.start_scheduler()
    return {job.id: job for job in fake.get_jobs()}


def test_bist_ownership_board_has_a_refresh_job(registered_jobs):
    """The regression: the BIST board's rebuild must be on a timer at all."""
    assert "bist_ownership_refresh_job" in registered_jobs


def test_both_ownership_boards_are_scheduled(registered_jobs):
    """
    The two boards are separate artefacts with separate upstreams, and the
    global one having a job says nothing about the Turkish one. Asserted as a
    pair because that is the shape the bug hid in.
    """
    assert "ownership_refresh_job" in registered_jobs
    assert "bist_ownership_refresh_job" in registered_jobs


def test_bist_ownership_refreshes_more_often_than_the_board_goes_stale(
    registered_jobs,
):
    """
    The cadence is the point, not the cron expression.

    `BOARD_STALE_AFTER_SECONDS` is a day plus two hours of slack, so a run that
    starts late still clears the flag before the next is due. Any schedule
    sparser than that — someone "tidying" this to weekly, or to a day-of-week
    cron — puts the board back to permanently stale, which is exactly the state
    this job was added to end.
    """
    from services.bist.ownership.board import BOARD_STALE_AFTER_SECONDS

    trigger = registered_jobs["bist_ownership_refresh_job"].trigger
    tz = ZoneInfo(settings.BIST_OWNERSHIP_REFRESH_TIMEZONE)

    # Two consecutive fires, taken from the trigger itself rather than from the
    # settings, so this still holds if the schedule is expressed differently.
    first = trigger.get_next_fire_time(None, datetime(2026, 3, 1, tzinfo=tz))
    second = trigger.get_next_fire_time(first, first)

    assert first is not None and second is not None
    assert (second - first).total_seconds() <= BOARD_STALE_AFTER_SECONDS


def test_bist_ownership_fires_at_the_configured_local_hour(registered_jobs):
    """
    The hour is a claim about Istanbul, and the container clock is UTC.

    Stated against a March date on purpose: Turkey holds UTC+3 year round, so a
    trigger that had silently fallen back to a naive hour would fire at 03:00
    UTC here and be off by three, not zero.
    """
    trigger = registered_jobs["bist_ownership_refresh_job"].trigger
    tz = ZoneInfo(settings.BIST_OWNERSHIP_REFRESH_TIMEZONE)

    fire = trigger.get_next_fire_time(None, datetime(2026, 3, 1, tzinfo=tz))

    assert fire is not None
    assert fire.astimezone(tz).hour == settings.BIST_OWNERSHIP_REFRESH_HOUR


def test_bist_ownership_job_does_not_stack_runs(registered_jobs):
    """
    The walk is minutes long and `refresh_board` serialises itself against the
    admin button with a module lock. Without `max_instances=1` a second fire
    would not race — it would queue behind the first and start an identical
    walk the moment it finished.
    """
    job = registered_jobs["bist_ownership_refresh_job"]

    assert job.max_instances == 1
    assert job.coalesce is True
