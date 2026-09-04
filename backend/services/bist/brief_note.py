"""
A grounded sentence for one followed Borsa İstanbul instrument.

The BIST board's answer to `services/asset_brief_service.py`'s note, built on
the same engine (`services/ai_notes.py`) and under the same contract: every
figure is computed in Python, quantized before it is fingerprinted, and rendered
into the prompt from those same rounded values — so a cached note can never cite
a number that has since moved.

What is different is the read. The crypto card's note is about a session; this
one is about a year, because that is the window this realm can deflate and the
nominal-versus-real gap is the fact the whole board exists to surface. A note
that described today's tape on a page arguing about purchasing power would be
answering a question nobody on it asked.

Nothing here raises. A note is decoration on a payload that is already complete,
so every failure comes back as `unavailable` and the card renders without it.
"""

from typing import Any, Optional

from services.ai_notes import NoteSpec, get_note

NOTE_SPEC = NoteSpec(
    kind="bist_brief",
    prompt="notes/bist_brief",
    # Two or three sentences. The card has room for a paragraph and no more, and
    # a longer note would push the figures it is explaining off the card.
    max_tokens=200,
    temperature=0.2,
    # Fund net asset values publish once a day and equity fundamentals move
    # slowly, so the fingerprint alone would hold a note for a long quiet
    # stretch. A day is the ceiling on how stale a reading may sound.
    max_age_seconds=24 * 3600,
)

UNKNOWN = "not available"


def _pct(value: Optional[float], digits: int = 1) -> Optional[float]:
    """A fraction as a rounded percentage, or None. The quantization step."""
    if value is None:
        return None
    try:
        return round(float(value) * 100, digits)
    except (TypeError, ValueError):
        return None


def _num(value: Optional[float], digits: int = 1) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _show_pct(value: Optional[float], sign: bool = True) -> str:
    if value is None:
        return UNKNOWN
    return f"{value:+.1f}%" if sign else f"{value:.1f}%"


def _framed(payload: dict[str, Any], window: str = "1y") -> dict[str, Any]:
    frames = payload.get("framed_returns") or payload.get("returns") or {}
    frame = frames.get(window) if isinstance(frames, dict) else None
    return frame if isinstance(frame, dict) else {}


# ── Shares ───────────────────────────────────────────────────────────────────


def stock_facts(payload: dict[str, Any]) -> dict[str, Any]:
    """
    The fingerprint input: everything the note may say, and nothing else.

    `range_position` is bucketed to 5% because it is derived from a price that
    moves every session; fingerprinting it raw would retire the note daily on an
    instrument whose story had not changed.
    """
    frame = _framed(payload)
    price = payload.get("price")
    low = payload.get("week52_low")
    high = payload.get("week52_high")

    position = None
    if all(isinstance(v, (int, float)) for v in (price, low, high)) and high > low:
        if low <= price <= high:
            position = round(((price - low) / (high - low)) * 20) * 5

    real_meta = payload.get("real_return") or {}

    return {
        "kind": "stock",
        "ticker": payload.get("ticker"),
        "name": payload.get("name"),
        "sector": payload.get("sector"),
        "change_pct": _pct(payload.get("change_pct")),
        "nominal_1y": _pct(frame.get("nominal")),
        "real_1y": _pct(frame.get("real")),
        "inflation_yoy": _pct(real_meta.get("inflation_yoy")),
        "rsi": None if payload.get("rsi") is None else round(float(payload["rsi"])),
        "relative_volume": _num(payload.get("relative_volume")),
        "range_position": position,
        "free_float_pct": _pct(payload.get("free_float_pct")),
        "pe": _num(payload.get("pe")),
        "beta": _num(payload.get("beta"), 2),
    }


def stock_values(facts: dict[str, Any]) -> dict[str, str]:
    """Render the prompt's placeholders from the facts, and from nothing else."""
    lines = [
        f"- Sector: {facts['sector'] or UNKNOWN}",
        f"- Change today: {_show_pct(facts['change_pct'])}",
        f"- Return over the trailing year, nominal: {_show_pct(facts['nominal_1y'])}",
    ]

    if facts["real_1y"] is None:
        lines.append(
            "- Return over the trailing year, real: not available — the inflation "
            "series does not cover this window, so the year cannot be read in "
            "purchasing-power terms"
        )
    else:
        lines.append(
            f"- Return over the trailing year, real: {_show_pct(facts['real_1y'])} "
            f"(annual CPI {_show_pct(facts['inflation_yoy'], sign=False)})"
        )
        if facts["nominal_1y"] is not None and facts["nominal_1y"] > 0 > facts["real_1y"]:
            lines.append("- Note: this is a gain in lira and a loss in purchasing power")

    lines.append(f"- RSI: {facts['rsi']}" if facts["rsi"] is not None else f"- RSI: {UNKNOWN}")
    lines.append(
        f"- Position in its own 52-week range: {facts['range_position']}% "
        "of the way from the low to the high"
        if facts["range_position"] is not None
        else f"- Position in its own 52-week range: {UNKNOWN}"
    )
    lines.append(
        f"- Volume today against its average: {facts['relative_volume']:.1f}x"
        if facts["relative_volume"] is not None
        else f"- Volume against its average: {UNKNOWN}"
    )
    lines.append(
        f"- Free float: {_show_pct(facts['free_float_pct'], sign=False)}"
        if facts["free_float_pct"] is not None
        else f"- Free float: {UNKNOWN}"
    )
    lines.append(f"- P/E: {facts['pe']}" if facts["pe"] is not None else f"- P/E: {UNKNOWN}")

    return {
        "instrument": f"{facts['ticker']} — {facts['name'] or ''}".strip(" —"),
        "instrument_class": "a share listed on Borsa İstanbul",
        "facts": "\n".join(lines),
    }


