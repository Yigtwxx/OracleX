"""
Oracle Chat Service — the conversational layer over the market snapshot.

Chat does not collect its own market data. It reuses the same snapshot the
analysis reports are built from (`services.analysis_data`), which fetches every
feed concurrently, computes the derived metrics in Python, and records failed
feeds in ``snapshot["unavailable"]`` instead of rendering a zero. That property
is the whole point: a chat answer must never present a missing value as a real
one.

What a turn gathers on top of the snapshot now lives in `services.chat_tools` as
a registry of named tools. This module owns the turn itself: resolving which
asset the question is about, choosing and running a plan, fitting the results
into the context window, and asking the model for an answer.
"""

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from config import settings
from services import chat_planner, chat_tools, llm, prompt_budget
from services.prompts import render_prompt

logger = logging.getLogger(__name__)

# How long the *answer* may take. This used to be 300s and to mean two things at
# once — the bound on the LLM call and the de facto ceiling on a whole turn. With
# tools running in front of the answer those cannot be the same number, so the
# turn is now bounded in pieces that add up:
#
#   TOOL_PHASE_BUDGET (150) + CHAT_TIMEOUT (180) < TURN_TIMEOUT (360)
CHAT_TIMEOUT = 180.0

# Wall clock across every tool step, checked before each one. Not per step: four
# searches at 35s each would otherwise leave nothing for the answer.
TOOL_PHASE_BUDGET = 150.0

# The outer bound on a whole turn, for the job runner.
TURN_TIMEOUT = 360.0

# Below this much left in the phase budget a step is not worth starting: it
# would be cut off before any upstream could answer, and a step that reports
# "timed out" after half a second is less honest than one that says it was
# skipped.
MIN_STEP_BUDGET = 1.0

# Conversation history bounds. The frontend sends the whole transcript.
HISTORY_TURNS = 8
HISTORY_CHARS = 1500

# What a block says in place of the part the token budget removed. A trimmed
# block that does not admit it is trimmed is worse than a missing one: the model
# reads four surviving turns as the entire conversation, or three surviving
# precedents as everything history had to offer, and calibrates accordingly.
HISTORY_TRIM_NOTE = (
    "[Earlier turns of this conversation were dropped to fit the context window. "
    "What follows is only the most recent exchange — do not assume it is the whole "
    "conversation.]"
)
EVIDENCE_TRIM_NOTE = "[The tail of this block was dropped to fit the context window.]"

MAX_TOKENS = {"concise": 2000, "detailed": 6000}

# Auto-titling of a session from its first message. The title lands in a fixed
# sidebar column, so anything past TITLE_MAX_CHARS would be clipped by CSS and
# never read — the model is asked for a short phrase and the reply is hard-capped
# here regardless of what it returns.
TITLE_MAX_CHARS = 48
# Only the opening of a long first message is sent: a title needs the subject,
# not the whole question, and a short prompt keeps this off the turn's critical path.
TITLE_SOURCE_CHARS = 500
TITLE_TOKENS = 32
TITLE_TIMEOUT = 20.0
# Decoration a model reaches for when asked for a title — quotes, bullet markers,
# a trailing period — stripped from both ends of the reply.
TITLE_STRIP_CHARS = "\"'`“”‘’«»*#—-. \t"

STYLE_RULES = {
    "concise": (
        "Keep it under 120 words: the answer, the two figures that carry it, and "
        "the one risk to it. No preamble, no summary of the question."
    ),
    "detailed": (
        "Go deep: 300-450 words. Cover what the data says, what would invalidate "
        "that read, and where the signals disagree. Still no filler."
    ),
}

# The per-block "this came back empty" strings that used to live here are gone.
# The evidence manifest states the outcome of every step by name, which covers
# the same ground for a plan whose shape is no longer fixed — and covers the
# case the constants could not: a tool that was never in the plan at all.

