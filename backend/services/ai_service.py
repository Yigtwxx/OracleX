"""
AI analysis service — prompt assembly, response parsing and fallbacks.

Provider-agnostic: the actual model call goes through `services.llm`, which
resolves the configured provider chain (local Ollama, Groq, Gemini, …).

The prompts themselves live under `backend/prompts/` and are loaded through
`services.prompts`; this module only renders the data blocks they interpolate.
"""

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from services import llm
from services.article_service import Article, render_article_block
from services.prompts import load_prompt, render_prompt
from utils import Colors


# Context window requested from Ollama for the news pipeline. Sized for the
# enriched prompt (system + article body + precedent + technicals + instructions)
# with room for the answer.
NEWS_NUM_CTX = 8192


def _log(emoji: str, msg: str, color: str = Colors.CYAN):
    print(f"{color}      {emoji}  {msg}{Colors.END}", flush=True)


async def check_ai_health() -> bool:
    """True if any configured LLM provider can serve a request."""
    return await llm.llm_health()


def _price_block(current_price: Optional[float]) -> str:
    """The spot price, or an explicit statement that there isn't one."""
    if current_price and current_price > 0:
        return f"CURRENT PRICE: ${current_price:.4f}"
    return "CURRENT PRICE: unavailable for this analysis."


def _is_degraded_technical(technical: Dict[str, Any]) -> bool:
    """
    True when a technicals payload carries no usable levels.

    `technical_analysis_service` returns None rather than a placeholder when it
    cannot compute anything, so this is a belt-and-braces check on the shape:
    without a spot price there is nothing to anchor the levels to, and a payload
    with no supports and no resistances has nothing to say.
    """
    if not technical.get("current_price"):
        return True
    return not (technical.get("support_levels") or technical.get("resistance_levels"))


def _technical_block(technical: Optional[Dict[str, Any]]) -> str:
    """
    Render computed technical levels as read-only ground truth.

    The model is never asked to derive levels from a spot price — that is
    fabrication, and it is what this block exists to prevent. When no levels were
    computed, the block says so and forbids inventing them.
    """
    unavailable = (
        "TECHNICAL LEVELS: not computed for this asset. No support, resistance, "
        "pivot or target levels exist for this analysis — do not construct any, "
        "and report the gap if the news turns on a level."
    )
    if not technical or _is_degraded_technical(technical):
        return unavailable

    def levels(key: str) -> str:
        values = technical.get(key) or []
        rendered = ", ".join(str(v) for v in values if v not in (None, ""))
        return rendered or "n/a"

    lines = [
        "TECHNICAL LEVELS (computed from market data — authoritative, copy exactly):",
        "Support and resistance are bands price reversed in, not single prices. Quote both "
        "bounds; a neater number inside a band is not a level.",
        f"- Support: {levels('support_levels')}",
        f"- Resistance: {levels('resistance_levels')}",
        f"- RSI: {technical.get('rsi_signal') or 'n/a'} ({technical.get('rsi_value', 'n/a')})",
        f"- Pivot: {technical.get('pivot_point') or 'n/a'}",
        f"- Target: {technical.get('target_price') or 'n/a'}",
    ]
    if technical.get("trend"):
        lines.append(f"- Trend: {technical['trend']}")
    if technical.get("atr"):
        lines.append(f"- ATR: {technical['atr']}")
    lines += _horizon_lines(technical)
    return "\n".join(lines)


def _horizon_lines(technical: Dict[str, Any]) -> List[str]:
    """
    The multi-timeframe context behind the flat levels above.

    A news verdict is a short-horizon call, but "RSI 41" reads very differently
    depending on whether the weekly is in an uptrend and where in its own range
    the asset trades. Both are already computed, so the only question was whether
    to spend the tokens; three lines is what that judgement came to.
    """
    lines: List[str] = []

    reads = technical.get("timeframes") or {}
    if reads:
        parts = []
        for label, read in reads.items():
            rsi = (read.get("rsi") or {}).get("value")
            slope = (read.get("rsi") or {}).get("slope") or ""
            cell = f"RSI {rsi:.1f} {slope}".strip() if isinstance(rsi, (int, float)) else "RSI n/a"
            parts.append(f"{label} {read.get('trend') or 'n/a'}, {cell}")
        lines.append(f"- Per timeframe: {' | '.join(parts)}")

    structure = technical.get("structure") or {}
    if structure.get("position_percent") is not None:
        lines.append(
            f"- Position: {structure['position_percent']:.0f}% of its "
            f"{structure.get('range_bars')}-bar {structure.get('range_timeframe')} range, "
            f"{structure.get('distance_to_high_percent', 0):+.1f}% from that high"
        )
    if structure.get("timeframe_alignment"):
        lines.append(f"- Timeframe agreement: {structure['timeframe_alignment']}")

    divergences = [
        f"{label} {read['rsi']['divergence']}"
        for label, read in reads.items()
        if (read.get("rsi") or {}).get("divergence")
    ]
    if divergences:
        lines.append(f"- RSI divergence: {'; '.join(divergences)}")

    return lines


