"""
Market report generation and user notes.

Reports are produced by a four-stage pipeline rather than a single prompt:

    collecting -> synthesis -> drafting -> review

`collecting` builds a deterministic market snapshot (see `analysis_data`), and
the three LLM stages extract evidence from it, write the report, and then
fact-check that report back against the same snapshot. Splitting the work this
way keeps arithmetic out of the model's hands and gives the review stage a
concrete reference to strike unsupported figures against.

Generation is expensive and slow, so nothing here is triggered by a read. The
routers start it explicitly through `analysis_jobs`.
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from config import settings
from services.analysis_data import build_market_snapshot, render_snapshot_markdown
from services.llm.base import LLMError
from services.prompts import load_prompt, render_prompt

logger = logging.getLogger(__name__)

REPORTS_FILE = "data/analysis_reports.json"
NOTES_FILE = "data/user_notes.json"

# How long a report stays fresh, per horizon.
FRESHNESS_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}

# Ordered pipeline stages, surfaced to the UI so it can show real progress.
STAGES = [
    {"key": "collecting", "label": "Collecting market data"},
    {"key": "synthesis", "label": "Extracting evidence"},
    {"key": "drafting", "label": "Drafting report"},
    {"key": "review", "label": "Reviewing & fact-checking"},
]

StageCallback = Callable[[str], None]


# ═══════════════════════════════════════════════════════════════════════════════
# DATA PERSISTENCE HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _load_json(filepath: str, default: Any) -> Any:
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(filepath: str, data: Any) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
# REPORT GENERATION
# ═══════════════════════════════════════════════════════════════════════════════


async def _run_stage(
    prompt: str,
    system_prompt: str,
    *,
    stage: str,
    temperature: float,
    max_tokens: int,
    user_id: Optional[str],
    json_mode: bool = False,
    reasoning: bool = False,
) -> str:
    """
    Run one LLM stage, raising instead of degrading to placeholder text.

    A stage that returns nothing means every configured provider failed. The
    caller surfaces that as a job error so the UI can offer a retry, rather than
    presenting a fabricated report as if it were real analysis.

    `reasoning` is enabled on the stages where the model has to weigh evidence
    against itself — extracting contradictions, and fact-checking the draft — and
    left off for drafting, where the thinking has already been done and the extra
    latency buys nothing.
    """
    from services import llm

    result = await llm.generate(
        prompt,
        system=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=300.0,
        reasoning=reasoning,
        json_mode=json_mode,
        # Without this the local server falls back to whatever context it decides
        # to allocate and silently drops the front of the prompt — which is the
        # system prompt, and with it every rule forbidding invented figures. The
        # chat and news paths already pass it; this one used to be the exception.
        extra={"num_ctx": settings.LLM_NUM_CTX, "repeat_penalty": 1.1},
        prefer=await llm.provider_for(user_id, "reports"),
    )

    if not result or not result.strip():
        raise LLMError(f"The '{stage}' stage returned no content — no LLM provider could serve it.")

    return result.strip()


def _parse_evidence(raw: str) -> Optional[str]:
    """
    Normalise the evidence stage output, or None if it is not JSON.

    Returning None rather than the raw text is the point: the drafting stage's
    prompt introduces this block as "EXTRACTED EVIDENCE — from the preceding
    analysis stage", and handing it a half-finished JSON fragment under that
    heading invites the model to treat truncated garbage as findings. The caller
    retries once and then fails the stage, which is the same rule the rest of
    this pipeline follows: no fabricated report presented as real analysis.
    """
    start, end = raw.find("{"), raw.rfind("}") + 1
    if start == -1 or end <= start:
        return None
    try:
        return json.dumps(json.loads(raw[start:end]), indent=2)
    except json.JSONDecodeError:
        return None


# The headings stage 2 is told to produce and stage 3 is told to restore. Checked
# in Python as well because nothing else does: the requirement lives in a prompt,
# and a model that drops a section ships a report missing it, silently.
REQUIRED_HEADINGS = (
    "Executive Summary",
    "Market Regime & Positioning",
    "Crypto Technicals",
    "Derivatives & Liquidity",
    "Equities & Macro Cross-Read",
    "News Catalysts",
    "Scenarios",
    "Watchlist & Key Levels",
    "Risk Disclosures & Data Coverage",
)


def missing_headings(report: str) -> List[str]:
    """Which required sections the report does not contain, in order."""
    lowered = report.lower()
    return [h for h in REQUIRED_HEADINGS if f"## {h}".lower() not in lowered]


# Bumped by hand when the pipeline's shape changes in a way the prompt files do
# not capture — a new stage, a different stage order.
PIPELINE_REVISION = "2"

# The prompts that decide what a report looks like. Editing any of them retires
# every stored report, the same way the news pipeline retires cached analyses.
_VERSIONED_PROMPTS = (
    "analysis/system_analyst",
    "analysis/rules",
    "analysis/stage1_evidence",
    "analysis/stage2_report",
    "analysis/stage3_review",
    "analysis/stage4_restore",
)

_pipeline_version: Optional[str] = None


def pipeline_version() -> str:
    """
    Short digest of everything that determines what a report looks like.

    Stored reports were keyed by timeframe alone, so a prompt edit left yesterday's
    report in place and served it as current. That is worse than a stale cache: it
    means an evaluation of a prompt change silently measures the old prompt.

    Computed once per process — prompt files do not change under a running server.
    """
    global _pipeline_version
    if _pipeline_version is not None:
        return _pipeline_version

    from services.prompts import load_prompt

    digest = hashlib.sha256()
    digest.update(PIPELINE_REVISION.encode())
    digest.update((settings.LLM_MODEL or "").encode())
    for name in _VERSIONED_PROMPTS:
        try:
            digest.update(load_prompt(name).encode())
        except Exception as e:  # noqa: BLE001 — a missing prompt fails louder elsewhere
            logger.warning("Could not hash prompt %s for the pipeline version: %s", name, e)

    _pipeline_version = digest.hexdigest()[:12]
    return _pipeline_version


async def generate_market_report(
    timeframe: str,
    user_id: Optional[str] = None,
    on_stage: Optional[StageCallback] = None,
) -> Dict[str, Any]:
    """
    Run the full report pipeline for one horizon and persist the result.

    `on_stage` is called with each stage key as it starts, so a caller can
    report progress. Raises on LLM failure; feed-level failures degrade to a
    documented gap in the report instead.
    """

    def report_stage(key: str) -> None:
        if on_stage:
            on_stage(key)

    started = time.monotonic()
    system_prompt = load_prompt("analysis/system_analyst")
    # The hard constraints ride at the tail of each stage prompt rather than in
    # the system prompt. Ollama renders `system` first and truncates from the
    # front, so rules placed there are the first thing an over-long prompt loses —
    # and a model that has lost "every number must appear in the snapshot" writes
    # a confident report full of invented levels. Kept in one file so the three
    # stages cannot drift apart.
    stage_rules = load_prompt("analysis/rules")
    report_date = datetime.now().strftime("%B %d, %Y %H:%M")

    # 1. Collect — deterministic, no model involved.
    report_stage("collecting")
    snapshot = await build_market_snapshot(timeframe)
    snapshot_md = render_snapshot_markdown(snapshot)

    # 2. Synthesis — pull structured evidence out of the snapshot.
    report_stage("synthesis")
    evidence_prompt = render_prompt(
        "analysis/stage1_evidence",
        timeframe=timeframe,
        report_date=report_date,
        snapshot=snapshot_md,
        rules=stage_rules,
    )
    evidence = None
    for attempt in range(2):
        raw = await _run_stage(
            evidence_prompt,
            system_prompt,
            stage="synthesis",
            temperature=0.1,
            max_tokens=2000,
            user_id=user_id,
            json_mode=True,
            # Finding where two independent signals contradict each other is the
            # one thing this stage exists for, and it is the part a small model
            # gets wrong when answering in one pass.
            reasoning=True,
        )
        evidence = _parse_evidence(raw)
        if evidence is not None:
            break
        logger.warning("Evidence stage returned malformed JSON (attempt %d/2)", attempt + 1)
    if evidence is None:
        raise LLMError(
            "The 'synthesis' stage did not return usable JSON after two attempts. "
            "Drafting from its raw output would present truncated text to the next "
            "stage as if it were extracted findings."
        )

    # 3. Drafting — write the report from snapshot + evidence.
    report_stage("drafting")
    draft = await _run_stage(
        render_prompt(
            "analysis/stage2_report",
            timeframe=timeframe,
            report_date=report_date,
            snapshot=snapshot_md,
            evidence=evidence,
            rules=stage_rules,
        ),
        system_prompt,
        stage="drafting",
        temperature=0.3,
        max_tokens=4000,
        user_id=user_id,
    )

    # 4. Review — strike anything the snapshot does not support.
    report_stage("review")
    final = await _run_stage(
        render_prompt(
            "analysis/stage3_review",
            snapshot=snapshot_md,
            draft=draft,
            rules=stage_rules,
        ),
        system_prompt,
        stage="review",
        temperature=0.15,
        max_tokens=4000,
        user_id=user_id,
        # Checking every figure in the draft against the snapshot line by line is
        # the stage that catches invented numbers. It is worth the latency.
        reasoning=True,
    )

    # The nine required headings are asked for in two prompts and checked in
    # neither. A review stage that drops one produces a report missing a section
    # nobody notices is missing — most damagingly "Risk Disclosures & Data
    # Coverage", the section that states which feeds were unavailable.
    missing = missing_headings(final)
    if missing:
        logger.warning("Review dropped section(s): %s — restoring", ", ".join(missing))
        final = await _run_stage(
            render_prompt(
                "analysis/stage4_restore",
                snapshot=snapshot_md,
                draft=final,
                missing="\n".join(f"- ## {heading}" for heading in missing),
                rules=stage_rules,
            ),
            system_prompt,
            stage="review",
            temperature=0.15,
            max_tokens=4000,
            user_id=user_id,
        )
        missing = missing_headings(final)

    report = {
        "content": final,
        "timestamp": datetime.now().isoformat(),
        "timeframe": timeframe,
        "unavailable": snapshot.get("unavailable", []),
        "duration_seconds": round(time.monotonic() - started, 1),
        "stale": False,
        # What produced this report. A prompt edit changes the digest, which
        # retires every stored report rather than serving one written by prompts
        # that no longer exist.
        "pipeline_version": pipeline_version(),
        # Surfaced rather than swallowed: a caller rendering this report should be
        # able to say the structure is incomplete instead of quietly showing eight
        # of nine sections as though that were the whole thing.
        "missing_sections": missing,
    }
    if missing:
        logger.warning(
            "%s report is missing section(s) after a restore pass: %s",
            timeframe,
            ", ".join(missing),
        )

    reports = _load_json(REPORTS_FILE, {})
    reports[timeframe] = report
    _save_json(REPORTS_FILE, reports)

    logger.info(
        "Generated %s report in %.1fs (%d feed(s) unavailable)",
        timeframe,
        report["duration_seconds"],
        len(report["unavailable"]),
    )
    return report


def _is_stale(timestamp: str, timeframe: str, version: Optional[str] = None) -> bool:
    """
    Whether a stored report should be regenerated.

    Age is the obvious axis. The pipeline version is the one that used to be
    missing: a report written by a different set of prompts is stale however
    recently it was written, because it is no longer an example of what this
    pipeline produces. Reports stored before versioning carry no version and are
    treated as stale, which costs one regeneration each.
    """
    if version != pipeline_version():
        return True
    try:
        age_days = (datetime.now() - datetime.fromisoformat(timestamp)).days
    except (TypeError, ValueError):
        return True
    return age_days >= FRESHNESS_DAYS.get(timeframe, 1)


def get_report(timeframe: str) -> Dict[str, Any]:
    """
    Read the stored report for a horizon. Never generates.

    Generation is explicit and job-driven; a page load must not be able to
    trigger a multi-minute LLM pipeline.
    """
    report = _load_json(REPORTS_FILE, {}).get(timeframe)
    if not report:
        return {"content": None, "timestamp": None, "timeframe": timeframe, "stale": True}

    return {
        "content": report.get("content"),
        "timestamp": report.get("timestamp"),
        "timeframe": timeframe,
        "unavailable": report.get("unavailable", []),
        "duration_seconds": report.get("duration_seconds"),
        "missing_sections": report.get("missing_sections", []),
        "stale": _is_stale(report.get("timestamp", ""), timeframe, report.get("pipeline_version")),
    }


def get_report_summaries() -> Dict[str, Dict[str, Any]]:
    """Freshness metadata for every horizon — powers the timeframe picker."""
    reports = _load_json(REPORTS_FILE, {})
    now = datetime.now()

    summaries: Dict[str, Dict[str, Any]] = {}
    for timeframe in FRESHNESS_DAYS:
        report = reports.get(timeframe)
        timestamp = report.get("timestamp") if report else None

        age_seconds = None
        if timestamp:
            try:
                age_seconds = int((now - datetime.fromisoformat(timestamp)).total_seconds())
            except ValueError:
                timestamp = None

        summaries[timeframe] = {
            "timeframe": timeframe,
            "generated_at": timestamp,
            "age_seconds": age_seconds,
            "stale": _is_stale(timestamp or "", timeframe, (report or {}).get("pipeline_version")),
            "unavailable": (report or {}).get("unavailable", []),
        }
    return summaries


# ═══════════════════════════════════════════════════════════════════════════════
# NOTES MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════


def get_user_notes() -> List[Dict]:
    return _load_json(NOTES_FILE, [])


def add_user_note(title: str, content: str) -> List[Dict]:
    notes = get_user_notes()
    new_note = {
        "id": str(int(datetime.now().timestamp())),
        "title": title,
        "content": content,
        "date": datetime.now().isoformat(),
    }
    notes.insert(0, new_note)  # Newest first
    _save_json(NOTES_FILE, notes)
    return notes


def delete_user_note(note_id: str) -> List[Dict]:
    notes = get_user_notes()
    notes = [n for n in notes if n["id"] != note_id]
    _save_json(NOTES_FILE, notes)
    return notes
