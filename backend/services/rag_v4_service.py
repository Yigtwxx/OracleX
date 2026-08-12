"""
RAG v4 Service — Reasoning Agent
Faz 3: Gelişmiş Akıl Yürütme — Karşılaştırmalı analiz ve senaryo simülasyonu.

Bu ajan 2 temel görev yapar:
1. Karşılaştırmalı Analiz: İki varlığı teknik ve tarihsel olarak kıyaslar
2. Senaryo Simülasyonu: "Eğer X olursa ne olur?" sorusunu geçmiş verilerle simüle eder
"""

from typing import Dict, Optional, Sequence

from services.okx_market import fetch_ticker_24h
from services.rag_scoring import (
    SOURCE_EVENT,
    SOURCE_NEWS,
    SOURCE_PRICE,
    horizons_from_metadata,
    weighted_mean,
    weighted_percentile_range,
    weighted_vote,
)
from services.rag_v2_service import (
    query_scored,
    generate_embedding,
    NEWS_COLLECTION,
    EVENTS_COLLECTION,
    PRICE_COLLECTION,
)

# Horizons that speak for the first reaction, in the order they are preferred.
IMMEDIATE_HORIZON_DAYS = (1, 7)


def _horizon_value(horizons: Dict[int, float], preferred: Sequence[int]) -> Optional[float]:
    """The first of the preferred horizons that was actually measured."""
    for days in preferred:
        if days in horizons:
            return horizons[days]
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 1. COMPARATIVE ANALYSIS — "SOL vs AVAX"
# ═══════════════════════════════════════════════════════════════════════════════


