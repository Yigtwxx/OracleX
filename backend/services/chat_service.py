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

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from config import settings
from services import chat_focus, chat_memory_service, chat_planner, chat_tools, llm, prompt_budget
from services.prompts import render_prompt

logger = logging.getLogger(__name__)

# The turn is bounded in pieces that add up. The arithmetic used to be stated as
#
#   TOOL_PHASE_BUDGET (150) + CHAT_TIMEOUT (180) < TURN_TIMEOUT (360)
#
# which left out the planner call: `chat_planner.plan_turn` runs *before*
# `run_plan` and is bounded only by its own PLANNER_TIMEOUT (25). The real worst
# case was therefore 25 + 150 + 180 = 355 against a 360 ceiling — five seconds
# for prompt assembly, snapshot rendering and scheduler jitter, which is not a
# margin, it is a coincidence. Every phase is now in the sum, and
# `tests/test_chat_budget.py` asserts it stays that way.
#
#   PLANNER_TIMEOUT      25   (services/chat_planner.py)
#   TOOL_PHASE_BUDGET   120
#   REFLECT_TIMEOUT      12
#   REFLECT_PHASE_BUDGET 45
#   CHAT_TIMEOUT        165
#   ────────────────────────
#                       367   against TURN_TIMEOUT 400

# How long the *answer* generation may take.
CHAT_TIMEOUT = 165.0

# Wall clock across every tool step of the first round, checked before each one.
# Not per step: four searches at 35s each would otherwise leave nothing for the
# answer.
TOOL_PHASE_BUDGET = 120.0

# The reflection round: one short JSON call, then at most a couple of remedial
# steps. Sized so a single browser page (30s in scrape_service) fits.
REFLECT_TIMEOUT = 12.0
REFLECT_PHASE_BUDGET = 45.0

# Below this much left on the turn, reflection is not worth starting: the call
# itself would land with no room to act on what it said.
MIN_REFLECT_VALUE = 20.0

# The tool phases may never eat into this. `run_plan` stops handing out time
# once the remaining turn is down to it, so the answer always gets a chance to
# be generated even when research overran.
ANSWER_FLOOR = 60.0

# The outer bound on a whole turn, for the job runner.
TURN_TIMEOUT = 400.0

# Below this much left in the phase budget a step is not worth starting: it
# would be cut off before any upstream could answer, and a step that reports
# "timed out" after half a second is less honest than one that says it was
# skipped.
MIN_STEP_BUDGET = 1.0

# Conversation history bounds. The frontend sends the whole transcript.
#
# Eight turns at 1 500 characters is up to 12 000 characters — around 3 400
# tokens of a 12 000-token budget, which made this quietly the largest block in
# the prompt and the first large thing the budget had to cut. The subject of the
# conversation now travels in its own pinned focus block (see `chat_focus`), so
# the transcript no longer has to carry it and can be trimmed harder.
#
# The caps are asymmetric because the two roles are worth different amounts. A
# past user message is a question that may still be live. A past assistant
# message is worth its subject and its conclusion; its prose is the part the
# model would write again anyway.
HISTORY_TURNS = 6
HISTORY_CHARS = 700
HISTORY_CHARS_ASSISTANT = 400

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

# Ollama counts a reasoning pass against `num_predict` along with the answer, so
# this ceiling has to cover both — and how long the model thinks is set by how
# hard the question is, not by how long the answer may be. Measured: a concise
# turn on "is BTC strong here" spent ~2 500 tokens thinking and then emitted 43
# words before the ceiling cut it off mid-number.
#
# So concise and detailed now share one ceiling. The old 2 000/6 000 split was
# making the token budget enforce brevity, which is `STYLE_RULES`' job and which
# the budget cannot do: it cannot shorten an answer, only truncate one. A
# concise turn still produces a short answer because the style rule says so; it
# just no longer runs out of room to finish the sentence.
ANSWER_TOKENS = 6000
MAX_TOKENS = {"concise": ANSWER_TOKENS, "detailed": ANSWER_TOKENS}

