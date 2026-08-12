"""
News Service - Fetches news from multiple sources
Crypto: Tree of Alpha, Decrypt, CoinDesk, CoinTelegraph, The Block, CryptoSlate
Turkish crypto: Koin Bülteni, Uzmancoin
Stocks: MarketWatch, Investing.com, Seeking Alpha (RSS)

Which asset each item is about is not decided here. A feed's own beat is only a
hint — CoinDesk covers Coinbase earnings, MarketWatch covers bitcoin ETFs — so
the symbol and the asset class both come back from `news_attribution`, which
resolves them from the text and remembers the answer.
"""

import logging
import asyncio
import re
from datetime import datetime, timedelta, timezone, UTC
from typing import List, Optional
import hashlib
import feedparser
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)

from models.schemas import NewsItem
from services import news_attribution
from services.http_client import get_json
from services.symbol_detection_service import (
    Attribution,
    asset_type_for_symbol,
    is_uncashtagged_acronym,
    resolve_crypto,
)


def parse_feed_date(entry) -> datetime:
    """
    Parse date from feed entry with proper timezone handling.
    Returns datetime in local time for accurate display.
    """
    now = datetime.now()

    try:
        # First try raw published string with timezone info
        raw_pub = entry.get("published", "")
        if raw_pub:
            try:
                # email.utils handles RFC 2822 dates with timezone
                dt = parsedate_to_datetime(raw_pub)
                # Convert to local timezone (Turkey UTC+3)
                local_tz = timezone(timedelta(hours=3))
                dt_local = dt.astimezone(local_tz)
                # Return as naive datetime for compatibility
                result = dt_local.replace(tzinfo=None)
                # Sanity check: date shouldn't be in the future
                if result > now:
                    return now
                return result
            except (ValueError, TypeError):
                pass

        # Fallback to parsed tuple (feedparser parses to UTC struct_time)
        published = entry.get("published_parsed")
        if published:
            # published_parsed is struct_time in UTC, convert to local (UTC+3)
            dt = datetime(*published[:6], tzinfo=UTC)
            local_tz = timezone(timedelta(hours=3))
            dt_local = dt.astimezone(local_tz)
            result = dt_local.replace(tzinfo=None)
            # Sanity check: date shouldn't be in the future
            if result > now:
                return now
            return result
    except (ValueError, TypeError, AttributeError):
        pass

    return now


# `detect_symbol` and its lookup tables used to live here. They were dead code
# — nothing called them — and both branches ended in a hardcoded default:
# BINANCE:BTCUSDT for anything crypto-shaped, AMEX:SPY for anything else.
# Attribution now goes through `news_attribution`, which resolves against the
# live exchange listings and returns None when it cannot identify an asset.


def generate_news_id(title: str, source: str) -> str:
    """Generate unique news ID from title and source."""
    data = f"{title}:{source}"
    return hashlib.md5(data.encode()).hexdigest()[:12]


async def _fetch_rss(source: str, url: str, hint: str, limit: int = 10) -> List[NewsItem]:
    """
    Fetch and normalise one RSS feed.

    Every source went through its own copy of these twenty lines, which is how
    the crypto feeds ended up with an `asyncio.to_thread` around the blocking
    parse and the equity feeds did not — those stalled the event loop while
    every other source waited. One function, one behaviour.

    `hint` is the feed's beat, passed to attribution as a tie-break only. The
    asset class stored on the item is whatever attribution actually resolved.
    """
    try:
        # `feedparser.parse` does blocking network I/O.
        feed = await asyncio.to_thread(feedparser.parse, url)
    except Exception as e:
        logger.error("%s RSS fetch error: %s", source, e)
        return []

    parsed = []
    for entry in feed.entries[:limit]:
        title = entry.get("title", "")
        if not title:
            continue
        # Koin Bülteni puts the body in `description`; the rest use `summary`.
        raw_summary = entry.get("summary") or entry.get("description") or ""
        parsed.append((entry, title, re.sub(r"<[^>]+>", "", raw_summary)))

    # Attribution is the slow step, so the feed's items go through it together
    # rather than one after another. The ceiling on how many actually run at
    # once lives in `symbol_detection_service`, which is where it belongs —
    # every source is being fetched concurrently too.
    attributions = await asyncio.gather(
        *(
            news_attribution.get_or_detect(generate_news_id(title, source), title, summary, hint)
            for _entry, title, summary in parsed
        ),
        return_exceptions=True,
    )

    items: List[NewsItem] = []
    for (entry, title, summary), attribution in zip(parsed, attributions):
        if isinstance(attribution, Exception):
            logger.error("%s attribution error for %r: %s", source, title[:60], attribution)
            continue

        items.append(
            NewsItem(
                id=generate_news_id(title, source),
                title=title,
                summary=summary[:200] + "..." if len(summary) > 200 else summary,
                source=source,
                published_at=parse_feed_date(entry),
                symbol=attribution.symbol,
                asset_type=attribution.asset_type,
                url=entry.get("link", ""),
            )
        )

    return items


