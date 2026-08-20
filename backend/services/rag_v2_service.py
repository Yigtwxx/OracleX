"""
RAG 2.0 Service - Advanced Retrieval Augmented Generation
Features:
- Historical news with price outcomes
- Historical price data indexing
- Event correlation analysis
- Temporal context retrieval
- Automatic learning from past predictions
"""

from typing import Any, List, Dict, Optional
from dataclasses import replace
from datetime import datetime
import hashlib
import logging
import os
import asyncio

from config import settings
from services import rag_chunking, rag_embeddings, rag_hybrid, rag_rerank
from services.okx_market import fetch_history_candles
from services.rag_bellwethers import default_crypto_symbols
from services.rag_outcomes import EventOutcome, measure_event_outcome
from services.rag_scoring import (
    SOURCE_EVENT,
    SOURCE_NEWS,
    SOURCE_PRICE,
    ScoredItem,
    candidate_pool_size,
    horizons_from_metadata,
    is_surprising,
    rank_candidates,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Data directory for persistent storage
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "rag_v2")

# Collections
NEWS_COLLECTION = "historical_news"
EVENTS_COLLECTION = "market_events"
PRICE_COLLECTION = "price_history"

# The embedding model lives in `services.rag_embeddings`, which both stores share.
# A constant naming it here would be a second place to change and — as of the
# move to qwen3-embedding — a place that had already gone stale.