# An answer cut off by the token ceiling ends mid-sentence. There is no flag for
# it in the response, so this is how the log says so — the alternative is a
# second full generation on a suspicion, which costs more than the problem.
_COMPLETE_ENDINGS = ".!?…:»\"'`*)]|-—"

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

# Length, and only length. What kind of claim is admissible is the answer mode's
# job (see ANSWER_MODES); these two strings must never mention evidence policy,
# and no answer mode may mention length. They fight otherwise, and the model
# resolves the fight by ignoring one of them.
#
# The rewrite that matters is concise: "under 120 words" was being read as
# permission to say less, when the constraint is on words and not on substance.
STYLE_RULES = {
    "concise": (
        "Under 120 words, and every sentence carries a figure. The verdict goes "
        "in the opening clause, then the two or three figures that decide it, "
        "then the level that would invalidate the read. No preamble, no "
        "restatement of the question, no background. Short is a constraint on "
        "words, not on substance: the worked example in your standing rules is "
        "still the shape to hit, compressed."
    ),
    "detailed": (
        "300-450 words. Cover what the data says, the precedent analogy if there "
        "is one, what would invalidate the read, and where the signals disagree. "
        "Every paragraph must add a figure or a mechanism — length is earned, "
        "not filled. If you run out of substance at 250 words, stop at 250."
    ),
}

# What kind of claim this turn may make, chosen by intent. Python constants
# rather than one markdown file per intent, for a reason that is not style:
# `tests/test_prompts.py` finds templates by scanning for *literal* string
# arguments to `render_prompt`/`load_prompt`, so `load_prompt(f"chat/modes/
# {intent}")` would leave every mode file looking unreferenced and fail the
# suite. `STYLE_RULES` above is already this pattern.
#
# Five modes, deliberately. A distinction that does not change which claims are
# admissible does not earn its own block — it just dilutes the one the model
# actually needs to read.
ANSWER_MODES = {
    "conceptual": (
        "**This turn asks how something works, not what it is doing right now.** "
        "Answer it from your own knowledge: define the mechanism, give the "
        "formula or the rule of thumb, say what it is used for and where it "
        "misleads. Do not open with a caveat about data, do not report which "
        "feeds were unavailable, and do not reach for a current price unless the "
        "context happens to hold one and it genuinely illustrates the point. The "
        "standing rule about current figures still binds — but a question with "
        "no current figure in it does not need one, and refusing it is the wrong "
        "answer, not the safe one."
    ),
    "current_state": (
        "**This turn asks where something stands now.** Weigh every axis the "
        "evidence covers before you commit to a read — price and levels, "
        "momentum across timeframes, positioning, flows, the narrative, the "
        "macro backdrop, and what precedent says about setups like this one. You "
        "are not required to walk through them in order; you are required to "
        "have considered them, and to name the ones that came back empty rather "
        "than answering as though they agreed with you. If retrieved precedent "
        "is in the context, one analogy sentence with its measured outcome is "
        "worth more than a paragraph of description."
    ),
    "analytic": (
        "**This turn asks why, or what would follow.** Lead with the mechanism — "
        "the thing that would have to be true for this to happen — then the "
        "closest precedent with what actually followed at its horizon, then the "
        "current figures that say whether the mechanism is operating now. A "
        "causal claim with no figure behind it is a guess; say so when that is "
        "all you have."
    ),
    "degraded": (
        "**The evidence for this turn is thin.** Say what you can support, state "
        "the assumption you are reasoning from, name the missing piece and what "
        "it would have settled — and then give the read anyway, at reduced "
        "confidence. Do not answer with a refusal, do not list which tools "
        "failed as though that were the answer, and do not invent the figure "
        "that would have closed the gap."
    ),
    "social": (
        "**This turn is conversational.** One line back, then a two-line read of "
        "the current market from the context. Nothing more."
    ),
}

# Which mode each intent renders. Several intents share one because they are the
# same question about admissibility wearing different clothes.
MODE_BY_INTENT = {
    "conceptual": "conceptual",
    "greeting": "social",
    "offtopic": "social",
    "causal": "analytic",
    "comparative": "analytic",
    "scenario": "analytic",
}
DEFAULT_MODE = "current_state"


