"""
The scan itself: one job, five stages, one persisted result.

Order is by cost. The snapshot gate runs over the whole index with no request;
candles are fetched only for its survivors; the statements come from the disk
cache for every name that has been seen before; the model writes last, for the
finalists only, one at a time, so a scan never puts fifteen prompts on a local
Ollama at once.

The result is written to disk as soon as the scores are known and again after
each memo lands, and each write is also published as the job's partial result.
So a reader who opens the tab mid-run sees the candidates within a minute and
watches the memos arrive, and a reader who opens it tomorrow sees the whole
thing without pressing anything.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, Optional

from services import analysis_jobs
from services.analysis_jobs import KIND_RADAR, Job, JobControls
from services.bist.equity_service import DELAY_MINUTES, fetch_candles, fetch_equity_board
from services.bist.kap_materiality import classify
from services.bist.kap_service import KapUnavailable, fetch_tape, filter_restrictions
from services.bist.macro_service import MacroUnavailable, fetch_macro_snapshot
from services.bist.radar import scoring, technical, voices
from services.bist.fundamentals import Fundamentals, fetch_many
from services.bist.radar.memo import memo_for
from services.bist.radar.profiles import Profile, get_profile
from services.bist.radar.store import read_last, write_last
from services.bist.radar.universe import xu100_rows
from services.bist.tradingview_client import EquityRow

logger = logging.getLogger(__name__)

STAGES: list[dict[str, str]] = [
    {"key": "universe", "label": "Evren"},
    {"key": "technical", "label": "Teknik tarama"},
    {"key": "fundamentals", "label": "Mali tablolar"},
    {"key": "scoring", "label": "Puanlama"},
    {"key": "voices", "label": "Yorumcular"},
    {"key": "memos", "label": "Yorumlar"},
]

DEPTH_CONCURRENCY = 4
"""Simultaneous Yahoo candle fetches. Four is what the chart page already tolerates."""

MAX_MEMOS = 15
MEMO_WAIT_SECONDS = 150
MEMO_POLL_SECONDS = 3

NEAREST = 3

KAP_TAPE_ROWS = 600
"""The whole buffer. Rights issues and measures are rare enough that all of it is the sample."""

_TICKER_RE = re.compile(r"[A-Z0-9]{3,6}")


def job_key(horizon: str) -> str:
    return f"radar:{horizon}"


async def start_scan(horizon: str) -> Job:
    """Start a scan for this horizon, or join the one already running."""
    profile = get_profile(horizon)

    async def runner(controls: JobControls) -> dict[str, Any]:
        return await run_scan(profile, controls)

    return await analysis_jobs.start(job_key(horizon), KIND_RADAR, STAGES, runner)


def last_result(horizon: str) -> Optional[dict[str, Any]]:
    get_profile(horizon)
    return read_last(horizon)


# ── The run ─────────────────────────────────────────────────────────────────


async def run_scan(profile: Profile, controls: JobControls) -> dict[str, Any]:
    started = time.monotonic()

    controls.on_stage("universe")
    board = await fetch_equity_board()
    rows = xu100_rows(board.equities)
    if not rows:
        raise RuntimeError("The equity board carried no XU100 members")

    controls.on_stage("technical")
    gate_reason: dict[str, str] = {}
    survivors: list[EquityRow] = []
    for row in rows:
        reason = technical.gate(row, profile)
        if reason is None:
            survivors.append(row)
        else:
            gate_reason[row.ticker] = reason

    reads = await _technical_depth(survivors, profile, controls)

    controls.on_stage("fundamentals")

    def fundamentals_progress(done: int, total: int) -> None:
        controls.on_partial({"progress": {"stage": "fundamentals", "done": done, "total": total}})

    funds = await fetch_many([row.ticker for row in rows], on_progress=fundamentals_progress)
    kap = await _kap_flags()
    inflation = await _inflation()

    controls.on_stage("scoring")
    result = _score(profile, rows, gate_reason, reads, funds, kap, inflation)
    result["duration_seconds"] = round(time.monotonic() - started, 1)
    write_last(profile.key, result)
    controls.on_partial(result)

    controls.on_stage("voices")
    await _attach_voices(profile, result, rows, controls)
    write_last(profile.key, result)
    controls.on_partial(result)

    controls.on_stage("memos")
    await _write_memos(profile, result, controls)
    result["duration_seconds"] = round(time.monotonic() - started, 1)
    write_last(profile.key, result)
    return result


async def _technical_depth(
    survivors: list[EquityRow], profile: Profile, controls: JobControls
) -> dict[str, technical.Levels | technical.Rejection]:
    semaphore = asyncio.Semaphore(DEPTH_CONCURRENCY)
    reads: dict[str, technical.Levels | technical.Rejection] = {}
    done = 0

    async def one(row: EquityRow) -> None:
        nonlocal done
        async with semaphore:
            try:
                candles = await fetch_candles(row.ticker, range_=profile.candle_range)
            except Exception as e:  # noqa: BLE001 — one chart must not end the scan
                logger.warning("Radar: candles for %s unavailable: %s", row.ticker, e)
                candles = []
            reads[row.ticker] = technical.analyse(candles, row, profile)
            done += 1
            controls.on_partial(
                {"progress": {"stage": "technical", "done": done, "total": len(survivors)}}
            )

    await asyncio.gather(*(one(row) for row in survivors))
    return reads


async def _kap_flags() -> Optional[dict[str, scoring.KapFlags]]:
    """
    Rights issues and trading measures per ticker, from the tape buffer.

    None — rather than "no flags" — when the tape cannot be read: the result
    then says the filings were not checked instead of implying they were clean.
    """
    try:
        rows = await fetch_tape(KAP_TAPE_ROWS)
    except KapUnavailable as e:
        logger.warning("Radar: KAP tape unavailable, filings unchecked: %s", e)
        return None
    if not rows:
        return None

    restricted = {t for d in filter_restrictions(rows) for t in _tickers_of(d.ticker)}
    rights: set[str] = set()
    for d in rows:
        text = f"{d.title} {d.summary}".casefold()
        if classify(d.title, d.summary, d.category).event == "sermaye" and "bedelli" in text:
            rights.update(_tickers_of(d.ticker))

    flags: dict[str, scoring.KapFlags] = {}
    for ticker in restricted | rights:
        flags[ticker] = scoring.KapFlags(
            rights_issue=ticker in rights, restriction=ticker in restricted
        )
    return flags


def _tickers_of(field: str) -> set[str]:
    return set(_TICKER_RE.findall((field or "").upper()))


async def _inflation() -> Optional[float]:
    try:
        return (await fetch_macro_snapshot()).inflation_yoy
    except MacroUnavailable as e:
        logger.warning("Radar: inflation unavailable, growth scored nominally-null: %s", e)
        return None


# ── Scoring into the result ─────────────────────────────────────────────────


def _score(
    profile: Profile,
    rows: list[EquityRow],
    gate_reason: dict[str, str],
    reads: dict[str, technical.Levels | technical.Rejection],
    funds: dict[str, Fundamentals],
    kap: Optional[dict[str, scoring.KapFlags]],
    inflation: Optional[float],
) -> dict[str, Any]:
    medians = scoring.sector_medians(rows)
    universe: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    vetoed = 0

    for row in rows:
        fund = funds.get(row.ticker)
        klass = scoring.sector_class(row, fund)
        fund_score, coverage = scoring.fundamental_score(row, fund, medians, inflation)
        kap_flags = kap.get(row.ticker) if kap is not None else None
        veto_keys = scoring.vetoes(row, fund, kap_flags)

        entry: dict[str, Any] = {
            "ticker": row.ticker,
            "symbol": row.symbol,
            "name": row.name,
            "sector": row.sector,
            "sector_class": klass,
            "price": row.price,
            "change_pct": row.change_pct,
            "market_cap": row.market_cap,
            "score_technical": None,
            "score_fundamental": fund_score,
            "fundamental_coverage": coverage,
            "fundamental_depth": "full" if fund is not None else "ratios_only",
            "score_total": None,
            "rr": None,
            "vetoes": [{"key": k, "label": scoring.VETO_LABELS.get(k, k)} for k in veto_keys],
            "stage_reached": "gate",
            "rejected_reason": None,
            "rejected_label": None,
        }

        if row.ticker in gate_reason:
            entry["rejected_reason"] = gate_reason[row.ticker]
            entry["rejected_label"] = technical.REASON_LABELS.get(gate_reason[row.ticker])
            universe.append(entry)
            continue

        read = reads.get(row.ticker)
        entry["stage_reached"] = "technical"
        if read is None or isinstance(read, technical.Rejection):
            reason = read.reason if read is not None else "insufficient_history"
            entry["rejected_reason"] = reason
            entry["rejected_label"] = technical.REASON_LABELS.get(reason, reason)
            universe.append(entry)
            continue

        levels = read
        tech_score = scoring.technical_score(levels, profile)
        adjustments = [a for a in (scoring.analyst_adjustment(row),) if a is not None]
        total = scoring.total_score(tech_score, fund_score, adjustments, profile)
        entry.update(
            {
                "stage_reached": "scored",
                "score_technical": tech_score,
                "score_total": total,
                "rr": levels.rr,
            }
        )

        if veto_keys:
            vetoed += 1
            entry["rejected_reason"] = "vetoed"
            entry["rejected_label"] = "Temel veto"
        elif levels.rr < scoring.MIN_RR:
            entry["rejected_reason"] = "reward_insufficient"
            entry["rejected_label"] = technical.REASON_LABELS["reward_insufficient"]
        elif total is None or total < scoring.MIN_TOTAL:
            entry["rejected_reason"] = "score_below_threshold"
            entry["rejected_label"] = f"Toplam puan {scoring.MIN_TOTAL} altında"
        else:
            entry["stage_reached"] = "candidate"
            flags = scoring.flags_for(levels, row)
            if technical.earnings_soon(row.next_earnings):
                flags.append("earnings_soon")
            if fund is None:
                flags.append("ratios_only")
            if kap is None:
                flags.append("kap_unchecked")
            street = scoring.street(row)
            candidates.append(
                {
                    **entry,
                    "pe": row.pe,
                    "pb": row.pb,
                    "ev_ebitda": row.ev_ebitda,
                    "week52_high": row.week52_high,
                    "week52_low": row.week52_low,
                    "next_earnings": row.next_earnings,
                    "levels": {**asdict(levels), "entry_mid": round(levels.entry_mid, 4)},
                    "fundamentals": _fund_summary(row, fund, inflation),
                    "adjustments": [asdict(a) for a in adjustments],
                    "flags": [{"key": f, "label": scoring.FLAG_LABELS.get(f, f)} for f in flags],
                    "street": asdict(street) if street else None,
                    "kap_checked": kap is not None,
                    "memo": None,
                    "voices": [],
                }
            )
        universe.append(entry)

    candidates.sort(key=lambda c: (-(c["score_total"] or 0), c["ticker"]))
    universe.sort(
        key=lambda u: (
            -(u["score_total"] if u["score_total"] is not None else -1),
            -(u["score_fundamental"] if u["score_fundamental"] is not None else -1),
            u["ticker"],
        )
    )

    candidate_tickers = {c["ticker"] for c in candidates}
    nearest = [
        u for u in universe if u["ticker"] not in candidate_tickers and u["score_total"] is not None
    ][:NEAREST]

    covered = len(funds)
    depth = "full" if covered >= 0.9 * len(rows) else "partial" if covered else "ratios_only"

    return {
        "horizon": profile.key,
        "horizon_label": profile.label,
        "scanned_at": datetime.now(UTC).isoformat(),
        "duration_seconds": None,
        "delay_minutes": DELAY_MINUTES,
        "universe_size": len(rows),
        "fundamental_depth": depth,
        "fundamentals_covered": covered,
        "kap_checked": kap is not None,
        "inflation_yoy": inflation,
        "counts": {
            "gate_passed": len(rows) - len(gate_reason),
            "technical_passed": sum(1 for r in reads.values() if isinstance(r, technical.Levels)),
            "vetoed": vetoed,
            "candidates": len(candidates),
        },
        "memos": {"done": 0, "total": min(len(candidates), MAX_MEMOS)},
        "candidates": candidates,
        "nearest": nearest,
        "universe": universe,
    }


def _fund_summary(
    row: EquityRow, fund: Optional[Fundamentals], inflation: Optional[float]
) -> dict[str, Any]:
    """What the card and the memo say about the statements — computed here, once."""
    klass = scoring.sector_class(row, fund)
    ebitda_based = scoring.uses_ebitda(klass)
    out: dict[str, Any] = {
        "layout": fund.layout if fund else None,
        "latest_period": fund.latest_period if fund else None,
        "quarters": len(fund.quarters) if fund else 0,
        "inflation": inflation,
        "roe": row.roe,
        "real_revenue_growth": None,
        "real_profit_growth": None,
        "net_debt_ebitda": None,
        "short_debt_share": None,
        "loss_quarters": None,
        "cash_conversion": None,
        "equity": None,
    }
    if fund is None:
        nominal = row.revenue_growth if ebitda_based else row.net_income_growth
        if nominal is not None and inflation is not None:
            from services.bist.real_return import deflate

            out["real_revenue_growth" if ebitda_based else "real_profit_growth"] = deflate(
                nominal, inflation
            )
        return out

    q = fund.quarters
    out["loss_quarters"] = sum(1 for x in q[:4] if x.net_income is not None and x.net_income < 0)
    out["equity"] = q[0].equity
    if ebitda_based:
        out["real_revenue_growth"] = scoring.real_growth(fund, "revenue", inflation)
        out["real_profit_growth"] = scoring.real_growth(fund, "ebitda", inflation)
        ratio = scoring.net_debt_to_ebitda(fund)
        out["net_debt_ebitda"] = None if ratio is None or ratio == float("inf") else round(ratio, 2)
        if q[0].short_term_debt is not None and q[0].total_debt:
            out["short_debt_share"] = q[0].short_term_debt / q[0].total_debt
        ocf, income = scoring.ttm(q, "ocf"), scoring.ttm(q, "net_income")
        if ocf is not None and income:
            out["cash_conversion"] = ocf / income
    else:
        out["real_revenue_growth"] = scoring.real_growth(fund, "revenue", inflation)
        out["real_profit_growth"] = scoring.real_growth(fund, "net_income", inflation)
    return out


# ── Voices ──────────────────────────────────────────────────────────────────


async def _attach_voices(
    profile: Profile, result: dict[str, Any], rows: list[EquityRow], controls: JobControls
) -> None:
    """
    What the trusted commentators said about the candidates, and the ±3 it earns.

    Applied to the total only — never to candidacy. A speaker's call is a claim
    about the future; the gate is about what the chart and the statements have
    already done, and a strong voice must not rescue a name that failed it.
    """
    candidates = result["candidates"]
    tickers = [c["ticker"] for c in candidates]

    def progress(done: int, total: int) -> None:
        controls.on_partial({"progress": {"stage": "voices", "done": done, "total": total}})

    try:
        by_ticker, report = await voices.voices_for(tickers, rows, on_progress=progress)
    except Exception as e:  # noqa: BLE001 — a commentator check must not end the scan
        logger.warning("Radar voices step failed: %s", e)
        by_ticker, report = {}, voices.VoicesReport(checked=False, failures=[str(e)])

    result["voices_report"] = asdict(report)
    for candidate in candidates:
        entries = by_ticker.get(candidate["ticker"], [])
        candidate["voices"] = entries
        adjustment = voices.adjustment_for(entries)
        if adjustment is not None and candidate["score_total"] is not None:
            candidate["adjustments"].append(asdict(adjustment))
            candidate["score_total"] = max(
                0, min(100, candidate["score_total"] + adjustment.points)
            )
    candidates.sort(key=lambda c: (-(c["score_total"] or 0), c["ticker"]))


# ── Memos ───────────────────────────────────────────────────────────────────


async def _write_memos(profile: Profile, result: dict[str, Any], controls: JobControls) -> None:
    """
    One memo at a time, each waited for, the result re-persisted after each.

    Sequential on purpose: the provider chain defaults to a local model, and
    fifteen simultaneous prompts would make every one of them slower than the
    fifteen in a row. Waiting is bounded so a stalled provider costs minutes, not
    the scan.
    """
    finalists = result["candidates"][:MAX_MEMOS]
    for index, candidate in enumerate(finalists, start=1):
        candidate["memo"] = await _settled_memo(candidate, profile.label)
        result["memos"] = {"done": index, "total": len(finalists)}
        write_last(profile.key, result)
        controls.on_partial(result)


async def _settled_memo(candidate: dict[str, Any], horizon_label: str) -> dict[str, Any]:
    deadline = time.monotonic() + MEMO_WAIT_SECONDS
    note = await memo_for(candidate, horizon_label)
    while note.get("status") == "generating" and time.monotonic() < deadline:
        await asyncio.sleep(MEMO_POLL_SECONDS)
        note = await memo_for(candidate, horizon_label)
    if note.get("status") == "generating":
        note = {
            "status": "unavailable",
            "note": None,
            "generated_at": None,
            "reason": "timeout",
        }
    return note
