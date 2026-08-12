"""
RAG v5 Service — Proactive Agent
Faz 4: Proaktif Asistan — Kullanıcı sormadan bilgi sunar.

Bu ajan 2 temel görev yapar:
1. Sabah Briffingi: Gece olan olayları, önemli haberleri ve bugünkü takvimi derler
2. Anomali Tespiti: Fiyat hareketi ile haber akışı arasındaki uyumsuzlukları tespit eder
"""

from typing import Dict, List, Optional
from datetime import datetime

from services.okx_market import fetch_tickers_24h
from services.rag_bellwethers import default_crypto_symbols
from services.rag_scoring import SOURCE_EVENT, SOURCE_NEWS, weighted_vote
from services.rag_v2_service import (
    query_scored,
    get_collection,
    generate_embedding,
    NEWS_COLLECTION,
    EVENTS_COLLECTION,
)

# A 24h move this large is what counts as an "overnight mover" and as the
# threshold for an anomaly worth checking against the news flow.
MOVER_THRESHOLD_PCT = 3.0


# ═══════════════════════════════════════════════════════════════════════════════
# 1. DAILY BRIEF — Sabah Briffingi
# ═══════════════════════════════════════════════════════════════════════════════


async def generate_daily_brief(symbols: List[str] = None) -> Dict:
    """
    Generate a comprehensive daily briefing.

    Covers:
    - Overnight price movements for watchlist symbols
    - Most important recent news from RAG
    - Any upcoming/recent events from events DB
    - Market sentiment summary

    Returns:
        {
            "date": "2025-02-21",
            "greeting": "Günaydın! İşte bugünkü piyasa özeti...",
            "market_snapshot": {...},
            "overnight_movers": [...],
            "top_news": [...],
            "upcoming_events": [...],
            "sentiment_summary": {...},
            "brief_text": "Full formatted brief"
        }
    """
    if symbols is None:
        # One curated list, in `rag_bellwethers`, instead of a per-function guess.
        symbols = default_crypto_symbols()[:5]

    today = datetime.now()
    result = {
        "date": today.strftime("%Y-%m-%d"),
        "greeting": "",
        "market_snapshot": {},
        "overnight_movers": [],
        "top_news": [],
        "upcoming_events": [],
        "sentiment_summary": {},
        "brief_text": "",
    }

    try:
        # Step 1: Market Snapshot — current prices for key assets. One OKX call
        # covers the whole spot book, so this costs the same at any list length.
        tickers = await fetch_tickers_24h(symbols[:8])

        for symbol, ticker in tickers.items():
            change = ticker["change_pct"]
            result["market_snapshot"][symbol] = {
                "price": ticker["price"],
                "change_24h": change,
                "volume": ticker["volume_usd"],
            }

            # Track big movers (>3% change)
            if abs(change) > MOVER_THRESHOLD_PCT:
                result["overnight_movers"].append(
                    {
                        "symbol": symbol,
                        "change_pct": change,
                        "direction": "📈" if change > 0 else "📉",
                        "price": ticker["price"],
                    }
                )

        # Sort movers by absolute change
        result["overnight_movers"].sort(key=lambda x: abs(x["change_pct"]), reverse=True)

        # Step 2: Top Recent News from RAG, ranked by relevance and recency
        # rather than by raw proximity — a brief that leads with a stale headline
        # because it embedded well is not a brief.
        query_embedding = generate_embedding("important crypto market news today breaking")
        for scored in query_scored(
            NEWS_COLLECTION, query_embedding, source=SOURCE_NEWS, query_symbol=None, k=5
        ):
            meta = scored.item.metadata
            result["top_news"].append(
                {
                    "title": meta.get("title", "")[:120],
                    "sentiment": meta.get("sentiment", "neutral"),
                    "date": meta.get("stored_at", "")[:10],
                    "relevance": round(scored.relevance, 3),
                    "score": round(scored.score, 4),
                }
            )

        # Step 3: Upcoming/Recent Events
        event_embedding = generate_embedding(f"upcoming event {today.strftime('%Y-%m')}")
        for scored in query_scored(
            EVENTS_COLLECTION, event_embedding, source=SOURCE_EVENT, query_symbol=None, k=3
        ):
            meta = scored.item.metadata
            result["upcoming_events"].append(
                {
                    "event": meta.get("event_name", ""),
                    "date": meta.get("date", ""),
                    "type": meta.get("event_type", ""),
                }
            )

        # Step 4: Sentiment Summary, weighted so a weak match does not swing the
        # mood as hard as a strong one.
        weights = [n["score"] for n in result["top_news"]]
        labels = [n.get("sentiment") for n in result["top_news"]]
        bullish_count = sum(w for label, w in zip(labels, weights) if label == "bullish")
        bearish_count = sum(w for label, w in zip(labels, weights) if label == "bearish")
        total_news = sum(weights) or 1

        if bullish_count > bearish_count:
            mood = "İyimser"
            emoji = "🟢"
        elif bearish_count > bullish_count:
            mood = "Temkinli"
            emoji = "🔴"
        else:
            mood = "Nötr"
            emoji = "🟡"

        result["sentiment_summary"] = {
            "mood": mood,
            "emoji": emoji,
            "bullish_pct": round(bullish_count / total_news * 100),
            "bearish_pct": round(bearish_count / total_news * 100),
        }

        # Step 5: Generate formatted brief
        result["greeting"] = _generate_greeting(today)
        result["brief_text"] = _format_daily_brief(result)

    except Exception as e:
        result["brief_text"] = f"Brifing oluşturulurken hata: {str(e)}"
        print(f"[RAG v5] Daily brief error: {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ANOMALY DETECTION — Fiyat-Haber Uyumsuzluk Tespiti
# ═══════════════════════════════════════════════════════════════════════════════


async def detect_anomalies(symbols: List[str] = None) -> Dict:
    """
    Detect anomalies: price movements that don't align with news sentiment.

    Examples:
    - Price rallying but all news is bearish → potential manipulation
    - Price crashing but no negative news found → possible whale activity
    - Sudden volume spike with no corresponding news → suspicious activity

    Returns:
        {
            "anomalies": [
                {
                    "symbol": "BTC",
                    "type": "price_news_divergence",
                    "severity": "high",
                    "description": "Fiyat yükseliyor ama olumsuz haberler var",
                    "price_direction": "up",
                    "news_sentiment": "bearish",
                    "confidence": 0.78
                }
            ],
            "checked_symbols": ["BTC", "ETH", ...],
            "anomaly_count": 2,
            "summary": "..."
        }
    """
    if symbols is None:
        symbols = default_crypto_symbols()

    result = {"anomalies": [], "checked_symbols": symbols, "anomaly_count": 0, "summary": ""}

    try:
        # One call covers every symbol, so the per-symbol check works from an
        # already-fetched ticker rather than issuing a request each.
        tickers = await fetch_tickers_24h(symbols)
        for symbol in symbols:
            ticker = tickers.get(symbol)
            if ticker is None:
                # OKX does not list the pair — no price to compare news against.
                continue
            anomaly = _check_symbol_anomaly(symbol, ticker["change_pct"])
            if anomaly:
                result["anomalies"].append(anomaly)

        result["anomaly_count"] = len(result["anomalies"])

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        result["anomalies"].sort(key=lambda x: severity_order.get(x.get("severity", "low"), 3))

        # Generate summary
        if result["anomalies"]:
            alerts = []
            for a in result["anomalies"][:3]:
                alerts.append(f"⚠️ {a['symbol']}: {a['description']}")
            result["summary"] = "\n".join(alerts)
        else:
            result["summary"] = (
                "✅ Anomali tespit edilmedi — tüm fiyat hareketleri haber akışıyla uyumlu."
            )

    except Exception as e:
        result["summary"] = f"Anomali analizi hatası: {str(e)}"
        print(f"[RAG v5] Anomaly detection error: {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _check_symbol_anomaly(symbol: str, price_change: float) -> Optional[Dict]:
    """Check one symbol's 24h move for divergence against the indexed news."""
    try:
        # Only flag significant moves
        if abs(price_change) < MOVER_THRESHOLD_PCT:
            return None

        price_direction = "up" if price_change > 0 else "down"

        # Search RAG for recent news about this symbol
        query = f"{symbol} recent news"
        query_embedding = generate_embedding(query)

        if get_collection(NEWS_COLLECTION).count() == 0:
            # No news at all but big price move → anomaly
            if abs(price_change) > 5:
                return {
                    "symbol": symbol,
                    "type": "no_news_coverage",
                    "severity": "medium",
                    "description": f"Fiyat {price_change:+.1f}% hareket etti ama RAG'da ilgili haber yok",
                    "price_direction": price_direction,
                    "price_change": price_change,
                    "news_sentiment": "none",
                    "confidence": 0.6,
                }
            return None

        # Only news that is genuinely about this symbol counts. The old 0.35
        # threshold sat inside the noise band of the broken similarity scale, so
        # unrelated headlines were being read as this asset's news flow — and a
        # divergence alarm raised against noise is worse than no alarm.
        scored = query_scored(
            NEWS_COLLECTION, query_embedding, source=SOURCE_NEWS, query_symbol=symbol, k=5
        )

        sentiments = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
        for s in scored:
            sent = (s.item.metadata.get("sentiment") or "neutral").lower()
            if sent in sentiments:
                sentiments[sent] += s.score

        relevant_count = len(scored)

        if relevant_count == 0:
            if abs(price_change) > 5:
                return {
                    "symbol": symbol,
                    "type": "no_news_coverage",
                    "severity": "medium",
                    "description": f"Fiyat {price_change:+.1f}% hareket etti ama ilgili haber bulunamadı",
                    "price_direction": price_direction,
                    "price_change": price_change,
                    "news_sentiment": "none",
                    "confidence": 0.5,
                }
            return None

        # Weighted, so three barely-related headlines no longer outvote the one
        # that is actually about this asset.
        vote = weighted_vote(
            [(s.item.metadata.get("sentiment") or "neutral").lower() for s in scored],
            [s.score for s in scored],
        )
        dominant_sentiment = vote[0] if vote else "neutral"

        # Check for divergence
        is_divergent = False
        divergence_desc = ""

        if price_direction == "up" and dominant_sentiment == "bearish":
            is_divergent = True
            divergence_desc = f"Fiyat yükseliyor ({price_change:+.1f}%) ama haberler olumsuz — Manipülasyon riski?"
        elif price_direction == "down" and dominant_sentiment == "bullish":
            is_divergent = True
            divergence_desc = f"Fiyat düşüyor ({price_change:+.1f}%) ama haberler olumlu — Balina satışı olabilir?"

        if is_divergent:
            severity = (
                "critical"
                if abs(price_change) > 10
                else "high"
                if abs(price_change) > 5
                else "medium"
            )
            # Share of the weighted sentiment, not a raw headline count.
            total_weight = sum(sentiments.values()) or 1.0
            share = sentiments[dominant_sentiment] / total_weight
            confidence = min(0.95, 0.5 + share * 0.3 + (abs(price_change) / 20) * 0.2)

            return {
                "symbol": symbol,
                "type": "price_news_divergence",
                "severity": severity,
                "description": divergence_desc,
                "price_direction": price_direction,
                "price_change": price_change,
                "news_sentiment": dominant_sentiment,
                "news_count": relevant_count,
                "confidence": round(confidence, 2),
            }

    except Exception as e:
        print(f"[RAG v5] Anomaly check error for {symbol}: {e}")

    return None


def _generate_greeting(now: datetime) -> str:
    """Generate time-appropriate greeting."""
    hour = now.hour
    if hour < 12:
        return "☀️ Günaydın! İşte bugünkü piyasa briffinginiz:"
    elif hour < 18:
        return "🌤️ İyi günler! İşte güncel piyasa briffinginiz:"
    else:
        return "🌙 İyi akşamlar! İşte piyasa briffinginiz:"


def _format_daily_brief(result: Dict) -> str:
    """Format the daily brief into readable text."""
    lines = [result["greeting"], ""]

    # Market Snapshot
    if result["market_snapshot"]:
        lines.append("📊 **Piyasa Anlık Görünümü:**")
        for symbol, data in list(result["market_snapshot"].items())[:5]:
            emoji = "🟢" if data["change_24h"] > 0 else "🔴" if data["change_24h"] < 0 else "⚪"
            lines.append(f"  {emoji} {symbol}: ${data['price']:,.2f} ({data['change_24h']:+.1f}%)")
        lines.append("")

    # Big Movers
    if result["overnight_movers"]:
        lines.append("🚀 **Büyük Hareketler (>3%):**")
        for mover in result["overnight_movers"][:3]:
            lines.append(f"  {mover['direction']} {mover['symbol']}: {mover['change_pct']:+.1f}%")
        lines.append("")

    # Top News
    if result["top_news"]:
        lines.append("📰 **Öne Çıkan Haberler:**")
        for news in result["top_news"][:3]:
            sent_emoji = (
                "🟢"
                if news["sentiment"] == "bullish"
                else "🔴"
                if news["sentiment"] == "bearish"
                else "⚪"
            )
            lines.append(f"  {sent_emoji} {news['title']}")
        lines.append("")

    # Upcoming Events
    if result["upcoming_events"]:
        lines.append("📅 **Yakın Olaylar:**")
        for event in result["upcoming_events"][:3]:
            lines.append(f"  • {event['event']} ({event['date']})")
        lines.append("")

    # Sentiment
    sentiment = result.get("sentiment_summary", {})
    if sentiment:
        lines.append(
            f"🎯 **Genel Sentiment:** {sentiment.get('emoji', '🟡')} {sentiment.get('mood', 'Nötr')}"
        )

    return "\n".join(lines)


print("[RAG v5] Proactive Agent loaded.")
