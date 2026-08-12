#!/usr/bin/env python
"""
Measure what relevance actually looks like in this store, so the floor is chosen
from data instead of guessed.

`RAG_MIN_RELEVANCE` decides which retrieved history reaches the model. Set too
low it admits noise — the failure this whole change exists to fix, where an
off-topic sentence scored above the threshold three call sites used. Set too high
it silently answers "no precedent" to questions that have one.

The number cannot be reasoned out in the abstract because it depends on what the
collections contain. Event documents are short synthetic sentences, news
documents are headlines, and price rows are generated prose; the same question
scores differently against each. So this runs on-topic and deliberately
off-topic probes against every collection and prints the two distributions. A
usable floor sits above the off-topic ceiling and below the on-topic floor. Where
those overlap, no single threshold works and the gap is worth knowing about.

Read-only: it queries the store and prints. Nothing is written.

    cd backend && ./venv/bin/python ../scripts/calibrate_rag_relevance.py
"""

import os
import sys

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
sys.path.insert(0, os.path.abspath(BACKEND))

from config import settings  # noqa: E402
from services.rag_scoring import (  # noqa: E402
    SOURCE_EVENT,
    SOURCE_NEWS,
    SOURCE_PRICE,
    iter_chroma_hits,
    relevance_from_distance,
)
from services.rag_v2_service import (  # noqa: E402
    EVENTS_COLLECTION,
    NEWS_COLLECTION,
    PRICE_COLLECTION,
    generate_embedding,
    get_collection,
)

# Questions the store should be able to answer.
ON_TOPIC = [
    "SEC lawsuit against a crypto project",
    "bitcoin halving and what followed it",
    "an exchange collapsing and the contagion after it",
    "Nvidia earnings and AI chip demand",
    "tariffs on imported semiconductors",
    "a spot ETF being approved",
    "banking crisis and its effect on risk assets",
]

# Questions it should not. The sourdough control is the measured case from the
# original bug report: under `1 / (1 + distance)` it scored 0.316 against
# "Bitcoin Halving 2024", clearing the 0.30 threshold that was in use.
OFF_TOPIC = [
    "how do I bake sourdough bread at home",
    "best hiking trails near Ankara in spring",
    "how to fix a leaking kitchen tap",
    "recipe for slow cooked lamb",
    "what time does the museum open on Sunday",
]

COLLECTIONS = [
    (EVENTS_COLLECTION, SOURCE_EVENT),
    (NEWS_COLLECTION, SOURCE_NEWS),
    (PRICE_COLLECTION, SOURCE_PRICE),
]


# The v1 store lives in its own Chroma directory and is the one the news
# analysis path actually reads, so it is probed too — a floor tuned only against
# the curated events would not describe it.
def _v1_collection():
    from services.rag_service import get_chroma_collection

    return get_chroma_collection()


TOP_K = 5


def best_relevances(collection, probes, k=TOP_K):
    """The top relevance each probe achieves against a collection."""
    scores = []
    for probe in probes:
        response = collection.query(
            query_embeddings=[generate_embedding(probe)],
            n_results=min(k, collection.count()),
            include=["metadatas", "distances"],
        )
        best = 0.0
        for _doc_id, _meta, distance in iter_chroma_hits(response):
            best = max(best, relevance_from_distance(distance))
        scores.append((probe, best))
    return scores


def summarise(label, scores):
    values = [value for _probe, value in scores]
    if not values:
        print(f"  {label}: no probes")
        return None, None

    low, high = min(values), max(values)
    mean = sum(values) / len(values)
    print(f"  {label}: min {low:.3f}  mean {mean:.3f}  max {high:.3f}")
    for probe, value in sorted(scores, key=lambda pair: -pair[1]):
        print(f"      {value:.3f}  {probe}")
    return low, high


def main():
    print(f"Current RAG_MIN_RELEVANCE = {settings.RAG_MIN_RELEVANCE}")
    print("Relevance is a true cosine: 1.0 identical, 0.0 unrelated.\n")

    probes = [(name, get_collection(name)) for name, _source in COLLECTIONS]
    try:
        probes.append(("financial_news (v1)", _v1_collection()))
    except Exception as e:  # pragma: no cover - diagnostic script
        print(f"  (v1 store unavailable: {e})\n")

    for name, collection in probes:
        count = collection.count()
        print(f"── {name} ({count} items) " + "─" * max(0, 46 - len(name)))

        if count == 0:
            print("  empty — nothing to calibrate against\n")
            continue

        on_low, _on_high = summarise("on-topic ", best_relevances(collection, ON_TOPIC))
        _off_low, off_high = summarise("off-topic", best_relevances(collection, OFF_TOPIC))

        if on_low is None or off_high is None:
            print()
            continue

        print()
        if off_high < on_low:
            midpoint = (off_high + on_low) / 2
            print(
                f"  → separable. Any floor in ({off_high:.3f}, {on_low:.3f}) works; "
                f"midpoint {midpoint:.3f}."
            )
        else:
            print(
                f"  → overlapping: the worst on-topic probe ({on_low:.3f}) scores below "
                f"the best off-topic one ({off_high:.3f})."
            )
            print(
                "     No single floor separates them. A floor at "
                f"{off_high:.3f} keeps noise out at the cost of the weakest real matches."
            )
        print()

    print(
        "Set RAG_MIN_RELEVANCE from the collection that matters most for your use.\n"
        "Per-collection floors are worth adding if these ranges disagree sharply."
    )


if __name__ == "__main__":
    main()
