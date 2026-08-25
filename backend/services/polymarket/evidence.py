"""
Gathering what is known about a market, and counting honestly what came back.

Four sources, run concurrently: dated news search, general web search, the
category's own wires, and this application's RAG memory. Everything they return
is normalised into one ranked ledger of `SourceRef`s, and the best of them are
read in full.

**Partial results survive.** The whole sweep runs under one `asyncio.wait`, and
whatever has landed by the deadline is kept. The obvious alternative — a
`gather` inside a `wait_for` — cancels every child the moment the deadline
passes, so four completed searches and one slow feed produce nothing at all.
That is survivable in `news_analysis_service`, where a missing gather is a
thinner note; here it is fatal, because the sufficiency rule exists precisely to
judge a partial set. An unfinished task is recorded as a timeout attempt and the
floors are applied to what did arrive.

**Every attempt is recorded, including the empty ones.** A query that returned
nothing is the most informative thing a refusal can say — it is the difference
between "nobody is covering this" and "we could not reach anything". Silence
about a failed query would make those two look the same.

Tiering is done here in Python and never asked of the model. A model asked to
rate its own sources will rate them by how well they support the answer it is
forming.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from models.polymarket import EvidenceCoverage, SourceRef, SweepAttempt
from services.polymarket.attribution import EvidenceLedger
from services.polymarket.registry import CategoryStrategy

logger = logging.getLogger(__name__)

SWEEP_BUDGET_SECONDS = 75.0
SEARCH_TIMEOUT = 10.0
SEARCH_CONCURRENCY = 4
SCRAPE_CONCURRENCY = 3
SCRAPE_BUDGET_SECONDS = 12.0

#: Shortest body that counts as having read an article rather than a stub.
TIER1_MIN_BODY = 400

#: Ceiling per body before the prompt budget sees it. Clipped here rather than
#: in `prompt_budget.fit` so that trimming drops whole low-ranked sources off the
#: end of a list instead of gutting one enormous block at the top of it.
BODY_CLIP_CHARS = 2500


def _domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _parse_date(value: Any) -> datetime | None:
    """
    A publication date, or None when the upstream gave something unusable.

    ddgs occasionally returns prose in the date field — "Opinion51 minute" has
    been seen in production. None is the honest answer, and an undated source is
    barred from being named as a trigger for a price move.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class Sweep:
    """One market's evidence gathering, and the record of what it tried."""

    def __init__(self, strategy: CategoryStrategy) -> None:
        self.strategy = strategy
        self.ledger = EvidenceLedger()
        self.attempts: list[SweepAttempt] = []
        self._by_url: dict[str, dict[str, Any]] = {}

    # ── collection ────────────────────────────────────────────────────────

    def _absorb(self, hits: list[dict[str, Any]], via: str) -> int:
        """Merge hits into the pool, deduplicating on URL. Returns new count."""
        added = 0
        for hit in hits:
            url = (hit.get("url") or "").strip()
            if not url or url in self._by_url:
                continue
            self._by_url[url] = {
                "url": url,
                "title": (hit.get("title") or "").strip(),
                "snippet": (hit.get("snippet") or "").strip(),
                "published_at": hit.get("published_at"),
                "via": via,
                "domain": _domain(url),
            }
            added += 1
        return added

    def record(
        self, kind: str, target: str, outcome: str, hits: int = 0, detail: str | None = None
    ) -> None:
        self.attempts.append(
            SweepAttempt(kind=kind, target=target, outcome=outcome, hits=hits, detail=detail)
        )

    # ── ranking and reading ───────────────────────────────────────────────

    def _rank(self) -> list[dict[str, Any]]:
        """
        Best first: allowlisted outlets, then dated items, then the rest.

        Ranking decides which pages get read in full, and a scrape is the most
        expensive thing in the sweep. Spending them on the outlets that publish
        corrections is the point of keeping the allowlist.
        """
        preferred = self.strategy.preferred_domains

        def key(item: dict[str, Any]) -> tuple[int, int]:
            return (
                0 if item["domain"] in preferred else 1,
                0 if item.get("published_at") else 1,
            )

        return sorted(self._by_url.values(), key=key)

    async def read_bodies(self, limit: int) -> None:
        """Scrape the top-ranked pages, recording each attempt."""
        from services.scrape_service import scrape

        semaphore = asyncio.Semaphore(SCRAPE_CONCURRENCY)
        targets = self._rank()[:limit]

        async def one(item: dict[str, Any]) -> None:
            async with semaphore:
                try:
                    # Never a browser. The browser rung is restricted to hosts
                    # like x.com and reddit.com, where it spends fifteen seconds
                    # of a seventy-five second budget to arrive at a login wall —
                    # from sources that could not carry a verdict anyway.
                    result = await scrape(
                        item["url"], budget=SCRAPE_BUDGET_SECONDS, allow_browser=False
                    )
                except Exception as error:  # noqa: BLE001
                    self.record("scrape", item["domain"], "error", detail=str(error)[:120])
                    return

            page = result.page
            if page is None:
                self.record("scrape", item["domain"], "empty", detail=result.reason[:120] or None)
                return
            item["body"] = page.text[:BODY_CLIP_CHARS]
            self.record("scrape", item["domain"], "hits", hits=1)

        await asyncio.gather(*(one(item) for item in targets), return_exceptions=True)

    # ── output ────────────────────────────────────────────────────────────

    def _tier(self, item: dict[str, Any]) -> int:
        body = len(item.get("body") or "")
        allowlisted = item["domain"] in self.strategy.preferred_domains
        if allowlisted and body >= TIER1_MIN_BODY:
            return 1
        if allowlisted or body:
            return 2
        return 3

    def finish(self) -> tuple[EvidenceLedger, EvidenceCoverage]:
        """Freeze the pool into an id-addressed ledger and count the coverage."""
        for index, item in enumerate(self._rank(), start=1):
            tier = self._tier(item)
            # RAG hits are capped at tier 2 whatever their domain: they are this
            # application's own earlier output, not an independent newsroom, and
            # letting them satisfy corroboration would let the system cite itself
            # into confidence.
            if item["via"] == "rag":
                tier = max(tier, 2)
            self.ledger.add(
                SourceRef(
                    id=f"S{index}",
                    url=item["url"],
                    domain=item["domain"],
                    title=item["title"][:200],
                    published_at=_parse_date(item.get("published_at")),
                    tier=tier,
                    via=item["via"],
                    body_chars=len(item.get("body") or ""),
                )
            )

        searches = [a for a in self.attempts if a.kind in ("search", "news")]
        coverage = EvidenceCoverage(
            attempted=self.attempts,
            total_sources=len(self.ledger.sources),
            distinct_domains=len({s.domain for s in self.ledger.sources}),
            tier1_sources=sum(1 for s in self.ledger.sources if s.tier == 1),
            body_chars=sum(s.body_chars for s in self.ledger.sources),
            queries_answered=sum(1 for a in searches if a.outcome == "hits"),
            queries_issued=len(searches),
        )
        return self.ledger, coverage

    def body_for(self, source_id: str) -> str:
        ref = self.ledger.by_id(source_id)
        if ref is None:
            return ""
        return (self._by_url.get(ref.url) or {}).get("body") or ""

    def snippet_for(self, source_id: str) -> str:
        ref = self.ledger.by_id(source_id)
        if ref is None:
            return ""
        return (self._by_url.get(ref.url) or {}).get("snippet") or ""