# Tickers and coin names that collide with ordinary English. A bare-word match on
# any of these says nothing about what the user asked, so name matching skips
# them; an explicit "$CORE" or an uppercase "CORE" still resolves normally.
GENERIC_NAME_TOKENS = frozenset(
    {
        "core",
        "sky",
        "story",
        "sun",
        "gas",
        "gods",
        "high",
        "just",
        "move",
        "next",
        "one",
        "only",
        "open",
        "play",
        "power",
        "prime",
        "pundi",
        "rare",
        "ray",
        "real",
        "reef",
        "rich",
        "rise",
        "run",
        "safe",
        "sale",
        "self",
        "share",
        "shop",
        "side",
        "solo",
        "space",
        "spell",
        "stable",
        "stack",
        "star",
        "step",
        "swell",
        "swipe",
        "time",
        "trust",
        "turbo",
        "vision",
        "wave",
        "wing",
        "world",
        "block",
        "meta",
        "unity",
        "now",
        "net",
        "team",
        "cat",
        "gm",
        "ge",
        "shell",
        # Venue and index words: "how are nasdaq stocks doing" is a market question,
        # not a question about Nasdaq, Inc.
        "nasdaq",
        "nyse",
        "amex",
        "dow",
        "russell",
        "euronext",
    }
)

# Words that look like tickers when a sentence is shouted or a message is typed
# in caps. Checked against the registry anyway, but these are common enough to
# be worth short-circuiting.
NON_TICKER_UPPERCASE = frozenset(
    {
        "A",
        "I",
        "AI",
        "AM",
        "AN",
        "AND",
        "ARE",
        "AS",
        "AT",
        "BE",
        "BUT",
        "BY",
        "CAN",
        "DO",
        "FOR",
        "GO",
        "HOW",
        "IF",
        "IN",
        "IS",
        "IT",
        "ME",
        "MY",
        "NO",
        "NOT",
        "OF",
        "ON",
        "OR",
        "SO",
        "THE",
        "TO",
        "UP",
        "US",
        "WE",
        "WHY",
        "YES",
        "OK",
        "USD",
        "USDT",
        "ETF",
        "CEO",
        "GDP",
        "CPI",
        "FED",
        "PM",
    }
)

# Uppercase run that could be a ticker: 2-5 letters, optionally dotted (BRK.B).
_UPPER_TICKER_RE = re.compile(r"\b([A-Z]{2,5}(?:\.[A-Z])?)\b")

# Legal suffixes the exchange screener appends to company names. Nobody asks
# about "Tesla Inc." — they ask about Tesla, so the suffix is stripped before
# a name is matched against the message.
_LEGAL_SUFFIX_RE = re.compile(
    r"[\s,]+(?:incorporated|inc|corporation|corp|company|co|limited|ltd|plc|"
    r"holdings?|group|llc|lp|nv|sa|ag|se)\.?$",
    re.IGNORECASE,
)


def _company_name(raw: str) -> str:
    """A registry name reduced to the part a person would actually type."""
    name = (raw or "").strip()
    previous = None
    while name != previous:
        previous = name
        name = _LEGAL_SUFFIX_RE.sub("", name).strip()
    return name


# ═══════════════════════════════════════════════════════════════════════════════
# QUERY FOCUS — which asset the question is actually about
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class QueryFocus:
    """The asset(s) a question is about, resolved against the asset registry."""

    symbols: Tuple[str, ...] = ()
    asset_type: str = "crypto"

    @property
    def primary(self) -> Optional[str]:
        return self.symbols[0] if self.symbols else None


def _stock_leaning(message: str) -> bool:
    """True if a symbol-free question is clearly about equities."""
    lowered = message.lower()
    return any(
        kw in lowered
        for kw in (
            "nasdaq",
            "stock",
            "equit",
            "hisse",
            "borsa",
            "s&p",
            "sp500",
            "dow jones",
            "share price",
            "wall street",
        )
    )


