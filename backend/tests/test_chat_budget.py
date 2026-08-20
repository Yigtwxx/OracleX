"""
The turn's time budget has to add up, and nothing in the type system says so.

The arithmetic broke silently once already: the module comment in
`chat_service` stated `TOOL_PHASE_BUDGET + CHAT_TIMEOUT < TURN_TIMEOUT` and left
out the planner call, which runs before either of them. The real worst case was
five seconds under the ceiling. These tests are the thing that notices when a
timeout is raised in isolation.
"""

import pytest

from services import chat_planner, chat_service, chat_tools

# Prompt assembly, snapshot rendering, the session-title task and scheduler
# jitter all happen outside the phases below. This is what is reserved for them.
OVERHEAD_ALLOWANCE = 20.0


def test_the_phases_fit_inside_the_turn():
    """Every phase that can spend wall clock, summed, against the outer bound."""
    phases = (
        chat_planner.PLANNER_TIMEOUT,
        chat_service.TOOL_PHASE_BUDGET,
        chat_service.REFLECT_TIMEOUT,
        chat_service.REFLECT_PHASE_BUDGET,
        chat_service.CHAT_TIMEOUT,
    )
    assert sum(phases) + OVERHEAD_ALLOWANCE <= chat_service.TURN_TIMEOUT, (
        f"phases sum to {sum(phases)}s, which leaves less than {OVERHEAD_ALLOWANCE}s "
        f"of the {chat_service.TURN_TIMEOUT}s turn for everything outside them"
    )


def test_the_answer_floor_leaves_room_for_a_full_answer():
    """A turn that spends every tool second must still be able to answer."""
    assert chat_service.ANSWER_FLOOR >= chat_service.CHAT_TIMEOUT / 3, (
        "ANSWER_FLOOR is what run_plan refuses to spend. Set below a third of "
        "CHAT_TIMEOUT it stops being a floor and becomes a rounding error."
    )


def test_reflection_is_not_started_without_room_to_act_on_it():
    """The reflection call is only worth making if a remedial step can follow."""
    assert chat_service.MIN_REFLECT_VALUE > 0
    assert chat_service.REFLECT_TIMEOUT + chat_service.MIN_REFLECT_VALUE < (
        chat_service.REFLECT_PHASE_BUDGET + chat_service.REFLECT_TIMEOUT
    )


def test_the_browser_gate_clears_a_browser_launch():
    """
    `BROWSER_MIN_REMAINING` has to exceed the browser rung's own timeout.

    Below that the gate would wave through a launch that cannot finish, which is
    the exact trade it exists to refuse.
    """
    from services import scrape_service

    assert chat_tools.BROWSER_MIN_REMAINING > scrape_service.BROWSER_TIMEOUT


@pytest.mark.parametrize(
    "tool",
    list(chat_tools.REGISTRY.values()),
    ids=lambda t: t.name,
)
def test_no_single_tool_can_consume_the_whole_tool_phase(tool):
    """
    A tool whose own timeout exceeds the phase budget can starve every later
    step on its own. The declared timeouts are worst cases and are allowed to
    add up to more than the phase, but no *one* of them may be the phase.
    """
    assert tool.timeout < chat_service.TOOL_PHASE_BUDGET, (
        f"{tool.name} declares {tool.timeout}s against a {chat_service.TOOL_PHASE_BUDGET}s phase"
    )