TREE_OF_ALPHA_URL = "https://news.treeofalpha.com/api/news"
# Items pulled per refresh. The feed is fast-moving (exchange listings, protocol
# announcements, market-moving posts), so this is deliberately larger than the
# ten a slow RSS feed contributes.
TREE_OF_ALPHA_LIMIT = 40


async def _treeofalpha_symbol(entry: dict, title: str) -> Optional[str]:
    """
    The ticker Tree of Alpha already tagged on an item, if any.

    Pairs arrive as "POL_USDT" / "POL_BTC". The base is extracted and resolved
    through the same gate as every other candidate, so the exchange on the
    symbol is one that actually lists the pair — the tag says which coin, not
    where it trades.

    The tag is metadata rather than a guess, but it is produced by a tagger
    that makes the same mistakes a model does: "MEXC expands offerings with AI
    infrastructure" arrives tagged `AI_USDT`. Acronym tags therefore face the
    same cashtag test as a model's answer.

    Returns None when the item carries no usable tag, so the caller falls
    through to the normal detection path instead of guessing.
    """
    symbols = entry.get("symbols") or []
    if not isinstance(symbols, list):
        return None

    pairs = [s for s in symbols if isinstance(s, str) and "_" in s]
    if not pairs:
        return None

    preferred = next((p for p in pairs if p.endswith("_USDT")), pairs[0])
    base = preferred.split("_")[0].upper()
    if not base or is_uncashtagged_acronym(base, title):
        return None

    return await resolve_crypto(base)


async def fetch_treeofalpha_news() -> List[NewsItem]:
    """
    Fetch the Tree of Alpha aggregated feed.

    Tree of Alpha aggregates what actually moves crypto markets — exchange
    listing and delisting notices, protocol accounts, and the news desks' own
    posts — minutes before it reaches the RSS feeds. It also ships a `symbols`
    field on the items it can tag, which is a real exchange pair rather than a
    guess, so those items skip symbol detection entirely.
    """
    items: List[NewsItem] = []

    try:
        entries = await get_json(
            TREE_OF_ALPHA_URL, params={"limit": TREE_OF_ALPHA_LIMIT}, timeout=15.0
        )
    except Exception as e:
        logger.error("Tree of Alpha fetch error: %s", e)
        return items

    if not isinstance(entries, list):
        logger.error("Tree of Alpha returned %s, expected a list", type(entries).__name__)
        return items

    usable = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # `en` is the English rendering when the original is not; some items
        # carry only one of the two.
        title = entry.get("title") or entry.get("en") or ""
        if title:
            usable.append((entry, title))

    async def attribute(entry: dict, title: str) -> Attribution:
        """The item's asset: Tree of Alpha's own tag first, detection second."""
        symbol = await _treeofalpha_symbol(entry, title)
        if symbol:
            return Attribution(symbol, asset_type_for_symbol(symbol, "crypto"))
        return await news_attribution.get_or_detect(
            generate_news_id(title, "Tree of Alpha"),
            title,
            str(entry.get("info") or ""),
            "crypto",
        )

    attributions = await asyncio.gather(
        *(attribute(entry, title) for entry, title in usable), return_exceptions=True
    )

    for (entry, title), attribution in zip(usable, attributions):
        if isinstance(attribution, Exception):
            logger.error("Tree of Alpha attribution error for %r: %s", title[:60], attribution)
            continue

        # The originating desk or account ("COINDESK", "Upbit"), which is more
        # informative than labelling everything "Tree of Alpha".
        origin = entry.get("sourceName") or entry.get("source") or "Tree of Alpha"
        info = str(entry.get("info") or "")

        published_at = datetime.now()
        timestamp_ms = entry.get("time")
        if isinstance(timestamp_ms, (int, float)) and timestamp_ms > 0:
            published_at = datetime.fromtimestamp(timestamp_ms / 1000)

        items.append(
            NewsItem(
                id=generate_news_id(title, "Tree of Alpha"),
                title=title[:300],
                summary=info[:200] or title[:200],
                source=f"Tree of Alpha · {origin}",
                published_at=published_at,
                symbol=attribution.symbol,
                asset_type=attribution.asset_type,
                url=entry.get("url") or "",
            )
        )

    return items


