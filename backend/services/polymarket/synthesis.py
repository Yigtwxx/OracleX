"""
Building both sides of the case, and weighing it.

Two LLM calls, both returning structured claims rather than prose, because the
attribution pass that follows can only audit objects. Everything the model
returns is checked in Python before it reaches a reader: source ids against the
ledger, figures against the facts block, confidence against the ceiling the
evidence earned.

The prompt is budgeted rather than assembled and hoped for. `LLM_NUM_CTX` is
32768 and eight scraped bodies clipped to 2500 characters each is already most
of that once the facts, the arguments and the rules are in — and Ollama truncates
from the front, so an overflow deletes the system prompt and with it every rule
that stops the model inventing a source. What `fit` drops is reported as a
coverage gap: a body that did not reach the prompt is a body that did not inform
the answer, and the reader is told so.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from config import settings
from models.polymarket import Claim, EvidenceCoverage, MarketFacts, Microstructure
from services.polymarket.attribution import EvidenceLedger
from services.polymarket.evidence import Sweep
from services.polymarket.registry import CategoryStrategy

logger = logging.getLogger(__name__)

ARGUMENTS_TIMEOUT = 50.0
SYNTHESIS_TIMEOUT = 60.0
ARGUMENTS_MAX_TOKENS = 900
SYNTHESIS_MAX_TOKENS = 1100

#: Headroom left under LLM_NUM_CTX for the reply and the system prompt. The
#: estimator over-counts prose on purpose, so this is a floor rather than a
#: guess, but the reply itself is not estimated at all and has to be reserved.
BUDGET_HEADROOM_TOKENS = 1200


def render_evidence(sweep: Sweep, ledger: EvidenceLedger) -> tuple[str, str]:
    """
    The evidence as the prompt sees it: bodies first, then snippet-only sources.

    Split into two blocks so the budget can drop snippets before it touches
    articles — a snippet is a claim about a piece of reporting, and losing one
    costs less than losing the reporting itself.
    """
    bodies: list[str] = []
    snippets: list[str] = []

    for ref in ledger.sources:
        head = f"[{ref.id}] {ref.domain} — {ref.title}"
        if ref.published_at:
            head += f" ({ref.published_at:%Y-%m-%d})"
        body = sweep.body_for(ref.id)
        if body:
            bodies.append(f"{head}\n{body}")
        else:
            snippet = sweep.snippet_for(ref.id)
            snippets.append(f"{head}\n    {snippet[:400]}")

    return "\n\n".join(bodies), "\n".join(snippets)


def render_microstructure(micro: Microstructure) -> str:
    lines = []
    if micro.leading_outcome and micro.leading_price is not None:
        lines.append(f"Leading outcome: {micro.leading_outcome} at {micro.leading_price:.4f}")
    for label, value in (
        ("24h drift (points)", micro.drift_24h),
        ("7d drift (points)", micro.drift_7d),
        ("Spread", micro.spread),
        ("Top holder share", micro.top_holder_share),
        ("Top five holder share", micro.top5_holder_share),
    ):
        lines.append(f"{label}: {value if value is not None else 'unknown'}")
    lines.extend(micro.notes)
    return "\n".join(lines)


def render_coverage(coverage: EvidenceCoverage) -> str:
    parts = [
        f"{coverage.total_sources} sources across {coverage.distinct_domains} outlets",
        f"{coverage.tier1_sources} read in full from a named desk",
        f"{coverage.body_chars:,} characters of article text",
        f"{coverage.queries_answered} of {coverage.queries_issued} searches returned anything",
    ]
    failed = [a.target for a in coverage.attempted if a.outcome in ("error", "timeout")]
    if failed:
        parts.append("Could not be read: " + ", ".join(failed[:5]))
    if coverage.dropped:
        parts.append("Too long for this prompt: " + ", ".join(coverage.dropped[:5]))
    return "; ".join(parts)


def render_claims(claims_for: list[Claim], claims_against: list[Claim]) -> str:
    def side(name: str, claims: list[Claim]) -> str:
        if not claims:
            return f"{name}: nothing the evidence supports."
        rows = [f"- ({c.weight}) {c.text} {list(c.sources)}" for c in claims]
        return f"{name}:\n" + "\n".join(rows)

    return side("For", claims_for) + "\n\n" + side("Against", claims_against)


def _parse_claims(raw: Any, key: str) -> list[Claim]:
    """Whatever the model returned for one side, as Claims. Never raises."""
    rows = (raw or {}).get(key) if isinstance(raw, dict) else None
    claims: list[Claim] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        sources = row.get("sources")
        claims.append(
            Claim(
                text=text,
                sources=[str(s).strip() for s in sources if str(s).strip()]
                if isinstance(sources, list)
                else [],
                direction=(
                    row.get("direction")
                    if row.get("direction") in ("yes", "no", "neutral")
                    else "neutral"
                ),
                weight=(
                    row.get("weight")
                    if row.get("weight") in ("strong", "moderate", "weak")
                    else "moderate"
                ),
            )
        )
    return claims


async def _generate(
    prompt: str,
    *,
    max_tokens: int,
    timeout: float,
    temperature: float,
    user_id: str | None,
) -> dict[str, Any] | None:
    from services import llm
    from services.prompts import load_prompt

    try:
        raw = await llm.generate(
            prompt,
            system=load_prompt("polymarket/system_forecaster"),
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            reasoning=False,
            json_mode=True,
            extra={"num_ctx": settings.LLM_NUM_CTX, "repeat_penalty": 1.1},
            prefer=await llm.provider_for(user_id, "reports"),
        )
    except Exception as error:  # noqa: BLE001
        logger.info("Polymarket generation failed: %s", error)
        return None

    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.info("Polymarket stage returned unparseable JSON")
        return None
    return parsed if isinstance(parsed, dict) else None


def _budgeted(
    blocks: list[tuple[str, str, int, bool]],
    max_tokens: int,
) -> tuple[dict[str, str], list[str]]:
    """Fit the variable blocks under the context window. Returns text and drops."""
    from services.prompt_budget import Block, fit

    result = fit(
        [
            Block(name=name, text=text, priority=priority, pinned=pinned)
            for name, text, priority, pinned in blocks
        ],
        settings.LLM_NUM_CTX - max_tokens - BUDGET_HEADROOM_TOKENS,
    )
    return result.blocks, result.dropped


async def build_arguments(
    facts: MarketFacts,
    facts_block: str,
    sweep: Sweep,
    ledger: EvidenceLedger,
    strategy: CategoryStrategy,
    *,
    user_id: str | None = None,
) -> tuple[list[Claim], list[Claim], list[str]]:
    """Both sides of the case, unverified. Returns (for, against, dropped)."""
    from services.prompts import load_prompt, render_prompt

    bodies, snippets = render_evidence(sweep, ledger)
    fitted, dropped = _budgeted(
        [
            ("facts", facts_block, 10, True),
            ("bodies", bodies, 3, False),
            ("snippets", snippets, 2, False),
        ],
        ARGUMENTS_MAX_TOKENS,
    )

    try:
        prompt = render_prompt(
            "polymarket/arguments",
            question=facts.market.question,
            resolution_criteria=(facts.resolution_criteria or "Not published.")[:1200],
            end_date=(f"{facts.market.end_date:%Y-%m-%d}" if facts.market.end_date else "unknown"),
            facts=fitted.get("facts", facts_block),
            evidence=fitted.get("bodies", "") + "\n\n" + fitted.get("snippets", ""),
            category_guidance=load_prompt(strategy.prompt),
            rules=load_prompt("polymarket/rules"),
        )
    except FileNotFoundError:
        logger.error("Polymarket arguments prompt is missing")
        return [], [], dropped

    parsed = await _generate(
        prompt,
        max_tokens=ARGUMENTS_MAX_TOKENS,
        timeout=ARGUMENTS_TIMEOUT,
        temperature=0.3,
        user_id=user_id,
    )
    if parsed is None:
        return [], [], dropped

    return _parse_claims(parsed, "claims_for"), _parse_claims(parsed, "claims_against"), dropped


async def synthesise(
    facts: MarketFacts,
    facts_block: str,
    micro: Microstructure,
    arguments: tuple[list[Claim], list[Claim]],
    sweep: Sweep,
    ledger: EvidenceLedger,
    coverage: EvidenceCoverage,
    strategy: CategoryStrategy,
    *,
    degraded: bool,
    gaps: list[str],
    user_id: str | None = None,
) -> dict[str, Any] | None:
    """The verdict, unverified and unclamped. None when the chain had nothing."""
    from services.prompts import load_prompt, render_prompt

    bodies, snippets = render_evidence(sweep, ledger)
    fitted, dropped = _budgeted(
        [
            ("facts", facts_block, 10, True),
            ("micro", render_microstructure(micro), 5, False),
            ("arguments", render_claims(*arguments), 6, False),
            ("bodies", bodies, 3, False),
            ("snippets", snippets, 2, False),
        ],
        SYNTHESIS_MAX_TOKENS,
    )
    coverage.dropped.extend(dropped)

    question = facts.market.question
    criteria = (facts.resolution_criteria or "Not published.")[:1200]
    end_date = f"{facts.market.end_date:%Y-%m-%d}" if facts.market.end_date else "unknown"
    facts_text = fitted.get("facts", facts_block)
    micro_text = fitted.get("micro", "")
    arguments_text = fitted.get("arguments", "")
    evidence_text = fitted.get("bodies", "") + "\n\n" + fitted.get("snippets", "")
    coverage_text = render_coverage(coverage)

    try:
        guidance = load_prompt(strategy.prompt)
        rules = load_prompt("polymarket/rules")
        # Two call sites spelling out the same keys rather than one with a
        # `**kwargs` dict. tests/test_prompts.py reads the source rather than
        # running it, so a splat supplies nothing it can see and every
        # placeholder in both templates reads as unfilled. Writing the keys out
        # is what lets that test catch a renamed placeholder, which is the whole
        # reason it exists.
        if degraded:
            prompt = render_prompt(
                "polymarket/synthesis_degraded",
                question=question,
                resolution_criteria=criteria,
                end_date=end_date,
                facts=facts_text,
                microstructure=micro_text,
                arguments=arguments_text,
                evidence=evidence_text,
                coverage=coverage_text,
                category_guidance=guidance,
                gaps="\n".join(f"- {gap}" for gap in gaps) or "- Not enumerated.",
                rules=rules,
            )
        else:
            prompt = render_prompt(
                "polymarket/synthesis",
                question=question,
                resolution_criteria=criteria,
                end_date=end_date,
                facts=facts_text,
                microstructure=micro_text,
                arguments=arguments_text,
                evidence=evidence_text,
                coverage=coverage_text,
                category_guidance=guidance,
                rules=rules,
            )
    except FileNotFoundError:
        logger.error("Polymarket synthesis prompt is missing")
        return None

    return await _generate(
        prompt,
        max_tokens=SYNTHESIS_MAX_TOKENS,
        timeout=SYNTHESIS_TIMEOUT,
        temperature=0.2,
        user_id=user_id,
    )