def _precedent_block(rag_context: str) -> str:
    """
    Wrap retrieved history so it cannot be mistaken for current data.

    Same framing the chat service uses for the same vector store
    (`chat_service._rag_block`): these are past events, and their figures are
    never today's.
    """
    if not rag_context:
        return "HISTORICAL PRECEDENT: none retrieved for this item."
    return (
        "HISTORICAL PRECEDENT (retrieved, not current)\n"
        "These are PAST events and price moves. Never present them as today's data.\n"
        "Use them to calibrate confidence, not to source figures.\n\n"
        f"{rag_context}"
    )


def _regime_block(regime: str) -> str:
    """
    The market backdrop, or an explicit statement that it could not be read.

    Rendered upstream by `analysis_data.render_regime_markdown`; this only
    handles the empty case, so a missing backdrop reads as a gap rather than as
    a calm market.
    """
    if regime and regime.strip():
        return regime.strip()
    return (
        "MARKET REGIME: not available for this analysis. No breadth, sentiment or "
        "positioning data could be collected — do not characterise the market "
        "backdrop, and report the gap."
    )


async def analyze_news(
    title: str,
    summary: str,
    symbol: Optional[str],
    asset_type: str,
    current_price: float = None,
    rag_context: str = "",
    user_id: Optional[str] = None,
    technical: Optional[Dict[str, Any]] = None,
    article: Optional[Article] = None,
    regime: str = "",
) -> dict:
    """
    Analyze a news item using the configured LLM with optional RAG context.

    Args:
        title: News headline
        summary: News summary/body
        symbol: Trading symbol (e.g., BINANCE:BTCUSDT)
        asset_type: "crypto" or "stock"
        current_price: Current asset price, shown to the model as context
        rag_context: Historical context from similar past news (RAG)
        user_id: Caller's id, so their own provider is used when they enabled
            it for news. None (e.g. the scheduler) uses the server chain.
        technical: Levels already computed by `technical_analysis_service`. Passed
            in rather than derived, so the model reads real levels instead of
            being asked to invent them from the spot price.
        article: The publisher's article body, when it could be fetched. The feed
            summary is truncated to 200 characters, which is not enough to judge
            a mechanism from; None makes the prompt say so rather than letting
            the model infer what the body would have contained.
        regime: Rendered market backdrop from `analysis_data.render_regime_markdown`.
            Empty renders as an explicit gap.

    Returns:
        Analysis result dictionary
    """
    # A headline that names no asset still gets analysed; the prompt is told so
    # explicitly rather than being handed a ticker the item is not about.
    clean_symbol = (symbol.split(":")[-1] if symbol else None) or "no specific asset"
    asset_name = "cryptocurrency" if asset_type == "crypto" else "stock"

    system_prompt = load_prompt("news/system_sentiment")
    user_prompt = render_prompt(
        "news/analyze",
        clean_symbol=clean_symbol,
        symbol=symbol or "none — this item was not attributed to a ticker",
        asset_name=asset_name,
        report_date=datetime.now().strftime("%B %d, %Y %H:%M"),
        price=_price_block(current_price),
        technical=_technical_block(technical),
        rag_context=_precedent_block(rag_context),
        regime=_regime_block(regime),
        article=render_article_block(article),
        title=title,
        summary=summary,
    )

    try:
        start_time = time.time()
        _log("💭", "AI is thinking... (this may take 10-30 seconds)", Colors.PURPLE)

        raw_response = await llm.generate(
            user_prompt,
            system=system_prompt,
            temperature=0.2,
            top_p=0.85,
            max_tokens=600,
            timeout=90.0,
            reasoning=False,  # structured JSON: keep the full budget for the answer
            json_mode=True,
            # Ollama-only options (the OpenAI-compatible adapter ignores `extra`).
            # `num_ctx` is not optional: Ollama defaults to 4096 and silently
            # truncates from the front, so an over-long prompt drops the system
            # prompt — the calibration and anti-fabrication rules — first.
            extra={"top_k": 40, "repeat_penalty": 1.1, "num_ctx": NEWS_NUM_CTX},
            prefer=await llm.provider_for(user_id, "news"),
        )

        elapsed = time.time() - start_time

        if raw_response is not None:
            _log("✓", f"AI responded in {elapsed:.1f} seconds", Colors.GREEN)

            # Parse JSON from response
            analysis = parse_llm_response(raw_response)

            # Log the result
            sentiment_emoji = {"bullish": "📈", "bearish": "📉", "neutral": "➖"}
            _log(
                sentiment_emoji.get(analysis.get("sentiment", "neutral"), "❓"),
                f"Result: {analysis.get('sentiment', 'unknown').upper()} ({analysis.get('confidence', 0) * 100:.0f}% confidence)",
                Colors.CYAN,
            )

            return analysis
        else:
            _log("⚠", "Using fallback keyword-based analysis...", Colors.YELLOW)
            return get_fallback_analysis(title, symbol)

    except Exception as e:
        # The LLM layer already exhausted retries and every fallback provider.
        _log("✗", f"AI analysis failed: {e}", Colors.RED)
        _log("⚠", "Using fallback keyword-based analysis...", Colors.YELLOW)
        return get_fallback_analysis(title, symbol)


