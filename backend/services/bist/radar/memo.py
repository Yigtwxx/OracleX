"""
The veteran's memo on one Radar candidate.

Same engine and same contract as every other note on the realm
(`services/ai_notes`): the scan computes the score, the levels and every flag
in Python; the figures are quantized, fingerprinted and rendered into the
prompt from those rounded values; the model explains a read it cannot change.
What differs is the voice — the prompt asks for a memo from someone who has
held Turkish equities through five crises — and the length, three short
paragraphs rather than one.

A memo that does not arrive leaves the candidate card complete: entry band,
stop, targets and the score breakdown are all drawn without it.
"""

from __future__ import annotations

from typing import Any, Optional

from services.ai_notes import NoteSpec, get_note

MEMO_SPEC = NoteSpec(
    kind="bist_radar_memo",
    prompt="notes/bist_radar_memo",
    # Three short paragraphs. Longer and the card scrolls past the levels it is
    # explaining.
    max_tokens=380,
    temperature=0.25,
    # A scan is a snapshot of a day. The fingerprint retires the memo when the
    # read changes; this caps how old a memo about an unchanged read may sound.
    max_age_seconds=12 * 3600,
    max_chars=1400,
)

UNKNOWN = "not available"


def _pct(value: Optional[float], digits: int = 1) -> Optional[float]:
    if value is None:
        return None
    return round(float(value) * 100, digits)


def _num(value: Optional[float], digits: int = 1) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)


def _step(value: Optional[int], step: int = 5) -> Optional[int]:
    """Scores to the nearest `step`, so a point's drift does not retire the memo."""
    if value is None:
        return None
    return int(round(value / step) * step)


def memo_facts(candidate: dict[str, Any], horizon_label: str) -> dict[str, Any]:
    """The fingerprint: everything the memo may cite, rounded, and nothing else."""
    levels = candidate.get("levels") or {}
    fundamentals = candidate.get("fundamentals") or {}
    street = candidate.get("street") or {}
    return {
        "ticker": candidate.get("ticker"),
        "name": candidate.get("name"),
        "sector": candidate.get("sector"),
        "sector_class": candidate.get("sector_class"),
        "horizon": horizon_label,
        "score_total": _step(candidate.get("score_total")),
        "score_technical": _step(candidate.get("score_technical")),
        "score_fundamental": _step(candidate.get("score_fundamental")),
        "fundamental_depth": candidate.get("fundamental_depth"),
        "pullback_pct": _pct(levels.get("pullback_pct"), 0),
        "rsi": None if levels.get("rsi") is None else round(float(levels["rsi"])),
        "structure": levels.get("structure"),
        "zone_source": levels.get("zone_source"),
        "zone_touches": levels.get("zone_touches"),
        "volume_ratio": _num(levels.get("volume_ratio")),
        "rr": _num(levels.get("rr")),
        "range_position": _step(_pct(levels.get("range_position"), 0), 10),
        "roe": _pct(fundamentals.get("roe"), 0),
        "real_revenue_growth": _pct(fundamentals.get("real_revenue_growth"), 0),
        "real_profit_growth": _pct(fundamentals.get("real_profit_growth"), 0),
        "net_debt_ebitda": _num(fundamentals.get("net_debt_ebitda")),
        "short_debt_share": _pct(fundamentals.get("short_debt_share"), 0),
        "loss_quarters": fundamentals.get("loss_quarters"),
        "cash_conversion": _num(fundamentals.get("cash_conversion")),
        "pe": _num(candidate.get("pe")),
        "pb": _num(candidate.get("pb")),
        "inflation": _pct(fundamentals.get("inflation"), 0),
        "street_gap": _pct(street.get("gap_pct"), 0),
        "analysts": street.get("analysts"),
        "flags": sorted(
            f["key"] if isinstance(f, dict) else str(f) for f in (candidate.get("flags") or [])
        ),
        "vetoes_checked": bool(candidate.get("kap_checked")),
        "voices": [
            {
                "name": v.get("voice_name"),
                "stance": v.get("stance"),
                "accuracy": None
                if not v.get("accuracy") or not v["accuracy"].get("n")
                else int(round(v["accuracy"]["shrunk"] * 20) * 5),
                "n": (v.get("accuracy") or {}).get("n"),
            }
            for v in (candidate.get("voices") or [])
            if v.get("stance") in ("bullish", "bearish", "neutral")
        ][:6],
    }


def _show_pct(value: Optional[float], sign: bool = True) -> str:
    if value is None:
        return UNKNOWN
    return f"{value:+.0f}%" if sign else f"{value:.0f}%"


