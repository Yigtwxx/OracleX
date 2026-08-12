"""
The news pipeline's contract: gather what you can, never stall on a missing
source, never invent a level, and say plainly what you could not read.
"""

import asyncio

import pytest

from models.schemas import NewsItem
from services import ai_service, news_analysis_service, news_analysis_store
from services.article_service import Article

ITEM = NewsItem(
    id="news-1",
    title="Regulator approves spot ETF",
    summary="A short feed summary.",
    source="Example Wire",
    published_at="2026-08-03T09:00:00",
    symbol="BINANCE:BTCUSDT",
    asset_type="crypto",
    url="https://example.com/story",
)

MODEL_JSON = {
    "sentiment": "bullish",
    "confidence": 0.78,
    "reasoning": "Approval opens a mandated-buyer channel.",
    "materiality": "significant",
    "mechanism": "A new mandated buyer must acquire spot to back creations.",
    "invalidation": "If the fee schedule prices it above the incumbent.",
    "regime_note": "Breadth at 18% advancing dampens the follow-through.",
    "evidence": [
        {
            "claim": "The product was approved.",
            "quote": "Regulators approved the exchange-traded product on Tuesday.",
            "direction": "bullish",
            "weight": "primary",
        }
    ],
    "key_factors": ["approval", "new flow"],
    "price_impact": "Upward pressure over days.",
    "risk_level": "medium",
    "time_horizon": "short-term",
}

TECHNICAL = {
    "current_price": 64000.0,
    "support_levels": ["62,500"],
    "resistance_levels": ["66,000"],
    "rsi_signal": "Neutral",
    "rsi_value": 51.2,
    "target_price": "67,000",
}

ARTICLE = Article(
    text="Regulators approved the exchange-traded product on Tuesday." * 10,
    char_count=590,
    url=ITEM.url,
    extracted_via="article-tag",
    truncated=False,
)


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch, tmp_path):
    """Keep the pipeline's writes out of the repo's data directory."""
    monkeypatch.setattr(news_analysis_store, "STORE_FILE", str(tmp_path / "analyses.json"))
    news_analysis_store.reset_state()
    yield
    news_analysis_store.reset_state()


@pytest.fixture
def wired(monkeypatch):
    """Fake every evidence source and the model; record what the model was sent."""
    seen = {}

    async def fake_generate(prompt, **kwargs):
        seen["prompt"] = prompt
        seen["system"] = kwargs.get("system")
        seen["extra"] = kwargs.get("extra")
        import json

        return json.dumps(MODEL_JSON)

    async def fake_provider_for(_user_id, _feature):
        return None

    async def fake_article(_url, **_kwargs):
        return seen.get("article", ARTICLE)

    async def fake_technical(_symbol):
        return seen.get("technical", TECHNICAL)

    async def fake_bundle(**_kwargs):
        return seen.get(
            "bundle",
            (
                "PRECEDENT ANALOGY\n- SEC v. Ripple",
                [
                    {
                        "title": "SEC sues Ripple Labs",
                        "date": "2020-12-22",
                        "symbol": "XRP",
                        "similarity": 0.82,
                        "outcome": "bullish",
                        "price_change": -8.4,
                        "apparent_sentiment": "bearish",
                        "durable_direction": "bullish",
                        "horizons": {"1": -8.4, "90": 58.1},
                        "surprised": True,
                        "inverted": True,
                        "source": "event",
                    }
                ],
            ),
        )

    async def fake_regime(_asset_type, **_kwargs):
        return seen.get("regime", "MARKET REGIME\n- Breadth: 18% advancing")

    monkeypatch.setattr(ai_service.llm, "generate", fake_generate)
    monkeypatch.setattr(ai_service.llm, "provider_for", fake_provider_for)
    monkeypatch.setattr(news_analysis_service, "fetch_article", fake_article)

    import services.analysis_data as analysis_data
    import services.rag_v3_service as rag_v3
    import services.technical_analysis_service as tech

    monkeypatch.setattr(tech, "get_technical_analysis", fake_technical)
    monkeypatch.setattr(rag_v3, "build_news_rag_bundle", fake_bundle)
    monkeypatch.setattr(analysis_data, "cached_regime_markdown", fake_regime)

    return seen


# ── the model sees the evidence ──────────────────────────────────────────────


async def test_the_article_body_reaches_the_prompt(wired):
    await news_analysis_service.analyse_news_item(ITEM)

    assert "Regulators approved the exchange-traded product" in wired["prompt"]
    assert "SOURCE ARTICLE" in wired["prompt"]


async def test_the_regime_block_reaches_the_prompt(wired):
    await news_analysis_service.analyse_news_item(ITEM)

    assert "Breadth: 18% advancing" in wired["prompt"]


async def test_the_precedent_block_reaches_the_prompt(wired):
    await news_analysis_service.analyse_news_item(ITEM)

    assert "SEC v. Ripple" in wired["prompt"]
    assert "HISTORICAL PRECEDENT" in wired["prompt"]