async def fetch_all_news() -> List[NewsItem]:
    """
    Fetch news from all sources concurrently and combine results.
    """
    # (source name, coroutine) pairs - names are used for per-source logging.
    #
    # Several publishers are unreachable from some of the networks this runs on
    # — cointelegraph.com and koinbulteni.com reset the TLS connection outright,
    # the same way Binance does, which no client-side change can work around.
    # They stay in the list because they work elsewhere, and the sources beside
    # them cover the same ground where they do not: The Block and CryptoSlate
    # for global crypto, Uzmancoin for Turkish, and Tree of Alpha for the
    # exchange and protocol announcements that break before any of the desks
    # publish. A blocked source contributes nothing and is logged; it never
    # holds up the others.
    sources = [
        # Aggregated real-time feed
        ("Tree of Alpha", fetch_treeofalpha_news()),
        # Global crypto sources. No trailing slash on the CoinDesk URL: the
        # slash variant returns a 308 redirect feedparser will not follow.
        ("Decrypt", _fetch_rss("Decrypt", "https://decrypt.co/feed", "crypto", 15)),
        (
            "CoinDesk",
            _fetch_rss("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss", "crypto"),
        ),
        ("CoinTelegraph", _fetch_rss("CoinTelegraph", "https://cointelegraph.com/rss", "crypto")),
        ("The Block", _fetch_rss("The Block", "https://www.theblock.co/rss.xml", "crypto")),
        ("CryptoSlate", _fetch_rss("CryptoSlate", "https://cryptoslate.com/feed/", "crypto")),
        # Turkish crypto sources
        ("Koin Bülteni", _fetch_rss("Koin Bülteni", "https://koinbulteni.com/feed", "crypto")),
        ("Uzmancoin", _fetch_rss("Uzmancoin", "https://uzmancoin.com/feed/", "crypto")),
        # Global stock sources
        (
            "MarketWatch",
            _fetch_rss(
                "MarketWatch",
                "https://feeds.content.dowjones.io/public/rss/mw_topstories",
                "stock",
            ),
        ),
        (
            "Investing.com",
            _fetch_rss("Investing.com", "https://www.investing.com/rss/news.rss", "stock"),
        ),
        (
            "Seeking Alpha",
            _fetch_rss("Seeking Alpha", "https://seekingalpha.com/market_currents.xml", "stock"),
        ),
    ]

    # Fetch from all sources concurrently
    results = await asyncio.gather(*(coro for _, coro in sources), return_exceptions=True)

    all_items = []
    for (name, _), result in zip(sources, results):
        if isinstance(result, list):
            logger.info("News source %s: %d items", name, len(result))
            all_items.extend(result)
        else:
            logger.error("News source %s fetch error: %s", name, result)

    # Remove duplicates by title similarity
    seen_titles = set()
    unique_items = []
    for item in all_items:
        title_key = item.title.lower()[:50]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_items.append(item)

    # Sort by published date (newest first)
    unique_items.sort(key=lambda x: x.published_at, reverse=True)

    # Attribution buffers its writes; this is the end of the batch.
    await news_attribution.flush()

    return unique_items
