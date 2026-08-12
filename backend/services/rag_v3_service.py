"""
RAG v3 Service — Insights Agent
Faz 2: Context Everywhere — Bağlamsal finansal zeka sağlar.

Bu ajan 3 temel görev yapar:
1. Fiyat Hareket Nedeni: Neden yükseliyor/düşüyor? (haber + sosyal sinyal korelasyonu)
2. Tarihsel Haber Benzerliği: Bir habere benzer geçmişte neler oldu + fiyat etkisi
3. Tarih Bazlı Olay Arama: Belirli bir tarihteki en önemli olayı bul (grafik tooltip)
"""

import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from services.okx_market import fetch_ticker_24h
from services.rag_scoring import (
    SOURCE_EVENT,
    SOURCE_NEWS,
    ScoredItem,
    class_weight,
    horizons_from_metadata,
    longest_horizon,
    symbol_weight,
    weighted_mean,
    weighted_vote,
)
from services.rag_v2_service import (
    query_scored,
    get_collection,
    generate_embedding,
    NEWS_COLLECTION,
    EVENTS_COLLECTION,
    PRICE_COLLECTION,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PRICE MOVEMENT REASONING — "Neden Yükseliyor/Düşüyor?"
# ═══════════════════════════════════════════════════════════════════════════════


async def get_price_movement_reason(symbol: str) -> Dict:
    """
    Analyze why a symbol is moving up or down.
    Correlates recent price change with recent news in RAG.

    Returns:
        {
            "symbol": "BTC",
            "price_change_24h": -5.2,
            "direction": "down",
            "reasons": [
                {"title": "SEC sues ...", "sentiment": "bearish", "confidence": 0.85, "similarity": 0.78},
                ...
            ],
            "confidence_score": 0.82,
            "summary": "📉 %5 Düşüş: SEC davası ile ilgili... (Güven: %82)"
        }
    """
    result = {
        "symbol": symbol,
        "price_change_24h": 0,
        "direction": "neutral",
        "reasons": [],
        "confidence_score": 0,
        "summary": "",
    }

    try:
        # Step 1: Get current price change from Binance
        price_data = await _get_24h_price_change(symbol)
        if not price_data:
            result["summary"] = f"{symbol} için fiyat verisi alınamadı."
            return result

        result["price_change_24h"] = price_data["change_pct"]
        result["direction"] = (
            "up"
            if price_data["change_pct"] > 0
            else "down"
            if price_data["change_pct"] < 0
            else "neutral"
        )

        # Step 2: Search RAG for recent news related to this symbol
        query = f"{symbol} price {'increase rally' if result['direction'] == 'up' else 'decrease drop crash'} recent news"
        query_embedding = generate_embedding(query)

        if get_collection(NEWS_COLLECTION).count() == 0:
            result["summary"] = (
                f"{symbol} {result['price_change_24h']:+.1f}% — RAG'da ilgili haber bulunamadı."
            )
            return result

        # Step 3: Rank by relevance to this symbol, not by proximity alone. The
        # old 0.35 threshold sat inside the noise band of the broken similarity
        # scale, so unrelated headlines were routinely offered as the reason a
        # price moved.
        scored = query_scored(
            NEWS_COLLECTION,
            query_embedding,
            source=SOURCE_NEWS,
            query_symbol=symbol,
            k=5,
        )
        reasons = [
            {
                "title": s.item.metadata.get("title", "")[:150],
                "sentiment": s.item.metadata.get("sentiment", "unknown"),
                "confidence": s.item.metadata.get("confidence", 0),
                "similarity": round(s.relevance, 3),
                "score": round(s.score, 4),
                "date": s.item.metadata.get("stored_at", "")[:10],
            }
            for s in scored
        ]

        result["reasons"] = reasons[:5]

        # Step 4: Confidence follows the strength of the match, weighted by how
        # much each item counted towards the answer.
        confidence = weighted_mean(
            [r["similarity"] for r in reasons], [r["score"] for r in reasons]
        )
        if confidence is not None:
            result["confidence_score"] = round(confidence, 2)

        # Step 5: Generate human-readable summary
        direction_emoji = (
            "📈" if result["direction"] == "up" else "📉" if result["direction"] == "down" else "➡️"
        )
        change_text = f"{result['price_change_24h']:+.1f}%"

        if reasons:
            top_reason = reasons[0]["title"][:80]
            conf_pct = int(result["confidence_score"] * 100)
            result["summary"] = (
                f"{direction_emoji} {change_text}: {top_reason}... (Güven Skoru: %{conf_pct})"
            )
        else:
            result["summary"] = f"{direction_emoji} {change_text}: İlişkili haber bulunamadı."

    except Exception as e:
        result["summary"] = f"Analiz hatası: {str(e)}"
        print(f"[RAG v3] Price movement reason error: {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 2. HISTORICAL NEWS SIMILARITY — "Benzer Geçmiş Olaylar"
# ═══════════════════════════════════════════════════════════════════════════════


def _analogy_from_event(scored: ScoredItem) -> Dict:
    """One catalogue event rendered as a precedent for a new headline."""
    meta = scored.item.metadata
    return {
        "title": meta.get("event_name", "")[:150],
        "date": meta.get("date", ""),
        "symbol": meta.get("symbol", ""),
        "outcome": meta.get("durable_direction") or meta.get("event_type", "unknown"),
        # No longer hardcoded to None. The measured aftermath lives in metadata
        # now, so an event contributes to the impact average like a news item.
        "price_change": longest_horizon(meta),
        "apparent_sentiment": meta.get("apparent_sentiment"),
        "durable_direction": meta.get("durable_direction"),
        "inverted": bool(meta.get("inverted", False)),
        "surprised": bool(meta.get("surprised", False)),
        "horizons": horizons_from_metadata(meta),
        "max_drawdown_pct": meta.get("max_drawdown_pct"),
        "max_runup_pct": meta.get("max_runup_pct"),
        "similarity": round(scored.relevance, 3),
        "score": round(scored.score, 4),
        "source": "event",
    }


async def find_historical_news_similarity(
    news_title: str,
    news_summary: str = "",
    symbol: Optional[str] = None,
    asset_type: Optional[str] = None,
) -> Dict:
    """
    Given a news item, find similar historical news and their price outcomes.

    Returns:
        {
            "query_news": "Bitcoin ETF rejected by SEC",
            "similar_events": [
                {
                    "title": "SEC rejects Winklevoss ETF 2017",
                    "date": "2017-03-10",
                    "outcome": "bearish",
                    "price_change": -8.5,
                    "similarity": 0.87
                },
                ...
            ],
            "avg_price_impact": -5.2,
            "dominant_outcome": "bearish",
            "summary": "Bu habere benzer 5 olay yaşandı. Fiyat ortalama %5.2 düştü."
        }
    """
    result = {
        "query_news": news_title[:200],
        "similar_events": [],
        "avg_price_impact": 0,
        "dominant_outcome": "neutral",
        "summary": "",
    }

    try:
        query_text = f"{news_title}. {news_summary}"
        query_embedding = generate_embedding(query_text)

        # Scored separately per collection, then merged. Event documents are
        # short synthetic sentences and news documents are headlines; their raw
        # cosines come from different distributions, so sorting one pooled list
        # by similarity was comparing two different scales.
        similar_events: List[Dict] = []

        for scored in query_scored(
            NEWS_COLLECTION, query_embedding, source=SOURCE_NEWS, query_symbol=symbol, k=5
        ):
            meta = scored.item.metadata
            similar_events.append(
                {
                    "title": meta.get("title", "")[:150],
                    "date": meta.get("stored_at", "")[:10],
                    "outcome": meta.get("actual_outcome", meta.get("sentiment", "unknown")),
                    # `store_news_with_outcome` writes `price_change_percent`;
                    # older records used `price_change`. Reading only the latter
                    # rendered every measured outcome as None. Same fallback as
                    # `rag_scoring._descriptor`.
                    "price_change": meta.get("price_change", meta.get("price_change_percent")),
                    "similarity": round(scored.relevance, 3),
                    "score": round(scored.score, 4),
                    "source": "news",
                }
            )

        for scored in query_scored(
            EVENTS_COLLECTION,
            query_embedding,
            source=SOURCE_EVENT,
            query_symbol=symbol,
            k=4,
            where={"asset_type": asset_type} if asset_type else None,
        ):
            similar_events.append(_analogy_from_event(scored))

        similar_events.sort(key=lambda x: x["score"], reverse=True)
        # Everything below is computed over the same list that is returned, so
        # the reported average describes the precedents the caller can actually
        # see rather than a wider set that was retrieved and then trimmed.
        reported = similar_events[:7]
        result["similar_events"] = reported

        # Weighted by score, so a close, large, recent precedent counts for more
        # than a distant one. This was a plain mean over whatever came back.
        weights = [e["score"] for e in reported]
        average = weighted_mean([e.get("price_change") for e in reported], weights)
        if average is not None:
            result["avg_price_impact"] = round(average, 2)

        # The durable direction, not the headline's tone — and weighted, so three
        # weak matches no longer outvote one strong one the way `Counter` let them.
        directions = [e.get("durable_direction") or e.get("outcome") for e in reported]
        vote = weighted_vote(directions, weights)
        if vote:
            result["dominant_outcome"] = vote[0]

        count = len(reported)
        surprising = [e for e in reported if e.get("surprised")]
        if count == 0:
            result["summary"] = "Benzer geçmiş olay bulunamadı."
        elif average is not None:
            direction = "arttı" if average > 0 else "düştü"
            result["summary"] = (
                f"Bu habere benzer geçmişte {count} olay yaşandı. "
                f"Fiyat ortalama %{abs(average):.1f} {direction}."
            )
            if surprising:
                result["summary"] += (
                    f" Bunların {len(surprising)} tanesinde piyasa manşetin ima ettiğinin "
                    "tersine hareket etti."
                )
        else:
            result["summary"] = f"Bu habere benzer geçmişte {count} olay bulundu."

    except Exception as e:
        result["summary"] = f"Benzerlik analizi hatası: {str(e)}"
        print(f"[RAG v3] News similarity error: {e}")

    return result


def render_precedent_analogies(analogies: List[Dict], limit: int = 3) -> str:
    """
    The precedent block a news analysis prompt carries.

    This is the deliverable the retrieval exists for: not "here are some old
    headlines", but "this item resembles that one, here is what the market
    actually did, and here is whether that matched what the headline implied".
    A model given only the first form reads "SEC sues Ripple" and reasons
    lawsuit-therefore-down; the same model given the second reads that the
    headline was bearish, the drawdown was 66%, and the price a year later was
    higher, and has to account for both.

    Framed as history throughout. These are past events, and the prompt says so
    — nothing here is a projection.
    """
    lines: List[str] = []
    for item in analogies[:limit]:
        if not item.get("title"):
            continue

        match = int(round(item.get("similarity", 0) * 100))
        where = f", {item['symbol']}" if item.get("symbol") else ""
        date = item.get("date") or "undated"
        lines.append(f'- "{item["title"]}" ({date}{where}) — match {match}%.')

        apparent = item.get("apparent_sentiment")
        if apparent:
            lines.append(f"  Headline implied {apparent.upper()}.")

        horizons = item.get("horizons") or {}
        if horizons:
            moves = ", ".join(f"{d}d {horizons[d]:+.1f}%" for d in sorted(horizons))
            drawdown, runup = item.get("max_drawdown_pct"), item.get("max_runup_pct")
            actual = f"  Actual: {moves}"
            if drawdown is not None and runup is not None:
                actual += f"; worst drawdown {drawdown:+.1f}%, best run-up {runup:+.1f}%"
            lines.append(actual + ".")
        elif item.get("price_change") is not None:
            lines.append(f"  Actual: {item['price_change']:+.1f}%.")

        if item.get("surprised"):
            lines.append(
                f"  The durable outcome was {item.get('durable_direction')} — the market "
                "did the opposite of what the headline implied."
            )
        elif item.get("inverted"):
            lines.append("  The immediate reaction and the durable outcome diverged.")

    if not lines:
        return ""

    return "\n".join(
        [
            "PRECEDENT ANALOGY (past events that resemble this headline)",
            "Each entry: how close the match is, what the headline implied at the time, "
            "and what the price actually did afterwards. These are historical outcomes, "
            "not projections.",
            *lines,
        ]
    )


async def build_news_rag_bundle(
    title: str,
    summary: str = "",
    symbol: Optional[str] = None,
    asset_type: Optional[str] = None,
) -> Tuple[str, List[Dict]]:
    """
    The historical block for a news analysis prompt, plus the precedents behind it.

    Combines similar past headlines with the precedent analogies drawn from the
    curated event catalogue. The catalogue is what makes this useful on day one:
    the news collection fills up over time, but the events are measured and
    indexed from the start.

    Returns `(rendered_markdown, precedents)`. The markdown goes to the model;
    the precedents go to the API, so the UI can show "this resembles X, and back
    then the price did the opposite of what the headline implied" instead of
    that reasoning being visible only to the model.

    The markdown is empty when nothing clears the relevance floor — the prompt
    template renders that as no precedent, which is the honest answer and better
    than handing the model whichever past item happened to be nearest.
    """
    from services.rag_service import get_rag_context

    # Chroma queries and the embedding model are both blocking; a slow first
    # load must not stall the event loop for every other request.
    analysis, similar = await asyncio.gather(
        asyncio.to_thread(
            get_rag_context, title=title, summary=summary, asset_type=asset_type or "crypto"
        ),
        find_historical_news_similarity(title, summary, symbol=symbol, asset_type=asset_type),
        return_exceptions=True,
    )

    blocks: List[str] = []
    precedents: List[Dict] = []

    if isinstance(analysis, str) and analysis:
        blocks.append(analysis)
    elif isinstance(analysis, Exception):
        print(f"[RAG v3] Similar-news context failed: {analysis}")

    if isinstance(similar, dict):
        precedents = similar.get("similar_events") or []
        rendered = render_precedent_analogies(precedents)
        if rendered:
            blocks.append(rendered)
    elif isinstance(similar, Exception):
        print(f"[RAG v3] Precedent analogy failed: {similar}")

    return "\n\n".join(blocks), precedents


async def build_news_rag_context(
    title: str,
    summary: str = "",
    symbol: Optional[str] = None,
    asset_type: Optional[str] = None,
) -> str:
    """The rendered precedent block alone. See `build_news_rag_bundle`."""
    context, _ = await build_news_rag_bundle(title, summary, symbol=symbol, asset_type=asset_type)
    return context


# ═══════════════════════════════════════════════════════════════════════════════
# 3. EVENT AT DATE — Grafik Tooltip İçin
# ═══════════════════════════════════════════════════════════════════════════════


async def get_event_at_date(symbol: str, date_str: str) -> Dict:
    """
    Find the most significant event near a specific date.
    Used for chart tooltip overlays.

    Args:
        symbol: Trading symbol (BTC, ETH, etc.)
        date_str: Date string (YYYY-MM-DD)

    Returns:
        {
            "date": "2024-03-12",
            "event": "ABD Enflasyon Verisi Açıklandı (%3.2)",
            "type": "macro",
            "price_impact": -2.1,
            "found": true
        }
    """
    result = {"date": date_str, "event": None, "type": None, "price_impact": None, "found": False}

    try:
        # This asks "what happened on this date", which is a lookup, not a
        # similarity question. It used to embed the sentence "BTC price event on
        # 2024-04-20" and search for neighbours, then discard almost all of them
        # with a date filter — so the ranking among whatever survived was decided
        # by how the date happened to embed. Read the metadata directly instead:
        # the catalogue is small, and the answer is exact rather than nearly.
        best_match = None
        best_importance = -1.0

        events_col = get_collection(EVENTS_COLLECTION)
        if events_col.count() > 0:
            stored = events_col.get(include=["metadatas"])
            for meta in stored.get("metadatas") or []:
                event_date = meta.get("date", "")
                if not event_date or not _is_date_nearby(date_str, event_date, days=3):
                    continue
                # Several events can sit within the window; the tooltip has room
                # for one, so it shows the one that mattered most rather than
                # whichever the vector search happened to surface first.
                importance = class_weight(meta.get("event_type")) * symbol_weight(
                    meta.get("symbol"), symbol
                )
                if importance > best_importance:
                    best_importance = importance
                    best_match = {
                        "event": meta.get("event_name", ""),
                        "type": meta.get("event_type", ""),
                        "date": event_date,
                    }

        # News has no curated date field to filter on, so it stays a similarity
        # search — but only when the catalogue had nothing for the date.
        if not best_match and get_collection(NEWS_COLLECTION).count() > 0:
            query_embedding = generate_embedding(f"{symbol} price event on {date_str}")
            for scored in query_scored(
                NEWS_COLLECTION,
                query_embedding,
                source=SOURCE_NEWS,
                query_symbol=symbol,
                k=5,
            ):
                stored_at = scored.item.metadata.get("stored_at", "")[:10]
                if stored_at and _is_date_nearby(date_str, stored_at, days=2):
                    best_match = {
                        "event": scored.item.metadata.get("title", "")[:100],
                        "type": scored.item.metadata.get("sentiment", "neutral"),
                        "date": stored_at,
                    }
                    break

        if best_match:
            result["found"] = True
            result["event"] = best_match["event"]
            result["type"] = best_match["type"]
            result["date"] = best_match.get("date", date_str)

            # An exact metadata lookup, for the same reason: the daily price row
            # for a given symbol and date is a key, not a neighbour.
            price_col = get_collection(PRICE_COLLECTION)
            if price_col.count() > 0:
                rows = price_col.get(
                    where={"$and": [{"symbol": symbol}, {"date": result["date"]}]},
                    include=["metadatas"],
                    limit=1,
                )
                metadatas = rows.get("metadatas") or []
                if metadatas:
                    result["price_impact"] = metadatas[0].get("change_pct", 0)

    except Exception as e:
        print(f"[RAG v3] Event at date error: {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


def _is_date_nearby(date1_str: str, date2_str: str, days: int = 3) -> bool:
    """Check if two dates are within N days of each other."""
    try:
        d1 = datetime.strptime(date1_str[:10], "%Y-%m-%d")
        d2 = datetime.strptime(date2_str[:10], "%Y-%m-%d")
        return abs((d1 - d2).days) <= days
    except (ValueError, TypeError):
        return False


async def _get_24h_price_change(symbol: str) -> Optional[Dict]:
    """
    Get the 24h price summary from OKX, or None when it does not list the pair.

    Binance was the original source but is unreachable from some of the networks
    this runs on, so this path returned None for every symbol.
    """
    return await fetch_ticker_24h(symbol)


print("[RAG v3] Insights Agent loaded.")