# Curated market events whose aftermath is worth learning from.
#
# Scope is deliberate: these are bellwether assets (see `rag_bellwethers`), not
# every symbol the app can price. Measuring an event costs a year of candles, and
# the pay-off is that a bellwether's lesson carries to the assets that follow it.
#
# Each entry is hand-written; nothing here is a measurement. `apparent_sentiment`
# records what the headline *implied* at the time, which is the half of the story
# the market can contradict — and events where it did are the most instructive
# ones in the list. `importance` is an optional override for cases the event-class
# prior gets wrong; leaving it out falls back to that prior.
#
# The dates matter more than anything else here: they anchor the measurement, so
# a wrong one produces a confident wrong answer. Verify before adding.
IMPORTANT_EVENTS = [
    # ── 2026 ────────────────────────────────────────────────────────────────
    # Recent entries cannot have their long horizons measured yet; they fill in
    # as history accumulates and re-indexing picks them up.
    {
        "date": "2026-07-01",
        "event": "AI chip selloff on valuation concerns after a 130% SOX rally",
        "symbol": "^IXIC",
        "asset_type": "stock",
        "type": "macro",
        "apparent_sentiment": "bearish",
        "importance": 0.8,
    },
    {
        "date": "2026-06-01",
        "event": "Strategy sells bitcoin, its first sale since 2022",
        "symbol": "BTC",
        "asset_type": "crypto",
        "type": "treasury",
        "apparent_sentiment": "bearish",
    },
    {
        "date": "2026-01-22",
        "event": "Micron surges on HBM4 demand as the memory supercycle accelerates",
        "symbol": "MU",
        "asset_type": "stock",
        "type": "earnings",
        "apparent_sentiment": "bullish",
        "importance": 0.85,
    },
    {
        "date": "2026-01-14",
        "event": "US imposes a 25% Section 232 tariff on advanced AI chips",
        "symbol": "NVDA",
        "asset_type": "stock",
        "type": "tariff",
        "apparent_sentiment": "bearish",
        "importance": 0.9,
    },
    # ── 2025 ────────────────────────────────────────────────────────────────
    {
        "date": "2025-07-17",
        "event": "US House passes the CLARITY Act on digital asset market structure",
        "symbol": "BTC",
        "asset_type": "crypto",
        "type": "regulatory",
        "apparent_sentiment": "bullish",
        "importance": 0.85,
    },
    # The largest single-day market-cap loss in US history, fully recovered and
    # then some within the year. The reason horizons run to 365 days.
    {
        "date": "2025-01-27",
        "event": "DeepSeek R1 release triggers an AI chip selloff",
        "symbol": "NVDA",
        "asset_type": "stock",
        "type": "macro",
        "apparent_sentiment": "bearish",
        "importance": 1.0,
    },
    {
        "date": "2025-01-23",
        "event": "Trump crypto executive order establishes a strategic reserve",
        "symbol": "BTC",
        "asset_type": "crypto",
        "type": "regulatory",
        "apparent_sentiment": "bullish",
    },
    {
        "date": "2025-01-20",
        "event": "Bitcoin all-time high near $109K on the inauguration rally",
        "symbol": "BTC",
        "asset_type": "crypto",
        "type": "price_milestone",
        "apparent_sentiment": "bullish",
    },
    {
        "date": "2025-01-17",
        "event": "Solana ETF applications filed",
        "symbol": "SOL",
        "asset_type": "crypto",
        "type": "regulatory",
        "apparent_sentiment": "bullish",
        "importance": 0.4,
    },
    {
        "date": "2025-02-12",
        "event": "Ethereum Pectra upgrade reaches testnet",
        "symbol": "ETH",
        "asset_type": "crypto",
        "type": "upgrade",
        "apparent_sentiment": "bullish",
        "importance": 0.35,
    },
    # ── 2024 ────────────────────────────────────────────────────────────────
    {
        "date": "2024-08-05",
        "event": "Yen carry trade unwinds, global risk assets sell off",
        "symbol": "^IXIC",
        "asset_type": "stock",
        "type": "macro",
        "apparent_sentiment": "bearish",
        "importance": 0.9,
    },
    {
        "date": "2024-07-23",
        "event": "Ethereum spot ETFs approved",
        "symbol": "ETH",
        "asset_type": "crypto",
        "type": "regulatory",
        "apparent_sentiment": "bullish",
    },
    {
        "date": "2024-07-05",
        "event": "Mt. Gox begins repaying creditors in bitcoin",
        "symbol": "BTC",
        "asset_type": "crypto",
        "type": "exchange",
        "apparent_sentiment": "bearish",
        "importance": 0.8,
    },
    {
        "date": "2024-04-20",
        "event": "Bitcoin Halving 2024",
        "symbol": "BTC",
        "asset_type": "crypto",
        "type": "halving",
        "apparent_sentiment": "bullish",
        "importance": 0.95,
    },
    {
        "date": "2024-03-13",
        "event": "Ethereum Dencun upgrade",
        "symbol": "ETH",
        "asset_type": "crypto",
        "type": "upgrade",
        "apparent_sentiment": "bullish",
    },
    {
        "date": "2024-02-21",
        "event": "Nvidia Q4 FY24 earnings beat on data-centre demand",
        "symbol": "NVDA",
        "asset_type": "stock",
        "type": "earnings",
        "apparent_sentiment": "bullish",
        "importance": 0.85,
    },
    {
        "date": "2024-01-11",
        "event": "Bitcoin spot ETFs approved",
        "symbol": "BTC",
        "asset_type": "crypto",
        "type": "regulatory",
        "apparent_sentiment": "bullish",
        "importance": 1.0,
    },
    # ── 2023 ────────────────────────────────────────────────────────────────
    {
        "date": "2023-07-13",
        "event": "Ripple wins partial summary judgment against the SEC",
        "symbol": "XRP",
        "asset_type": "crypto",
        "type": "regulatory",
        "apparent_sentiment": "bullish",
        "importance": 0.9,
    },
    {
        "date": "2023-05-24",
        "event": "Nvidia guides quarterly revenue far above consensus",
        "symbol": "NVDA",
        "asset_type": "stock",
        "type": "earnings",
        "apparent_sentiment": "bullish",
        "importance": 0.9,
    },
    # A banking failure read as contagion risk; bitcoin treated it as the
    # argument for holding bitcoin. Bearish headline, bullish aftermath.
    {
        "date": "2023-03-10",
        "event": "Silicon Valley Bank collapses, regional banking crisis",
        "symbol": "BTC",
        "asset_type": "crypto",
        "type": "macro",
        "apparent_sentiment": "bearish",
        "importance": 1.0,
    },
    {
        "date": "2023-03-10",
        "event": "Silicon Valley Bank collapses, regional banking crisis",
        "symbol": "^IXIC",
        "asset_type": "stock",
        "type": "macro",
        "apparent_sentiment": "bearish",
        "importance": 0.9,
    },
    # Named for the fear that drove it: unlocked staked ETH was widely expected
    # to be dumped. The upgrade itself read as routine.
    {
        "date": "2023-04-12",
        "event": "Ethereum Shanghai upgrade unlocks staked ETH, feared as sell pressure",
        "symbol": "ETH",
        "asset_type": "crypto",
        "type": "upgrade",
        "apparent_sentiment": "bearish",
    },
    # ── 2022 ────────────────────────────────────────────────────────────────
    {
        "date": "2022-11-11",
        "event": "FTX collapses into bankruptcy",
        "symbol": "BTC",
        "asset_type": "crypto",
        "type": "exchange",
        "apparent_sentiment": "bearish",
        "importance": 1.0,
    },
    {
        "date": "2022-11-10",
        "event": "October CPI undershoots, Fed pivot trade ignites",
        "symbol": "^IXIC",
        "asset_type": "stock",
        "type": "macro",
        "apparent_sentiment": "bullish",
        "importance": 0.85,
    },
    # The textbook sell-the-news: an upgrade years in the making, priced in.
    {
        "date": "2022-09-15",
        "event": "Ethereum completes the Merge to proof of stake",
        "symbol": "ETH",
        "asset_type": "crypto",
        "type": "upgrade",
        "apparent_sentiment": "bullish",
        "importance": 0.9,
    },
    {
        "date": "2022-06-13",
        "event": "Celsius halts withdrawals as 3AC unwinds",
        "symbol": "BTC",
        "asset_type": "crypto",
        "type": "exchange",
        "apparent_sentiment": "bearish",
    },
    {
        "date": "2022-05-09",
        "event": "Terra UST depegs and LUNA collapses",
        "symbol": "BTC",
        "asset_type": "crypto",
        "type": "exchange",
        "apparent_sentiment": "bearish",
        "importance": 1.0,
    },
    # ── 2021 ────────────────────────────────────────────────────────────────
    # Both of these read as triumphs and both marked cycle tops.
    {
        "date": "2021-11-10",
        "event": "Bitcoin all-time high near $69K",
        "symbol": "BTC",
        "asset_type": "crypto",
        "type": "price_milestone",
        "apparent_sentiment": "bullish",
        "importance": 0.8,
    },
    {
        "date": "2021-05-19",
        "event": "China bans bitcoin mining and crypto services",
        "symbol": "BTC",
        "asset_type": "crypto",
        "type": "regulatory",
        "apparent_sentiment": "bearish",
        "importance": 0.95,
    },
    {
        "date": "2021-04-14",
        "event": "Coinbase lists on Nasdaq",
        "symbol": "BTC",
        "asset_type": "crypto",
        "type": "adoption",
        "apparent_sentiment": "bullish",
        "importance": 0.75,
    },
    # ── 2020 ────────────────────────────────────────────────────────────────
    # The case the whole feature exists for: an unambiguously bearish headline,
    # a 73% drawdown, and a far higher price within the year.
    {
        "date": "2020-12-22",
        "event": "SEC sues Ripple over unregistered XRP sales",
        "symbol": "XRP",
        "asset_type": "crypto",
        "type": "regulatory",
        "apparent_sentiment": "bearish",
        "importance": 1.0,
    },
    {
        "date": "2020-05-11",
        "event": "Bitcoin Halving 2020",
        "symbol": "BTC",
        "asset_type": "crypto",
        "type": "halving",
        "apparent_sentiment": "bullish",
        "importance": 0.95,
    },
    {
        "date": "2020-03-16",
        "event": "Covid crash, Nasdaq's worst session since 1987",
        "symbol": "^IXIC",
        "asset_type": "stock",
        "type": "macro",
        "apparent_sentiment": "bearish",
        "importance": 0.95,
    },
    {
        "date": "2020-03-12",
        "event": "Covid crash Black Thursday, bitcoin halves in a day",
        "symbol": "BTC",
        "asset_type": "crypto",
        "type": "macro",
        "apparent_sentiment": "bearish",
        "importance": 1.0,
    },
]

