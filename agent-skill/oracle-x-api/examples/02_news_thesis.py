#!/usr/bin/env python3
"""Turn a headline into something with a precedent attached.

The shape worth copying is the cache check. News analysis is generated once and
stored, so the common path is a single GET. Starting a job for an article that
was already analysed spends the operator's own LLM budget to reproduce a result
they already have — which is why the job call only happens after the cached
read misses.

    python 02_news_thesis.py            # newest crypto item
    python 02_news_thesis.py <news_id>
"""

from __future__ import annotations

import sys
import time
from typing import Any

from client import NotFound, OracleXError, get, post

POLL_INTERVAL_SECONDS = 3.0
POLL_TIMEOUT_SECONDS = 180.0


def latest_news_id(asset_type: str = "crypto") -> str:
    items = get("/api/news", {"limit": 5, "asset_type": asset_type})
    rows = items.get("news", items) if isinstance(items, dict) else items
    if not rows:
        raise OracleXError(
            "The news cache is empty. The scheduler may not have run yet — "
            "check /api/system/health."
        )
    return str(rows[0].get("id") or rows[0].get("news_id"))


def analysis_for(news_id: str) -> dict[str, Any]:
    """Return the LLM read of one article, generating it only if needed."""
    try:
        return get(f"/api/news/{news_id}/analysis")
    except NotFound:
        pass  # Nothing cached — fall through and generate it.

    job = post(f"/api/news/{news_id}/analysis/jobs")
    job_id = job.get("job_id") or job.get("id")
    if not job_id:
        raise OracleXError(f"Analysis job did not return an id: {job}")

    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)
        state = get(f"/api/news/analysis/jobs/{job_id}")
        status = state.get("status")
        if status in {"completed", "done", "finished"}:
            return state.get("result") or state
        if status in {"failed", "error", "cancelled"}:
            raise OracleXError(f"Analysis failed: {state.get('error', status)}")

    raise OracleXError(
        f"Analysis for {news_id} did not finish within "
        f"{POLL_TIMEOUT_SECONDS:.0f}s. It may still complete — poll "
        f"/api/news/analysis/jobs/{job_id} again later."
    )


def precedent(headline: str) -> Any:
    """Ask the store whether this story has run before.

    This is the step that separates a summary from a thesis. A regulatory
    headline resembling four earlier ones, each followed by a drawdown, is a
    different object from one with no precedent — and the answer only exists
    inside this instance's own memory.
    """
    return post("/api/rag/news-similarity", {"text": headline})


def main() -> int:
    news_id = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        news_id = news_id or latest_news_id()
        article = get(f"/api/news/{news_id}")
        headline = article.get("title", "")
        print(f"# {headline}\n")

        analysis = analysis_for(news_id)
        print("## Analysis")
        print(analysis.get("summary") or analysis.get("analysis") or analysis)

        print("\n## Precedent")
        similar = precedent(headline)
        matches = similar.get("results", similar) if isinstance(similar, dict) else []
        if not matches:
            print("Nothing in the store resembles this. Treat it as unprecedented.")
        for match in matches[:5]:
            print(f"- {match.get('title', match)}")
    except OracleXError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
