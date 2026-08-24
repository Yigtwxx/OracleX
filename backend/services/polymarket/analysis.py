"""
One market, analysed end to end — or explicitly not.

The pipeline is six stages, and the third one is a gate. Facts and
microstructure are computed without a model and are always returned; the origin
trace and the evidence sweep run next; and only if the sweep clears the floors in
`sufficiency` is the model asked for a verdict at all. Below them the endpoint
answers with a refusal that names every query it ran and every one that came
back empty.

That ordering is the design. A refusal here is not an error page — the reader
still gets the odds, the drift, the holder concentration and the timeline of when
the market moved, because all of that was true before any search was run. What is
withheld is the judgement, and only the judgement.

Everything the model returns is checked before it is served: source ids against
the ledger, figures in market-sourced claims against the rendered facts, and the
confidence of a degraded run against a ceiling it cannot argue its way past. A
synthesis that loses too many claims to those checks is discarded rather than
shown thin — a verdict standing on one corroborated claim is not a verdict.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from config import settings
from models.polymarket import (
    EvidenceCoverage,
    MarketFacts,
    Microstructure,
    Origin,
    PolymarketAnalysis,
    PolymarketRefusal,
    SourceRef,
)
from services.polymarket import evidence as evidence_stage
from services.polymarket import facts as facts_stage
from services.polymarket import microstructure as micro_stage
from services.polymarket import origin as origin_stage
from services.polymarket import sufficiency, synthesis
from services.polymarket.attribution import (
    MIN_KEPT_CLAIMS,
    drop_unsourced_sentences,
    enforce_attribution,
)
from services.polymarket.category import market_subject, resolution_year
from services.polymarket.registry import strategy_for

logger = logging.getLogger(__name__)

STAGES = [
    {"key": "facts", "label": "Resolving market"},
    {"key": "origin", "label": "Tracing why this market opened"},
    {"key": "sweep", "label": "Gathering evidence"},
    {"key": "microstructure", "label": "Reading the order book"},
    {"key": "arguments", "label": "Building both sides"},
    {"key": "synthesis", "label": "Weighing the case"},
]


def _refusal(
    facts: MarketFacts | None,
    micro: Microstructure | None,
    origin: Origin | None,
    coverage: EvidenceCoverage,
    reason: str,
    explanation: str,
    *,
    slug: str,
    question: str,
    market_id: str,
    category: str,
) -> PolymarketRefusal:
    return PolymarketRefusal(
        market_id=market_id,
        slug=slug,
        question=question,
        category=category,
        reason_code=reason,
        explanation=explanation,
        facts=facts,
        microstructure=micro,
        origin=origin,
        coverage=coverage,
        generated_at=datetime.now(UTC),
    )


async def analyse_market(
    raw: dict[str, Any],
    *,
    user_id: str | None = None,
    on_stage=None,
) -> PolymarketAnalysis | PolymarketRefusal:
    """
    Analyse one Gamma market payload. Never raises.

    `on_stage` is the job runner's stage callback; it is optional so the
    pipeline can be exercised directly in tests without a job around it.
    """

    def stage(key: str) -> None:
        if on_stage:
            on_stage(key)

    stage("facts")
    market_facts, micro = await facts_stage.gather_facts(raw, include_trades=False)
    market = market_facts.market
    strategy = strategy_for(market.category)
    subject = market_subject(market.question)
    year = resolution_year(market.end_date)
    facts_block = micro_stage.render_facts_block(market_facts, micro)

    identity = {
        "market_id": market.market_id,
        "slug": market.slug,
        "question": market.question,
        "category": market.category,
    }

    if not settings.USE_AI:
        return _refusal(
            market_facts,
            micro,
            None,
            EvidenceCoverage(),
            "ai_disabled",
            "AI features are switched off on this instance, so no analysis was attempted.",
            **identity,
        )

    stage("origin")
    origin, origin_candidates = await origin_stage.trace_origin(
        market_facts, subject, strategy, user_id=user_id
    )

    stage("sweep")
    sweep = await evidence_stage.run_sweep(subject, strategy, year=year)
    # The origin stage already paid for these searches; folding them in rather
    # than re-fetching is free corroboration, and a story that explained a price
    # move is evidence about the question by construction.
    sweep._absorb(
        [
            {
                "url": hit.get("url", ""),
                "title": hit.get("title", ""),
                "snippet": hit.get("snippet", ""),
                "published_at": (
                    hit["published_at"].isoformat() if hit.get("published_at") else None
                ),
            }
            for hit in origin_candidates.values()
        ],
        "news",
    )
    ledger, coverage = sweep.finish()

    stage("microstructure")
    verdict = sufficiency.assess(coverage, strategy)

    if verdict.mode == "insufficient":
        return _refusal(
            market_facts,
            micro,
            origin,
            coverage,
            verdict.reason_code or "thin_evidence",
            sufficiency.describe_failure(coverage, verdict),
            **identity,
        )

    degraded = verdict.mode == "degraded"

    stage("arguments")
    claims_for, claims_against, dropped = await synthesis.build_arguments(
        market_facts, facts_block, origin, sweep, ledger, strategy, user_id=user_id
    )
    coverage.dropped.extend(dropped)

    stage("synthesis")
    parsed = await synthesis.synthesise(
        market_facts,
        facts_block,
        micro,
        origin,
        (claims_for, claims_against),
        sweep,
        ledger,
        coverage,
        strategy,
        degraded=degraded,
        gaps=list(verdict.failures),
        user_id=user_id,
    )

    if parsed is None:
        return _refusal(
            market_facts,
            micro,
            origin,
            coverage,
            "model_unavailable",
            "Evidence was gathered, but no model in the chain could write the verdict. "
            + sufficiency.describe_failure(coverage, verdict),
            **identity,
        )

    final_for = synthesis._parse_claims(parsed, "claims_for") or claims_for
    final_against = synthesis._parse_claims(parsed, "claims_against") or claims_against

    kept_for, report_for = enforce_attribution(final_for, ledger, facts_block)
    kept_against, report_against = enforce_attribution(final_against, ledger, facts_block)

    if len(kept_for) + len(kept_against) < MIN_KEPT_CLAIMS:
        return _refusal(
            market_facts,
            micro,
            origin,
            coverage,
            "unsourced_output",
            "A verdict was written but did not survive the source check: only "
            f"{len(kept_for) + len(kept_against)} of "
            f"{report_for.claims_in + report_against.claims_in} claims cited evidence we hold. "
            + sufficiency.describe_failure(coverage, verdict),
            **identity,
        )

    bottom_line, sentences_dropped = drop_unsourced_sentences(
        str(parsed.get("bottom_line") or ""), ledger
    )

    confidence = _confidence(parsed.get("confidence"), degraded=degraded)
    leaning = parsed.get("leaning")
    if leaning not in ("yes", "no", "unclear"):
        leaning = "unclear"

    gaps = [str(g).strip() for g in (parsed.get("gaps") or []) if str(g).strip()]
    if degraded:
        gaps = list(verdict.failures) + gaps

    return PolymarketAnalysis(
        status="degraded" if degraded else "ok",
        facts=market_facts,
        microstructure=micro,
        origin=origin,
        confidence=confidence,
        leaning=leaning,
        bottom_line=bottom_line,
        claims_for=kept_for,
        claims_against=kept_against,
        sources=_cited(ledger.sources, kept_for + kept_against),
        coverage=coverage,
        attribution=_merge(report_for, report_against, sentences_dropped),
        gaps=gaps,
        generated_at=datetime.now(UTC),
        **identity,
    )


def _confidence(raw: Any, *, degraded: bool) -> float:
    """
    The model's confidence, clamped into [0, 1] and capped for a degraded run.

    Clamped in Python because a model handed a thin evidence base still returns
    round confident numbers, and the ceiling is the only thing that stops the
    reader seeing one. Asking for it in the prompt is a request; this is a rule.
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.3
    value = min(1.0, max(0.0, value))
    if degraded:
        value = min(value, settings.POLYMARKET_DEGRADED_MAX_CONFIDENCE)
    return round(value, 2)