# ═══════════════════════════════════════════════════════════════════════════════
# GLOBALS (Lazy Loading)
# ═══════════════════════════════════════════════════════════════════════════════

_chroma_client = None
_collections = {}


def get_chroma_client():
    """Get or initialize ChromaDB client."""
    global _chroma_client
    if _chroma_client is None:
        # Deferred for the same reason as in rag_service: this module is
        # reachable from the news pipeline, the chat tools and the scheduler,
        # and none of them should pay ChromaDB's import cost to be loaded.
        import chromadb

        os.makedirs(DATA_DIR, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=DATA_DIR)
        print(f"[RAG 2.0] ChromaDB client initialized at {DATA_DIR}")
    return _chroma_client


def get_collection(name: str):
    """Get or create a collection."""
    global _collections
    if name not in _collections:
        client = get_chroma_client()
        _collections[name] = client.get_or_create_collection(
            name=name, metadata={"description": f"RAG 2.0 collection: {name}"}
        )
        count = _collections[name].count()
        print(f"[RAG 2.0] Collection '{name}' ready with {count} items")
        # A store built by a different embedding model does not fail loudly — it
        # just returns neighbours that mean nothing. Say so once, at load.
        mismatch = rag_embeddings.assert_store_compatible(_collections[name], name)
        if mismatch:
            logger.error("[RAG 2.0] %s", mismatch)
    return _collections[name]


def generate_embedding(text: str) -> List[float]:
    """
    Embed a document for storage. See `rag_embeddings` for the backend.

    Documents and queries are embedded differently — the query model is
    instruction-conditioned — so retrieval paths must call `embed_query` rather
    than this. Kept as the document-side entry point because the indexers and the
    v3/v4/v5 agents already call it by this name.
    """
    return rag_embeddings.embed_document(text)


# ═══════════════════════════════════════════════════════════════════════════════
# HISTORICAL PRICE DATA
# ═══════════════════════════════════════════════════════════════════════════════


async def fetch_historical_prices(symbol: str, days: int = 365) -> List[Dict]:
    """
    Fetch historical daily candles from OKX, oldest-first.

    Binance was the original source but is unreachable from some of the networks
    this runs on, which meant the price collection silently indexed nothing.
    """
    try:
        candles = await fetch_history_candles(symbol, bar="1D", limit=days)
    except Exception as e:
        logger.error("[RAG 2.0] Error fetching historical prices for %s: %s", symbol, e)
        return []

    prices = []
    for candle in candles:
        if candle["open"] <= 0:
            continue
        prices.append(
            {
                "date": datetime.fromtimestamp(candle["time"]).strftime("%Y-%m-%d"),
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"],
                "change_pct": ((candle["close"] - candle["open"]) / candle["open"]) * 100,
            }
        )

    return prices


async def index_price_history(symbol: str = "BTC", days: int = 365) -> int:
    """
    Index historical price data into vector store.
    Creates embeddings for price patterns and events.
    """
    collection = get_collection(PRICE_COLLECTION)
    prices = await fetch_historical_prices(symbol, days)

    if not prices:
        return 0

    indexed = 0
    for i, price in enumerate(prices):
        # Create descriptive text for embedding
        trend = "up" if price["change_pct"] > 0 else "down"
        magnitude = (
            "strong"
            if abs(price["change_pct"]) > 3
            else "moderate"
            if abs(price["change_pct"]) > 1
            else "slight"
        )

        text = f"{symbol} on {price['date']}: Price moved {magnitude}ly {trend} ({price['change_pct']:.1f}%). "
        text += f"Opened at ${price['open']:,.0f}, closed at ${price['close']:,.0f}. "
        text += f"Volume: ${price['volume'] / 1e9:.2f}B. "

        # Add weekly context
        if i >= 7:
            weekly_change = (
                (price["close"] - prices[i - 7]["close"]) / prices[i - 7]["close"]
            ) * 100
            text += f"Weekly change: {weekly_change:+.1f}%."

        try:
            embedding = generate_embedding(text)
            doc_id = f"{symbol}_{price['date']}"

            collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                metadatas=[
                    {
                        "symbol": symbol,
                        "date": price["date"],
                        "close": price["close"],
                        "change_pct": price["change_pct"],
                        "volume": price["volume"],
                        "type": "daily_price",
                    }
                ],
                documents=[text],
            )
            indexed += 1
        except Exception as e:
            print(f"[RAG 2.0] Error indexing price: {e}")

    print(f"[RAG 2.0] Indexed {indexed} price records for {symbol}")
    return indexed


# ═══════════════════════════════════════════════════════════════════════════════
# MARKET EVENTS
# ═══════════════════════════════════════════════════════════════════════════════


