"""
Tests for the startup readiness gate.

The frontend holds its first paint on this state machine, so the cases that
matter are the ones where it could hold forever: an optional step that never
succeeds, a required step that fails, and a warm-up that overruns its deadline.
"""

import pytest

from services.readiness import OPTIONAL, REQUIRED, Readiness


@pytest.fixture
def r() -> Readiness:
    """A registry with one required and one optional step, nothing run yet."""
    registry = Readiness(deadline_seconds=60.0)
    registry.register("registry", "Varlık kaydı", REQUIRED)
    registry.register("news", "Haber akışı", OPTIONAL)
    return registry


# ── the happy path ───────────────────────────────────────────────────────────


def test_no_steps_registered_is_not_ready():
    """An empty registry means startup has not begun, not that it is done."""
    assert Readiness().ready is False


def test_not_ready_while_steps_are_pending(r):
    assert r.ready is False


def test_ready_as_soon_as_the_required_steps_are_done(r):
    """
    An optional step that is merely slow must not hold the gate.

    This used to assert the opposite. Production disproved it: the news warm-up
    measured 206s against a 60s deadline, so every cold start sat on the splash
    for the full minute and then opened *anyway* with news still running — the
    same screen it could have shown at four seconds, an unexplained 56 seconds
    later. Waiting bought nothing but the wait.
    """
    r.succeed("registry")
    assert r.ready is True
    assert r.degraded is False, "Optional work still in flight is not a degradation"


def test_ready_once_all_steps_succeed(r):
    r.succeed("registry")
    r.succeed("news")
    assert r.ready is True
    assert r.degraded is False


def test_a_slow_required_step_still_holds_the_gate(r):
    """The gate is not gone, just narrowed to what the app cannot open without."""
    r.start("registry")
    r.succeed("news")
    assert r.ready is False


# ── failures ─────────────────────────────────────────────────────────────────


def test_optional_failure_still_opens_the_screen(r):
    r.succeed("registry")
    r.fail("news", RuntimeError("feed down"))
    assert r.ready is True, "An optional failure is an answer, not a reason to wait"
    assert r.degraded is True


def test_required_failure_keeps_the_gate_shut(r):
    r.fail("registry", RuntimeError("no universe"))
    r.succeed("news")
    assert r.ready is False
    assert r.blocked is True


def test_blocked_is_false_while_a_required_step_is_merely_slow(r):
    r.start("registry")
    assert r.blocked is False


def test_failure_reason_is_recorded_for_the_ui(r):
    r.fail("news", RuntimeError("feed down"))
    step = next(s for s in r.snapshot()["steps"] if s["key"] == "news")
    assert step["state"] == "failed"
    assert "feed down" in step["error"]


def test_failure_reason_names_the_type_when_the_message_is_empty(r):
    """A bare ConnectError stringifies to nothing — the type is the only signal."""
    r.fail("news", ConnectionError())
    step = next(s for s in r.snapshot()["steps"] if s["key"] == "news")
    assert step["error"] == "ConnectionError"


def test_failure_reason_is_bounded(r):
    r.fail("news", RuntimeError("x" * 5000))
    step = next(s for s in r.snapshot()["steps"] if s["key"] == "news")
    assert len(step["error"]) < 260, "An unbounded upstream body must not reach the browser"


# ── the deadline ─────────────────────────────────────────────────────────────


def test_deadline_opens_the_screen_on_a_hung_step():
    registry = Readiness(deadline_seconds=0.0)
    registry.register("news", "Haber akışı", OPTIONAL)
    assert registry.ready is True, "A hung optional step must not shut the UI forever"
    assert registry.degraded is True


def test_deadline_overrides_even_a_required_step():
    """Better a degraded screen than none at all."""
    registry = Readiness(deadline_seconds=0.0)
    registry.register("registry", "Varlık kaydı", REQUIRED)
    assert registry.ready is True
    assert registry.degraded is True


def test_deadline_not_reached_holds_the_gate(r):
    assert r.expired is False
    assert r.ready is False


# ── the payload the frontend reads ───────────────────────────────────────────


def test_snapshot_lists_steps_in_registration_order(r):
    assert [s["key"] for s in r.snapshot()["steps"]] == ["registry", "news"]


def test_snapshot_reports_the_deadline_budget(r):
    assert r.snapshot()["deadline_ms"] == 60_000


def test_snapshot_carries_no_error_for_a_healthy_step(r):
    r.succeed("registry")
    step = next(s for s in r.snapshot()["steps"] if s["key"] == "registry")
    assert step["error"] is None


def test_duration_is_reported_once_a_step_finishes(r):
    r.start("registry")
    r.succeed("registry")
    step = next(s for s in r.snapshot()["steps"] if s["key"] == "registry")
    assert step["duration_ms"] is not None and step["duration_ms"] >= 0


def test_duration_is_absent_while_a_step_is_still_running(r):
    r.start("registry")
    step = next(s for s in r.snapshot()["steps"] if s["key"] == "registry")
    assert step["duration_ms"] is None


def test_unknown_step_keys_are_ignored(r):
    """A typo in a call site must not crash startup."""
    r.start("nope")
    r.succeed("nope")
    r.fail("nope", RuntimeError("boom"))
    assert len(r.snapshot()["steps"]) == 2