async def resolve_query_assets(message: str) -> QueryFocus:
    """
    Resolve the assets a message is about, in descending order of confidence.

    Only symbols that exist in the asset registry are returned. A message with
    no recognisable asset resolves to an empty focus and is answered as a
    general market question — inventing a default symbol is what used to send
    the whole pipeline off analysing the wrong thing.
    """
    from services import asset_registry
    from services.symbol_detection_service import (
        CRYPTO_ALIASES,
        EQUITY_ALIASES,
        find_pattern_matches,
    )

    try:
        crypto_meta = await asset_registry.get_crypto_metadata()
        stock_meta = await asset_registry.get_stock_metadata()
    except Exception as e:  # noqa: BLE001 — a cold registry must not kill the turn
        logger.warning("Asset registry unavailable for symbol resolution: %s", e)
        crypto_meta, stock_meta = {}, {}

    ordered: List[str] = []
    kinds: Dict[str, str] = {}

    def accept(symbol: str, kind: str) -> None:
        symbol = symbol.upper()
        if symbol not in kinds:
            ordered.append(symbol)
            kinds[symbol] = kind

    def classify(symbol: str) -> Optional[str]:
        """Which registry knows this ticker, preferring the app's crypto focus."""
        symbol = symbol.upper()
        if not crypto_meta and not stock_meta:
            # Registry is cold: the alias table is the only ground truth left.
            return "crypto" if symbol in set(CRYPTO_ALIASES.values()) else None
        in_crypto, in_stock = symbol in crypto_meta, symbol in stock_meta
        if in_crypto and in_stock:
            return "stock" if _stock_leaning(message) else "crypto"
        if in_crypto:
            return "crypto"
        if in_stock:
            return "stock"
        return None

    # 1. Explicit markup — $BTC, BTC/USDT, (NASDAQ: NVDA). Unambiguous by
    #    construction.
    for symbol, notation in find_pattern_matches(message):
        resolved = CRYPTO_ALIASES.get(symbol.lower(), symbol).upper()
        kind = classify(resolved)
        if kind:
            accept(resolved, kind)
        elif notation in ("cashtag", "pair"):
            # The user was explicit about a ticker the registry does not track;
            # honour it rather than silently answering about something else.
            accept(resolved, "stock" if _stock_leaning(message) else "crypto")

    # 2. Uppercase tickers as typed. Matching against the original casing — not
    #    an uppercased copy of the message — is what keeps "do you" out of this.
    for token in _UPPER_TICKER_RE.findall(message):
        if token in NON_TICKER_UPPERCASE:
            continue
        kind = classify(token)
        if kind:
            accept(token, kind)

    # 3. Names and aliases, whole-word and case-insensitive: "bitcoin", "nvidia".
    lowered = message.lower()

    def name_at(name: str) -> Optional[int]:
        """Where this name occurs in the message, or None if it does not."""
        name = name.strip().lower()
        if len(name) < 4 or name in GENERIC_NAME_TOKENS:
            return None
        match = re.search(rf"\b{re.escape(name)}\b", lowered)
        return match.start() if match else None

    # Collected rather than accepted immediately so that "Tesla and Apple"
    # resolves with Tesla primary — the order the user wrote them in.
    named: List[Tuple[int, str, str]] = []

    def collect(name: str, symbol: str, kind: str) -> None:
        position = name_at(name)
        if position is not None:
            named.append((position, symbol.upper(), kind))

    # Curated alias tables carry the informal names ("amazon", "google") that
    # the exchange's own listing names do not.
    for alias, symbol in CRYPTO_ALIASES.items():
        if symbol in crypto_meta or not crypto_meta:
            collect(alias, symbol, "crypto")

    for alias, ticker in EQUITY_ALIASES.items():
        collect(alias, ticker, "stock")

    for symbol, record in crypto_meta.items():
        collect(_company_name(record.get("name", "")), symbol, "crypto")

    for symbol, record in stock_meta.items():
        collect(_company_name(record.get("name", "")), symbol, "stock")

    for _position, symbol, kind in sorted(named, key=lambda row: row[0]):
        accept(symbol, kind)

    if not ordered:
        return QueryFocus(symbols=(), asset_type="stock" if _stock_leaning(message) else "crypto")

    # The asset type follows the highest-confidence match, so one stray mention
    # of a coin in an equities question does not flip the whole context.
    return QueryFocus(symbols=tuple(ordered[:3]), asset_type=kinds[ordered[0]])


def _step_label(
    ctx: chat_tools.ToolContext,
    tool: Optional[chat_tools.Tool],
    step: chat_tools.PlannedStep,
) -> str:
    """
    The row a user reads while a step runs.

    A tool that defaults an argument leaves it out of its args, so the label has
    to fall back to the same places the executor does — the declared defaults
    and the resolved focus. Otherwise `asset_technicals` renders as "Checking
    levels" with a hole in it, and worse, `read_chart` renders as "Reading the
    BTC chart" while actually reading the 4h series. A label that hides which
    timeframe was read is a label that lets the user assume it was theirs.
    """
    if tool is None:
        return step.tool

    args = {arg.name: arg.default for arg in tool.args if arg.default is not None}
    args["symbol"] = ctx.focus.primary or ""
    args.update(step.args)
    return chat_tools.label_for(tool, args)


