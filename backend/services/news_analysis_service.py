"""
Orchestration for the single-news research note.

The news equivalent of `analysis_service.generate_market_report`: it gathers the
evidence, calls the model, and assembles a `NewsAnalysis`. The staging exists so
the wait is legible — a user watching "Gathering evidence → Judging price impact"
is not watching a spinner.

Design rules carried over from the report pipeline:

* **Partial degradation.** Every evidence source is fetched independently; a
  failure becomes a named entry in ``coverage.unavailable`` rather than an error.
* **No fabricated levels.** Technical levels come from
  `technical_analysis_service` and are copied into the response verbatim. The
  model is never asked for one and anything it supplies is discarded.
* **Gaps are stated.** A verdict built on a headline alone must not look like one
  built on the full article and four feeds.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import settings
from models.schemas import (
    Citation,
    DataCoverage,
    EvidenceItem,
    NewsAnalysis,
    NewsItem,
    PrecedentAnalogy,
    TechnicalSignals,
)
from services import ai_service, news_analysis_store
from services.article_service import Article, fetch_article

logger = logging.getLogger(__name__)

StageCallback = Callable[[str], None]
PartialCallback = Callable[[Dict[str, Any]], None]

STAGES: List[Dict[str, str]] = [
    {"key": "gathering", "label": "Gathering evidence"},
    {"key": "judging", "label": "Judging price impact"},
]

# The whole gathering stage, not each feed. Everything inside runs concurrently,
# so this is a wall-clock ceiling: past it, whatever has arrived is what the
# model gets and the rest is reported as a gap.
GATHER_TIMEOUT_SECONDS = 8.0

# Human-readable names for the evidence sources, so a gap in the UI reads as
# "Market regime" rather than "regime".
SOURCE_NAMES = {
    "article": "Source article",
    "technical": "Technical levels",
    "precedent": "Historical precedent",
    "regime": "Market regime",
    "price": "Spot price",
}

RISK_LABELS = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH"}
HORIZON_LABELS = {
    "immediate": "Immediate (minutes to hours)",
    "short-term": "Short-term (1-7 days)",
    "medium-term": "Medium-term (1-4 weeks)",
    "long-term": "Long-term (1+ months)",
}


class Evidence:
    """Everything the gathering stage managed to collect."""

    def __init__(self) -> None:
        self.article: Optional[Article] = None
        self.technical: Optional[Dict[str, Any]] = None
        self.precedent_markdown: str = ""
        self.precedents: List[Dict[str, Any]] = []
        self.regime_markdown: str = ""
        self.current_price: Optional[float] = None
        self.unavailable: List[str] = []

    def mark_missing(self, source: str) -> None:
        name = SOURCE_NAMES.get(source, source)
        if name not in self.unavailable:
            self.unavailable.append(name)


async def _safe(name: str, coro: Any) -> Tuple[str, Optional[Any]]:
    """Await one evidence source, turning any failure into a None result."""
    try:
        return name, await coro
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 — one missing source must not kill the note
        logger.warning("News evidence source '%s' failed: %s", name, e)
        return name, None


async def _fetch_price(symbol: Optional[str]) -> Optional[float]:
    """
    Spot price, fetched server-side.

    This used to be a separate round-trip from the browser before the analysis
    request, which serialised two calls and swallowed every error to null.
    """
    if not symbol:
        return None
    from services.price_service import get_current_price

    return await get_current_price(symbol)


async def gather_evidence(news_item: NewsItem, current_price: Optional[float]) -> Evidence:
    """
    Collect every input the model reads, concurrently and independently.

    Never raises: the whole stage is bounded, and anything that fails or is still
    in flight at the deadline is recorded as a gap.
    """
    from services.analysis_data import cached_regime_markdown
    from services.rag_v3_service import build_news_rag_bundle
    from services.technical_analysis_service import get_technical_analysis

    evidence = Evidence()
    evidence.current_price = current_price

    tasks = [
        # Trusted: the URL came from one of the RSS feeds in `news_service`, not
        # from a user or a model, so the impersonated retry stays available for
        # the publishers that fingerprint the handshake.
        _safe("article", fetch_article(news_item.url, trusted_source=True)),
        _safe(
            "precedent",
            build_news_rag_bundle(
                title=news_item.title,
                summary=news_item.summary,
                symbol=news_item.symbol,
                asset_type=news_item.asset_type,
            ),
        ),
        _safe("regime", cached_regime_markdown(news_item.asset_type)),
    ]
    if news_item.symbol:
        # Real levels for equities as much as for crypto: get_technical_analysis
        # routes crypto to OKX candles and stocks to Yahoo daily bars.
        tasks.append(_safe("technical", get_technical_analysis(news_item.symbol)))
    if current_price is None and news_item.symbol:
        tasks.append(_safe("price", _fetch_price(news_item.symbol)))

    try:
        results = dict(await asyncio.wait_for(asyncio.gather(*tasks), GATHER_TIMEOUT_SECONDS))
    except TimeoutError:
        logger.warning(
            "Evidence gathering for '%s' hit the %.0fs ceiling",
            news_item.title[:60],
            GATHER_TIMEOUT_SECONDS,
        )
        results = {}

    evidence.article = results.get("article")
    evidence.technical = results.get("technical")

    bundle = results.get("precedent")
    if bundle:
        evidence.precedent_markdown, evidence.precedents = bundle

    evidence.regime_markdown = results.get("regime") or ""
    if evidence.current_price is None:
        evidence.current_price = results.get("price")

    if not evidence.article:
        evidence.mark_missing("article")
    if news_item.symbol and not evidence.technical:
        evidence.mark_missing("technical")
    if not evidence.precedents:
        evidence.mark_missing("precedent")
    if not evidence.regime_markdown:
        evidence.mark_missing("regime")

    return evidence


def _coverage(evidence: Evidence) -> DataCoverage:
    if evidence.article:
        article_state = "full"
        chars = evidence.article.char_count
    else:
        # The feed summary is always present; calling that "unavailable" would
        # overstate the gap, and calling it "full" would understate it.
        article_state = "summary-only"
        chars = 0

    return DataCoverage(
        article_text=article_state,
        article_chars=chars,
        unavailable=list(evidence.unavailable),
    )


def _technical_signals(technical: Optional[Dict[str, Any]]) -> Optional[TechnicalSignals]:
    """
    Computed levels only. None hides the section rather than showing blanks.

    The multi-timeframe read rides along rather than being summarised away: the
    panel that renders this is the only place a reader can check the levels the
    verdict was written from, and "support: $61,830 – $63,238" alone does not
    say that three timeframes found that band or that the weekly is bearish
    under it. Every field is optional, so an older stored analysis — written
    before this shape existed — still parses.
    """
    if not technical:
        return None

    zones = technical.get("zones") or {}
    return TechnicalSignals(
        rsi_signal=technical.get("rsi_signal"),
        support_levels=technical.get("support_levels") or [],
        resistance_levels=technical.get("resistance_levels") or [],
        target_price=technical.get("target_price"),
        current_price=technical.get("current_price"),
        primary_timeframe=technical.get("primary_timeframe") or technical.get("timeframe"),
        # A dict keyed by timeframe becomes an ordered list here: the reading
        # order (short to long) is part of the meaning, and JSON objects do not
        # promise it.
        timeframes=list((technical.get("timeframes") or {}).values()),
        support_zones=zones.get("support") or [],
        resistance_zones=zones.get("resistance") or [],
        inside_zones=zones.get("inside") or [],
        structure=technical.get("structure"),
    )


def _precedent_models(rows: List[Dict[str, Any]]) -> List[PrecedentAnalogy]:
    models = []
    for row in rows:
        try:
            models.append(
                PrecedentAnalogy(
                    title=row.get("title") or "(untitled)",
                    date=row.get("date"),
                    symbol=row.get("symbol"),
                    similarity=float(row.get("similarity") or 0.0),
                    outcome=row.get("outcome"),
                    price_change=row.get("price_change"),
                    apparent_sentiment=row.get("apparent_sentiment"),
                    durable_direction=row.get("durable_direction"),
                    horizons={str(k): float(v) for k, v in (row.get("horizons") or {}).items()},
                    max_drawdown_pct=row.get("max_drawdown_pct"),
                    max_runup_pct=row.get("max_runup_pct"),
                    surprised=bool(row.get("surprised", False)),
                    inverted=bool(row.get("inverted", False)),
                    source=row.get("source") or "news",
                )
            )
        except (TypeError, ValueError) as e:
            logger.debug("Dropping malformed precedent %r: %s", row.get("title"), e)
    return models


def _legacy_context(analysis: Dict[str, Any]) -> str:
    """
    The old flat `historical_context` string.

    Kept populated so `SentimentAnalysis` consumers keep working, but built here
    rather than in the router — assembling prose was never the router's job.
    """
    risk = RISK_LABELS.get(str(analysis.get("risk_level", "medium")).lower(), "MEDIUM")
    horizon = HORIZON_LABELS.get(
        str(analysis.get("time_horizon", "short-term")).lower(), "Short-term (1-7 days)"
    )

    parts = [f"Risk Level: {risk} | Time Horizon: {horizon}"]
    factors = analysis.get("key_factors") or []
    if factors:
        parts.append(f"Key factors: {', '.join(str(f) for f in factors[:3])}")
    if analysis.get("price_impact"):
        parts.append(f"Expected impact: {analysis['price_impact']}")
    return ". ".join(parts)


def _citations(news_item: NewsItem, evidence: Evidence) -> List[Citation]:
    if not news_item.url:
        return []
    label = news_item.source or "Source article"
    if evidence.article:
        label = f"{label} (full text read)"
    return [Citation(label=label, url=news_item.url, kind="article")]


async def analyse_news_item(
    news_item: NewsItem,
    current_price: Optional[float] = None,
    user_id: Optional[str] = None,
    on_stage: Optional[StageCallback] = None,
    on_partial: Optional[PartialCallback] = None,
) -> NewsAnalysis:
    """
    Run the pipeline for one news item and return the finished note.

    `on_stage` reports progress; `on_partial` is reserved for the review stage
    added in the next phase, where a verdict is publishable before the audit
    finishes.
    """
    started = time.monotonic()
    stages_run: List[str] = []

    def advance(key: str) -> None:
        stages_run.append(key)
        if on_stage:
            on_stage(key)

    advance("gathering")
    evidence = await gather_evidence(news_item, current_price)

    advance("judging")
    raw = await ai_service.analyze_news(
        title=news_item.title,
        summary=news_item.summary,
        symbol=news_item.symbol,
        asset_type=news_item.asset_type,
        current_price=evidence.current_price,
        rag_context=evidence.precedent_markdown,
        user_id=user_id,
        technical=evidence.technical,
        article=evidence.article,
        regime=evidence.regime_markdown,
    )

    sentiment = raw.get("sentiment", "neutral")
    confidence = float(raw.get("confidence", 0.5))

    analysis = NewsAnalysis(
        sentiment=sentiment,
        confidence=confidence,
        reasoning=raw.get("reasoning", "Analysis completed."),
        historical_context=_legacy_context(raw),
        technical_signals=_technical_signals(evidence.technical),
        prediction_hash=ai_service.generate_prediction_hash(news_item.id, sentiment, confidence),
        tx_hash=None,
        source=raw.get("source"),
        key_factors=raw.get("key_factors") or [],
        price_impact=raw.get("price_impact") or None,
        risk_level=raw.get("risk_level"),
        time_horizon=raw.get("time_horizon"),
        materiality=raw.get("materiality"),
        mechanism=raw.get("mechanism"),
        invalidation=raw.get("invalidation"),
        regime_note=raw.get("regime_note"),
        evidence=[EvidenceItem(**item) for item in (raw.get("evidence") or [])],
        precedents=_precedent_models(evidence.precedents),
        citations=_citations(news_item, evidence),
        coverage=_coverage(evidence),
        analysed_at=datetime.now(),
        duration_seconds=round(time.monotonic() - started, 1),
        model=settings.LLM_MODEL,
        stages_run=stages_run,
    )

    _persist(news_item, analysis, evidence)
    return analysis


def _persist(news_item: NewsItem, analysis: NewsAnalysis, evidence: Evidence) -> None:
    """
    Cache the note, feed the prediction into the vector store, and index the body.

    All three are best-effort: a research note that could not be filed is still a
    research note, and failing the request over it would be absurd.
    """
    payload = analysis.model_dump(mode="json")
    try:
        news_analysis_store.put(
            news_item.id,
            payload,
            news_snapshot={
                "id": news_item.id,
                "title": news_item.title,
                "summary": news_item.summary,
                "source": news_item.source,
                "symbol": news_item.symbol,
                "asset_type": news_item.asset_type,
                "url": news_item.url,
                "published_at": news_item.published_at,
            },
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not cache the analysis for %s: %s", news_item.id, e)

    try:
        from services.rag_service import store_news_with_outcome

        store_news_with_outcome(
            news_id=news_item.id,
            title=news_item.title,
            summary=news_item.summary,
            symbol=news_item.symbol,
            asset_type=news_item.asset_type,
            sentiment=analysis.sentiment,
            confidence=analysis.confidence,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not index the analysis for %s: %s", news_item.id, e)

    # The article body was fetched for this analysis anyway. Indexing it here is
    # the only place it is ever available — the news cache holds headlines and
    # summaries, never the full text — so a body not captured now is a body no
    # future question can retrieve.
    if evidence.article and evidence.article.text:
        try:
            from services.rag_v2_service import index_article_body

            chunks = index_article_body(
                title=news_item.title,
                body=evidence.article.text,
                url=news_item.url or "",
                symbol=news_item.symbol or "",
                asset_type=news_item.asset_type or "crypto",
                published_at=news_item.published_at or "",
            )
            if chunks:
                logger.debug("Indexed %d body chunks for %s", chunks, news_item.id)
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not index the article body for %s: %s", news_item.id, e)


async def start_analysis_job(
    news_item: NewsItem, current_price: Optional[float] = None, user_id: Optional[str] = None
):
    """Start (or re-attach to) the analysis job for this news item."""
    from services import analysis_jobs

    async def runner(controls: "analysis_jobs.JobControls") -> Dict[str, Any]:
        analysis = await analyse_news_item(
            news_item,
            current_price=current_price,
            user_id=user_id,
            on_stage=controls.on_stage,
            on_partial=controls.on_partial,
        )
        return analysis.model_dump(mode="json")

    return await analysis_jobs.start(news_item.id, analysis_jobs.KIND_NEWS, STAGES, runner)