def _event_document(event: Dict, outcome: Optional[EventOutcome]) -> str:
    """
    The text an event is embedded and retrieved as.

    The measured aftermath goes into the document, not just the metadata, so a
    query about consequences ("what happened after the SEC sued a crypto
    project") can match on the consequence and not only on the headline. Where
    the headline and the outcome disagree, the document says so in words —
    that sentence is what a model retrieving this precedent needs to read.
    """
    parts = [
        f"{event['event']} happened on {event['date']}. "
        f"This was a {event['type']} event affecting {event['symbol']}."
    ]

    apparent = event.get("apparent_sentiment")
    if apparent:
        parts.append(f"The headline read {apparent}.")

    if outcome is None:
        return " ".join(parts)

    moves = ", ".join(f"{days}d {pct:+.1f}%" for days, pct in sorted(outcome.horizons.items()))
    if moves:
        parts.append(f"Price afterwards: {moves}.")
    if outcome.max_drawdown_pct is not None and outcome.max_runup_pct is not None:
        parts.append(
            f"Worst drawdown {outcome.max_drawdown_pct:+.1f}%, "
            f"best run-up {outcome.max_runup_pct:+.1f}%."
        )

    if apparent and outcome.durable_direction:
        if is_surprising(apparent, outcome.durable_direction):
            parts.append(
                f"The durable outcome was {outcome.durable_direction}, contradicting "
                "the headline: the market did the opposite of what the news implied."
            )
        else:
            parts.append(f"The durable outcome was {outcome.durable_direction}.")
    elif outcome.durable_direction:
        parts.append(f"The durable outcome was {outcome.durable_direction}.")

    if outcome.inverted:
        parts.append("The immediate reaction and the durable outcome diverged.")

    return " ".join(parts)


async def index_market_events() -> int:
    """
    Measure and index the curated event catalogue.

    Each event's aftermath is measured across every configured horizon and
    stored in metadata, where retrieval can weigh it. Previously the ±7-day
    change was computed here and then dropped into free text only — so the one
    number the system had about an event's size was unreadable to the code that
    ranked events, which is why `find_historical_news_similarity` hardcoded a
    null price change for every event it returned.

    An event whose history cannot be fetched is still indexed. It simply carries
    no measurement, and importance falls back to its class prior rather than to
    an invented figure.
    """
    collection = get_collection(EVENTS_COLLECTION)
    indexed = 0
    measured = 0

    for event in IMPORTANT_EVENTS:
        try:
            event_date = datetime.strptime(event["date"], "%Y-%m-%d")
        except ValueError:
            logger.warning("[RAG 2.0] Skipping event with unparseable date: %s", event)
            continue

        asset_type = event.get("asset_type", "crypto")
        outcome = await measure_event_outcome(event["symbol"], event_date, asset_type)
        if outcome is not None:
            measured += 1

        text = _event_document(event, outcome)

        metadata: Dict[str, Any] = {
            "symbol": event["symbol"],
            "date": event["date"],
            "event_type": event["type"],
            "event_name": event["event"],
            "asset_type": asset_type,
        }
        if event.get("apparent_sentiment"):
            metadata["apparent_sentiment"] = event["apparent_sentiment"]
        if event.get("importance") is not None:
            metadata["importance_base"] = float(event["importance"])
        if outcome is not None:
            # Chroma rejects null metadata, so unmeasured horizons are absent
            # rather than present-and-empty.
            metadata.update(outcome.as_metadata())
            if event.get("apparent_sentiment") and outcome.durable_direction:
                metadata["surprised"] = is_surprising(
                    event["apparent_sentiment"], outcome.durable_direction
                )

        try:
            embedding = generate_embedding(text)
            # Two events can share a date (one crisis, two asset classes), so the
            # id carries the symbol as well.
            doc_id = f"event_{event['date']}_{event['symbol']}"

            collection.upsert(
                ids=[doc_id],
                embeddings=[embedding],
                metadatas=[metadata],
                documents=[text],
            )
            indexed += 1
        except Exception as e:
            print(f"[RAG 2.0] Error indexing event: {e}")

    print(f"[RAG 2.0] Indexed {indexed} market events ({measured} with a measured outcome)")
    return indexed


# ═══════════════════════════════════════════════════════════════════════════════
# NEWS INDEXING
# ═══════════════════════════════════════════════════════════════════════════════


