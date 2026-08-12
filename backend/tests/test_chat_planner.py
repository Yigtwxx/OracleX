"""
Reading a plan out of whatever a small local model actually emitted.

Ollama's `format: "json"` guarantees the reply parses. It guarantees nothing
about the shape, and every case below is a shape a small model produces in
practice: the list under a different key, a step as a bare string, args as a
JSON string, a tool name that is almost right, a ticker nobody mentioned.

The property that matters most is the last section: whatever goes wrong, the
turn ends up with the fixed pipeline rather than with nothing.
"""

import pytest

from services import chat_planner, chat_tools
from services.chat_service import QueryFocus

CRYPTO = QueryFocus(symbols=("BTC",), asset_type="crypto")
PAIR = QueryFocus(symbols=("BTC", "ETH"), asset_type="crypto")
MESSAGE = "what is happening with BTC today"


def _catalogue(focus=CRYPTO, message=MESSAGE):
    return chat_tools.available_tools(message, focus)


def _parse(raw, focus=CRYPTO, message=MESSAGE):
    return chat_planner.parse_plan(raw, _catalogue(focus, message), focus, message)


# ── the shape the prompt asks for ────────────────────────────────────────────


def test_the_documented_shape_parses():
    steps = _parse('{"steps": [{"tool": "web_search", "args": {"query": "BTC ETF"}}]}')

    assert [(s.tool, s.args) for s in steps] == [("web_search", {"query": "BTC ETF"})]


def test_step_order_is_preserved():
    """Later steps consume what earlier ones found, so order is meaning."""
    steps = _parse(
        '{"steps": [{"tool": "web_search", "args": {"query": "x"}}, {"tool": "read_page"}]}'
    )

    assert [s.tool for s in steps] == ["web_search", "read_page"]


# ── shapes it does not ask for ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        '{"plan": [{"tool": "web_search", "args": {"query": "x"}}]}',
        '{"tools": [{"tool": "web_search", "args": {"query": "x"}}]}',
        '{"actions": [{"tool": "web_search", "args": {"query": "x"}}]}',
        '[{"tool": "web_search", "args": {"query": "x"}}]',
        '{"tool": "web_search", "args": {"query": "x"}}',
        '{"steps": [{"name": "web_search", "arguments": {"query": "x"}}]}',
        'Here is the plan: {"steps": [{"tool": "web_search", "args": {"query": "x"}}]} Hope that helps!',
    ],
)
def test_the_list_is_found_wherever_the_model_put_it(raw):
    steps = _parse(raw)

    assert [s.tool for s in steps] == ["web_search"]


def test_args_supplied_as_a_json_string_are_reparsed():
    steps = _parse('{"steps": [{"tool": "web_search", "args": "{\\"query\\": \\"BTC\\"}"}]}')

    assert steps[0].args["query"] == "BTC"


def test_a_bare_string_is_treated_as_a_tool_name():
    steps = _parse('{"steps": ["asset_technicals"]}')

    assert [s.tool for s in steps] == ["asset_technicals"]


def test_args_that_are_not_an_object_are_discarded_not_fatal():
    steps = _parse('{"steps": [{"tool": "asset_technicals", "args": ["BTC"]}]}')

    assert [s.tool for s in steps] == ["asset_technicals"]


# ── tool names ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,expected",
    [
        ("web_search", "web_search"),
        ("Web Search", "web_search"),
        ("web-search", "web_search"),
        ("search", "web_search"),
        ("technicals", "asset_technicals"),
        ("chart", "read_chart"),
        ("reddit", "social_search"),
    ],
)
def test_names_resolve_exactly_then_loosely_then_by_alias(name, expected):
    raw = f'{{"steps": [{{"tool": "{name}", "args": {{"query": "x", "symbol": "BTC"}}}}]}}'
    steps = _parse(raw)

    assert [s.tool for s in steps] == [expected]