def _window_for(published: datetime | None) -> str | None:
    """Recency window a search should use, from how old the target period is."""
    if published is None:
        return None
    from datetime import UTC

    age_days = (datetime.now(UTC) - published).days
    if age_days <= 2:
        return "d"
    if age_days <= 8:
        return "w"
    if age_days <= 32:
        return "m"
    return "y"


#: Move dates turned into queries. Two, because the third-largest move on a
#: market is usually the same story as the second and the searches are the
#: slowest thing in the sweep.
MAX_MOVE_QUERIES = 2


async def run_sweep(
    subject: str,
    strategy: CategoryStrategy,
    *,
    year: str,
    rag_query: str | None = None,
    move_dates: list[datetime] | None = None,
    budget: float = SWEEP_BUDGET_SECONDS,
) -> Sweep:
    """
    Gather evidence about `subject`. Never raises; a dead source is a gap.

    Returns a `Sweep` whose `finish()` produces the ledger and the coverage the
    sufficiency rule is applied to.

    `move_dates` are the days this market re-priced on. They are searched by
    calendar date because the category's own query templates return the same
    broad coverage every time, and the day the crowd changed its mind is the one
    day a story about this question is most likely to exist.
    """
    from services.web_search_service import search_news, search_web

    sweep = Sweep(strategy)
    semaphore = asyncio.Semaphore(SEARCH_CONCURRENCY)

    async def run_search(query: str, kind: str) -> None:
        async with semaphore:
            fn = search_news if kind == "news" else search_web
            hits = await fn(query, max_results=6, timeout=SEARCH_TIMEOUT)
        added = sweep._absorb(hits, kind)
        sweep.record(kind, query, "hits" if hits else "empty", hits=added)

    async def run_feed(name: str, url: str) -> None:
        from services.polymarket import feeds

        try:
            items = await feeds.fetch_feed(url)
        except TimeoutError:
            sweep.record("feed", name, "timeout")
            return
        added = sweep._absorb(items, "feed")
        sweep.record("feed", name, "hits" if items else "empty", hits=added)

    async def run_rag() -> None:
        from services import rag_v2_service

        try:
            # Synchronous: embedding, a Chroma query and a cross-encoder rerank.
            # On the event loop it blocks every other request in the process for
            # seconds — the mistake rag_v2_service documents against itself.
            context = await asyncio.to_thread(
                functools.partial(
                    rag_v2_service.query_historical_context,
                    rag_query or subject,
                    # Keyword, not positional: the second positional parameter
                    # is `symbol`, and a category key like "crypto" passed there
                    # silently filters the whole retrieval to a ticker that does
                    # not exist.
                    asset_type=strategy.rag_asset_type,
                )
            )
        except Exception as error:  # noqa: BLE001
            sweep.record("rag", "memory", "error", detail=str(error)[:120])
            return
        hits = _rag_hits(context)
        added = sweep._absorb(hits, "rag")
        sweep.record("rag", "memory", "hits" if hits else "empty", hits=added)

    tasks: list[asyncio.Task] = []
    for template in strategy.query_templates:
        query = template.format(subject=subject, year=year).strip()
        tasks.append(asyncio.create_task(run_search(query, "news")))
    tasks.append(asyncio.create_task(run_search(f"{subject} {year}".strip(), "search")))
    for when in (move_dates or [])[:MAX_MOVE_QUERIES]:
        tasks.append(asyncio.create_task(run_search(f"{subject} {when:%B %-d %Y}", "news")))
    for name, url in strategy.feeds:
        tasks.append(asyncio.create_task(run_feed(name, url)))
    if strategy.rag_enabled:
        tasks.append(asyncio.create_task(run_rag()))

    _done, pending = await asyncio.wait(tasks, timeout=budget)
    for task in pending:
        task.cancel()
    if pending:
        sweep.record("search", f"{len(pending)} sources", "timeout")

    await sweep.read_bodies(strategy.scrape_budget)
    return sweep


def _rag_hits(context: Any) -> list[dict[str, Any]]:
    """
    Normalise the RAG layer's return into search-hit shape.

    It comes back as `{"events": [...], "news": [...], "prices": [...]}`, so the
    buckets are flattened rather than indexed by name — which bucket a precedent
    landed in says nothing the sweep acts on, and naming them here would break
    silently the next time a collection is added.
    """
    if isinstance(context, dict):
        rows = [row for bucket in context.values() if isinstance(bucket, list) for row in bucket]
    elif isinstance(context, list):
        rows = context
    else:
        rows = []

    hits: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = (row.get("url") or row.get("source_url") or "").strip()
        if not url:
            continue
        hits.append(
            {
                "url": url,
                "title": row.get("title") or "",
                "snippet": (row.get("summary") or row.get("text") or "")[:600],
                "published_at": row.get("published_at") or row.get("date"),
            }
        )
    return hits