def index_article_body(
    *,
    title: str,
    body: str,
    url: str,
    symbol: str = "",
    asset_type: str = "crypto",
    published_at: str = "",
) -> int:
    """
    Index the paragraphs of an article, not just its headline.

    The body is fetched for every analysed story and was then thrown away: only
    the headline and a summary truncated at 2000 characters ever reached the
    index. So a question could match "SEC sues Ripple" and never reach the
    paragraph explaining what the filing actually claimed — which is the part
    that answers a question rather than restating it.

    Each chunk carries the headline, because a body paragraph read alone often
    never names the asset it is about, and an unattributable chunk cannot be
    ranked by symbol. `parent_id` lets retrieval fold several chunks of one story
    back into a single source; without it the top of a result list is one article
    wearing five hats.

    Returns the number of chunks written.
    """
    body = (body or "").strip()
    if not body:
        return 0

    try:
        collection = get_collection(NEWS_COLLECTION)
        parent = rag_chunking.parent_id_for(url or title)
        chunks = rag_chunking.chunk_document(
            body,
            parent_id=parent,
            header=title,
            metadata={
                "title": title[:500],
                "symbol": symbol or "",
                "asset_type": asset_type or "crypto",
                "url": url or "",
                "published_at": published_at or "",
                "source": "article_body",
                "stored_at": datetime.now().isoformat(),
                # The chunk carries no sentiment of its own; the headline-level
                # record holds the verdict. Empty rather than absent — Chroma
                # rejects None in metadata.
                "sentiment": "",
                "confidence": 0.0,
            },
        )
        if not chunks:
            return 0

        embeddings = rag_embeddings.embed_documents([chunk.text for chunk in chunks])
        collection.upsert(
            ids=[chunk.id for chunk in chunks],
            embeddings=embeddings,
            metadatas=[chunk.metadata for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
        )
        rag_hybrid.invalidate(NEWS_COLLECTION)
        return len(chunks)
    except Exception as e:  # noqa: BLE001 — indexing must not fail an analysis
        logger.warning("[RAG 2.0] Could not index article body for '%s': %s", title[:60], e)
        return 0


def store_news_with_outcome(
    title: str,
    summary: str,
    symbol: str,
    sentiment: str,
    confidence: float,
    price_before: Optional[float] = None,
    price_after: Optional[float] = None,
    actual_outcome: Optional[str] = None,
) -> bool:
    """
    Store news with its outcome for future learning.
    """
    try:
        collection = get_collection(NEWS_COLLECTION)

        # Create rich text for embedding
        text = f"{title}. {summary}"
        if actual_outcome:
            text += f" Outcome: {actual_outcome}."

        embedding = generate_embedding(text)

        # Calculate price change if available
        price_change = None
        if price_before and price_after:
            price_change = ((price_after - price_before) / price_before) * 100

        # Determine if prediction was correct
        prediction_correct = None
        if actual_outcome and sentiment:
            if sentiment == "bullish" and actual_outcome in ["price_up", "bullish"]:
                prediction_correct = True
            elif sentiment == "bearish" and actual_outcome in ["price_down", "bearish"]:
                prediction_correct = True
            elif actual_outcome == "neutral":
                prediction_correct = sentiment == "neutral"
            else:
                prediction_correct = False

        doc_id = hashlib.md5(f"{title}:{datetime.now().isoformat()}".encode()).hexdigest()[:16]

        metadata = {
            "title": title[:500],
            "symbol": symbol,
            "sentiment": sentiment,
            "confidence": confidence,
            "stored_at": datetime.now().isoformat(),
        }

        if price_change is not None:
            metadata["price_change"] = price_change
        if actual_outcome:
            metadata["actual_outcome"] = actual_outcome
        if prediction_correct is not None:
            metadata["prediction_correct"] = prediction_correct

        collection.upsert(
            ids=[doc_id], embeddings=[embedding], metadatas=[metadata], documents=[text[:2000]]
        )

        return True
    except Exception as e:
        print(f"[RAG 2.0] Error storing news: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# ADVANCED RETRIEVAL
# ═══════════════════════════════════════════════════════════════════════════════


def _dense_hits(collection, query_embedding: List[float], pool: int, where: Optional[Dict]):
    """Vector search, returned as an id-ordered list plus a lookup by id."""
    response = collection.query(
        query_embeddings=[query_embedding],
        n_results=pool,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    ids = (response.get("ids") or [[]])[0]
    documents = (response.get("documents") or [[]])[0]
    metadatas = (response.get("metadatas") or [[]])[0]
    distances = (response.get("distances") or [[]])[0]
    by_id = {
        doc_id: (documents[i] if i < len(documents) else "", metadatas[i], distances[i])
        for i, doc_id in enumerate(ids)
        if i < len(metadatas) and i < len(distances)
    }
    return ids, by_id


def _fetch_lexical_only(collection, ids: List[str], query_embedding: List[float]) -> Dict:
    """
    Load documents BM25 found that vector search did not, with a real distance.

    They have no distance of their own — they were never in the vector result —
    and inventing one would corrupt the relevance gate. Chroma stores the vectors,
    so the exact squared-L2 distance is recomputed here from the stored embedding.
    That identity only holds because embeddings are unit-normalised; see
    `rag_embeddings`.
    """
    if not ids:
        return {}
    stored = collection.get(ids=ids, include=["documents", "metadatas", "embeddings"])
    found = stored.get("ids") or []
    documents = stored.get("documents") or []
    metadatas = stored.get("metadatas") or []
    # Chroma hands embeddings back as a numpy array, and `x or []` on one raises
    # "truth value of an array is ambiguous" rather than falling through.
    embeddings = stored.get("embeddings")
    if embeddings is None:
        embeddings = []

    extra: Dict = {}
    for i, doc_id in enumerate(found):
        if i >= len(metadatas) or i >= len(embeddings):
            continue
        dot = sum(a * b for a, b in zip(query_embedding, embeddings[i]))
        extra[doc_id] = (
            documents[i] if i < len(documents) else "",
            metadatas[i],
            max(0.0, 2.0 - 2.0 * dot),
        )
    return extra


def query_scored(
    collection_name: str,
    query_embedding: List[float],
    *,
    source: str,
    query_symbol: Optional[str],
    k: int,
    where: Optional[Dict] = None,
    query_text: Optional[str] = None,
) -> List[ScoredItem]:
    """
    Retrieve from one collection and rank by importance rather than proximity.

    Three stages, each correcting the one before it:

    1. **Search** — vector search for meaning, BM25 for the tickers, dates and
       figures embeddings blur, fused by reciprocal rank. Deliberately
       over-fetches: nothing downstream can rank a candidate that was never
       retrieved.
    2. **Filter and weigh** — `rank_candidates` drops anything below the relevance
       floor, then weighs recency, measured magnitude, event class and symbol,
       and promotes precedents whose outcome contradicted their headline.
    3. **Re-rank** — a cross-encoder reads the query against each surviving
       document and its verdict multiplies the composite score. It corrects
       relevance; it is not allowed to override the domain weighting, because it
       knows nothing about which precedents are instructive.

    `query_text` is what enables stages 1's lexical half and stage 3. Without it
    the function behaves exactly as it did before both existed, which is what
    keeps the older callers in `rag_v4` and `rag_v5` working unchanged.
    """
    try:
        collection = get_collection(collection_name)
        pool = candidate_pool_size(k, collection.count())
        if pool <= 0:
            return []

        dense_ids, hits = _dense_hits(collection, query_embedding, pool, where)

        # Lexical search has no `where` clause, so its hits are filtered against
        # the dense result's contract by hand: an id the metadata filter would
        # have excluded must not enter through the side door.
        lexical_ids: List[str] = []
        if query_text and settings.RAG_HYBRID_SEARCH:
            candidates = rag_hybrid.lexical_ids(collection, collection_name, query_text, pool)
            unseen = [doc_id for doc_id in candidates if doc_id not in hits]
            extra = _fetch_lexical_only(collection, unseen, query_embedding)
            if where:
                extra = {
                    doc_id: value
                    for doc_id, value in extra.items()
                    if _matches_where(value[1], where)
                }
            hits.update(extra)
            lexical_ids = [doc_id for doc_id in candidates if doc_id in hits]

        fused = (
            rag_hybrid.reciprocal_rank_fusion(
                [dense_ids, lexical_ids], limit=max(pool, settings.RAG_RERANK_CANDIDATES)
            )
            if lexical_ids
            else dense_ids
        )
        if not fused:
            return []

        response = {
            "ids": [fused],
            "documents": [[hits[i][0] for i in fused]],
            "metadatas": [[hits[i][1] for i in fused]],
            "distances": [[hits[i][2] for i in fused]],
        }

        # Keep more than `k` alive so the cross-encoder has something to reorder.
        shortlist_size = max(k, settings.RAG_RERANK_CANDIDATES) if query_text else k
        shortlist = rank_candidates(
            response, source=source, query_symbol=query_symbol, k=shortlist_size
        )
        if not query_text or not shortlist:
            return shortlist[:k]

        return _apply_rerank(shortlist, query_text, hits, k)
    except Exception as e:
        logger.warning("[RAG 2.0] Error querying %s: %s", collection_name, e)
        return []


def _matches_where(metadata: Dict, where: Dict) -> bool:
    """Chroma's equality-only `where` clauses, applied to a locally fetched row."""
    return all(metadata.get(key) == value for key, value in where.items())


def _apply_rerank(
    shortlist: List[ScoredItem], query_text: str, hits: Dict, k: int
) -> List[ScoredItem]:
    """
    Multiply each candidate's composite score by the cross-encoder's verdict.

    `rag_rerank.score` already returns [0, 1]; squashing it again here would map a
    decisive verdict (0.146 against 0.000063) onto a 7% difference that reorders
    nothing.
    """
    documents = [hits.get(s.item.doc_id, ("", {}, 0.0))[0] for s in shortlist]
    scores = rag_rerank.score(query_text, documents)
    if scores is None:
        return shortlist[:k]

    reranked = [replace(item, rerank=value) for item, value in zip(shortlist, scores)]
    reranked.sort(key=lambda s: s.final_score, reverse=True)
    return reranked[:k]


def _event_payload(scored: ScoredItem) -> Dict:
    """One retrieved event, with the parts that produced its rank exposed."""
    meta = scored.item.metadata
    return {
        # Exposed so retrieval can be evaluated against a fixed answer key —
        # reconstructing an id from date and symbol works until two events share
        # both, which the catalogue already allows.
        "doc_id": scored.item.doc_id,
        "event": meta.get("event_name", ""),
        "date": meta.get("date", ""),
        "type": meta.get("event_type", ""),
        "symbol": meta.get("symbol", ""),
        "asset_type": meta.get("asset_type", ""),
        # Still called `similarity` for callers that read it, but it now carries
        # a true cosine instead of the old 1/(1+distance) reading.
        "similarity": round(scored.relevance, 3),
        "importance": round(scored.importance, 3),
        "score": round(scored.score, 4),
        "apparent_sentiment": meta.get("apparent_sentiment"),
        "immediate_direction": meta.get("immediate_direction"),
        "durable_direction": meta.get("durable_direction"),
        "inverted": bool(meta.get("inverted", False)),
        "surprised": bool(meta.get("surprised", False)),
        "max_drawdown_pct": meta.get("max_drawdown_pct"),
        "max_runup_pct": meta.get("max_runup_pct"),
        "horizons": horizons_from_metadata(meta),
    }


def query_historical_context(
    query: str,
    symbol: Optional[str] = None,
    include_events: bool = True,
    include_prices: bool = True,
    include_news: bool = True,
    k: int = 5,
    asset_type: Optional[str] = None,
) -> Dict[str, List[Dict]]:
    """
    Retrieve historical context, ranked by how much each item mattered.

    Every branch here used to convert distance with `1 / (1 + distance)` and
    admit anything above 0.3 or 0.4. Because the embedding model returns unit
    vectors that formula compressed the whole range into [0.2, 1.0]: an
    off-topic English sentence scored 0.316 against "Bitcoin Halving 2024",
    clearing the events threshold. Relevance is now a real cosine and it is only
    the gate — ranking is `rag_scoring.score_item`, which weighs recency,
    measured magnitude, event class and symbol relevance on top of it.

    `asset_type` restricts events to one side of the house. Without it a question
    about a stock retrieves crypto precedent, which is why the chat pipeline
    skipped this call outright for equities.
    """
    results = {"events": [], "prices": [], "news": [], "summary": ""}

    # Queries carry a task instruction that documents do not — see
    # `rag_embeddings.embed_query`. `query` is passed on as text too, which is
    # what turns on the lexical half of the search and the cross-encoder.
    query_embedding = rag_embeddings.embed_query(query)

    if include_events:
        for scored in query_scored(
            EVENTS_COLLECTION,
            query_embedding,
            source=SOURCE_EVENT,
            query_symbol=symbol,
            k=k,
            where={"asset_type": asset_type} if asset_type else None,
            query_text=query,
        ):
            results["events"].append(_event_payload(scored))

    if include_prices:
        for scored in query_scored(
            PRICE_COLLECTION,
            query_embedding,
            source=SOURCE_PRICE,
            query_symbol=symbol,
            k=k,
            where={"symbol": symbol} if symbol else None,
            query_text=query,
        ):
            meta = scored.item.metadata
            results["prices"].append(
                {
                    "date": meta.get("date", ""),
                    "close": meta.get("close", 0),
                    "change_pct": meta.get("change_pct", 0),
                    "symbol": meta.get("symbol", ""),
                    "similarity": round(scored.relevance, 3),
                    "score": round(scored.score, 4),
                }
            )

    if include_news:
        for scored in query_scored(
            NEWS_COLLECTION,
            query_embedding,
            source=SOURCE_NEWS,
            query_symbol=symbol,
            k=k,
            query_text=query,
        ):
            meta = scored.item.metadata
            results["news"].append(
                {
                    "title": meta.get("title", ""),
                    "sentiment": meta.get("sentiment", ""),
                    "outcome": meta.get("actual_outcome", ""),
                    "price_change": meta.get("price_change"),
                    "prediction_correct": meta.get("prediction_correct"),
                    "similarity": round(scored.relevance, 3),
                    "score": round(scored.score, 4),
                }
            )

    results["summary"] = _generate_context_summary(results)

    return results


def _generate_context_summary(results: Dict) -> str:
    """Generate a human-readable summary of retrieved context."""
    parts = []

    if results["events"]:
        parts.append("📅 İlgili Tarihsel Olaylar:")
        for event in results["events"][:3]:
            parts.append(f"  • {event['event']} ({event['date']}) - {event['type']}")

    if results["prices"]:
        parts.append("\n📊 Benzer Fiyat Hareketleri:")
        for price in results["prices"][:3]:
            direction = "📈" if price["change_pct"] > 0 else "📉"
            parts.append(
                f"  • {price['date']}: {direction} {price['change_pct']:+.1f}% (${price['close']:,.0f})"
            )

    if results["news"]:
        parts.append("\n📰 Benzer Geçmiş Haberler:")
        for news in results["news"][:3]:
            outcome = f" → {news['outcome']}" if news.get("outcome") else ""
            parts.append(f"  • {news['title'][:60]}... ({news['sentiment']}{outcome})")

    return "\n".join(parts) if parts else "Tarihsel veri bulunamadı."


def render_event_lines(
    events: List[Dict], limit: int = 3, include_similarity: bool = False
) -> List[str]:
    """
    Retrieved events as prompt lines, including how each one actually resolved.

    The measured aftermath is spelled out rather than summarised, and where the
    headline and the durable outcome disagree the line says so in words. That
    sentence is the whole point of the retrieval: without it a model reads "SEC
    sues Ripple" and concludes the price fell, when what followed was a 66%
    drawdown and then a higher price than before the suit.
    """
    lines: List[str] = []
    for event in events[:limit]:
        line = f"- {event['date']} ({event['type']}) {event.get('symbol', '')}: {event['event']}"

        # Only the chat turn asks for this. An analogy is worth as much as its
        # match is close, and without the score the model cannot tell a precise
        # precedent from a loose one — so it either hedges everything or hedges
        # nothing. The news pipeline's lines are unchanged by default.
        if include_similarity and event.get("similarity") is not None:
            line += f" [match {event['similarity']:.2f}]"

        apparent = event.get("apparent_sentiment")
        if apparent:
            line += f". Headline read {apparent}"

        horizons = event.get("horizons") or {}
        if horizons:
            moves = ", ".join(f"{d}d {horizons[d]:+.1f}%" for d in sorted(horizons))
            line += f". Actual: {moves}"

        drawdown, runup = event.get("max_drawdown_pct"), event.get("max_runup_pct")
        if drawdown is not None and runup is not None:
            line += f"; worst drawdown {drawdown:+.1f}%, best run-up {runup:+.1f}%"

        lines.append(line)

        if event.get("surprised"):
            lines.append(
                f"  The durable outcome was {event.get('durable_direction')}, the opposite "
                "of what the headline implied."
            )
        elif event.get("inverted"):
            lines.append("  The immediate reaction and the durable outcome diverged.")

    return lines


def get_rag_context_v2(
    query: str,
    symbol: Optional[str] = None,
    context_type: str = "all",
    asset_type: Optional[str] = None,
) -> str:
    """
    Get enhanced RAG context for LLM prompts.

    Args:
        query: User's question or news title
        symbol: Filter by symbol (BTC, ETH, etc.)
        context_type: 'all', 'events', 'prices', 'news'
        asset_type: 'crypto' or 'stock'; restricts events to that side

    Returns:
        Formatted context string for LLM, empty when nothing cleared the
        relevance floor. An empty string is a real answer — the callers treat it
        as "no precedent" and say so, which beats handing the model whichever
        unrelated event happened to be nearest.
    """
    include_events = context_type in ["all", "events"]
    include_prices = context_type in ["all", "prices"]
    include_news = context_type in ["all", "news"]

    results = query_historical_context(
        query=query,
        symbol=symbol,
        include_events=include_events,
        include_prices=include_prices,
        include_news=include_news,
        k=5,
        asset_type=asset_type,
    )

    # Formatted as markdown, matching the market snapshot the same prompt carries.
    # This used to emit <rag_events>/<price_move> XML, which put two different
    # markup languages in one prompt and invited the model to echo the
    # scaffolding back — something the chat system prompt explicitly forbids.
    context_parts = []

    if results["events"]:
        context_parts.append("Past events:")
        context_parts.extend(render_event_lines(results["events"], include_similarity=True))
        context_parts.append("")

    if results["prices"]:
        context_parts.append("Past price moves:")
        for price in results["prices"][:5]:
            context_parts.append(
                f"- {price['date']} {price['symbol']}: "
                f"close ${price['close']:,.0f}, change {price['change_pct']:+.1f}%"
            )
        context_parts.append("")

    if results["news"]:
        context_parts.append("Past news and how it resolved:")
        for news in results["news"][:3]:
            outcome = news.get("outcome", "unknown")
            price_change = news.get("price_change")
            correct = news.get("prediction_correct")

            line = f'- "{news["title"][:100]}" — called {news["sentiment"]}, outcome {outcome}'
            if price_change is not None:
                line += f", moved {price_change:+.1f}%"
            if correct is not None:
                line += f", prediction {'correct' if correct else 'incorrect'}"
            context_parts.append(line)
        context_parts.append("")

    return "\n".join(context_parts).strip()


# ═══════════════════════════════════════════════════════════════════════════════
# INITIALIZATION & MAINTENANCE
# ═══════════════════════════════════════════════════════════════════════════════


async def initialize_rag_v2(symbols: Optional[List[str]] = None) -> Dict:
    """
    Initialize RAG 2.0 with historical data.
    Should be called once to populate the vector store.
    """
    if symbols is None:
        # One curated list, in `rag_bellwethers`. Several services each carried
        # their own idea of "the important coins" and they had drifted apart.
        symbols = default_crypto_symbols()

    print("[RAG 2.0] Initializing with historical data...")

    stats = {"events_indexed": 0, "prices_indexed": 0, "status": "success"}

    try:
        # Index market events
        stats["events_indexed"] = await index_market_events()

        # Index price history for each symbol
        for symbol in symbols:
            indexed = await index_price_history(symbol, days=365)
            stats["prices_indexed"] += indexed
            await asyncio.sleep(0.5)  # Rate limiting

        print(f"[RAG 2.0] Initialization complete: {stats}")

    except Exception as e:
        stats["status"] = f"error: {str(e)}"
        print(f"[RAG 2.0] Initialization error: {e}")

    return stats


def get_rag_stats() -> Dict:
    """Get statistics about RAG 2.0 collections."""
    try:
        return {
            "news_count": get_collection(NEWS_COLLECTION).count(),
            "events_count": get_collection(EVENTS_COLLECTION).count(),
            "prices_count": get_collection(PRICE_COLLECTION).count(),
            "status": "healthy",
        }
    except Exception as e:
        return {"news_count": 0, "events_count": 0, "prices_count": 0, "status": f"error: {str(e)}"}


def _index_news_sync(cached_news: Dict[str, Any]) -> int:
    """
    The blocking half of `auto_index_recent_news`: embed and upsert.

    Every call in here is synchronous — the encode is CPU-bound and ChromaDB's
    client has no async surface — so this must only ever run in a worker thread.
    Run on the event loop it froze every request for as long as indexing took,
    the boot gate's own readiness poll included.
    """
    collection = get_collection(NEWS_COLLECTION)
    existing_ids = set()

    # Get existing IDs to avoid duplicates
    if collection.count() > 0:
        try:
            all_items = collection.get(include=[])
            existing_ids = set(all_items.get("ids", []))
        except Exception:
            pass

    # Collect first, embed once. A per-item encode pays the model's fixed
    # overhead on every headline; one batch pays it once for all of them.
    ids: List[str] = []
    texts: List[str] = []
    metadatas: List[Dict[str, Any]] = []

    for news_item in cached_news.values():
        # Per item, as before: one malformed entry skips itself rather than
        # taking the rest of the batch down with it.
        try:
            # Generate consistent ID from title
            doc_id = hashlib.md5(f"{news_item.title}".encode()).hexdigest()[:16]

            if doc_id in existing_ids:
                continue
            # The cache can hold two items with the same title; a duplicate id
            # in a single upsert is an error rather than a no-op.
            existing_ids.add(doc_id)

            metadata = {
                "title": news_item.title[:500],
                "symbol": "",  # Detected later
                "sentiment": "",  # Not analyzed yet
                "confidence": 0.0,
                "stored_at": datetime.now().isoformat(),
                "source": "auto_index",
                # Detect asset type from symbols
                "asset_type": news_item.asset_type or "crypto",
            }
        except Exception:
            continue

        ids.append(doc_id)
        texts.append(f"{news_item.title}. {news_item.summary or ''}")
        metadatas.append(metadata)

    if not ids:
        return 0

    embeddings = rag_embeddings.embed_documents(texts)

    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        metadatas=metadatas,
        documents=[text[:2000] for text in texts],
    )
    # The lexical index is a snapshot of the collection; leaving it in place
    # would make BM25 blind to everything indexed after startup.
    rag_hybrid.invalidate(NEWS_COLLECTION)
    return len(ids)


async def auto_index_recent_news() -> int:
    """
    Auto-index recent news from the shared cache into RAG v2.
    Called by background scheduler. Only indexes items not already in the database.
    Returns number of newly indexed items.
    """
    try:
        from utils import get_news_cache

        cached_news = get_news_cache()
        if not cached_news:
            return 0

        indexed = await asyncio.to_thread(_index_news_sync, cached_news)

        if indexed > 0:
            print(f"[RAG 2.0] ✓ Auto-indexed {indexed} news items into RAG")

        return indexed
    except Exception as e:
        print(f"[RAG 2.0] Auto-index error: {e}")
        return 0


print("[RAG 2.0] Service module loaded. Use initialize_rag_v2() to populate data.")