def answer_mode_for(intent: str, *, degraded: bool = False) -> str:
    """
    The rule block for this turn.

    `degraded` outranks the intent: a conceptual question needs no evidence, so
    thin evidence never degrades it, but every other intent answers differently
    when the research came back empty than when it came back full.
    """
    if degraded and intent not in ("conceptual", "greeting", "offtopic"):
        return ANSWER_MODES["degraded"]
    return ANSWER_MODES[MODE_BY_INTENT.get(intent, DEFAULT_MODE)]


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


STOCK_LEANING_KEYWORDS = (
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

# The mirror of the above, and it exists for one caller: `chat_focus` has to
# notice when a follow-up has crossed from one asset class to the other, which
# is a two-sided question. "Leaning" is the right word for both — these are
# hints from vocabulary, not resolutions, and a message that names an actual
# ticker never reaches them.
CRYPTO_LEANING_KEYWORDS = (
    "crypto",
    "kripto",
    "altcoin",
    "defi",
    "on-chain",
    "onchain",
    "stablecoin",
    "memecoin",
    "coin",
)


def stock_leaning(message: str) -> bool:
    """True if a symbol-free question is clearly about equities."""
    lowered = message.lower()
    return any(kw in lowered for kw in STOCK_LEANING_KEYWORDS)


def crypto_leaning(message: str) -> bool:
    """True if a symbol-free question is clearly about crypto."""
    lowered = message.lower()
    return any(kw in lowered for kw in CRYPTO_LEANING_KEYWORDS)


# Kept as a private alias: this module already calls it in three places and the
# rename is not what this change is about.
_stock_leaning = stock_leaning


async def load_asset_metadata() -> Tuple[Dict, Dict]:
    """
    The crypto and equity registries, or empty ones if they are cold.

    Split out because resolving a *conversation's* focus runs the resolver over
    several past messages, and fetching the registry once per message would turn
    one pair of awaits into ten. See `services.chat_focus`.
    """
    from services import asset_registry

    try:
        return (
            await asset_registry.get_crypto_metadata(),
            await asset_registry.get_stock_metadata(),
        )
    except Exception as e:  # noqa: BLE001 — a cold registry must not kill the turn
        logger.warning("Asset registry unavailable for symbol resolution: %s", e)
        return {}, {}


async def resolve_query_assets(message: str) -> QueryFocus:
    """
    Resolve the assets a message is about, in descending order of confidence.

    Only symbols that exist in the asset registry are returned. A message with
    no recognisable asset resolves to an empty focus and is answered as a
    general market question — inventing a default symbol is what used to send
    the whole pipeline off analysing the wrong thing.
    """
    crypto_meta, stock_meta = await load_asset_metadata()
    return resolve_against(message, crypto_meta, stock_meta)


def resolve_against(message: str, crypto_meta: Dict, stock_meta: Dict) -> QueryFocus:
    """
    `resolve_query_assets` without the I/O, so it can be run over many messages.

    Every symbol this returns has been checked against one of the two registries
    passed in — which is the property `chat_planner._coerce_value` relies on when
    it refuses any symbol the model names that is not in the focus.
    """
    from services.symbol_detection_service import (
        CRYPTO_ALIASES,
        EQUITY_ALIASES,
        find_pattern_matches,
    )

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
    offset: int = 0,
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

    Two deadlines bound the loop and the earlier one wins: this phase's own
    budget, and the whole turn's deadline less `ANSWER_FLOOR`. Summing phase
    budgets independently is what let the planner call fall outside the
    arithmetic; taking the minimum against a single turn deadline is what stops
    an overrun anywhere upstream from being paid for by the answer.
    """
    outcomes: List[StepOutcome] = []
    deadline = time.monotonic() + budget
    if ctx.deadline is not None:
        deadline = min(deadline, ctx.deadline - ANSWER_FLOOR)

    for index, step in enumerate(plan):
        tool = chat_tools.REGISTRY.get(step.tool)
        label = _step_label(ctx, tool, step)
        # Offset so a second round appends to the timeline rather than
        # overwriting the first — the transport upserts by id.
        step_id = str(index + offset)

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


def _render_evidence(
    outcomes: List[StepOutcome],
    budget: "prompt_budget.BudgetResult",
    gap: str = "",
) -> str:
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
    if gap:
        # Named by the reflection round, which looked at what came back and
        # concluded nothing further would close it. Without this line the model
        # sees a manifest of steps that ran and no reason to suspect the answer
        # is short of something — the difference between an answer that hedges
        # for the right reason and one that does not hedge at all.
        manifest.append(
            f"RESEARCH GAP — wanted this turn and could not be obtained: {gap}. "
            "Do not fill it in. Reason from what is here, say what that missing "
            "piece would have decided, and lower your confidence accordingly."
        )

    sections = []
    for index, outcome in enumerate(outcomes):
        text = budget.text(f"tool:{outcome.step.tool}:{index}")
        if text:
            sections.append(text)

    return "\n".join(manifest) + "\n\n" + "\n\n".join(sections)


# Templates for the suggestions shown under an answer, when the reflection round
# did not supply any. Keyed by the tool that would answer them, so a suggestion
# is only ever offered when that tool is actually available for this focus — a
# button that leads to "I could not look that up" is worse than no button.
FOLLOWUP_TEMPLATES = {
    "read_chart": ("{symbol} 4 saatlik grafikte ne diyor?", "What does the {symbol} 4h chart say?"),
    "derivatives": (
        "{symbol} funding ve likidasyonlar nerede?",
        "Where are {symbol} funding and liquidations?",
    ),
    "asset_news": ("{symbol} için son haberler ne?", "What is the latest news on {symbol}?"),
    "historical_precedent": (
        "Bunun benzeri geçmişte ne zaman oldu?",
        "When did something like this happen before?",
    ),
    "stock_fundamentals": ("{symbol} değerlemesi ne durumda?", "How is {symbol} valued?"),
    "macro_board": ("Makro tarafta ne var?", "What is the macro backdrop doing?"),
    "market_voices": ("Bu konuda kim ne dedi?", "Who has said what about this?"),
}

# Turkish-specific characters are the cheapest reliable signal for which of the
# two templates to render. The alternative — asking the model — is a whole extra
# call for a button label.
_TURKISH_CHARS = set("çğıöşüÇĞİÖŞÜ")

# Turkish written without its own characters is common — "nedir", "nasil",
# "neden" all type cleanly on an English keyboard — so the character test alone
# answered "funding rate nedir?" in English. These are the interrogatives that
# carry a question, matched as whole words so "ne" does not fire inside "news".
_TURKISH_WORDS = (
    "ne",
    "nedir",
    "nasil",
    "nasıl",
    "neden",
    "niye",
    "niçin",
    "kac",
    "kaç",
    "hangi",
    "kim",
    "icin",
    "için",
    "mi",
    "mı",
    "mu",
    "mü",
    "var",
    "yok",
    "gibi",
)

_TURKISH_WORD_RE = re.compile(
    r"\b(?:" + "|".join(_TURKISH_WORDS) + r")\b", re.IGNORECASE | re.UNICODE
)


def _is_turkish(message: str) -> bool:
    """
    Which language a follow-up button should be written in.

    A heuristic on purpose. The alternative is asking the model, which is a
    whole extra call for a button label — and getting it wrong costs a button
    in the wrong language, not a wrong answer.
    """
    if set(message or "") & _TURKISH_CHARS:
        return True
    return bool(_TURKISH_WORD_RE.search(message or ""))


def suggest_followups(
    state, intent: str, outcomes: List[StepOutcome], message: str = ""
) -> Tuple[str, ...]:
    """
    Two or three next questions, when the reflection round did not supply them.

    Templated rather than generated, because the alternative is a fourth serial
    LLM call in a budget that has about thirty seconds of slack. The reflection
    round produces better ones and produces them for free — this is the floor
    for the turns where it did not run.

    Filtered to tools that are genuinely offerable for this focus, so a
    suggestion never leads to a question the next turn cannot research.
    """
    if intent in ("greeting", "offtopic"):
        return ()

    symbol = state.primary or ""
    already = {outcome.step.tool for outcome in outcomes if outcome.status == "done"}
    turkish = _is_turkish(message)

    offerable = {tool.name for tool in chat_tools.available_tools(message, state.focus, intent)}

    suggestions: List[str] = []
    for tool, (tr, en) in FOLLOWUP_TEMPLATES.items():
        if tool in already or tool not in offerable:
            continue
        template = tr if turkish else en
        if "{symbol}" in template and not symbol:
            continue
        suggestions.append(template.format(symbol=symbol))
        if len(suggestions) >= chat_planner.MAX_FOLLOWUPS:
            break

    return tuple(suggestions)


# Beyond this many links a citation list stops being read and starts being
# scrolled past.
MAX_CITATIONS = 8


def _citations_from(outcomes: List[StepOutcome]) -> List[Dict[str, str]]:
    """Every source a completed step actually used, deduped by URL."""
    from urllib.parse import urlparse

    seen: set = set()
    citations: List[Dict[str, str]] = []
    for outcome in outcomes:
        if outcome.status != "done":
            continue
        for url in outcome.result.sources:
            if not url or url in seen:
                continue
            seen.add(url)
            citations.append(
                {
                    "url": url,
                    "label": (urlparse(url).hostname or url).removeprefix("www."),
                    "tool": outcome.step.tool,
                }
            )
            if len(citations) >= MAX_CITATIONS:
                return citations
    return citations


def build_reflection_digest(outcomes: List[StepOutcome]) -> str:
    """
    What the research produced, in a form that is safe to plan against.

    This is the load-bearing function of the reflection round. `chat_planner`'s
    docstring documents a real invariant — the planner never reads a web page,
    because by the time any page is fetched the plan is already fixed — and the
    reflection round runs *after* pages are fetched. Preserving the invariant
    therefore has to be structural rather than a line in a prompt.

    So this is built from the step's *status* and from `chat_tools.digest_line`,
    which each tool implements over the scalars its executor computed: a count,
    a hostname, whether a field was present. `ToolResult.block` never appears
    here, and neither does `ToolResult.detail` — the latter is written for the
    timeline and several tools interpolate upstream text into it.

    `tests/test_chat_reflection.py` puts an instruction inside a block and
    asserts it does not survive into the rendered prompt. That test is the thing
    to argue with before making this richer.
    """
    lines = []
    for outcome in outcomes:
        note = chat_tools.digest_line(outcome.tool, outcome.result)
        lines.append(f"- {outcome.step.tool} [{outcome.status}] — {note}")
    return "\n".join(lines) or "- nothing ran"


def _history_block(history: Optional[List[Dict[str, str]]]) -> str:
    """The recent turns, bounded — the client sends the entire transcript."""
    if not history:
        return "(this is the first message of the conversation)"

    lines = []
    for msg in history[-HISTORY_TURNS:]:
        is_user = msg.get("role") == "user"
        speaker = "User" if is_user else "Oracle"
        limit = HISTORY_CHARS if is_user else HISTORY_CHARS_ASSISTANT
        content = (msg.get("content") or "").strip()[:limit]
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
    focus_override: Optional[str] = None,
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

    # One deadline for the whole turn, set before anything can spend time. Every
    # phase below takes `min(its own budget, what is left)` against this, so an
    # overrun in the planner or in a slow tool is paid for by the phases after
    # it rather than by the answer. The job runner's own `TURN_TIMEOUT` is the
    # hard stop; this is the cooperative one that lets the turn degrade
    # gracefully instead of being killed with nothing to show.
    turn_deadline = time.monotonic() + TURN_TIMEOUT

    # The focus spans the conversation, not just this message. `resolve_state`
    # replays the same registry-backed resolver over the recent user turns and
    # decides whether this one inherits what it found — which is what makes
    # "peki RSI'ı?" a question about BTC rather than a question about nothing.
    state = await chat_focus.resolve_state(message, history, override=focus_override)
    focus, intent = state.focus, state.intent

    # What this user has told the assistant in earlier sessions. Never fails a
    # turn: an unreachable memory is an empty one.
    memory = await chat_memory_service.recall(user_id)

    # The snapshot is pinned rather than planned: it is the one source that
    # outranks everything else, so no plan gets to leave it out. It also runs
    # first, which is what lets later steps read `ctx.snapshot`.
    turn_plan = await chat_planner.plan_turn(
        message,
        focus,
        user_id=user_id,
        intent=intent,
        history=history,
        # A concise turn sees a shorter catalogue. Not to make it thinner — the
        # plan is the same either way — but a shorter list is a faster and more
        # reliable pick, and a concise answer has less room to recover from a
        # wrong one.
        limit=(
            chat_tools.MAX_CATALOGUE_TOOLS_CONCISE
            if style == "concise"
            else chat_tools.MAX_CATALOGUE_TOOLS
        ),
    )
    # The planner reads the question rather than its keywords, so where it names
    # an intent the taxonomy knows, it is the better answer.
    intent = turn_plan.intent
    plan = [chat_tools.PlannedStep(chat_tools.PINNED_TOOL, {})] + turn_plan.steps
    ctx = chat_tools.ToolContext(
        message=message,
        focus=focus,
        deadline=turn_deadline,
        user_id=user_id,
        # Known before the first step runs, so the snapshot can drop the
        # market-wide sections a dedicated tool is about to cover per-asset.
        planned=tuple(step.tool for step in plan),
    )
    outcomes = await run_plan(ctx, plan, on_step)

    # ── the second look ──────────────────────────────────────────────────────
    #
    # One bounded round: was that enough, and if not, what would fix it. This is
    # what turns "the tool came back empty" from a dead end into either another
    # attempt or an honest, reasoned answer that names the gap.
    reflection = chat_planner.Reflection()
    remaining = turn_deadline - time.monotonic()
    worth_reflecting = (
        settings.CHAT_REFLECTION_ENABLED
        and intent not in ("conceptual", "greeting", "offtopic")
        # A concise turn pays for a second round only when there is plenty left.
        # Not to make it thinner — the first round's plan is the same either way
        # — but a short answer has less to gain from a marginal extra source.
        and (style == "detailed" or remaining > 90)
        and remaining > ANSWER_FLOOR + REFLECT_TIMEOUT + MIN_REFLECT_VALUE
    )

    if worth_reflecting:
        reflection = await chat_planner.reflect_turn(
            message,
            focus,
            intent,
            build_reflection_digest(outcomes),
            chat_tools.available_tools(message, focus, intent, user_id=user_id),
            user_id=user_id,
        )
        # What the turn learned about the person, as opposed to about the
        # market. Fire-and-forget: a memory write must never be something the
        # answer waits on.
        if reflection.remember:
            asyncio.create_task(chat_memory_service.remember(user_id, reflection.remember))

        if reflection.steps:
            ctx.planned = ctx.planned + tuple(step.tool for step in reflection.steps)
            outcomes += await run_plan(
                ctx, reflection.steps, on_step, budget=REFLECT_PHASE_BUDGET, offset=len(outcomes)
            )

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
        # Ranked just under the snapshot and above every derived block. It is
        # ~30 tokens and it is the only thing in the prompt that says which
        # asset the evidence is about when the question did not name one — a
        # turn that loses it answers confidently about an unnamed subject.
        prompt_budget.Block("focus", chat_focus.describe(state), priority=90),
        # Low: it shapes the answer rather than grounding it, so when the prompt
        # is tight this is worth less than any measured figure. It is also small
        # enough that it rarely comes to that.
        prompt_budget.Block("memory", chat_memory_service.describe(memory), priority=12),
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

    # "Every research step came back with nothing" is a different question from
    # "no research was planned". A conceptual turn plans little and needs less,
    # so an empty result set there is success, not a gap — which is why the mode
    # selector, not this line, decides whether `degraded` can apply at all.
    researched = [o for o in outcomes if o.step.tool != chat_tools.PINNED_TOOL]
    everything_empty = bool(researched) and all(
        o.status in ("empty", "failed", "skipped") for o in researched
    )
    # Two independent ways to end up short: every step came back with nothing,
    # or the reflection round looked at what did come back and said it was not
    # enough with no remedy available. Either one changes what an honest answer
    # looks like.
    unresolved_gap = not reflection.sufficient and not reflection.steps
    degraded = everything_empty or unresolved_gap

    followups = reflection.followups or suggest_followups(state, intent, outcomes, message)

    user_prompt = render_prompt(
        "chat/turn",
        evidence=_render_evidence(outcomes, budget, reflection.missing if unresolved_gap else ""),
        history=budget.text("history") or "(this is the first message of the conversation)",
        question=message,
        answer_mode=answer_mode_for(intent, degraded=degraded),
        style_rule=STYLE_RULES[style],
    )

    # The sidebar wants short names, not the planner-facing descriptions.
    sources_used = [
        o.step.tool.replace("_", " ").capitalize() for o in outcomes if o.status == "done"
    ]

    # The real URLs, which used to be collected and then thrown away: this
    # function overwrote `sources` with the tool names above, so
    # `ToolResult.sources` never left the server and the client had no citation
    # list independent of what the model chose to inline. Both are returned now
    # — the names for the sidebar, the links for the reader.
    #
    # The visible label is the host, not any title the page supplied. A
    # search-result title is attacker-influenced text; React escapes it, but the
    # host is both safer and tidier, and it is what a reader actually scans for.
    citations = _citations_from(outcomes)

    provider = await llm.provider_for(user_id, "chat")

    async def _answer(*, reasoning: bool) -> Optional[str]:
        return await llm.generate(
            user_prompt,
            system=system_prompt,
            temperature=0.3,
            top_p=0.9,
            max_tokens=MAX_TOKENS[style],
            timeout=CHAT_TIMEOUT,
            reasoning=reasoning,
            # Ollama-only knobs; other providers ignore them. The real ceiling is
            # PROMPT_TOKEN_BUDGET, enforced above — this is what the server is
            # asked to allocate, and it does not by itself prevent truncation.
            extra={"repeat_penalty": 1.1, "num_ctx": settings.LLM_NUM_CTX},
            prefer=provider,
        )

    try:
        # Reasoning is on for both styles now. It used to be detailed-only, on
        # the argument that a concise answer is "two figures and a risk" and
        # pays the latency for nothing — but that is what made concise answers
        # feel superficial: a small local model was answering a market question
        # in a single pass. The <think> block is stripped centrally in the LLM
        # layer, so this decides how the model reasons, never what the user sees.
        response = await _answer(reasoning=True)

        # A reasoning pass shares `num_predict` with the answer on Ollama, so a
        # long think can consume the whole allowance and leave nothing after the
        # stripped block. That is a specific, recognisable failure — an empty
        # reply where a reasoning model was asked — and it is cheap to make
        # non-fatal by asking once more without it.
        if not (response or "").strip():
            logger.info("Empty reply with reasoning on; retrying without it")
            response = await _answer(reasoning=False)
        elif response.rstrip()[-1:] not in _COMPLETE_ENDINGS:
            # Not retried, only reported. A retry would spend another full
            # generation, and the fix for a real ceiling problem is the ceiling.
            logger.warning(
                "Answer may have hit the %s-token ceiling — it ends %r",
                MAX_TOKENS[style],
                response.rstrip()[-40:],
            )
    except Exception as e:  # noqa: BLE001 — surface as a chat message, not a 500
        logger.exception("Chat generation failed")
        return {
            "response": f"🔴 Something went wrong while generating the answer: {e}",
            "thinking_time": round((datetime.now() - start_time).total_seconds(), 1),
            "sources": [],
            "detected_symbol": focus.primary,
            "focus_inherited": bool(state.inherited),
            "intent": intent,
            "followups": list(followups),
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
            "focus_inherited": bool(state.inherited),
            "intent": intent,
            "followups": list(followups),
        }

    answer = response.strip()
    if not answer:
        answer = "I could not produce an answer for that. Please try rephrasing the question."

    return {
        "response": answer,
        "thinking_time": elapsed,
        "sources": sources_used,
        "detected_symbol": focus.primary,
        # Whether the subject was asked for or carried. The badge in the UI
        # needs it, and so does anyone reading a log wondering why a turn
        # answered about an asset the question never mentioned.
        "focus_inherited": bool(state.inherited),
        "intent": intent,
        "followups": list(followups),
        "citations": citations,
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