def test_an_unknown_tool_is_dropped_not_guessed_at():
    """A wrong tool costs a real thirty seconds; there is no fuzzy matching."""
    steps = _parse('{"steps": [{"tool": "quantum_oracle"}, {"tool": "asset_technicals"}]}')

    assert [s.tool for s in steps] == ["asset_technicals"]


def test_a_tool_withheld_for_this_question_cannot_be_planned():
    """`available_tools` is the gate; the planner never sees the rest."""
    steps = _parse(
        '{"steps": [{"tool": "compare_assets", "args": {"symbol_a": "BTC", "symbol_b": "ETH"}}]}',
        focus=CRYPTO,  # only one asset resolved
    )

    assert steps == []


# ── arguments ────────────────────────────────────────────────────────────────


def test_a_hallucinated_ticker_never_reaches_a_tool():
    """The exchange APIs must only ever see something the question resolved to."""
    steps = _parse('{"steps": [{"tool": "asset_technicals", "args": {"symbol": "DOGE"}}]}')

    assert steps[0].args.get("symbol") is None


def test_a_resolved_ticker_is_kept_and_normalised():
    steps = _parse('{"steps": [{"tool": "asset_technicals", "args": {"symbol": "$btc"}}]}')

    assert steps[0].args["symbol"] == "BTC"


def test_unknown_argument_keys_are_dropped():
    steps = _parse(
        '{"steps": [{"tool": "web_search", "args": {"query": "x", "temperature": 0.9}}]}'
    )

    assert steps[0].args == {"query": "x"}


def test_integers_are_clamped_to_the_declared_range():
    steps = _parse(
        '{"steps": [{"tool": "read_chart", "args": {"symbol": "BTC", "lookback": 9999}}]}'
    )

    assert steps[0].args["lookback"] == 200


def test_an_enum_is_matched_case_insensitively_and_otherwise_dropped():
    ok = _parse('{"steps": [{"tool": "read_chart", "args": {"symbol": "BTC", "interval": "4H"}}]}')
    bad = _parse(
        '{"steps": [{"tool": "read_chart", "args": {"symbol": "BTC", "interval": "hourly"}}]}'
    )

    assert ok[0].args["interval"] == "4h"
    assert "interval" not in bad[0].args


def test_a_missing_required_argument_is_defaulted_from_the_question():
    steps = _parse('{"steps": [{"tool": "web_search"}]}')

    assert steps[0].args["query"] == MESSAGE


def test_a_required_argument_with_no_sensible_default_drops_the_step():
    steps = _parse('{"steps": [{"tool": "compare_assets"}]}', focus=PAIR)

    # symbol_a/symbol_b both default from focus.primary, which is the same value
    # for both — a comparison of an asset with itself is not worth running.
    assert steps[0].args["symbol_a"] == steps[0].args["symbol_b"] == "BTC"


# ── bounds ───────────────────────────────────────────────────────────────────


def test_the_plan_is_capped():
    inner = ",".join(f'{{"tool": "web_search", "args": {{"query": "q{i}"}}}}' for i in range(9))
    raw = f'{{"steps": [{inner}]}}'

    assert len(_parse(raw)) == chat_planner.MAX_PLAN_STEPS


def test_a_list_valued_argument_does_not_break_deduplication():
    """
    `social_search` takes a list of platforms, and a list cannot go in a set —
    the real model supplied one on its first run and the parser crashed.
    """
    raw = (
        '{"steps": [{"tool": "social_search", "args": '
        '{"query": "BTC", "platforms": ["reddit.com", "x.com"]}}]}'
    )

    steps = _parse(raw)

    assert steps[0].args["platforms"] == ["reddit.com", "x.com"]


def test_repeated_identical_steps_are_deduped():
    """Small models repeat themselves; running the same search twice is waste."""
    inner = ",".join(['{"tool": "web_search", "args": {"query": "same"}}'] * 3)
    raw = f'{{"steps": [{inner}]}}'

    assert len(_parse(raw)) == 1


