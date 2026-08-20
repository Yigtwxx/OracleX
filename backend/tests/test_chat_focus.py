"""
Whether a follow-up knows what it is following up on.

The bug these pin down: `resolve_query_assets` reads one message, so "BTC
nasıl?" → "peki RSI'ı?" resolved nothing on the second turn, every asset tool
was withheld, and the answer was about the market in general.

`test_an_asset_named_only_by_the_assistant_is_never_inherited` is the one to
argue with before changing anything here. It is not a quality test.
"""

import pytest

from services import chat_focus


def turn(role: str, content: str) -> dict:
    return {"role": role, "content": content}


BTC_HISTORY = [
    turn("user", "BTC nasıl?"),
    turn("assistant", "BTC $64,200 civarında; SOL ve AVAX bu haftada geride kaldı."),
]


@pytest.mark.asyncio
async def test_a_message_that_names_an_asset_needs_no_history():
    state = await chat_focus.resolve_state("BTC nasıl?", [])
    assert state.symbols == ("BTC",)
    assert state.inherited == ()


@pytest.mark.asyncio
async def test_a_follow_up_that_names_nothing_inherits_the_subject():
    """The original bug, in one line."""
    state = await chat_focus.resolve_state("peki RSI'ı?", BTC_HISTORY)
    assert state.symbols == ("BTC",)
    assert state.inherited == ("BTC",)


@pytest.mark.asyncio
async def test_an_inherited_turn_says_so():
    """
    The answer is about an asset the question did not name. That has to be
    visible — to the model, through the focus block, and to the user, through
    the badge — or the turn is confidently answering an unasked question.
    """
    state = await chat_focus.resolve_state("peki RSI'ı?", BTC_HISTORY)
    described = chat_focus.describe(state)
    assert "BTC" in described
    assert "carried over" in described


@pytest.mark.asyncio
async def test_an_asset_named_only_by_the_assistant_is_never_inherited():
    """
    Assistant prose routinely names comparables. `chat_planner._coerce_value`
    refuses any symbol the model proposes that is not already in the focus, so
    inheriting from assistant text would let the model's own output widen the
    set it is checked against.

    The history here has the assistant naming SOL and AVAX and the user naming
    neither. Neither may appear.
    """
    history = [
        turn("user", "Piyasa nasıl?"),
        turn("assistant", "SOL ve AVAX bu hafta en çok düşenler arasında."),
    ]
    state = await chat_focus.resolve_state("peki seviyeleri?", history)
    assert "SOL" not in state.symbols
    assert "AVAX" not in state.symbols


@pytest.mark.asyncio
async def test_naming_a_new_asset_replaces_the_old_one():
    state = await chat_focus.resolve_state("SOL nasıl?", BTC_HISTORY)
    assert state.symbols == ("SOL",)
    assert state.inherited == ()


@pytest.mark.asyncio
async def test_an_additive_opener_adds_rather_than_replaces():
    """ "peki ETH?" is still partly about BTC; "ETH nasıl?" is not."""
    state = await chat_focus.resolve_state("peki ETH?", BTC_HISTORY)
    assert state.symbols[0] == "ETH"
    assert "BTC" in state.symbols
    assert state.inherited == ("BTC",)


@pytest.mark.asyncio
async def test_a_conceptual_question_does_not_inherit():
    """
    "What is a funding rate" asked after three turns about BTC is still not a
    question about BTC — and dragging BTC in would pull asset tools onto a turn
    that needs none of them.
    """
    state = await chat_focus.resolve_state("funding rate nedir?", BTC_HISTORY)
    assert state.symbols == ()
    assert state.intent == "conceptual"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    ["piyasa genel olarak nasıl?", "how is the market overall?", "altcoinler ne durumda?"],
)
async def test_a_market_wide_question_does_not_inherit(message):
    state = await chat_focus.resolve_state(message, BTC_HISTORY)
    assert state.symbols == ()


@pytest.mark.asyncio
async def test_crossing_asset_classes_clears_the_focus():
    """A question that has moved to equities is not a follow-up about a coin."""
    state = await chat_focus.resolve_state("nasdaq hisseleri nasıl?", BTC_HISTORY)
    assert state.symbols == ()
    assert state.switched is True


@pytest.mark.asyncio
async def test_a_timeframe_is_read_off_the_message():
    state = await chat_focus.resolve_state("4 saatlik grafiği ne diyor?", BTC_HISTORY)
    assert state.symbols == ("BTC",)
    assert state.timeframe == "4h"


@pytest.mark.asyncio
async def test_a_timeframe_is_inherited_with_the_subject():
    """Same subject, no new timeframe named: still the same chart."""
    history = [
        turn("user", "BTC'nin 1 saatlik grafiği nasıl?"),
        turn("assistant", "..."),
    ]
    state = await chat_focus.resolve_state("peki hacim?", history)
    assert state.symbols == ("BTC",)
    assert state.timeframe == "1h"


@pytest.mark.asyncio
async def test_inheritance_does_not_reach_past_the_lookback_window():
    """
    A question that still has not named an asset after several turns is usually
    about something else. Carrying a stale symbol is worse than losing one,
    because the answer is confidently about the wrong thing.
    """
    history = [turn("user", "BTC nasıl?")] + [
        turn("user", f"devam et {i}") for i in range(chat_focus.FOCUS_LOOKBACK_TURNS + 1)
    ]
    state = await chat_focus.resolve_state("peki?", history)
    assert state.symbols == ()


@pytest.mark.asyncio
async def test_the_focus_is_capped():
    history = [
        turn("user", "BTC nasıl?"),
        turn("user", "ETH ve SOL nasıl?"),
    ]
    state = await chat_focus.resolve_state("peki AVAX?", history)
    assert len(state.symbols) <= chat_focus.MAX_FOCUS_SYMBOLS


@pytest.mark.asyncio
async def test_an_override_goes_through_the_registry_like_anything_else():
    """
    The override is a string from a client. It reaches the symbol set only by
    resolving, never by assignment — otherwise the focus badge would become a
    way to put an arbitrary ticker into the set `_coerce_value` validates
    against.
    """
    state = await chat_focus.resolve_state("nasıl gidiyor?", [], override="ETH")
    assert state.symbols == ("ETH",)

    junk = await chat_focus.resolve_state("nasıl gidiyor?", [], override="NOTATICKER!!")
    assert junk.symbols == ()


@pytest.mark.asyncio
async def test_no_history_is_not_an_error():
    for history in (None, [], [turn("assistant", "merhaba")]):
        state = await chat_focus.resolve_state("BTC nasıl?", history)
        assert state.symbols == ("BTC",)


@pytest.mark.asyncio
async def test_describe_says_something_useful_even_with_no_asset():
    state = await chat_focus.resolve_state("piyasa nasıl?", [])
    assert chat_focus.describe(state).strip()
