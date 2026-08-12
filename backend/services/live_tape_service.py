"""
Headline tape.

The single-line wire feed that runs beside the Live tab's calendar and player.
It fetches nothing: the scheduler's `news_update_job` already refreshes every
source every two minutes, and this reads that cache. Polling the tape is
therefore free upstream, which is what lets the frontend poll it faster than
anything else on the page.

What it adds over the plain news feed is selection and tagging. The full feed
carries protocol upgrades and earnings previews alongside "Powell says the
committee is not on a preset course"; the tape wants only the second kind, and
wants it labelled so a row can be read at a glance.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from utils import get_news_cache

logger = logging.getLogger(__name__)

# Tag → the phrases that earn it. A headline can carry several; order here is
# the order they render in, so the most specific groups come first.
#
# These are matched against the headline and its summary, lowercased, as plain
# substrings. Deliberately not regex: the list is meant to be edited by whoever
# notices the tape missing something, and a bad regex fails less obviously than
# a phrase that simply never matches.
TAG_PHRASES: dict[str, tuple[str, ...]] = {
    "fed": (
        "powell",
        "fomc",
        "federal reserve",
        # "fed's Barkin", "Fed speaker", "the Fed said" — the bare word with a
        # trailing space or apostrophe is how wire copy actually refers to it,
        # and matching only the two-word titles missed most of the tape.
        "fed ",
        "fed'",
        "rate cut",
        "rate hike",
        "basis point",
        "beige book",
        "dot plot",
    ),
    "ecb": ("ecb", "lagarde", "european central bank", "eurozone rates"),
    "rates": ("rate decision", "interest rate", "monetary policy", "central bank", "yield curve"),
    "politics": (
        "trump",
        "white house",
        "president",
        "treasury secretary",
        "bessent",
        "executive order",
        "congress",
        "senate",
    ),
    "trade": ("tariff", "trade deal", "trade war", "export control", "sanction"),
    "inflation": ("cpi", "inflation", "ppi", "pce", "price index"),
    "jobs": ("payroll", "nonfarm", "jobless", "unemployment", "labor market"),
    "growth": ("gdp", "recession", "retail sales", "ism", "pmi"),
}


def _tags(text: str) -> list[str]:
    return [tag for tag, phrases in TAG_PHRASES.items() if any(p in text for p in phrases)]


def fetch_tape(limit: int = 50) -> dict[str, Any]:
    """
    The most recent market-moving headlines, newest first.

    An empty `items` list here is honest rather than an outage: the news cache
    is populated by a job that runs on its own schedule, and a quiet stretch
    with nothing macro in it is a real state the tab renders as such. The
    `warming` flag distinguishes that from the cache not being filled yet, which
    is the case the UI must not read as "nothing is happening".
    """
    cache = get_news_cache()
    if not cache:
        return {
            "items": [],
            "as_of": datetime.now(UTC).isoformat(),
            "warming": True,
        }

    items: list[dict[str, Any]] = []
    for news in cache.values():
        haystack = f"{news.title} {news.summary or ''}".lower()
        tags = _tags(haystack)
        if not tags:
            continue

        published_at = news.published_at
        if isinstance(published_at, datetime):
            # Feed dates arrive naive often enough that sorting them against
            # aware ones would raise partway through a quiet day.
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=UTC)
            published_iso = published_at.isoformat()
        else:
            published_iso = str(published_at)

        items.append(
            {
                "id": news.id,
                "text": news.title,
                "source": news.source,
                "published_at": published_iso,
                "url": news.url,
                "symbol": news.symbol,
                "tags": tags,
            }
        )

    items.sort(key=lambda item: item["published_at"], reverse=True)
    return {
        "items": items[:limit],
        "as_of": datetime.now(UTC).isoformat(),
        "warming": False,
    }