def test_scrapes_are_capped_in_the_plan_as_well_as_the_executor():
    """A timeline should not display steps that were never going to run."""
    inner = ",".join(f'{{"tool": "read_page", "args": {{"rank": {i}}}}}' for i in range(1, 5))
    raw = f'{{"steps": [{{"tool": "web_search", "args": {{"query": "x"}}}}, {inner}]}}'

    steps = _parse(raw)

    assert sum(1 for s in steps if s.tool == "read_page") == chat_tools.MAX_SCRAPES_PER_TURN


# ── the fallback ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "I think we should search the web for BTC news.",
        "{}",
        '{"steps": []}',
        "[]",
        "null",
        '{"steps": [{"tool": "nonexistent"}]}',
        '{"steps": "web_search"}',
    ],
)
async def test_every_unusable_reply_falls_back_to_the_fixed_plan(monkeypatch, raw):
    """
    The floor. Whatever the model does, the turn gathers what it always did.
    """
    monkeypatch.setattr(chat_planner.settings, "CHAT_PLANNER_ENABLED", True)

    async def _reply(*_args, **_kwargs):
        return raw

    monkeypatch.setattr(chat_planner.llm, "generate", _reply)
    monkeypatch.setattr(chat_planner.llm, "provider_for", _none)

    steps = await chat_planner.plan_turn(MESSAGE, CRYPTO)
    tools = [s.tool for s in steps]

    assert tools == [s.tool for s in chat_tools.heuristic_plan(MESSAGE, CRYPTO)]
    assert "historical_precedent" in tools and "web_search" in tools


async def test_a_planner_that_raises_falls_back(monkeypatch):
    monkeypatch.setattr(chat_planner.settings, "CHAT_PLANNER_ENABLED", True)

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("provider is down")

    monkeypatch.setattr(chat_planner.llm, "generate", _boom)
    monkeypatch.setattr(chat_planner.llm, "provider_for", _none)

    steps = await chat_planner.plan_turn(MESSAGE, CRYPTO)

    assert [s.tool for s in steps] == [s.tool for s in chat_tools.heuristic_plan(MESSAGE, CRYPTO)]


async def test_the_planner_is_not_called_when_the_flag_is_off(monkeypatch):
    monkeypatch.setattr(chat_planner.settings, "CHAT_PLANNER_ENABLED", False)
    called = []

    async def _spy(*_args, **_kwargs):
        called.append(1)
        return '{"steps": []}'

    monkeypatch.setattr(chat_planner.llm, "generate", _spy)

    await chat_planner.plan_turn(MESSAGE, CRYPTO)

    assert called == []


async def test_a_greeting_is_not_worth_a_planner_call(monkeypatch):
    monkeypatch.setattr(chat_planner.settings, "CHAT_PLANNER_ENABLED", True)
    called = []

    async def _spy(*_args, **_kwargs):
        called.append(1)
        return '{"steps": []}'

    monkeypatch.setattr(chat_planner.llm, "generate", _spy)
    monkeypatch.setattr(chat_planner.llm, "provider_for", _none)

    await chat_planner.plan_turn("hi", CRYPTO)

    assert called == []


async def test_a_usable_plan_is_used(monkeypatch):
    """The whole point: a plan the fixed pipeline could never have produced."""
    monkeypatch.setattr(chat_planner.settings, "CHAT_PLANNER_ENABLED", True)

    async def _reply(*_args, **_kwargs):
        return '{"steps": [{"tool": "social_search", "args": {"query": "BTC"}}]}'

    monkeypatch.setattr(chat_planner.llm, "generate", _reply)
    monkeypatch.setattr(chat_planner.llm, "provider_for", _none)

    steps = await chat_planner.plan_turn(MESSAGE, CRYPTO)

    assert [s.tool for s in steps] == ["social_search"]


async def _none(*_args, **_kwargs):
    return None