def _cited(sources: list[SourceRef], claims) -> list[SourceRef]:
    """
    Only the sources a surviving claim actually cites.

    Serving the whole ledger would put a footnote list under the verdict that is
    mostly things it did not use, which reads as broader support than there was.
    """
    used = {source_id for claim in claims for source_id in claim.sources}
    return [s for s in sources if s.id in used]


def _merge(report_for, report_against, sentences_dropped: int):
    from models.polymarket import AttributionReport

    return AttributionReport(
        claims_in=report_for.claims_in + report_against.claims_in,
        claims_kept=report_for.claims_kept + report_against.claims_kept,
        sentences_dropped=sentences_dropped,
        dropped=report_for.dropped + report_against.dropped,
    )


async def start_analysis_job(raw: dict[str, Any], *, user_id: str | None = None):
    """
    Run `analyse_market` as a staged job, or re-attach to the one in flight.

    The import is deferred because `analysis_jobs` pulls in the AI layer at
    module scope; importing it at the top of this module would make `main.py`'s
    early router import reach a half-initialised package. Both existing
    consumers of the job engine do the same thing for the same reason.

    Keyed by slug, so a double-clicked Analysis button re-attaches to the run it
    already started instead of paying for a second one.
    """
    from services import analysis_jobs

    slug = str(raw.get("slug") or raw.get("id") or "")

    async def runner(controls: analysis_jobs.JobControls) -> dict[str, Any]:
        result = await analyse_market(raw, user_id=user_id, on_stage=controls.on_stage)
        return result.model_dump(mode="json")

    return await analysis_jobs.start(
        slug,
        analysis_jobs.KIND_POLYMARKET,
        STAGES,
        runner,
        owner_id=user_id,
    )
