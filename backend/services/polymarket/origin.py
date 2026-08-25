"""
Why a market exists, and what moved it since — as its own answer.

This runs as a job of its own, started by the same button as the verdict and
finishing whenever it finishes. Nothing downstream waits for it and nothing it
produces reaches the synthesis prompt, which is what makes the last section of
this file safe to write at all.

The mechanism is the market's own price history. `moves.detect_sharp_moves`
returns the windows in which the crowd re-priced something, and those windows
are timestamps rather than guesses — so an open-ended question ("why does this
market exist?") becomes a searchable one ("what broke on the afternoon of the
20th?"). Two independent NATO markets repricing inside the same six hours is not
a coincidence a model has to be persuaded of; it is a measurement.

Three constraints hold the stage honest.

**A story must be dated and inside a window to be named as a trigger.** Search
backends return a publication date most of the time and prose in the date field
some of the time. An undated result is now kept — as *context*, marked as such,
and barred in Python from being a trigger. It was previously thrown away, which
is why markets whose backend happened to return unparseable dates reported
"undetermined" with the reporting sitting right there unread.

**A trigger must be one of the candidates.** The model picks from a numbered
list and its choice is checked against that list in Python afterwards. A trigger
naming a source that was not offered is dropped.

**When nothing can be traced, the answer is a labelled hypothesis, not silence.**
`conjecture` says what kind of thing opens a market like this one — a regulator's
calendar, a scheduled vote, a listing decision — grounded in the category's
mechanism and the market's own dates. It may name institutions and event types;
it may not assert that a particular event happened on a particular day, and the
prompt says so in those words. It carries no source id, it is populated only
when there is no traced answer to displace, and it is fenced out of the verdict
entirely. A reader can tell the two apart because they are different statuses
and the UI badges them differently.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from config import settings
from models.polymarket import (
    MarketFacts,
    Origin,
    OriginReport,
    SharpMove,
    SourceRef,
    SweepAttempt,
    Trigger,
)
from services.polymarket.registry import CategoryStrategy

logger = logging.getLogger(__name__)

ORIGIN_SEARCH_BUDGET = 30.0
ORIGIN_LLM_TIMEOUT = 35.0
SEARCH_CONCURRENCY = 4

#: How far either side of a window a story may be published and still count.
#: A day, because a wire moves within hours of an event while an analysis piece
#: explaining it lands the next morning, and both are the story.
WINDOW_SLACK = timedelta(hours=24)

#: Windows searched. Beyond the top few the moves are small and the budget is
#: better spent reading the ones that mattered.
MAX_WINDOWS = 3

MAX_CANDIDATES_PER_WINDOW = 5

#: Undated or out-of-window stories kept as context, across all windows. They
#: cannot be cited as triggers, so their only job is to stop the model reasoning
#: about a subject it has been told nothing about — a handful is enough for that
#: and more would spend the context window on material that cannot be the answer.
MAX_CONTEXT_CANDIDATES = 6

ORIGIN_STAGES = [
    {"key": "windows", "label": "Measuring when the price moved"},
    {"key": "search", "label": "Searching those days"},
    {"key": "explain", "label": "Explaining why it opened"},
]


def _recency_window(when: datetime) -> str | None:
    """
    The search backend's recency filter for a target date.

    Only d/w/m/y are safe to pass — two of the engines behind `backend="auto"`
    index a dict by this value and raise on anything else. A custom range is not
    on offer, which is why the results are date-filtered again afterwards.
    """
    age_days = (datetime.now(UTC) - when).days
    if age_days <= 2:
        return "d"
    if age_days <= 8:
        return "w"
    if age_days <= 32:
        return "m"
    if age_days <= 366:
        return "y"
    return None


def _in_window(published: datetime | None, move: SharpMove) -> bool:
    if published is None:
        return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    return (move.started_at - WINDOW_SLACK) <= published <= (move.ended_at + WINDOW_SLACK)


def _parse_date(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalise_id(raw: str) -> str:
    """
    A citation as the ledger keys it.

    Models decorate ids — "[S3]", "S3.", "s3" — and a lookup that only accepts
    the bare form drops a correct citation over punctuation. This forgives the
    decoration and nothing else: an id that is not in the list still fails, which
    is the check that matters.
    """
    cleaned = raw.strip().strip("[]().,;: ").upper()
    return cleaned


async def _search_window(
    subject: str,
    move: SharpMove,
    index: int,
) -> tuple[list[dict[str, Any]], list[SweepAttempt]]:
    """
    Search one window. Returns (hits, attempts).

    Every hit comes back, tagged with `in_window` rather than filtered on it.
    Dropping the rest was the old behaviour and it cost more than it saved: on a
    market whose backend returned prose in the date field, every result was
    discarded, the candidate list came back empty and the model was never asked
    anything at all. A story that cannot date itself still says what the subject
    is about, and the trigger check further down does not depend on the list
    being pre-cleaned.
    """
    from services.web_search_service import search_news

    when = move.started_at
    # The calendar date in the query text is what actually pulls in-window
    # results; the recency filter alone returns the same broad coverage every
    # time. Measured against a live market: "NATO Russia" returned nothing from
    # the target day, "NATO Russia August 20 2026" returned four of five.
    queries: list[tuple[str, str | None]] = [
        (f"{subject} {when:%B %-d %Y}", _recency_window(when)),
        (f"{subject} news {when:%B %Y}", _recency_window(when)),
    ]
    # The opening window gets one undated query as well. A market opened three
    # months ago has no fresh reporting on its opening day, so the two dated
    # queries above come back empty and the stage would have nothing at all to
    # reason from — not even enough to say what kind of question this is.
    if move.kind == "creation":
        queries.append((subject, None))

    hits: list[dict[str, Any]] = []
    attempts: list[SweepAttempt] = []
    for query, timelimit in queries:
        try:
            found = await search_news(query, max_results=6, timeout=10.0, timelimit=timelimit)
        except Exception as error:  # noqa: BLE001
            logger.info("Origin search failed (%s): %s", query, error)
            attempts.append(
                SweepAttempt(kind="news", target=query, outcome="error", detail=str(error)[:120])
            )
            continue
        attempts.append(
            SweepAttempt(
                kind="news",
                target=query,
                outcome="hits" if found else "empty",
                hits=len(found),
            )
        )
        for hit in found:
            published = _parse_date(hit.get("published_at"))
            hits.append(
                {
                    **hit,
                    "published_at": published,
                    "move_index": index,
                    "in_window": _in_window(published, move),
                }
            )

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for hit in hits:
        url = hit.get("url") or ""
        if url and url not in seen:
            seen.add(url)
            unique.append(hit)

    # In-window first, and only those are capped per window — the context tail is
    # trimmed once, globally, so one loud window cannot crowd out the others.
    in_window = [h for h in unique if h["in_window"]][:MAX_CANDIDATES_PER_WINDOW]
    context = [h for h in unique if not h["in_window"]]
    return in_window + context, attempts


def _render_windows(moves: list[SharpMove]) -> str:
    lines = []
    for index, move in enumerate(moves):
        if move.kind == "creation":
            lines.append(f"[{index}] Market opened {move.started_at:%Y-%m-%d %H:%M}Z")
        else:
            lines.append(
                f"[{index}] {move.started_at:%Y-%m-%d %H:%M}Z to {move.ended_at:%H:%M}Z — "
                f"{move.outcome_label or 'price'} moved {move.price_from:.2f} to "
                f"{move.price_to:.2f} ({move.delta:+.2f})"
            )
    return "\n".join(lines) or "No windows could be measured."


def _render_candidates(candidates: dict[str, dict[str, Any]]) -> str:
    """
    The candidate list, with the citable half in its own id namespace.

    The split is carried by the ids, not just by a heading. Told in prose which
    section was citable and handed one flat run of S-ids, a local model cited a
    context story anyway — observed on a live Fed market, where the trigger was
    then deleted in Python and the panel showed nothing at all. `C` ids make the
    mistake visible in the citation itself, and the membership check catches it
    either way.
    """
    if not candidates:
        return "No stories were found for any window."

    citable: list[str] = []
    context: list[str] = []
    for source_id, hit in candidates.items():
        published = hit["published_at"]
        title = hit.get("title", "")
        snippet = (hit.get("snippet") or "")[:300]
        if source_id.startswith("S"):
            citable.append(
                f"[{source_id}] window {hit['move_index']} — {published:%Y-%m-%d %H:%M}Z — "
                f"{hit.get('source') or ''} — {title}\n    {snippet}"
            )
        else:
            when = f"{published:%Y-%m-%d}" if published else "undated"
            context.append(
                f"[{source_id}] {when} — {hit.get('source') or ''} — {title}\n    {snippet}"
            )

    blocks = []
    if citable:
        blocks.append(
            "### S — dated, inside a window. Only these ids may be cited as triggers.\n\n"
            + "\n".join(citable)
        )
    else:
        blocks.append(
            "### S — dated, inside a window. Only these ids may be cited as triggers.\n\n"
            "None. There are no S ids, so no trigger can be named for any window."
        )
    if context:
        blocks.append(
            "### C — background only. Undated or outside every window. A trigger citing a "
            "C id is deleted.\n\n" + "\n".join(context)
        )
    return "\n\n".join(blocks)


async def trace_origin(
    facts: MarketFacts,
    subject: str,
    strategy: CategoryStrategy,
    *,
    user_id: str | None = None,
) -> tuple[Origin, dict[str, dict[str, Any]], list[SweepAttempt]]:
    """
    Work out why this market exists. Never raises.

    Returns the origin, the candidate stories keyed by the id they were offered
    under, and the record of every search that was run — including the ones that
    came back empty, which is the only thing that distinguishes "nobody covered
    this" from "we could not reach anything".

    The model is asked even when no candidate was found. That is the change this
    module exists for: with nothing to cite there is still a category, an opening
    date and a set of resolution criteria, and those are enough to say what kind
    of thing usually opens a market like this one.
    """
    moves = facts.moves[:MAX_WINDOWS]
    attempts: list[SweepAttempt] = []
    candidates: dict[str, dict[str, Any]] = {}

    if moves:
        semaphore = asyncio.Semaphore(SEARCH_CONCURRENCY)

        async def one(index: int, move: SharpMove):
            async with semaphore:
                return await _search_window(subject, move, index)

        tasks = [asyncio.create_task(one(i, m)) for i, m in enumerate(moves)]
        _done, pending = await asyncio.wait(tasks, timeout=ORIGIN_SEARCH_BUDGET)
        for task in pending:
            task.cancel()
        if pending:
            attempts.append(
                SweepAttempt(kind="news", target=f"{len(pending)} windows", outcome="timeout")
            )

        # Iterated in window order rather than over the completion set. Ids are
        # what a trigger cites, and `asyncio.wait` returns an unordered set, so
        # numbering by completion made S1 mean a different story on every run —
        # invisible in a single response and impossible to reason about across two.
        collected: list[dict[str, Any]] = []
        for task in tasks:
            if task in pending:
                continue
            try:
                hits, hit_attempts = task.result()
            except Exception:  # noqa: BLE001
                continue
            attempts.extend(hit_attempts)
            collected.extend(hits)

        # "S", not "O". The shared rules block and the system prompt both teach
        # the model that a source is cited as [S1], so numbering these candidates
        # in a different namespace produced a model that dutifully answered with
        # S-ids against an O-keyed list — every trigger then failed the
        # membership check and the stage reported "undetermined" on markets whose
        # candidates were sitting right there. Observed on a live NATO market
        # with five in-window stories found and zero triggers kept.
        citable = 0
        context = 0
        for hit in sorted(collected, key=lambda h: (not h["in_window"], h["move_index"])):
            if hit["in_window"]:
                citable += 1
                candidates[f"S{citable}"] = hit
            else:
                if context >= MAX_CONTEXT_CANDIDATES:
                    continue
                context += 1
                candidates[f"C{context}"] = hit

    parsed = await _ask(facts, moves, candidates, strategy, user_id)
    if parsed is None:
        return Origin(status="undetermined"), candidates, attempts

    triggers: list[Trigger] = []
    for raw in parsed.get("triggers") or []:
        if not isinstance(raw, dict):
            continue
        source_id = _normalise_id(str(raw.get("source_id") or ""))
        hit = candidates.get(source_id)
        # A trigger naming a story that was not on the list is a fabrication,
        # not a near miss — there is nothing to correct it to.
        if hit is None:
            logger.info("Dropping origin trigger citing unknown source %r", source_id)
            continue
        # The dating rule lives here rather than in the prompt. The only thing
        # tying a story to a price move is when it was published, so an undated
        # or out-of-window item has no claim on any window however plausible the
        # model found it. A prompt can ask for this; only code can guarantee it.
        if hit["published_at"] is None or not hit["in_window"]:
            logger.info("Dropping origin trigger citing out-of-window source %r", source_id)
            continue
        summary = str(raw.get("summary") or "").strip()
        if not summary:
            continue
        triggers.append(
            Trigger(
                summary=summary,
                source_id=source_id,
                occurred_at=hit["published_at"],
                move_index=hit["move_index"],
            )
        )

    rationale = parsed.get("opening_rationale")
    rationale = str(rationale).strip() if rationale else None

    # The hypothesis exists to fill a silence, so anything that fills it first
    # displaces the hypothesis. Showing both would put a guess next to a sourced
    # answer and invite the reader to average them.
    #
    # The gate is here rather than in the prompt because the model cannot know
    # which of its triggers will survive: one citing a background source is
    # deleted after it replies. Asked to withhold the conjecture whenever it
    # named a trigger, it withheld one for a trigger that was then dropped, and
    # the reader got an empty panel. So the prompt asks for it every time and
    # this is what decides whether anyone sees it.
    conjecture: str | None = None
    basis: list[str] = []
    if not triggers and not rationale:
        raw_conjecture = parsed.get("conjecture")
        conjecture = str(raw_conjecture).strip() if raw_conjecture else None
        if conjecture:
            basis = [
                str(item).strip()
                for item in (parsed.get("conjecture_basis") or [])
                if str(item).strip()
            ]

    if triggers or rationale:
        status = "traced"
    elif conjecture:
        status = "conjectured"
    else:
        status = "undetermined"

    return (
        Origin(
            status=status,
            opening_rationale=rationale,
            triggers=triggers,
            conjecture=conjecture,
            conjecture_basis=basis,
        ),
        candidates,
        attempts,
    )


async def _ask(
    facts: MarketFacts,
    moves: list[SharpMove],
    candidates: dict[str, dict[str, Any]],
    strategy: CategoryStrategy,
    user_id: str | None,
) -> dict[str, Any] | None:
    """
    One call, all windows at once. None when the chain had nothing to say.

    Not budgeted through `prompt_budget.fit` the way `synthesis` is, because this
    prompt is bounded by construction rather than by whatever the sweep happened
    to scrape: at most `MAX_WINDOWS * MAX_CANDIDATES_PER_WINDOW` citable items
    plus `MAX_CONTEXT_CANDIDATES` background ones, each a snippet clipped to 300
    characters, and the criteria clipped to 1200. That worst case is a few
    thousand tokens against a 32k window. `synthesis` needs the budget because it
    carries scraped article bodies, which have no such ceiling.
    """
    from services import llm
    from services.prompts import load_prompt, render_prompt

    try:
        prompt = render_prompt(
            "polymarket/origin",
            question=facts.market.question,
            created_at=(
                f"{facts.market.created_at:%Y-%m-%d}" if facts.market.created_at else "unknown"
            ),
            end_date=(f"{facts.market.end_date:%Y-%m-%d}" if facts.market.end_date else "unknown"),
            resolution_criteria=(facts.resolution_criteria or "Not published.")[:1200],
            category=strategy.label,
            windows=_render_windows(moves),
            candidates=_render_candidates(candidates),
            category_guidance=load_prompt(strategy.prompt),
            rules=load_prompt("polymarket/rules"),
        )
        system = load_prompt("polymarket/system_forecaster")
    except FileNotFoundError:
        logger.error("Polymarket origin prompt is missing — no origin can be traced")
        return None

    try:
        raw = await llm.generate(
            prompt,
            system=system,
            temperature=0.1,
            max_tokens=500,
            timeout=ORIGIN_LLM_TIMEOUT,
            reasoning=False,
            json_mode=True,
            extra={"num_ctx": settings.LLM_NUM_CTX, "repeat_penalty": 1.1},
            prefer=await llm.provider_for(user_id, "reports"),
        )
    except Exception as error:  # noqa: BLE001
        logger.info("Origin generation failed: %s", error)
        return None

    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.info("Origin returned unparseable JSON")
        return None
    return parsed if isinstance(parsed, dict) else None


def _sources(candidates: dict[str, dict[str, Any]]) -> list[SourceRef]:
    """The candidate list as source refs, so a trigger's id resolves to a link."""
    from urllib.parse import urlparse

    refs: list[SourceRef] = []
    for source_id, hit in candidates.items():
        url = hit.get("url") or ""
        host = (urlparse(url).hostname or "").lower()
        refs.append(
            SourceRef(
                id=source_id,
                url=url,
                domain=host[4:] if host.startswith("www.") else host,
                title=str(hit.get("title") or "")[:200],
                published_at=hit.get("published_at"),
                # Tier is a corroboration rank for the evidence ledger and means
                # nothing here: these were picked for when they were published,
                # not for whose desk filed them. Flat 3 rather than a number that
                # would look like a quality judgement nobody made.
                tier=3,
                via="news",
                body_chars=0,
            )
        )
    return refs


