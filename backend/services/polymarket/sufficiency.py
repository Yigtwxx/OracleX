"""
Whether there is enough to say anything, and how to say there was not.

This module is the one that decides a verdict does not get written. Everything
else in the analysis pipeline can degrade quietly; this cannot, because the
failure it guards against is the pipeline producing a fluent, sourced-looking
paragraph out of two headlines and a state wire.

The rule is a floor test rather than a score, deliberately. A weighted quality
score would let a large pile of weak material outvote the requirement that at
least two independent newsrooms saw the same thing, and "lots of sources" is
exactly what a thin story looks like when it is being amplified rather than
reported.

Four things are counted, and the second is the one that matters most:

* **sources** — distinct URLs, after normalisation.
* **domains** — distinct hosts. Four articles from one outlet are four accounts
  of one newsroom's reading; nothing in them can contradict the others, so no
  amount of them adds up to corroboration.
* **tier-1 bodies** — full text from a desk that publishes corrections. A
  snippet is a claim about an article, not the article.
* **body characters** — how much primary text actually reached the prompt. Six
  headlines are six facts; they are not an account of anything.

`describe_failure` composes the reader-facing explanation in Python and never
asks the model for it. A model asked to explain why it had too little to go on
will write a paragraph that reads exactly like the analysis being withheld,
which would hand back through the back door the thing the floor just refused.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from config import settings
from models.polymarket import EvidenceCoverage, RefusalReason
from services.polymarket.registry import CategoryStrategy

#: RAG hits never count toward the tier-1 requirement. They are this
#: application's own earlier output — a memory of what it once concluded, not an
#: independent newsroom. Letting them satisfy corroboration would let the system
#: cite itself into confidence.
RAG_COUNTS_AS_TIER1 = False


@dataclass(frozen=True)
class SufficiencyVerdict:
    mode: Literal["ok", "degraded", "insufficient"]
    reason_code: RefusalReason | None
    #: Human-readable floor failures, e.g. ("only 2 distinct domains, 3 needed",).
    failures: tuple[str, ...]


def _floor_failures(coverage: EvidenceCoverage, strategy: CategoryStrategy) -> list[str]:
    """Which full floors this evidence base misses, in the reader's terms."""
    failures: list[str] = []

    min_sources = (
        strategy.min_sources
        if strategy.min_sources is not None
        else settings.POLYMARKET_MIN_SOURCES
    )
    if coverage.total_sources < min_sources:
        failures.append(f"{coverage.total_sources} usable sources, {min_sources} needed")
    if coverage.distinct_domains < settings.POLYMARKET_MIN_DOMAINS:
        failures.append(
            f"{coverage.distinct_domains} distinct outlets, "
            f"{settings.POLYMARKET_MIN_DOMAINS} needed — a single-outlet evidence "
            "base cannot be cross-checked"
        )
    if coverage.tier1_sources < strategy.min_tier1:
        failures.append(f"no readable article from a named desk ({strategy.min_tier1} needed)")
    if coverage.body_chars < settings.POLYMARKET_MIN_BODY_CHARS:
        failures.append(
            f"{coverage.body_chars:,} characters of primary text, "
            f"{settings.POLYMARKET_MIN_BODY_CHARS:,} needed"
        )
    if coverage.queries_answered < settings.POLYMARKET_MIN_QUERIES_ANSWERED:
        failures.append(
            f"{coverage.queries_answered} of {coverage.queries_issued} searches "
            "returned anything usable"
        )
    return failures


def _passes_degraded(coverage: EvidenceCoverage) -> bool:
    return (
        coverage.total_sources >= settings.POLYMARKET_DEGRADED_MIN_SOURCES
        and coverage.distinct_domains >= settings.POLYMARKET_DEGRADED_MIN_DOMAINS
        and coverage.body_chars >= settings.POLYMARKET_DEGRADED_MIN_BODY_CHARS
    )


def assess(coverage: EvidenceCoverage, strategy: CategoryStrategy) -> SufficiencyVerdict:
    """
    Decide whether the model gets asked for a verdict at all.

    A timeout is not a separate branch. Whatever landed by the deadline is
    judged against the same floors as a run that finished early, because a
    sweep that timed out having already collected five sources across four
    outlets is not a failure — it is a slow success. Only a partial set that
    also misses the floors becomes a refusal, and then the timeout is what gets
    reported as the cause.
    """
    failures = _floor_failures(coverage, strategy)
    if not failures:
        return SufficiencyVerdict("ok", None, ())

    if _passes_degraded(coverage):
        return SufficiencyVerdict("degraded", None, tuple(failures))

    timed_out = any(a.outcome == "timeout" for a in coverage.attempted)
    if coverage.total_sources == 0:
        reason: RefusalReason = "timeout" if timed_out else "no_sources"
    elif coverage.distinct_domains < 2:
        reason = "single_domain"
    elif timed_out:
        reason = "timeout"
    else:
        reason = "thin_evidence"

    return SufficiencyVerdict("insufficient", reason, tuple(failures))


def _quote(targets: list[str], limit: int = 3) -> str:
    shown = [f'"{t}"' for t in targets[:limit]]
    joined = ", ".join(shown)
    extra = len(targets) - len(shown)
    return f"{joined} and {extra} more" if extra > 0 else joined


def describe_failure(
    coverage: EvidenceCoverage,
    verdict: SufficiencyVerdict,
) -> str:
    """
    One paragraph naming what was tried and what came back empty.

    Written here rather than by the model — see the module docstring. The shape
    is: what was attempted, what failed, what was actually collected, and the
    rule that was not met. A reader should be able to tell from it whether the
    market is genuinely uncovered or the fetch simply went badly, because those
    call for different responses and only one of them is worth retrying.
    """
    searches = [a for a in coverage.attempted if a.kind in ("search", "news")]
    feeds = [a for a in coverage.attempted if a.kind == "feed"]

    parts: list[str] = []
    tried = []
    if searches:
        tried.append(f"{len(searches)} searches")
    if feeds:
        tried.append(f"{len(feeds)} news feeds")
    parts.append(f"Ran {' and '.join(tried)}." if tried else "No sources were reached.")

    empty = [a.target for a in searches if a.outcome == "empty"]
    if empty:
        parts.append(f"{len(empty)} searches returned nothing ({_quote(empty)}).")

    broken = [a.target for a in coverage.attempted if a.outcome in ("error", "timeout")]
    if broken:
        parts.append(f"{len(broken)} sources could not be read ({_quote(broken)}).")

    if coverage.total_sources:
        parts.append(
            f"{coverage.total_sources} pages were usable across "
            f"{coverage.distinct_domains} outlets, totalling "
            f"{coverage.body_chars:,} characters of article text."
        )
    else:
        parts.append("Nothing usable was collected.")

    if verdict.failures:
        parts.append("No verdict was produced: " + "; ".join(verdict.failures) + ".")

    return " ".join(parts)