# ── Funds ────────────────────────────────────────────────────────────────────


def fund_facts(payload: dict[str, Any]) -> dict[str, Any]:
    """The fingerprint input for a TEFAS fund."""
    frame = _framed(payload)
    metrics = payload.get("metrics") or {}
    real_meta = payload.get("real_return") or {}

    return {
        "kind": "fund",
        "code": payload.get("code"),
        "title": payload.get("title"),
        "umbrella": payload.get("umbrella"),
        "risk_value": payload.get("risk_value"),
        "nominal_1y": _pct(frame.get("nominal")),
        "real_1y": _pct(frame.get("real")),
        "inflation_yoy": _pct(real_meta.get("inflation_yoy")),
        "sharpe": _num(metrics.get("sharpe"), 2),
        "sortino": _num(metrics.get("sortino"), 2),
        "max_drawdown": _pct(metrics.get("max_drawdown")),
        "volatility": _pct(metrics.get("volatility")),
        "recovery_days": metrics.get("recovery_days"),
        "category_rank": payload.get("category_rank"),
        "category_size": payload.get("category_size"),
    }


def fund_values(facts: dict[str, Any]) -> dict[str, str]:
    lines = [
        f"- Umbrella type: {facts['umbrella'] or UNKNOWN}",
        f"- TEFAS risk grade: {facts['risk_value']}/7"
        if facts["risk_value"] is not None
        else f"- TEFAS risk grade: {UNKNOWN}",
        f"- Return over the trailing year, nominal: {_show_pct(facts['nominal_1y'])}",
    ]

    if facts["real_1y"] is None:
        lines.append(
            "- Return over the trailing year, real: not available — the inflation "
            "series does not cover this window, so the year cannot be read in "
            "purchasing-power terms"
        )
    else:
        lines.append(
            f"- Return over the trailing year, real: {_show_pct(facts['real_1y'])} "
            f"(annual CPI {_show_pct(facts['inflation_yoy'], sign=False)})"
        )
        if facts["nominal_1y"] is not None and facts["nominal_1y"] > 0 > facts["real_1y"]:
            lines.append("- Note: this is a gain in lira and a loss in purchasing power")

    lines.append(
        f"- Sharpe ratio: {facts['sharpe']}"
        if facts["sharpe"] is not None
        else f"- Sharpe ratio: {UNKNOWN}"
    )
    lines.append(
        f"- Maximum drawdown: {_show_pct(facts['max_drawdown'])}"
        if facts["max_drawdown"] is not None
        else f"- Maximum drawdown: {UNKNOWN}"
    )
    lines.append(
        f"- Days to recover from that drawdown: {facts['recovery_days']}"
        if facts["recovery_days"] is not None
        else "- Days to recover from that drawdown: never recovered within the window"
    )
    lines.append(
        f"- Annualised volatility: {_show_pct(facts['volatility'], sign=False)}"
        if facts["volatility"] is not None
        else f"- Annualised volatility: {UNKNOWN}"
    )
    if facts["category_rank"] is not None and facts["category_size"]:
        lines.append(
            f"- Rank within its category: {facts['category_rank']} of {facts['category_size']}"
        )

    return {
        "instrument": f"{facts['code']} — {facts['title'] or ''}".strip(" —"),
        "instrument_class": "a TEFAS mutual fund",
        "facts": "\n".join(lines),
    }


# ── Entry points ─────────────────────────────────────────────────────────────


async def note_for_stock(payload: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
    facts = stock_facts(payload)
    return await get_note(NOTE_SPEC, facts, stock_values(facts), user_id)


async def note_for_fund(payload: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
    facts = fund_facts(payload)
    return await get_note(NOTE_SPEC, facts, fund_values(facts), user_id)
