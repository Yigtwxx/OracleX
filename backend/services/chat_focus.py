"""
What the conversation is about, not just what the last message said.

`chat_service.resolve_query_assets` reads one message. That is correct for the
first question and wrong for every follow-up: "BTC nasıl?" resolves BTC, and
then "peki RSI'ı?" resolves nothing at all — so `chat_tools.available_tools`
withholds every asset tool, no chart is read, and the model answers about the
market in general. The transcript was in the prompt the whole time; it was just
never consulted by anything that made a decision.

This module is that consultation. It replays the same registry-backed resolver
over the recent *user* messages and decides whether the current turn inherits
what it found.

Three properties are load-bearing:

* **Nothing is stored.** The client already sends the transcript on every turn,
  so the state is derived, not persisted. No new request field, no database
  column, no server-side session. It also means the state cannot be spoofed:
  every symbol in it came out of the same registry lookup that a first message
  would have gone through.
* **Assistant turns are never read.** An answer routinely names comparables —
  "BTC is outperforming SOL and AVAX" — and `chat_planner._coerce_value` refuses
  any symbol the model proposes that is not already in the focus. Inheriting
  from assistant text would let the model's own prose widen the set it is
  checked against. That is the one rule here that is a security property rather
  than a quality one.
* **Inheritance is the exception.** A message that names an asset replaces the
  focus; a message that changes subject clears it. Carrying a stale symbol into
  an unrelated question is a worse failure than losing one, because the answer
  is confidently about the wrong thing.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from services import chat_intent

logger = logging.getLogger(__name__)

# How far back a follow-up may reach for its subject. Four user messages is
# roughly two exchanges of "how is X" / "and its levels?" / "why?" — past that,
# a question that still has not named an asset is usually about something else.
FOCUS_LOOKBACK_TURNS = 4

# The focus never grows past this, however many turns contribute to it. Matches
# the cap `resolve_query_assets` already applies within a single message.
MAX_FOCUS_SYMBOLS = 3


@dataclass(frozen=True)
class ConversationState:
    """
    The subject of this turn, and where it came from.

    `explicit` and `inherited` are kept apart rather than merged into `focus`
    because the difference is worth telling the user and worth telling the
    model: an answer about an asset the current question did not name should say
    so, and the focus badge in the UI reads `inherited` to decide what to show.
    """

    focus: "object"  # QueryFocus — untyped here to avoid an import cycle
    intent: str
    explicit: Tuple[str, ...] = ()
    inherited: Tuple[str, ...] = ()
    timeframe: Optional[str] = None
    switched: bool = False

    @property
    def symbols(self) -> Tuple[str, ...]:
        return tuple(getattr(self.focus, "symbols", ()))

    @property
    def primary(self) -> Optional[str]:
        return self.symbols[0] if self.symbols else None


def _user_messages(history: Optional[List[Dict[str, str]]]) -> List[str]:
    """
    Recent user messages, newest first.

    Assistant turns are filtered out here rather than at the call site so there
    is exactly one place to argue with about it. See the module docstring.
    """
    if not history:
        return []
    texts = [
        (message.get("content") or "").strip()
        for message in history
        if message.get("role") == "user"
    ]
    return [text for text in reversed(texts) if text][:FOCUS_LOOKBACK_TURNS]


def _class_flipped(message: str, inherited_type: str) -> bool:
    """
    Whether the question has crossed from equities to crypto or back.

    A question that leans one way while the carried focus sits on the other is
    not a follow-up about that asset, whatever else it does or does not name.
    """
    from services.chat_service import crypto_leaning, stock_leaning

    if inherited_type == "crypto" and stock_leaning(message):
        return True
    return inherited_type == "stock" and crypto_leaning(message)


async def resolve_state(
    message: str,
    history: Optional[List[Dict[str, str]]] = None,
    *,
    override: Optional[str] = None,
) -> ConversationState:
    """
    The focus and intent for this turn.

    Ordering matters and is the whole design. The intent is classified from what
    the *current* message resolves on its own, because that is what decides
    whether inheriting is even appropriate — a definitional question asked after
    three turns about BTC is still not a question about BTC. The intent is then
    recomputed once the focus is settled, so a comparison that only becomes a
    comparison after inheritance is labelled as one.
    """
    from services.chat_service import QueryFocus, load_asset_metadata, resolve_against

    crypto_meta, stock_meta = await load_asset_metadata()

    # An override comes from the user clicking the focus badge. It is a string
    # from a client, so it goes through the same resolver as anything else
    # rather than straight into the symbol set.
    if override:
        forced = resolve_against(override, crypto_meta, stock_meta)
        if forced.symbols:
            intent = chat_intent.classify(message, symbol_count=len(forced.symbols))
            return ConversationState(
                focus=forced,
                intent=intent,
                explicit=forced.symbols,
                timeframe=chat_intent.timeframe_in(message),
                switched=True,
            )

    explicit = resolve_against(message, crypto_meta, stock_meta)
    intent = chat_intent.classify(message, symbol_count=len(explicit.symbols))
    timeframe = chat_intent.timeframe_in(message)

    # A question about the market, about a definition, or about the day as a
    # whole does not belong to whatever asset came before it.
    clears = intent in chat_intent.FOCUS_CLEARING_INTENTS or chat_intent.is_market_wide(message)

    additive = chat_intent.is_additive(message)

    if explicit.symbols and not additive:
        return ConversationState(
            focus=explicit,
            intent=intent,
            explicit=explicit.symbols,
            timeframe=timeframe,
            switched=False,
        )

    if clears:
        return ConversationState(
            focus=explicit,
            intent=intent,
            explicit=explicit.symbols,
            timeframe=timeframe,
            switched=bool(_first_prior_focus(history, crypto_meta, stock_meta)),
        )

    prior = _first_prior_focus(history, crypto_meta, stock_meta)
    if prior is None or _class_flipped(message, prior[0].asset_type):
        return ConversationState(
            focus=explicit,
            intent=intent,
            explicit=explicit.symbols,
            timeframe=timeframe,
            switched=prior is not None,
        )

    prior_focus, prior_message = prior

    # "peki ETH?" keeps the previous subject and adds to it; a message that
    # named nothing at all simply continues with it.
    merged: List[str] = list(explicit.symbols)
    for symbol in prior_focus.symbols:
        if symbol not in merged:
            merged.append(symbol)
    merged = merged[:MAX_FOCUS_SYMBOLS]

    focus = QueryFocus(
        symbols=tuple(merged),
        asset_type=explicit.asset_type if explicit.symbols else prior_focus.asset_type,
    )
    inherited = tuple(s for s in merged if s not in explicit.symbols)

    # A follow-up that names no timeframe of its own is asking about the same
    # one, because it is asking about the same thing.
    if timeframe is None:
        timeframe = chat_intent.timeframe_in(prior_message)

    logger.debug("Focus inherited %s from an earlier turn for %r", inherited, message[:60])

    return ConversationState(
        focus=focus,
        # Recomputed: "compare them" carries no symbols of its own and is only a
        # comparison once the previous two are back in hand.
        intent=chat_intent.classify(message, symbol_count=len(merged)),
        explicit=explicit.symbols,
        inherited=inherited,
        timeframe=timeframe,
        switched=False,
    )


def _first_prior_focus(
    history: Optional[List[Dict[str, str]]],
    crypto_meta: Dict,
    stock_meta: Dict,
) -> Optional[Tuple["object", str]]:
    """The most recent user message that resolved an asset, and that message."""
    from services.chat_service import resolve_against

    for text in _user_messages(history):
        focus = resolve_against(text, crypto_meta, stock_meta)
        if focus.symbols:
            return focus, text
    return None


def describe(state: ConversationState) -> str:
    """
    The focus as a prompt block.

    Without this the model cannot see the inheritance at all: it is handed
    evidence about BTC and a question that says "peki 4 saatlikte?", and nothing
    connects them. One sentence is enough, and it has to say that the subject
    was carried rather than asked for — an answer that silently assumes the
    subject is worse than one that names it.
    """
    if not state.symbols:
        return "This turn resolved no specific asset; answer it as a general market question."

    subject = ", ".join(state.symbols)
    asset_type = getattr(state.focus, "asset_type", "crypto")
    line = f"This turn is about {subject} ({asset_type})."

    if state.inherited:
        carried = ", ".join(state.inherited)
        line += (
            f" {carried} was carried over from an earlier message in this conversation —"
            " the current question did not name it. If that is not what the user meant,"
            " say so rather than answering about the wrong asset."
        )
    if state.timeframe:
        line += f" The timeframe under discussion is {state.timeframe}."
    return line