@dataclass
class StepOutcome:
    """One executed plan step: what ran, what came back, how it went."""

    step: chat_tools.PlannedStep
    tool: Optional[chat_tools.Tool]
    result: chat_tools.ToolResult
    status: str  # "done" | "empty" | "failed" | "skipped"
    label: str = ""
    duration_seconds: float = 0.0


async def _run_step(
    ctx: chat_tools.ToolContext,
    step: chat_tools.PlannedStep,
    *,
    timeout: Optional[float] = None,
) -> StepOutcome:
    """Run one step, never raising, always reporting how it ended."""
    tool = chat_tools.REGISTRY.get(step.tool)
    if tool is None:
        return StepOutcome(
            step, None, chat_tools.ToolResult(ok=False, detail="unknown tool"), "failed"
        )

    label = _step_label(ctx, tool, step)
    started = datetime.now()
    result = await chat_tools.guard(
        f"tool:{tool.name}",
        tool.run(ctx, **step.args),
        min(tool.timeout, timeout) if timeout is not None else tool.timeout,
        chat_tools.ToolResult(ok=False, detail="timed out"),
    )
    elapsed = round((datetime.now() - started).total_seconds(), 1)

    # "Ran and found nothing" is not "was never consulted": one is a gap worth
    # reporting in the answer, the other is silence. The manifest keeps them
    # apart, so the status has to as well.
    status = "done" if result.ok and result.block else "empty" if result.ok else "failed"
    return StepOutcome(step, tool, result, status, label, elapsed)


async def run_plan(
    ctx: chat_tools.ToolContext,
    plan: List[chat_tools.PlannedStep],
    on_step: Optional[Callable[[Dict[str, object]], None]] = None,
    *,
    budget: float = TOOL_PHASE_BUDGET,
) -> List[StepOutcome]:
    """
    Execute a plan in order, reporting each step as it starts and finishes.

    Sequential, deliberately. The product is a live timeline, and steps running
    concurrently would make it a lie — three rows would appear to tick over in
    an order nothing actually happened in. Sequencing is also what lets a step
    use what an earlier one found: `read_page` opens a URL that `web_search`
    put in the context, which is only meaningful if search really did run first.

    The budget is checked *before* each step rather than around the whole loop.
    A step that would not fit is marked skipped and reported as such — the turn
    then answers from what it has, instead of the answer itself being the thing
    that ran out of time.
    """
    outcomes: List[StepOutcome] = []
    deadline = time.monotonic() + budget

    for index, step in enumerate(plan):
        tool = chat_tools.REGISTRY.get(step.tool)
        label = _step_label(ctx, tool, step)
        step_id = str(index)

        # Skip on an exhausted budget, not on one too small for the tool's full
        # timeout. Those are very different tests: the declared timeouts add up
        # to more than the phase budget by design — they are worst cases, and
        # tools almost never spend them — so requiring the whole allowance to
        # fit would skip a step that takes a second, every single turn.
        remaining = deadline - time.monotonic()
        if remaining <= MIN_STEP_BUDGET:
            outcome = StepOutcome(
                step,
                tool,
                chat_tools.ToolResult(ok=False, detail="ran out of time for this turn"),
                "skipped",
                label,
            )
            outcomes.append(outcome)
            _report(on_step, step_id, outcome)
            continue

        if on_step:
            on_step(
                {
                    "id": step_id,
                    "tool": step.tool,
                    "label": label,
                    "status": "running",
                    "detail": None,
                    "duration_seconds": None,
                }
            )

        # The step gets its own timeout or what is left of the phase, whichever
        # is shorter — so a slow tool near the end of the budget is cut off
        # rather than being allowed to overrun into the answer's time.
        outcome = await _run_step(ctx, step, timeout=remaining)
        outcomes.append(outcome)
        _report(on_step, step_id, outcome)

    return outcomes


def _report(
    on_step: Optional[Callable[[Dict[str, object]], None]], step_id: str, outcome: StepOutcome
) -> None:
    if not on_step:
        return
    on_step(
        {
            "id": step_id,
            "tool": outcome.step.tool,
            "label": outcome.label or outcome.step.tool,
            "status": outcome.status,
            "detail": outcome.result.detail or None,
            "duration_seconds": outcome.duration_seconds,
        }
    )


