#!/usr/bin/env python3
"""
Measure retrieval quality against a fixed answer key.

Nothing here measured retrieval before, so every change to the embedding model,
the relevance floors, hybrid search or the reranker was an act of faith. The
golden set is small and hand-written, which is enough to catch a regression and
enough to tell whether a change helped — and both of those were previously
impossible to know.

The flags are the point: the same set can be run with each stage disabled, so
"the reranker helps" is a measurement rather than a claim.

Usage:
    python evals/eval_retrieval.py                    # current configuration
    python evals/eval_retrieval.py --no-rerank        # isolate the reranker
    python evals/eval_retrieval.py --no-hybrid        # isolate lexical search
    python evals/eval_retrieval.py --compare          # run all three, side by side

Requires a populated store. Run scripts/reindex_embeddings.py first if the
embedding backend has changed.
"""

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings  # noqa: E402

GOLDEN_SET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_set.jsonl")
K = 5


def load_cases() -> List[Dict]:
    cases = []
    with open(GOLDEN_SET) as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _retrieve(case: Dict) -> List[str]:
    """Ordered doc ids the pipeline returns for one case."""
    from services.rag_v2_service import query_historical_context

    result = query_historical_context(
        case["query"],
        symbol=case.get("symbol"),
        include_prices=False,
        include_news=False,
        k=K,
        asset_type=case.get("asset_type"),
    )
    return [event.get("doc_id", "") for event in result["events"]]


def evaluate(cases: List[Dict], *, verbose: bool = False) -> Dict[str, float]:
    """
    Recall@K, MRR and false-positive rate over the golden set.

    Cases expecting nothing are scored separately: for those the only question is
    whether the relevance floor held, and averaging that into recall would let a
    pipeline that retrieves nothing at all look respectable.
    """
    recalls: List[float] = []
    reciprocal_ranks: List[float] = []
    false_positives = 0
    control_cases = 0
    misses: List[str] = []

    for case in cases:
        retrieved = _retrieve(case)
        expected = set(case.get("expect_events") or [])

        if not expected:
            control_cases += 1
            if retrieved:
                false_positives += 1
                if verbose:
                    print(f"  [noise] {case['id']}: returned {len(retrieved)} for a control query")
            continue

        hits = expected & set(retrieved[:K])
        recall = len(hits) / len(expected)
        recalls.append(recall)

        rank = next((i for i, doc in enumerate(retrieved) if doc in expected), None)
        reciprocal_ranks.append(1.0 / (rank + 1) if rank is not None else 0.0)

        if recall < 1.0:
            missed = expected - set(retrieved[:K])
            misses.append(f"{case['id']} (missed {len(missed)}/{len(expected)})")
            if verbose:
                print(f"  [miss]  {case['id']}: {sorted(missed)}")
                print(f"          got: {retrieved}")

    return {
        "cases": len(recalls),
        "recall@k": sum(recalls) / len(recalls) if recalls else 0.0,
        "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0,
        "perfect": sum(1 for r in recalls if r == 1.0),
        "controls": control_cases,
        "false_positives": false_positives,
        "misses": misses,
    }


def _report(label: str, metrics: Dict) -> None:
    print(f"\n── {label} ───────────────────────────────────")
    print(f"  recall@{K}       {metrics['recall@k']:.3f}")
    print(f"  MRR             {metrics['mrr']:.3f}")
    print(f"  perfect recall  {metrics['perfect']}/{metrics['cases']} cases")
    print(
        f"  control leaks   {metrics['false_positives']}/{metrics['controls']} "
        "(off-topic queries that returned anything)"
    )
    if metrics["misses"]:
        print(f"  incomplete      {', '.join(metrics['misses'])}")


def _configure(rerank: bool, hybrid: bool, rerank_model: Optional[str]) -> None:
    settings.RAG_RERANK_MODEL = rerank_model if rerank else ""
    settings.RAG_HYBRID_SEARCH = hybrid


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-rerank", action="store_true", help="disable the cross-encoder")
    parser.add_argument("--no-hybrid", action="store_true", help="disable lexical search")
    parser.add_argument("--compare", action="store_true", help="run every combination")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every miss")
    args = parser.parse_args()

    cases = load_cases()
    rerank_model = settings.RAG_RERANK_MODEL
    print(f"Golden set: {len(cases)} cases, k={K}")
    print(f"Embedding : {settings.RAG_EMBEDDING_BACKEND} / {settings.RAG_EMBEDDING_MODEL}")

    if args.compare:
        for label, rerank, hybrid in (
            ("dense only", False, False),
            ("dense + hybrid", False, True),
            ("dense + hybrid + rerank", True, True),
        ):
            _configure(rerank, hybrid, rerank_model)
            _report(label, evaluate(cases, verbose=args.verbose))
        print(
            "\nEach row adds one stage. A stage that does not move recall or MRR is\n"
            "not earning its latency."
        )
    else:
        _configure(not args.no_rerank, not args.no_hybrid, rerank_model)
        label = (
            f"rerank={'off' if args.no_rerank else 'on'}, "
            f"hybrid={'off' if args.no_hybrid else 'on'}"
        )
        _report(label, evaluate(cases, verbose=args.verbose))

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
