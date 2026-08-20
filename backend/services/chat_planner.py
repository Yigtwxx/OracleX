"""
Letting the model choose what to look up.

One extra LLM call at the top of a turn, in JSON mode, whose only job is to
name the tools worth running. The answer pass then writes prose from whatever
those tools returned. Two passes rather than a tool-calling loop, for three
reasons that all point the same way with a small local model:

* **It is one JSON object, not a protocol.** A ReAct loop needs the model to
  emit well-formed tool calls repeatedly, interleaved with prose it must not
  emit yet. Small models lose that thread. Here it is asked once, for a shape
  it can be forced into (`json_mode`), and never again.
* **It is bounded.** A loop's cost is whatever the model decides; this is one
  call plus at most `MAX_PLAN_STEPS` tools.
* **The planner never sees a web page.** Everything it reads is ours — the
  question, the catalogue. A scraped page cannot influence which tools run,
  because by the time any page is fetched the plan is already fixed. That is a
  real security property of this design and the reason it must not be
  "improved" into a loop later.

The parser assumes the model will get it wrong. Ollama's `format: "json"`
guarantees the reply parses, not that it has the shape asked for, and every
recovery below corresponds to something small models actually emit.

When nothing usable comes back the turn falls through to
`chat_tools.heuristic_plan`, which reproduces the fixed pipeline exactly. The
degraded path is therefore the old behaviour, not a broken one.
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import settings
from services import chat_intent, chat_tools, llm
from services.chat_tools import PlannedStep, Tool
from services.prompts import render_prompt

logger = logging.getLogger(__name__)

PLANNER_TIMEOUT = 25.0
PLANNER_MAX_TOKENS = 400
MAX_PLAN_STEPS = 4

# Below this a message is a greeting or an acknowledgement. Spending ten seconds
# of local inference to decide that "ok" needs no research is a bad trade.
MIN_PLANNABLE_CHARS = 12

# Keys a model reaches for instead of "steps".
_LIST_KEYS = ("steps", "plan", "tools", "actions", "calls")

# Names models produce for tools that exist under another one. Deliberately an
# explicit table and not fuzzy matching: a wrong tool costs a real 30 seconds,
# so a name we do not recognise should be dropped, not guessed at.
_ALIASES = {
    "search": "web_search",
    "websearch": "web_search",
    "search_web": "web_search",
    "google": "web_search",
    "news": "web_search",
    "social": "social_search",
    "reddit": "social_search",
    "twitter": "social_search",
    "sentiment": "social_search",
    "ta": "asset_technicals",
    "technicals": "asset_technicals",
    "technical_analysis": "asset_technicals",
    "price": "asset_technicals",
    "chart": "read_chart",
    "candles": "read_chart",
    "history": "historical_precedent",
    "precedent": "historical_precedent",
    "rag": "historical_precedent",
    "compare": "compare_assets",
    "scenario": "simulate_scenario",
    "what_if": "simulate_scenario",
    "explain": "explain_price_move",
    "why": "explain_price_move",
    "read": "read_page",
    "open_page": "read_page",
    "scrape": "read_page",
    # The tools added when the registry went from ten to nineteen. Same rule as
    # above: an explicit table, because a wrong tool costs a real thirty seconds.
    "fundamentals": "stock_fundamentals",
    "valuation": "stock_fundamentals",
    "financials": "stock_fundamentals",
    "earnings": "stock_fundamentals",
    "profile": "crypto_profile",
    "supply": "crypto_profile",
    "tokenomics": "crypto_profile",
    "funding": "derivatives",
    "funding_rate": "derivatives",
    "open_interest": "derivatives",
    "liquidations": "derivatives",
    "positioning": "derivatives",
    "headlines": "asset_news",
    "asset_headlines": "asset_news",
    "symbol_news": "asset_news",
    "macro": "macro_board",
    "commodities": "macro_board",
    "rates": "macro_board",
    "regime": "macro_board",
    "brief": "market_brief",
    "briefing": "market_brief",
    "daily_brief": "market_brief",
    "voices": "market_voices",
    "statements": "market_voices",
    "officials": "market_voices",
    "fed": "market_voices",
    "holders": "ownership",
    "institutional": "ownership",
    "13f": "ownership",
    "insiders": "ownership",
    "open_url": "read_url",
    "read_link": "read_url",
    "user_link": "read_url",
}


@dataclass(frozen=True)
class TurnPlan:
    """
    What this turn will look up, and what kind of question it decided it was.

    The intent travels with the plan because the planner refines it: a
    deterministic classifier reads the words, and the model reads the question.
    Where they disagree on a label the taxonomy knows, the model wins — it is
    the one that can tell "how is BTC doing" from "how does BTC work".
    """

    steps: List[PlannedStep]
    intent: str
    source: str  # "planner" | "heuristic"
    timeframe: Optional[str] = None


async def plan_turn(
    message: str,
    focus,
    user_id: Optional[str] = None,
    *,
    intent: str = "current_state",
    history: Optional[List[Dict[str, str]]] = None,
    limit: int = chat_tools.MAX_CATALOGUE_TOOLS,
) -> TurnPlan:
    """
    Choose the tools for this turn.

    Never raises and never returns nothing usable: every failure path ends at
    `heuristic_plan`, so the worst case is the pipeline this replaced.

    The catalogue is filtered by the *deterministic* intent, not the model's,
    because it has to be built before the model is asked. If the model's reading
    turns out to want a tool the catalogue withheld, the reflection round is
    where that is recovered — re-filtering and re-planning here would be a loop,
    and the module docstring explains at length why this is not one.
    """
    catalogue = chat_tools.available_tools(message, focus, intent, limit=limit, user_id=user_id)

    def fallback(reason: Optional[str] = None) -> TurnPlan:
        if reason:
            logger.info("%s; falling back to the fixed plan", reason)
        return TurnPlan(
            chat_tools.heuristic_plan(message, focus, intent, user_id=user_id), intent, "heuristic"
        )

    if not settings.CHAT_PLANNER_ENABLED:
        return fallback()

    if len(message.strip()) < MIN_PLANNABLE_CHARS:
        return fallback()

    raw = await _ask(message, focus, catalogue, user_id, intent=intent, history=history)
    if not raw:
        return fallback("Planner returned nothing")

    payload = _load_json(raw)
    steps = parse_plan(raw, catalogue, focus, message, max_steps_for(intent))
    if not steps:
        # Logged with the raw reply so the prompt can be tuned against what the
        # local model actually emits rather than against a guess about it.
        return fallback(f"Planner produced no usable steps from {raw[:200]!r}")

    refined = intent
    timeframe = None
    if isinstance(payload, dict):
        refined = chat_intent.coerce(payload.get("intent")) or intent
        timeframe = _timeframe_from(payload)

    return TurnPlan(steps, refined, "planner", timeframe)


def _timeframe_from(payload: Dict[str, Any]) -> Optional[str]:
    """The interval the planner named for the turn, validated against the enum."""
    raw = payload.get("timeframe")
    if not isinstance(raw, str):
        return None
    candidate = raw.strip().lower()
    return candidate if candidate in chat_intent.TIMEFRAME_WORDS else None


# `current_state` and `causal` questions are the ones an experienced desk
# answers by covering several axes at once — levels, positioning, flow,
# narrative, macro, precedent — so those get room for more steps. Everything
# else keeps the old ceiling, because breadth there is just latency.
MAX_PLAN_STEPS_BROAD = 6
BROAD_INTENTS = frozenset({"current_state", "causal"})


def max_steps_for(intent: str) -> int:
    return MAX_PLAN_STEPS_BROAD if intent in BROAD_INTENTS else MAX_PLAN_STEPS


def _recent_exchange(history: Optional[List[Dict[str, str]]], limit: int = 4) -> str:
    """
    The tail of the conversation, for the planner.

    It plans for a question that is often a fragment — "peki 4 saatlikte?" says
    nothing on its own about what to look up. The focus resolver already carries
    the subject forward; this carries the *shape* of what was asked, which is
    what decides whether the follow-up wants a chart or a headline.
    """
    if not history:
        return "(no earlier turns)"
    lines = []
    for message in history[-limit:]:
        speaker = "User" if message.get("role") == "user" else "Oracle"
        content = (message.get("content") or "").strip().replace("\n", " ")[:200]
        if content:
            lines.append(f"{speaker}: {content}")
    return "\n".join(lines) or "(no earlier turns)"


async def _ask(
    message: str,
    focus,
    catalogue: Sequence[Tool],
    user_id: Optional[str],
    *,
    intent: str = "current_state",
    history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """The planner call itself. Returns the raw reply, or an empty string."""
    prompt = render_prompt(
        "chat/plan",
        today=datetime.now().strftime("%d %B %Y"),
        tools=chat_tools.render_catalogue(catalogue),
        symbols=", ".join(focus.symbols) or "none",
        asset_type=focus.asset_type,
        intent=intent,
        history=_recent_exchange(history),
        max_steps=str(max_steps_for(intent)),
        question=message,
    )

    try:
        reply = await llm.generate(
            prompt,
            system=render_prompt("chat/plan_system"),
            # Planning is a lookup against a fixed catalogue, not a place for
            # invention: the same question should plan the same way twice.
            temperature=0.0,
            max_tokens=PLANNER_MAX_TOKENS,
            timeout=PLANNER_TIMEOUT,
            json_mode=True,
            # A reasoning pass would spend the whole token budget thinking
            # before it emitted the object — the same reason session titling
            # turns it off.
            reasoning=False,
            prefer=await llm.provider_for(user_id, "chat"),
        )
    except Exception as e:  # noqa: BLE001 — a failed plan is a fallback, not an error
        logger.warning("Planner call failed: %s", e)
        return ""

    return (reply or "").strip()


# ═══════════════════════════════════════════════════════════════════════════════
# PARSING
# ═══════════════════════════════════════════════════════════════════════════════


def parse_plan(
    raw: str,
    catalogue: Sequence[Tool],
    focus,
    message: str,
    max_steps: int = MAX_PLAN_STEPS,
) -> List[PlannedStep]:
    """
    Turn whatever the model said into steps we are willing to run.

    Ordered by how often each recovery is needed, and every one of them exists
    because a small model does it.
    """
    payload = _load_json(raw)
    if payload is None:
        return []

    entries = _unwrap(payload)
    allowed = {tool.name: tool for tool in catalogue}

    steps: List[PlannedStep] = []
    seen: set = set()
    scrapes = 0

    for entry in entries:
        step = _coerce_step(entry)
        if step is None:
            continue

        name = _resolve_name(step[0], allowed)
        if name is None:
            continue

        args = _coerce_args(allowed[name], step[1], focus, message)
        if args is None:
            continue

        if name == "read_page":
            # Enforced here as well as in the executor: the plan should not even
            # contain more scrapes than a turn will run, or the timeline would
            # show steps that were never going to happen.
            if scrapes >= chat_tools.MAX_SCRAPES_PER_TURN:
                continue
            scrapes += 1

        fingerprint = _fingerprint(name, args)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)

        steps.append(PlannedStep(name, args))
        if len(steps) >= max_steps:
            break

    return steps


def _fingerprint(name: str, args: Dict[str, Any]) -> tuple:
    """
    A hashable identity for a step, for deduplication.

    List-valued arguments are real — `social_search` takes `platforms` — and a
    list cannot go in a set, so values are flattened to tuples rather than used
    as they are.
    """
    items = tuple(
        (key, tuple(value) if isinstance(value, list) else value)
        for key, value in sorted(args.items(), key=lambda kv: kv[0])
    )
    return (name, items)


def _load_json(raw: str) -> Optional[Any]:
    """Parse the reply, salvaging an object or array out of surrounding prose."""
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        pass

    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = raw.find(opener), raw.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except ValueError:
                continue
    return None


def _unwrap(payload: Any) -> List[Any]:
    """Find the list of steps, wherever the model decided to put it."""
    if isinstance(payload, list):
        return payload

    if not isinstance(payload, dict):
        return []

    for key in _LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return value

    # A single step, unwrapped: {"tool": "web_search", "args": {...}}
    if "tool" in payload or "name" in payload:
        return [payload]

    # Any list value at all, when the key is one we did not anticipate.
    for value in payload.values():
        if isinstance(value, list):
            return value

    return []


def _coerce_step(entry: Any) -> Optional[tuple]:
    """Reduce one entry to (name, args-dict), or None if it is not a step."""
    if isinstance(entry, str):
        return entry, {}

    if not isinstance(entry, dict):
        return None

    name = entry.get("tool") or entry.get("name") or entry.get("action")
    if not isinstance(name, str) or not name.strip():
        return None

    args = entry.get("args")
    if args is None:
        args = entry.get("arguments") or entry.get("parameters")
    if isinstance(args, str):
        # Models routinely emit args as a JSON string rather than an object.
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    if not isinstance(args, dict):
        args = {}

    return name.strip(), args


def _resolve_name(raw_name: str, allowed: Dict[str, Tool]) -> Optional[str]:
    """Match a tool name exactly, then loosely, then by the alias table."""
    if raw_name in allowed:
        return raw_name

    normalised = re.sub(r"[^a-z0-9]+", "_", raw_name.lower()).strip("_")
    if normalised in allowed:
        return normalised

    aliased = _ALIASES.get(normalised)
    if aliased and aliased in allowed:
        return aliased

    logger.debug("Planner named an unavailable tool: %r", raw_name)
    return None


def _coerce_args(tool: Tool, raw: Dict[str, Any], focus, message: str) -> Optional[Dict[str, Any]]:
    """
    Fit the model's arguments to what the tool declares.

    Returns None when a required argument is missing and cannot be defaulted —
    dropping the step is better than running a tool against a value invented to
    fill a hole.
    """
    declared = {arg.name: arg for arg in tool.args}
    args: Dict[str, Any] = {}

    for name, value in raw.items():
        spec = declared.get(name)
        if spec is None:
            continue  # unknown key, silently dropped
        coerced = _coerce_value(spec, value, focus)
        if coerced is not None:
            args[name] = coerced

    for name, spec in declared.items():
        if name in args or not spec.required:
            continue
        fallback = _default_for(spec, focus, message)
        if fallback is None:
            logger.debug("Dropping %s: no value for required arg %s", tool.name, name)
            return None
        args[name] = fallback

    return args


def _coerce_value(spec, value: Any, focus) -> Optional[Any]:
    """Coerce one argument, or return None to leave it unset."""
    if value is None:
        return None

    if spec.kind == "symbol":
        symbol = str(value).strip().upper().lstrip("$")
        if not symbol:
            return None
        # A hallucinated ticker must never reach an exchange API. Anything the
        # question did not resolve to is dropped in favour of the tool's own
        # default, which reads from the focus.
        return symbol if symbol in focus.symbols else None

    if spec.kind == "int":
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return None
        if spec.minimum is not None:
            number = max(spec.minimum, number)
        if spec.maximum is not None:
            number = min(spec.maximum, number)
        return number

    if spec.kind == "enum":
        candidate = str(value).strip().lower()
        for choice in spec.choices:
            if choice.lower() == candidate:
                return choice
        return None

    if spec.kind == "list":
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(v) for v in value if v]
        return None

    text = str(value).strip()
    return text or None


def _default_for(spec, focus, message: str) -> Optional[Any]:
    """What a missing required argument falls back to."""
    if spec.kind == "symbol":
        return focus.primary
    if spec.name in ("query", "scenario"):
        return message
    if spec.default is not None:
        return spec.default
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# REFLECTION
# ═══════════════════════════════════════════════════════════════════════════════
#
# One bounded look back at what the research actually produced, and one chance
# to fix it. This is what turns "the tool came back empty" from a dead end into
# either a second attempt or an honest, reasoned answer.
#
# It does NOT make this a ReAct loop, and the difference is a security property
# rather than a preference. The module docstring above states that the planner
# never reads a web page — by the time any page is fetched, the plan is fixed.
# The reflection round runs *after* pages are fetched, so preserving that has to
# be structural: it is handed a digest built from scalars the executors
# computed, never the blocks themselves. `chat_service.build_reflection_digest`
# owns that, and `tests/test_chat_reflection.py` pins it.
#
# It is also bounded to exactly one round of at most two steps. A loop's cost is
# whatever the model decides; this is one call plus a fixed remainder.

REFLECT_TIMEOUT = 12.0
REFLECT_MAX_TOKENS = 240
MAX_REFLECT_STEPS = 2
MAX_FOLLOWUPS = 3

# These become clickable buttons that turn into the next user message, so they
# are bounded and stripped rather than passed through.
FOLLOWUP_MAX_CHARS = 80
# Decoration a model reaches for when asked for a list of questions.
FOLLOWUP_STRIP_CHARS = "-*•\"'` \t"


@dataclass(frozen=True)
class Reflection:
    """
    Whether the evidence is enough, and what to do if it is not.

    `sufficient=False` with empty `steps` is a real and important outcome: it
    means nothing further would help, which is what switches the answer into its
    degraded mode instead of letting the turn quietly answer as if the gap were
    not there.
    """

    sufficient: bool = True
    missing: str = ""
    steps: List[PlannedStep] = None
    followups: Tuple[str, ...] = ()
    # Facts about the *person* the turn learned, for `chat_memory_service`. The
    # keys are validated there against a fixed allowlist and the values are
    # cleaned — nothing proposed here reaches storage unchecked, and it must
    # not, because a memory outlives the turn that wrote it.
    remember: Dict[str, str] = None

    def __post_init__(self):
        if self.steps is None:
            object.__setattr__(self, "steps", [])
        if self.remember is None:
            object.__setattr__(self, "remember", {})


async def reflect_turn(
    message: str,
    focus,
    intent: str,
    digest: str,
    catalogue: Sequence[Tool],
    user_id: Optional[str] = None,
) -> Reflection:
    """
    Ask whether the research answered the question, and what would fix it.

    Never raises. A reflection that fails is simply one that found nothing to
    add, which leaves the turn exactly where it was.
    """
    if not settings.CHAT_REFLECTION_ENABLED:
        return Reflection()

    try:
        reply = await llm.generate(
            render_prompt(
                "chat/reflect",
                question=message,
                intent=intent,
                symbols=", ".join(focus.symbols) or "none",
                digest=digest,
                tools=chat_tools.render_catalogue(catalogue),
                max_steps=str(MAX_REFLECT_STEPS),
            ),
            system=render_prompt("chat/reflect_system"),
            temperature=0.0,
            max_tokens=REFLECT_MAX_TOKENS,
            timeout=REFLECT_TIMEOUT,
            json_mode=True,
            reasoning=False,
            prefer=await llm.provider_for(user_id, "chat"),
        )
    except Exception as e:  # noqa: BLE001 — a failed reflection is not a failed turn
        logger.warning("Reflection call failed: %s", e)
        return Reflection()

    return parse_reflection(reply or "", catalogue, focus, message)


def parse_reflection(raw: str, catalogue: Sequence[Tool], focus, message: str) -> Reflection:
    """
    Read a reflection out of whatever the model emitted.

    Same defensive posture as `parse_plan`, and the extra steps go through
    exactly the same pipeline — `_resolve_name`, `_coerce_args`, `_coerce_value`
    — so a reflection step still cannot name a URL and still cannot name a
    symbol the question never resolved.
    """
    payload = _load_json(raw)
    if not isinstance(payload, dict):
        return Reflection()

    sufficient = payload.get("sufficient")
    sufficient = bool(sufficient) if isinstance(sufficient, bool) else True

    missing = payload.get("missing")
    missing = missing.strip()[:200] if isinstance(missing, str) else ""

    steps = parse_plan(raw, catalogue, focus, message, MAX_REFLECT_STEPS)

    remember = payload.get("remember")
    remember = (
        {k: v for k, v in remember.items() if isinstance(k, str) and isinstance(v, str)}
        if isinstance(remember, dict)
        else {}
    )

    return Reflection(
        sufficient=sufficient,
        missing=missing,
        steps=steps,
        followups=_clean_followups(payload.get("followups")),
        remember=remember,
    )


def _clean_followups(raw: Any) -> Tuple[str, ...]:
    """
    Suggestions, sanitised.

    They are rendered as buttons whose text becomes the next user message. The
    model that wrote them only ever saw our own digest, so the injection surface
    is small — but "small" is not "none", and a suggestion carrying a URL or a
    newline is a suggestion doing something other than asking a question.
    """
    if not isinstance(raw, list):
        return ()

    cleaned: List[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        text = re.sub(r"\s+", " ", item).strip().strip(FOLLOWUP_STRIP_CHARS)
        if not text or "http" in text.lower():
            continue
        cleaned.append(text[:FOLLOWUP_MAX_CHARS])
        if len(cleaned) >= MAX_FOLLOWUPS:
            break
    return tuple(cleaned)