def _render_evidence(outcomes: List[StepOutcome], budget: "prompt_budget.BudgetResult") -> str:
    """
    The evidence section: a manifest of what ran, then the surviving blocks.

    The manifest is what makes "missing data is stated, not filled in"
    enforceable for a plan the model did not know in advance. Without it a step
    that failed is indistinguishable from a step that never happened, and the
    model has no way to report the gap it should be reporting.
    """
    manifest = ["TOOLS RUN THIS TURN"]
    for outcome in outcomes:
        note = outcome.result.detail or {
            "done": "ok",
            "empty": "found nothing",
            "failed": "did not complete",
            "skipped": "not run",
        }.get(outcome.status, outcome.status)
        manifest.append(f"- {outcome.step.tool} [{outcome.status}] — {note}")
    manifest.append(
        "Anything not listed above was not consulted. A step marked `empty` or "
        "`failed` is a gap to state plainly, never one to fill in."
    )

    sections = []
    for index, outcome in enumerate(outcomes):
        text = budget.text(f"tool:{outcome.step.tool}:{index}")
        if text:
            sections.append(text)

    return "\n".join(manifest) + "\n\n" + "\n\n".join(sections)


def _history_block(history: Optional[List[Dict[str, str]]]) -> str:
    """The recent turns, bounded — the client sends the entire transcript."""
    if not history:
        return "(this is the first message of the conversation)"

    lines = []
    for msg in history[-HISTORY_TURNS:]:
        speaker = "User" if msg.get("role") == "user" else "Oracle"
        content = (msg.get("content") or "").strip()[:HISTORY_CHARS]
        if content:
            lines.append(f"{speaker}: {content}")

    return "\n\n".join(lines) or "(this is the first message of the conversation)"


# ═══════════════════════════════════════════════════════════════════════════════
# THE TURN
# ═══════════════════════════════════════════════════════════════════════════════


async def chat_with_oracle(
    message: str,
    history: Optional[List[Dict[str, str]]] = None,
    style: str = "detailed",
    user_id: Optional[str] = None,
    on_step: Optional[Callable[[Dict[str, object]], None]] = None,
) -> Dict:
    """
    Answer one chat turn against live market data.

    A plan decides which tools run; each one is optional, and whatever arrives
    in time goes into the prompt. The model is told to report gaps rather than
    fill them, and the manifest is how it can tell a gap from a silence.

    `on_step` is how the job transport watches progress. Left unset — as the
    blocking `POST /api/chat` leaves it — the turn behaves exactly as before.
    """
    start_time = datetime.now()
    style = style if style in MAX_TOKENS else "detailed"

    focus = await resolve_query_assets(message)

    # The snapshot is pinned rather than planned: it is the one source that
    # outranks everything else, so no plan gets to leave it out. It also runs
    # first, which is what lets later steps read `ctx.snapshot`.
    chosen = await chat_planner.plan_turn(message, focus, user_id=user_id)
    plan = [chat_tools.PlannedStep(chat_tools.PINNED_TOOL, {})] + chosen
    ctx = chat_tools.ToolContext(message=message, focus=focus)
    outcomes = await run_plan(ctx, plan, on_step)

    system_prompt = render_prompt("chat/system")

    # Fit the context to the model's window before the server does it for us.
    #
    # Ollama truncates an over-long prompt from the front, and the system prompt
    # renders first — so an overflow deletes the standing rules and answers the
    # question without them, with nothing in the response to say so. Budgeting
    # here means an overflow costs the oldest turns of the conversation instead.
    #
    # Priorities are what the answer can least afford to lose: the question and
    # the rules are pinned, the snapshot outranks everything derived from it, and
    # the transcript goes first because the current question is already in hand.
    blocks = [
        prompt_budget.Block("system", system_prompt, priority=100, pinned=True),
        prompt_budget.Block("question", message, priority=100, pinned=True),
        prompt_budget.Block(
            "history",
            _history_block(history),
            priority=10,
            trim_from="head",
            trim_note=HISTORY_TRIM_NOTE,
        ),
    ]
    # One block per step that produced something. The name carries the index so
    # a tool that ran twice does not collide — `BudgetResult.blocks` is keyed by
    # name, and a collision would silently drop one of the two.
    for index, outcome in enumerate(outcomes):
        if outcome.result.block:
            blocks.append(
                prompt_budget.Block(
                    f"tool:{outcome.step.tool}:{index}",
                    outcome.result.block,
                    priority=outcome.tool.priority if outcome.tool else 20,
                    trim_note=EVIDENCE_TRIM_NOTE,
                )
            )

    budget = prompt_budget.fit(blocks, settings.PROMPT_TOKEN_BUDGET)

    user_prompt = render_prompt(
        "chat/turn",
        evidence=_render_evidence(outcomes, budget),
        history=budget.text("history") or "(this is the first message of the conversation)",
        question=message,
        style_rule=STYLE_RULES[style],
    )

    # The sidebar wants short names, not the planner-facing descriptions.
    sources_used = [
        o.step.tool.replace("_", " ").capitalize() for o in outcomes if o.status == "done"
    ]

    try:
        response = await llm.generate(
            user_prompt,
            system=system_prompt,
            temperature=0.3,
            top_p=0.9,
            max_tokens=MAX_TOKENS[style],
            timeout=CHAT_TIMEOUT,
            # A detailed answer has to weigh conflicting signals against each
            # other and name what would invalidate its own read — the work a
            # small model gets wrong when it answers in one pass. A concise
            # answer is two figures and a risk, and pays the latency for nothing.
            # Either way the <think> block is stripped in the LLM layer, so this
            # only decides how the model reasons, never what the user sees.
            reasoning=(style == "detailed"),
            # Ollama-only knobs; other providers ignore them. The real ceiling is
            # PROMPT_TOKEN_BUDGET, enforced above — this is what the server is
            # asked to allocate, and it does not by itself prevent truncation.
            extra={"repeat_penalty": 1.1, "num_ctx": settings.LLM_NUM_CTX},
            prefer=await llm.provider_for(user_id, "chat"),
        )
    except Exception as e:  # noqa: BLE001 — surface as a chat message, not a 500
        logger.exception("Chat generation failed")
        return {
            "response": f"🔴 Something went wrong while generating the answer: {e}",
            "thinking_time": round((datetime.now() - start_time).total_seconds(), 1),
            "sources": [],
            "detected_symbol": focus.primary,
        }

    elapsed = round((datetime.now() - start_time).total_seconds(), 1)

    if response is None:
        return {
            "response": (
                "⚠️ No AI provider responded. Check the configured provider chain at "
                "`/api/llm/status`."
            ),
            "thinking_time": elapsed,
            "sources": [],
            "detected_symbol": focus.primary,
        }

    answer = response.strip()
    if not answer:
        answer = "I could not produce an answer for that. Please try rephrasing the question."

    return {
        "response": answer,
        "thinking_time": elapsed,
        "sources": sources_used,
        "detected_symbol": focus.primary,
    }