async def compare_assets(symbol_a: str, symbol_b: str) -> Dict:
    """
    Compare two crypto assets using historical RAG data and live prices.

    Returns comprehensive comparison including:
    - Current prices and 24h changes
    - Historical price patterns from RAG
    - Related events for each
    - News sentiment for each
    - Overall comparison verdict
    """
    result = {
        "symbol_a": symbol_a,
        "symbol_b": symbol_b,
        "comparison": {
            "price_data": {},
            "historical_events": {},
            "news_sentiment": {},
            "price_patterns": {},
        },
        "verdict": "",
        "summary": "",
    }

    try:
        # Step 1: Get live price data for both
        price_a = await _get_live_data(symbol_a)
        price_b = await _get_live_data(symbol_b)

        result["comparison"]["price_data"] = {
            symbol_a: price_a or {"price": 0, "change_24h": 0, "volume": 0},
            symbol_b: price_b or {"price": 0, "change_24h": 0, "volume": 0},
        }

        # Step 2: Get historical events related to each symbol.
        # The old `where` clause filtered on an exact symbol match, but only for
        # a hardcoded ["BTC", "ETH", "SOL"] — every other asset got no filter at
        # all and could be compared against another coin's history. Symbol
        # relevance is a weight now, so a bellwether's precedent still counts for
        # a smaller asset without an unrelated one counting equally.
        for symbol in [symbol_a, symbol_b]:
            embedding = generate_embedding(f"{symbol} major events milestones")
            result["comparison"]["historical_events"][symbol] = [
                {
                    "event": s.item.metadata.get("event_name", ""),
                    "date": s.item.metadata.get("date", ""),
                    "type": s.item.metadata.get("event_type", ""),
                    "durable_direction": s.item.metadata.get("durable_direction"),
                    "surprised": bool(s.item.metadata.get("surprised", False)),
                }
                for s in query_scored(
                    EVENTS_COLLECTION,
                    embedding,
                    source=SOURCE_EVENT,
                    query_symbol=symbol,
                    k=3,
                )
            ]

        # Step 3: Get news sentiment for each symbol, weighted by how much each
        # item counts. Counting headlines one apiece let a stack of barely
        # related items outvote the one that was actually about this asset.
        for symbol in [symbol_a, symbol_b]:
            embedding = generate_embedding(f"{symbol} recent news sentiment analysis")
            scored = query_scored(
                NEWS_COLLECTION,
                embedding,
                source=SOURCE_NEWS,
                query_symbol=symbol,
                k=10,
            )

            sentiments = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
            for s in scored:
                sent = (s.item.metadata.get("sentiment") or "neutral").lower()
                if sent in sentiments:
                    sentiments[sent] += s.score

            total = sum(sentiments.values()) or 1.0
            vote = weighted_vote(
                [(s.item.metadata.get("sentiment") or "neutral").lower() for s in scored],
                [s.score for s in scored],
            )
            result["comparison"]["news_sentiment"][symbol] = {
                "bullish_pct": round(sentiments["bullish"] / total * 100),
                "bearish_pct": round(sentiments["bearish"] / total * 100),
                "neutral_pct": round(sentiments["neutral"] / total * 100),
                "news_count": len(scored),
                "dominant": vote[0] if vote else "neutral",
            }

        # Step 4: Get price pattern analysis from RAG
        for symbol in [symbol_a, symbol_b]:
            embedding = generate_embedding(f"{symbol} price trend pattern weekly monthly")
            result["comparison"]["price_patterns"][symbol] = [
                {
                    "date": s.item.metadata.get("date", ""),
                    "change_pct": s.item.metadata.get("change_pct", 0),
                    "close": s.item.metadata.get("close", 0),
                }
                for s in query_scored(
                    PRICE_COLLECTION,
                    embedding,
                    source=SOURCE_PRICE,
                    query_symbol=symbol,
                    k=5,
                    where={"symbol": symbol},
                )
            ]

        # Step 5: Generate verdict
        result["verdict"] = _generate_comparison_verdict(result, symbol_a, symbol_b)
        result["summary"] = _generate_comparison_summary(result, symbol_a, symbol_b)

    except Exception as e:
        result["summary"] = f"Karşılaştırma hatası: {str(e)}"
        print(f"[RAG v4] Compare assets error: {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SCENARIO SIMULATION — "Eğer Bitcoin ETF reddedilirse ne olur?"
# ═══════════════════════════════════════════════════════════════════════════════


async def simulate_scenario(scenario_query: str, symbol: str = "BTC") -> Dict:
    """
    Simulate a scenario by finding similar historical events and their price impacts.

    Args:
        scenario_query: "What if Bitcoin ETF is rejected?" or "Fed faiz artırırsa?"
        symbol: Primary symbol to analyze

    Returns:
        {
            "scenario": "Bitcoin ETF reddedilirse",
            "symbol": "BTC",
            "similar_past_events": [...],
            "price_impact_range": {"min": -15, "max": -5, "avg": -8.5},
            "recovery_time_days": 14,
            "confidence": 0.72,
            "simulation_summary": "..."
        }
    """
    result = {
        "scenario": scenario_query,
        "symbol": symbol,
        "similar_past_events": [],
        "price_impact_range": {"min": 0, "max": 0, "avg": 0},
        # Declared up front so the response shape does not depend on how far the
        # simulation got — a caller reading `.get("contradicted_precedents")`
        # should not have to distinguish "none found" from "we bailed early".
        "immediate_impact_avg": None,
        "contradicted_precedents": [],
        "recovery_time_days": None,
        "confidence": 0,
        "simulation_summary": "",
    }

    try:
        # Step 1: Search for similar historical events
        query_embedding = generate_embedding(scenario_query)

        similar_events = []

        for scored in query_scored(
            EVENTS_COLLECTION,
            query_embedding,
            source=SOURCE_EVENT,
            query_symbol=symbol,
            k=5,
        ):
            meta = scored.item.metadata
            horizons = horizons_from_metadata(meta)
            similar_events.append(
                {
                    "event": meta.get("event_name", ""),
                    "date": meta.get("date", ""),
                    "type": meta.get("event_type", ""),
                    "symbol": meta.get("symbol", ""),
                    "apparent_sentiment": meta.get("apparent_sentiment"),
                    "durable_direction": meta.get("durable_direction"),
                    "surprised": bool(meta.get("surprised", False)),
                    "inverted": bool(meta.get("inverted", False)),
                    "horizons": horizons,
                    "immediate_pct": _horizon_value(horizons, IMMEDIATE_HORIZON_DAYS),
                    "durable_pct": horizons[max(horizons)] if horizons else None,
                    "price_change": horizons[max(horizons)] if horizons else None,
                    "similarity": round(scored.relevance, 3),
                    "score": round(scored.score, 4),
                    "source": "events",
                }
            )

        for scored in query_scored(
            NEWS_COLLECTION,
            query_embedding,
            source=SOURCE_NEWS,
            query_symbol=symbol,
            k=5,
        ):
            meta = scored.item.metadata
            change = meta.get("price_change")
            similar_events.append(
                {
                    "event": meta.get("title", "")[:100],
                    "date": meta.get("stored_at", "")[:10],
                    "type": meta.get("sentiment", "neutral"),
                    "price_change": change,
                    "immediate_pct": change,
                    "durable_pct": change,
                    "similarity": round(scored.relevance, 3),
                    "score": round(scored.score, 4),
                    "source": "news",
                }
            )

        similar_events.sort(key=lambda x: x["score"], reverse=True)
        result["similar_past_events"] = similar_events[:7]

        # Step 2: The impacts come from the events' own measured outcomes. This
        # used to re-derive them by embedding the sentence "BTC price on
        # 2024-04-20" and searching the price collection for neighbours — a
        # vector search for something that is a key lookup, and one the events
        # themselves can now answer directly.
        weights = [e["score"] for e in similar_events[:5]]
        immediate = [e.get("immediate_pct") for e in similar_events[:5]]
        durable = [e.get("durable_pct") for e in similar_events[:5]]

        durable_avg = weighted_mean(durable, weights)
        band = weighted_percentile_range(durable, weights)
        if durable_avg is not None and band is not None:
            # A weighted percentile band, not raw min/max. Over five samples the
            # extremes are whichever two outliers were retrieved, and quoting
            # them as the range of plausible outcomes overstates the history.
            result["price_impact_range"] = {
                "min": round(band[0], 2),
                "max": round(band[1], 2),
                "avg": round(durable_avg, 2),
            }

            immediate_avg = weighted_mean(immediate, weights)
            if immediate_avg is not None:
                # Reported separately because the two regularly disagree: the
                # first reaction and where it settled are different facts, and
                # collapsing them into one average hides exactly the cases worth
                # retrieving.
                result["immediate_impact_avg"] = round(immediate_avg, 2)

            magnitude = abs(durable_avg)
            if magnitude > 10:
                result["recovery_time_days"] = 30
            elif magnitude > 5:
                result["recovery_time_days"] = 14
            elif magnitude > 2:
                result["recovery_time_days"] = 7
            else:
                result["recovery_time_days"] = 3

        # Step 3: Confidence follows how strong the matches were and how many of
        # them carried a measured outcome.
        if similar_events:
            top = similar_events[:5]
            relevance = (
                weighted_mean([e["similarity"] for e in top], [e["score"] for e in top]) or 0.0
            )
            measured = sum(1 for e in top if e.get("durable_pct") is not None)
            data_richness = min(1.0, measured / 3)
            result["confidence"] = round(relevance * 0.6 + data_richness * 0.4, 2)

        result["contradicted_precedents"] = [e for e in similar_events[:5] if e.get("surprised")]

        # Step 5: Generate simulation summary
        result["simulation_summary"] = _generate_scenario_summary(result)

    except Exception as e:
        result["simulation_summary"] = f"Simülasyon hatası: {str(e)}"
        print(f"[RAG v4] Scenario simulation error: {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


async def _get_live_data(symbol: str) -> Optional[Dict]:
    """
    Live 24h price data from OKX, or None when it does not list the pair.

    Binance was the original source but is unreachable from some of the networks
    this runs on, so this path returned None for every symbol.
    """
    ticker = await fetch_ticker_24h(symbol)
    if not ticker:
        return None

    return {
        "price": ticker["price"],
        "change_24h": ticker["change_pct"],
        "volume": ticker["volume_usd"],
        "high_24h": ticker["high_24h"],
        "low_24h": ticker["low_24h"],
    }


def _generate_comparison_verdict(result: Dict, sym_a: str, sym_b: str) -> str:
    """Generate a comparative verdict between two assets."""
    price_data = result["comparison"]["price_data"]
    sentiment = result["comparison"]["news_sentiment"]

    a_change = price_data.get(sym_a, {}).get("change_24h", 0)
    b_change = price_data.get(sym_b, {}).get("change_24h", 0)

    a_sentiment = sentiment.get(sym_a, {}).get("dominant", "neutral")
    b_sentiment = sentiment.get(sym_b, {}).get("dominant", "neutral")

    # Simple scoring
    a_score = 0
    b_score = 0

    if a_change > b_change:
        a_score += 1
    else:
        b_score += 1

    sentiment_order = {"bullish": 2, "neutral": 1, "bearish": 0}
    a_score += sentiment_order.get(a_sentiment, 1)
    b_score += sentiment_order.get(b_sentiment, 1)

    if a_score > b_score:
        return f"{sym_a} şu an daha güçlü görünüyor (Momentum: {a_change:+.1f}%, Sentiment: {a_sentiment})"
    elif b_score > a_score:
        return f"{sym_b} şu an daha güçlü görünüyor (Momentum: {b_change:+.1f}%, Sentiment: {b_sentiment})"
    else:
        return f"{sym_a} ve {sym_b} birbirine yakın performans gösteriyor."


def _generate_comparison_summary(result: Dict, sym_a: str, sym_b: str) -> str:
    """Generate human-readable comparison summary."""
    price_data = result["comparison"]["price_data"]

    a_price = price_data.get(sym_a, {}).get("price", 0)
    b_price = price_data.get(sym_b, {}).get("price", 0)
    a_change = price_data.get(sym_a, {}).get("change_24h", 0)
    b_change = price_data.get(sym_b, {}).get("change_24h", 0)

    lines = [
        f"📊 {sym_a} vs {sym_b} Karşılaştırması",
        "",
        f"💰 Fiyat: {sym_a}=${a_price:,.2f} ({a_change:+.1f}%) | {sym_b}=${b_price:,.2f} ({b_change:+.1f}%)",
        "",
        result["verdict"],
    ]

    return "\n".join(lines)


def _generate_scenario_summary(result: Dict) -> str:
    """Generate simulation summary text."""
    result["symbol"]
    impact = result["price_impact_range"]
    events_count = len(result["similar_past_events"])
    confidence = int(result["confidence"] * 100)

    if events_count == 0:
        return f"'{result['scenario']}' senaryosu için geçmişte benzer olay bulunamadı."

    avg_impact = impact["avg"]
    direction = "yükseliş" if avg_impact > 0 else "düşüş"

    lines = [
        f"🔮 Senaryo Simülasyonu: {result['scenario']}",
        "",
        f"📊 Geçmişte benzer {events_count} olay bulundu:",
        f"   • Kalıcı etki aralığı: {impact['min']:+.1f}% ile {impact['max']:+.1f}% arası",
        f"   • Kalıcı ortalama: {avg_impact:+.1f}% ({direction})",
    ]

    immediate = result.get("immediate_impact_avg")
    if immediate is not None:
        lines.append(f"   • İlk tepki ortalaması: {immediate:+.1f}%")

    if result["recovery_time_days"]:
        lines.append(f"   • Tahmini toparlanma: ~{result['recovery_time_days']} gün")

    lines.append(f"   • Güven skoru: %{confidence}")

    # The point of retrieving history at all: where the market has previously
    # done the opposite of what the headline implied, say so rather than letting
    # the average quietly absorb it.
    contradicted = result.get("contradicted_precedents") or []
    if contradicted:
        lines.append("")
        lines.append(
            f"⚠️ Bu olaylardan {len(contradicted)} tanesinde piyasa manşetin ima ettiğinin "
            "tersine hareket etti:"
        )
        for event in contradicted[:3]:
            lines.append(
                f"   • {event['date']} {event['event'][:60]} — manşet "
                f"{event.get('apparent_sentiment')}, kalıcı sonuç "
                f"{event.get('durable_direction')}"
            )

    return "\n".join(lines)


print("[RAG v4] Reasoning Agent loaded.")