async def build_origin_report(
    raw: dict[str, Any],
    *,
    user_id: str | None = None,
    on_stage=None,
) -> OriginReport:
    """
    The full "why was this bet opened" answer for one Gamma payload. Never raises.

    `on_stage` is the job runner's stage callback; it is optional so the stage
    can be exercised directly in tests without a job around it.
    """
    from services.polymarket import facts as facts_stage
    from services.polymarket.category import market_subject
    from services.polymarket.registry import strategy_for

    def stage(key: str) -> None:
        if on_stage:
            on_stage(key)

    stage("windows")
    market_facts, _micro = await facts_stage.gather_facts(raw, include_trades=False)
    market = market_facts.market
    strategy = strategy_for(market.category)

    identity = {
        "market_id": market.market_id,
        "slug": market.slug,
        "question": market.question,
        "category": market.category,
    }

    if not settings.USE_AI:
        return OriginReport(
            status="undetermined",
            moves=market_facts.moves[:MAX_WINDOWS],
            generated_at=datetime.now(UTC),
            **identity,
        )

    stage("search")
    origin, candidates, attempts = await trace_origin(
        market_facts, market_subject(market.question), strategy, user_id=user_id
    )

    stage("explain")
    return OriginReport(
        status=origin.status,
        opening_rationale=origin.opening_rationale,
        triggers=origin.triggers,
        conjecture=origin.conjecture,
        conjecture_basis=origin.conjecture_basis,
        moves=market_facts.moves[:MAX_WINDOWS],
        sources=_sources(candidates),
        attempted=attempts,
        generated_at=datetime.now(UTC),
        **identity,
    )


async def start_origin_job(raw: dict[str, Any], *, user_id: str | None = None):
    """
    Run `build_origin_report` as a staged job, or re-attach to the one in flight.

    The import is deferred because `analysis_jobs` pulls in the AI layer at
    module scope; importing it at the top of this module would make `main.py`'s
    early router import reach a half-initialised package.

    Keyed by slug like the verdict job, and distinguished from it by kind — the
    key namespace is shared, so a market's origin run and its analysis run would
    otherwise dedup into each other.
    """
    from services import analysis_jobs

    slug = str(raw.get("slug") or raw.get("id") or "")

    async def runner(controls: analysis_jobs.JobControls) -> dict[str, Any]:
        report = await build_origin_report(raw, user_id=user_id, on_stage=controls.on_stage)
        return report.model_dump(mode="json")

    return await analysis_jobs.start(
        slug,
        analysis_jobs.KIND_POLYMARKET_ORIGIN,
        ORIGIN_STAGES,
        runner,
        owner_id=user_id,
    )
