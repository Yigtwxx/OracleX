"""
Lexical retrieval and rank fusion — the other half of hybrid search.

Dense search was the only retrieval path here, and it is the wrong tool for a
large share of the questions this app gets. Embeddings encode meaning and
deliberately discard surface form, so "XRP" and "SOL" sit close together, "$104,230"
carries almost no signal at all, and a query naming a specific ticker, date or
regulator can rank a document that never mentions it above one that does.

BM25 is the opposite failure mode: it matches tokens exactly and understands
nothing. Neither is sufficient alone, which is why both run and their rankings
are fused.

Fusion is Reciprocal Rank Fusion, which combines *positions* rather than scores.
That matters because the two systems' scores are not comparable — a cosine of
0.62 and a BM25 score of 11.3 have no common unit, and normalising them invents
a relationship that isn't there. RRF only asks "how near the top did each system
put this document", which is a question both can answer.

The BM25 index is built from whatever the collection holds and cached until the
collection's size changes. Rebuilding is cheap at these volumes and the
alternative — a stale index that silently ignores everything indexed since
startup — is the failure that would be hardest to notice.
"""

import logging
import re
import threading
from typing import Dict, List, Optional, Sequence

from config import settings

logger = logging.getLogger(__name__)

# Tokenisation for the lexical index. Keeps digits, decimal points and the
# internal punctuation of things like "BTC-USD" or "4.25%" together, because
# those *are* the query terms that make lexical search worth running.
_TOKEN = re.compile(r"[A-Za-z]+|\d+(?:[.,]\d+)*")

_indexes: Dict[str, "_BM25Index"] = {}
_lock = threading.Lock()


def tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN.findall(text or "")]


class _BM25Index:
    """A BM25 index over one collection, tagged with the size it was built at."""

    def __init__(self, ids: List[str], documents: List[str], size: int) -> None:
        from rank_bm25 import BM25Okapi

        self.ids = ids
        self.size = size
        tokenized = [tokenize(doc) for doc in documents]
        # Kept alongside the index because membership and score answer different
        # questions — see `top`.
        self._token_sets = [set(tokens) for tokens in tokenized]
        self._bm25 = BM25Okapi(tokenized)

    def top(self, query: str, limit: int) -> List[str]:
        """
        Ids of the best lexical matches, best first.

        Membership decides who is eligible; BM25 only decides the order. Filtering
        on a positive score instead looks equivalent and is not: BM25's IDF term
        goes negative for a word carried by more than about half the collection,
        and on a small collection that is most words. A document that genuinely
        contains the query's rare term would then be dropped for scoring ≤ 0,
        which is precisely the hit hybrid search exists to contribute.
        """
        tokens = set(tokenize(query))
        if not tokens:
            return []
        scores = self._bm25.get_scores(list(tokens))
        eligible = [i for i, present in enumerate(self._token_sets) if tokens & present]
        eligible.sort(key=lambda i: scores[i], reverse=True)
        return [self.ids[i] for i in eligible[:limit]]


def _build(collection, name: str) -> Optional[_BM25Index]:
    try:
        size = collection.count()
        if size == 0:
            return None
        stored = collection.get(include=["documents"])
        ids = stored.get("ids") or []
        documents = stored.get("documents") or []
        if not ids or len(ids) != len(documents):
            return None
        index = _BM25Index(ids, documents, size)
        logger.info("Built BM25 index for '%s' over %d documents", name, size)
        return index
    except Exception as e:  # noqa: BLE001 — dense search must still work
        logger.warning("Could not build BM25 index for '%s': %s", name, e)
        return None


def lexical_ids(collection, name: str, query: str, limit: int) -> List[str]:
    """
    Best lexical matches in `collection`, best first. Empty if unavailable.

    An empty result is not an error — it is the honest answer when no query term
    appears anywhere in the collection, and the dense ranking then stands alone.
    """
    if not settings.RAG_HYBRID_SEARCH:
        return []

    with _lock:
        index = _indexes.get(name)
        try:
            current_size = collection.count()
        except Exception:  # noqa: BLE001
            return []
        if index is None or index.size != current_size:
            index = _build(collection, name)
            if index is None:
                return []
            _indexes[name] = index

    return index.top(query, limit)


def invalidate(name: Optional[str] = None) -> None:
    """Drop cached indexes after a write. Called by the indexers."""
    with _lock:
        if name is None:
            _indexes.clear()
        else:
            _indexes.pop(name, None)


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], *, k: Optional[int] = None, limit: int = 20
) -> List[str]:
    """
    Fuse several ranked id lists into one, best first.

    Each list contributes `1 / (k + rank)` per id, so a document ranked highly by
    one system still places well even if the other never returned it, while a
    document both systems liked outranks either system's favourite. `k` damps how
    much the very top positions dominate; 60 is the value from the original paper.
    """
    k = k if k is not None else settings.RAG_RRF_K
    scores: Dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda doc_id: scores[doc_id], reverse=True)[:limit]