async def generate_completion(
    prompt: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 1000,
    user_id: Optional[str] = None,
) -> str:
    """
    Generic text generation. Useful for generating reports, summaries, etc.

    `system_prompt` defaults to the terminal's standing grounding rules
    (`prompts/generic/system_default`) rather than a generic assistant persona —
    anything this app generates is read as research output.

    `user_id` routes through that user's own provider when they enabled it for
    reports; None uses the server chain.
    """
    try:
        result = await llm.generate(
            prompt,
            system=system_prompt or load_prompt("generic/system_default"),
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=120.0,
            reasoning=False,  # report generation: deterministic, no hidden reasoning
            prefer=await llm.provider_for(user_id, "reports"),
        )
        return result or ""

    except Exception as e:
        _log("✗", f"Text generation failed: {e}", Colors.RED)
        return ""


MATERIALITY_LEVELS = ("extraordinary", "significant", "routine", "noise")
EVIDENCE_DIRECTIONS = ("bullish", "bearish", "neutral")
EVIDENCE_WEIGHTS = ("primary", "supporting", "context")

# A model that pads the evidence list is padding the analysis. Six claims is
# already more than a single news item supports.
MAX_EVIDENCE_ITEMS = 6


def _clean_str(value: Any) -> Optional[str]:
    """A trimmed string, or None — never an empty string masquerading as content."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def _normalise_materiality(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    return lowered if lowered in MATERIALITY_LEVELS else None


def _parse_evidence(value: Any) -> list:
    """
    Keep only well-formed evidence items.

    A claim is mandatory; a quote is not, because a point drawn from the market
    or regime data has no article line to cite. Malformed entries are dropped
    rather than repaired — a half-parsed claim in the UI reads as a real one.
    """
    if not isinstance(value, list):
        return []

    items = []
    for entry in value[:MAX_EVIDENCE_ITEMS]:
        if not isinstance(entry, dict):
            continue
        claim = _clean_str(entry.get("claim"))
        if not claim:
            continue

        direction = str(entry.get("direction", "")).strip().lower()
        weight = str(entry.get("weight", "")).strip().lower()
        items.append(
            {
                "claim": claim,
                "quote": _clean_str(entry.get("quote")),
                "direction": direction if direction in EVIDENCE_DIRECTIONS else "neutral",
                "weight": weight if weight in EVIDENCE_WEIGHTS else "supporting",
            }
        )
    return items


def parse_llm_response(raw_response: str) -> dict:
    """Parse the LLM response and extract JSON."""
    try:
        # Try to find JSON in the response
        start_idx = raw_response.find("{")
        end_idx = raw_response.rfind("}") + 1

        if start_idx != -1 and end_idx > start_idx:
            json_str = raw_response[start_idx:end_idx]
            analysis = json.loads(json_str)

            # Validate required fields
            required_fields = ["sentiment", "confidence", "reasoning"]
            for field in required_fields:
                if field not in analysis:
                    raise ValueError(f"Missing required field: {field}")

            # Normalize sentiment
            sentiment = analysis["sentiment"].lower()
            if sentiment not in ["bullish", "bearish", "neutral"]:
                sentiment = "neutral"

            # Ensure confidence is in valid range (allow lower values now)
            confidence = float(analysis.get("confidence", 0.50))  # Default to 50%, not 70%
            confidence = max(0.35, min(0.95, confidence))  # Allow 35-95% range

            # Only the fields the prompt actually asks for. Technical levels are
            # deliberately absent: they come from `technical_analysis_service`,
            # never from the model.
            return {
                "sentiment": sentiment,
                "confidence": round(confidence, 2),
                "reasoning": analysis.get("reasoning", "Analysis completed."),
                "materiality": _normalise_materiality(analysis.get("materiality")),
                "mechanism": _clean_str(analysis.get("mechanism")),
                "invalidation": _clean_str(analysis.get("invalidation")),
                "regime_note": _clean_str(analysis.get("regime_note")),
                "evidence": _parse_evidence(analysis.get("evidence")),
                "key_factors": analysis.get("key_factors", []),
                "price_impact": analysis.get("price_impact", ""),
                "risk_level": analysis.get("risk_level", "medium"),
                "time_horizon": analysis.get("time_horizon", "short-term"),
            }
    except (json.JSONDecodeError, ValueError) as e:
        print(f"JSON parse error: {e}")

    # If parsing fails, extract what we can
    return extract_analysis_from_text(raw_response)


def extract_analysis_from_text(text: str) -> dict:
    """Extract analysis from non-JSON text response."""
    text_lower = text.lower()

    # Determine sentiment from text
    bullish_keywords = ["bullish", "positive", "growth", "surge", "rally", "upward", "gain", "rise"]
    bearish_keywords = ["bearish", "negative", "decline", "crash", "fall", "drop", "loss", "down"]

    bullish_count = sum(1 for kw in bullish_keywords if kw in text_lower)
    bearish_count = sum(1 for kw in bearish_keywords if kw in text_lower)

    if bullish_count > bearish_count:
        sentiment = "bullish"
        confidence = min(0.65, 0.45 + (bullish_count * 0.05))  # Conservative: max 65%
    elif bearish_count > bullish_count:
        sentiment = "bearish"
        confidence = min(0.65, 0.45 + (bearish_count * 0.05))  # Conservative: max 65%
    else:
        sentiment = "neutral"
        confidence = 0.50  # Default to 50% for unclear

    return {
        "sentiment": sentiment,
        "confidence": round(confidence, 2),
        "reasoning": text[:300] if len(text) > 300 else text,
        "key_factors": [],
        "price_impact": "",
        "risk_level": "medium",
        "time_horizon": "short-term",
    }


def get_fallback_analysis(title: str, symbol: Optional[str]) -> dict:
    """
    Keyword-count analysis, used only when no LLM provider could be reached.

    It carries `source: "keyword-fallback"` so the UI can label it. Without that
    marker it is rendered identically to a model's read of the article, and a
    word count over the headline is not that.
    """
    # Simple keyword-based fallback
    title_lower = title.lower()

    bullish_words = [
        "surge",
        "rally",
        "grow",
        "gain",
        "rise",
        "high",
        "record",
        "breakthrough",
        "success",
    ]
    bearish_words = ["crash", "fall", "drop", "decline", "loss", "low", "fail", "concern", "risk"]

    bullish_score = sum(1 for w in bullish_words if w in title_lower)
    bearish_score = sum(1 for w in bearish_words if w in title_lower)

    if bullish_score > bearish_score:
        sentiment = "bullish"
        confidence = 0.55  # Conservative fallback
    elif bearish_score > bullish_score:
        sentiment = "bearish"
        confidence = 0.55  # Conservative fallback
    else:
        sentiment = "neutral"
        confidence = 0.50

    return {
        "sentiment": sentiment,
        "confidence": confidence,
        "reasoning": (
            "No AI provider was reachable, so this is a keyword count over the "
            "headline rather than an analysis of the article."
        ),
        "key_factors": ["Keyword-based analysis"],
        "price_impact": "Unable to determine - using fallback",
        "risk_level": "medium",
        "time_horizon": "short-term",
        "source": "keyword-fallback",
    }


def generate_prediction_hash(news_id: str, sentiment: str, confidence: float) -> str:
    """Generate a unique hash for the prediction."""
    data = f"{news_id}:{sentiment}:{confidence}:{datetime.now().isoformat()}"
    return hashlib.sha256(data.encode()).hexdigest()


# Per-provider budget for symbol detection. The task is a twenty-token
# extraction that a warm model answers in well under a second; the headroom is
# there for a cold local model still being paged into memory. Callers that wrap
# this in a timeout of their own must allow more than this, or the LLM layer
# never gets to try the next provider in the chain.
SYMBOL_DETECTION_TIMEOUT_S = 10.0

# What a usable answer looks like: an optional exchange prefix and a ticker.
# Anything else is not a symbol, however confident the model sounded.
_SYMBOL_RE = re.compile(r"^(?:([A-Z]{2,10}):)?([A-Z0-9][A-Z0-9.\-^]{0,11})$")


@dataclass(frozen=True)
class SymbolVerdict:
    """
    What the model said about a piece of text.

    `answered` separates "the model read this and found no tradeable asset"
    from "we never got a usable answer". They demand opposite responses: the
    first is a result and must be respected, the second is a gap that may be
    filled by a fallback. Collapsing both into a bare None is what made every
    macro headline end up attributed to a coin by the heuristic matcher.
    """

    symbol: Optional[str]  # "EXCHANGE:TICKER" or "TICKER" — not yet validated
    answered: bool


def parse_symbol_answer(raw: str) -> SymbolVerdict:
    """
    Turn a raw model completion into a verdict.

    Only strings that look like a symbol get through. The previous version
    returned anything it could not classify verbatim, so a completion of
    "Bitcoin" became the news item's symbol and was charted as one.
    """
    # Models wrap short answers in quotes, backticks or a markdown span.
    cleaned = raw.strip().strip("`").strip('"').strip("'").strip()
    tokens = cleaned.split()

    if not tokens:
        # Nothing was said. That is not "no asset" — it is no answer.
        return SymbolVerdict(symbol=None, answered=False)

    # Despite the stop sequences, some providers append a sentence. A symbol
    # followed by chatter is still usable; a sentence that merely opens with a
    # word is not, so anything running on needs an unambiguous first token.
    if len(tokens) > 2 and ":" not in tokens[0]:
        _log("⚠", f"Symbol detection: prose, not a symbol — {cleaned[:40]!r}", Colors.YELLOW)
        return SymbolVerdict(symbol=None, answered=False)

    cleaned = tokens[0].rstrip(".,;:").upper()

    if cleaned in ("NULL", "NONE"):
        return SymbolVerdict(symbol=None, answered=True)

    if not _SYMBOL_RE.match(cleaned):
        _log("⚠", f"Symbol detection: unusable answer {raw.strip()[:40]!r}", Colors.YELLOW)
        return SymbolVerdict(symbol=None, answered=False)

    return SymbolVerdict(symbol=cleaned, answered=True)


async def detect_asset_symbol(text: str, asset_type: str = "crypto") -> SymbolVerdict:
    """
    Ask the LLM which trading symbol a piece of financial text is about.

    Returns a `SymbolVerdict`. The symbol it carries is *unvalidated* — it is
    what the model said, not a ticker anyone confirmed exists. Callers must run
    it through `symbol_detection_service.resolve` before using it.

    `asset_type` is the class the caller is looking for. It is a hint, not a
    constraint: passing it lets the model pick the right exchange family up front
    instead of the caller rejecting a mismatched answer afterwards
    (`symbol_detection_service.detect_symbol_smart`).
    """
    system_prompt = load_prompt("detection/system_symbol")
    user_prompt = render_prompt(
        "detection/extract_symbol",
        asset_type=asset_type,
        text=text[:500],
    )

    try:
        raw = await llm.generate(
            user_prompt,
            system=system_prompt,
            temperature=0.1,  # Very low temp for deterministic output
            max_tokens=20,  # Short output
            stop=["\n", " "],  # Stop at newline or space to get just the symbol
            timeout=SYMBOL_DETECTION_TIMEOUT_S,
            reasoning=False,  # need just the symbol, not reasoning tokens
        )
    except Exception as e:
        _log("✗", f"Symbol detection error: {e}", Colors.RED)
        return SymbolVerdict(symbol=None, answered=False)

    # None means every provider in the chain failed — not an answer.
    if raw is None:
        return SymbolVerdict(symbol=None, answered=False)

    return parse_symbol_answer(raw)