async def test_an_explicit_context_window_is_requested(wired):
    await news_analysis_service.analyse_news_item(ITEM)

    assert wired["extra"]["num_ctx"] == ai_service.NEWS_NUM_CTX


async def test_a_missing_article_is_stated_not_inferred(wired):
    wired["article"] = None

    analysis = await news_analysis_service.analyse_news_item(ITEM)

    assert "not retrievable" in wired["prompt"]
    assert analysis.coverage.article_text == "summary-only"
    assert "Source article" in analysis.coverage.unavailable


async def test_a_missing_regime_forbids_characterising_the_backdrop(wired):
    wired["regime"] = ""

    analysis = await news_analysis_service.analyse_news_item(ITEM)

    assert "do not characterise" in wired["prompt"].lower()
    assert "Market regime" in analysis.coverage.unavailable


# ── the response carries the structure ───────────────────────────────────────


async def test_structured_fields_survive_to_the_response(wired):
    analysis = await news_analysis_service.analyse_news_item(ITEM)

    assert analysis.materiality == "significant"
    assert analysis.mechanism.startswith("A new mandated buyer")
    assert analysis.invalidation
    assert analysis.regime_note
    assert len(analysis.evidence) == 1
    assert analysis.evidence[0].weight == "primary"
    assert analysis.evidence[0].quote


async def test_precedents_reach_the_response_not_just_the_model(wired):
    analysis = await news_analysis_service.analyse_news_item(ITEM)

    assert len(analysis.precedents) == 1
    precedent = analysis.precedents[0]
    assert precedent.title == "SEC sues Ripple Labs"
    assert precedent.surprised is True, "the market-did-the-opposite flag is the whole point"
    assert precedent.horizons["90"] == 58.1


async def test_the_legacy_context_string_is_still_populated(wired):
    analysis = await news_analysis_service.analyse_news_item(ITEM)

    assert "Risk Level: MEDIUM" in analysis.historical_context
    assert "Short-term" in analysis.historical_context


async def test_technical_signals_come_from_the_feed_never_the_model(wired):
    analysis = await news_analysis_service.analyse_news_item(ITEM)

    assert analysis.technical_signals is not None
    assert analysis.technical_signals.support_levels == ["62,500"]


async def test_no_computed_levels_means_no_technical_section(wired):
    wired["technical"] = None

    analysis = await news_analysis_service.analyse_news_item(ITEM)

    assert analysis.technical_signals is None, "a blank levels card is worse than none"
    assert "Technical levels" in analysis.coverage.unavailable


async def test_the_source_article_is_cited(wired):
    analysis = await news_analysis_service.analyse_news_item(ITEM)

    assert analysis.citations[0].url == ITEM.url
    assert analysis.citations[0].kind == "article"


async def test_stages_are_reported_in_order(wired):
    seen_stages = []

    await news_analysis_service.analyse_news_item(ITEM, on_stage=seen_stages.append)

    assert seen_stages == ["gathering", "judging"]


# ── degradation ──────────────────────────────────────────────────────────────


async def test_a_failing_source_does_not_fail_the_analysis(monkeypatch, wired):
    async def boom(_url, **_kwargs):
        raise RuntimeError("publisher is down")

    monkeypatch.setattr(news_analysis_service, "fetch_article", boom)

    analysis = await news_analysis_service.analyse_news_item(ITEM)

    assert analysis.sentiment == "bullish"
    assert "Source article" in analysis.coverage.unavailable


async def test_a_hanging_source_is_bounded_by_the_gather_ceiling(monkeypatch, wired):
    async def hang(_url, **_kwargs):
        await asyncio.sleep(30)

    monkeypatch.setattr(news_analysis_service, "fetch_article", hang)
    monkeypatch.setattr(news_analysis_service, "GATHER_TIMEOUT_SECONDS", 0.05)

    analysis = await news_analysis_service.analyse_news_item(ITEM)

    assert analysis.sentiment == "bullish", "a stalled feed must not stall the verdict"
    assert "Source article" in analysis.coverage.unavailable


# ── caching ──────────────────────────────────────────────────────────────────


async def test_a_finished_analysis_is_stored_with_its_news_snapshot(wired):
    await news_analysis_service.analyse_news_item(ITEM)

    entry = news_analysis_store.get(ITEM.id)
    assert entry is not None
    assert entry["news"]["url"] == ITEM.url, (
        "the news cache is wiped every 10 minutes; the outcome job needs its own copy"
    )
    assert entry["outcome"] is None


def test_editing_a_prompt_retires_cached_analyses(monkeypatch):
    first = news_analysis_store.pipeline_version()

    news_analysis_store.reset_state()
    monkeypatch.setattr(news_analysis_store, "PIPELINE_REVISION", "999")

    assert news_analysis_store.pipeline_version() != first