def _clean_title(raw: str) -> str:
    """Reduce a model reply — or a raw first message — to one short sidebar line."""
    first_line = next((line for line in raw.splitlines() if line.strip()), "")
    line = re.sub(r"\s+", " ", first_line).strip(TITLE_STRIP_CHARS)
    if len(line) <= TITLE_MAX_CHARS:
        return line

    # Cut on a word boundary so the ellipsis does not land mid-word. A single
    # token longer than the cap has no boundary to find, hence the fallback.
    head = line[:TITLE_MAX_CHARS]
    cut = head.rsplit(" ", 1)[0] if " " in head else head
    return cut.rstrip(TITLE_STRIP_CHARS) + "…"


async def generate_session_title(message: str, *, user_id: Optional[str] = None) -> Optional[str]:
    """
    A short title for a chat session, derived from its first message.

    When the LLM is unavailable the trimmed message itself is returned rather
    than a generic label: that is still the user's own text, so the sidebar keeps
    saying what the session is about instead of showing another "Yeni Sohbet".
    None means there was nothing to title — an empty message.
    """
    trimmed = message.strip()
    if not trimmed:
        return None

    fallback = _clean_title(trimmed)

    try:
        response = await llm.generate(
            render_prompt("chat/title", message=trimmed[:TITLE_SOURCE_CHARS]),
            temperature=0.2,
            max_tokens=TITLE_TOKENS,
            timeout=TITLE_TIMEOUT,
            # Bounded output: hidden reasoning would eat the whole token budget
            # before the title itself is emitted.
            reasoning=False,
            prefer=await llm.provider_for(user_id, "chat"),
        )
    except Exception:  # noqa: BLE001 — a missing title must never fail the turn
        logger.exception("Session title generation failed")
        return fallback

    if not response:
        return fallback

    return _clean_title(response) or fallback


async def check_chat_available() -> bool:
    """Check if any configured LLM provider can serve the chat."""
    return await llm.llm_health()