def memo_values(facts: dict[str, Any]) -> dict[str, str]:
    """The prompt's placeholders, rendered from the facts and from nothing else."""
    structure = {
        "higher": "higher highs and higher lows",
        "mixed": "mixed swing structure",
        "lower": "lower lows",
    }.get(facts["structure"] or "", UNKNOWN)
    band = (
        f"a support cluster the price has respected {facts['zone_touches']} times"
        if facts["zone_source"] == "support_zone"
        else "the slow moving average, with no swing cluster close by"
    )
    technical = [
        f"- Setup score: {facts['score_technical']}/100 within a total of {facts['score_total']}/100",
        f"- Pulled back about {_show_pct(facts['pullback_pct'], sign=False)} from its 20-day high, "
        f"into {band}",
        f"- Swing structure: {structure}",
        f"- RSI: {facts['rsi'] if facts['rsi'] is not None else UNKNOWN}",
        (
            f"- Volume on the pullback against the month before: {facts['volume_ratio']:.1f}x"
            if facts["volume_ratio"] is not None
            else f"- Volume on the pullback: {UNKNOWN}"
        ),
        f"- Reward to risk from the band to the first target: {facts['rr']}",
        (
            f"- Position in its 52-week range: about {facts['range_position']}% up from the low"
            if facts["range_position"] is not None
            else f"- Position in its 52-week range: {UNKNOWN}"
        ),
    ]

    if facts["fundamental_depth"] == "full":
        fundamentals = [
            f"- Fundamental score: {facts['score_fundamental']}/100 from eight quarters of statements",
        ]
    else:
        fundamentals = [
            f"- Fundamental score: {facts['score_fundamental']}/100 — the statements could not be "
            "read, so this rests on the valuation multiples alone and the balance sheet is unverified",
        ]
    fundamentals += [
        f"- Return on equity: {_show_pct(facts['roe'], sign=False)} against annual CPI of "
        f"{_show_pct(facts['inflation'], sign=False)}",
        f"- Revenue over the trailing year, in real terms: {_show_pct(facts['real_revenue_growth'])}",
        f"- Operating profit over the trailing year, in real terms: {_show_pct(facts['real_profit_growth'])}",
        (
            f"- Net debt to EBITDA: {facts['net_debt_ebitda']}"
            if facts["net_debt_ebitda"] is not None
            else f"- Net debt to EBITDA: {UNKNOWN}"
        ),
        (
            f"- Share of financial debt due within a year: {_show_pct(facts['short_debt_share'], sign=False)}"
            if facts["short_debt_share"] is not None
            else f"- Share of financial debt due within a year: {UNKNOWN}"
        ),
        (
            f"- Losing quarters in the last four: {facts['loss_quarters']}"
            if facts["loss_quarters"] is not None
            else f"- Losing quarters in the last four: {UNKNOWN}"
        ),
        (
            f"- Operating cash flow over net income: {facts['cash_conversion']:.1f}"
            if facts["cash_conversion"] is not None
            else f"- Operating cash flow over net income: {UNKNOWN}"
        ),
        f"- P/E: {facts['pe'] if facts['pe'] is not None else UNKNOWN}; "
        f"P/B: {facts['pb'] if facts['pb'] is not None else UNKNOWN}",
    ]

    context = []
    if facts["analysts"]:
        context.append(
            f"- Analyst consensus: {facts['analysts']} analysts, average target "
            f"{_show_pct(facts['street_gap'])} from the price"
        )
    else:
        context.append("- Analyst consensus: no coverage in the data")
    context.append(
        "- Filings checked for rights issues and trading measures: none found"
        if facts["vetoes_checked"]
        else "- Filings could not be checked this run"
    )
    if facts["flags"]:
        context.append(f"- Flags raised by the scan: {', '.join(facts['flags'])}")
    if facts["voices"]:
        for v in facts["voices"]:
            record = (
                f"graded accuracy about {v['accuracy']}% over {v['n']} calls"
                if v["accuracy"] is not None
                else "no graded record yet"
            )
            context.append(
                f"- Commentator {v['name']} was {v['stance']} on this name in the last four weeks "
                f"({record})"
            )
    else:
        context.append(
            "- None of the followed commentators mentioned this name in the last four weeks"
        )

    return {
        "instrument": f"{facts['ticker']} — {facts['name'] or ''} ({facts['sector'] or UNKNOWN})".strip(),
        "horizon": facts["horizon"],
        "technical": "\n".join(technical),
        "fundamentals": "\n".join(fundamentals),
        "context": "\n".join(context),
    }


async def memo_for(candidate: dict[str, Any], horizon_label: str) -> dict[str, Any]:
    facts = memo_facts(candidate, horizon_label)
    return await get_note(MEMO_SPEC, facts, memo_values(facts))
