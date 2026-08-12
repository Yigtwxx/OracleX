"""
Lexical retrieval and rank fusion.

The claim these tests defend is that hybrid search finds documents dense search
structurally cannot: a query naming a specific ticker, figure or date. Embeddings
discard surface form on purpose, so "XRP" and "SOL" sit near each other and
"$104,230.55" carries almost no signal — which is exactly the sort of term a
market question is made of.
"""

import pytest

from services import rag_hybrid
from services.rag_hybrid import reciprocal_rank_fusion, tokenize


class _FakeCollection:
    """Enough of Chroma's surface for the lexical index to be built from."""

    def __init__(self, documents):
        self._ids = [f"doc-{i}" for i in range(len(documents))]
        self._documents = list(documents)

    def count(self):
        return len(self._ids)

    def get(self, include=None, ids=None):
        return {"ids": list(self._ids), "documents": list(self._documents)}

    def append(self, document):
        self._ids.append(f"doc-{len(self._ids)}")
        self._documents.append(document)


@pytest.fixture(autouse=True)
def _clear_index_cache():
    rag_hybrid.invalidate()
    yield
    rag_hybrid.invalidate()


# ── Tokenisation ────────────────────────────────────────────────────────────


def test_tokenizer_keeps_figures_intact():
    """
    A price is one term, not a pile of digits.

    Splitting "104,230.55" into "104", "230", "55" would match any document
    containing any of those numbers, which is every document.
    """
    tokens = tokenize("BTC-USD at $104,230.55, up 4.25%")
    assert "104,230.55" in tokens
    assert "4.25" in tokens
    assert "btc" in tokens and "usd" in tokens


def test_tokenizer_is_case_insensitive():
    assert tokenize("SEC Sues Ripple") == tokenize("sec sues ripple")


def test_tokenizer_handles_empty_input():
    assert tokenize("") == []
    assert tokenize(None) == []


# ── Lexical search ──────────────────────────────────────────────────────────


def test_finds_the_document_containing_the_rare_term():
    collection = _FakeCollection(
        [
            "Ethereum staking yields drift lower as validator count climbs.",
            "The SEC filed suit against Ripple Labs over XRP distributions.",
            "Bitcoin dominance holds above 58% while breadth narrows.",
        ]
    )
    hits = rag_hybrid.lexical_ids(collection, "news", "XRP lawsuit", limit=5)
    assert hits and hits[0] == "doc-1"


def test_returns_nothing_when_no_query_term_appears():
    """
    An empty result is the honest answer, not a failure.

    Padding the candidate pool with zero-scoring documents would have RRF reward
    them purely for being present in the lexical list.
    """
    collection = _FakeCollection(["Bitcoin dominance holds above 58%."])
    assert rag_hybrid.lexical_ids(collection, "news", "sourdough starter", limit=5) == []


def test_empty_collection_yields_no_hits():
    assert rag_hybrid.lexical_ids(_FakeCollection([]), "news", "BTC", limit=5) == []


def test_index_is_rebuilt_when_the_collection_grows():
    """
    A cached index that ignores everything indexed since startup is the failure
    that would be hardest to notice — search simply stops seeing new documents.
    """
    collection = _FakeCollection(["Bitcoin dominance holds above 58%."])
    assert rag_hybrid.lexical_ids(collection, "news", "Ripple", limit=5) == []

    collection.append("The SEC filed suit against Ripple Labs.")
    assert rag_hybrid.lexical_ids(collection, "news", "Ripple", limit=5) == ["doc-1"]


def test_invalidate_forces_a_rebuild():
    collection = _FakeCollection(["alpha beta"])
    rag_hybrid.lexical_ids(collection, "news", "alpha", limit=5)
    rag_hybrid.invalidate("news")
    assert rag_hybrid.lexical_ids(collection, "news", "alpha", limit=5) == ["doc-0"]


def test_disabled_hybrid_search_returns_nothing(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "RAG_HYBRID_SEARCH", False)
    collection = _FakeCollection(["The SEC filed suit against Ripple Labs."])
    assert rag_hybrid.lexical_ids(collection, "news", "Ripple", limit=5) == []


# ── Reciprocal rank fusion ──────────────────────────────────────────────────


def test_a_document_both_systems_rank_beats_either_favourite():
    """
    This is the whole point of fusing. Agreement between two independent
    retrieval strategies is stronger evidence than one strategy's top hit.
    """
    dense = ["a", "shared", "b"]
    lexical = ["c", "shared", "d"]
    assert reciprocal_rank_fusion([dense, lexical], limit=5)[0] == "shared"


def test_a_document_only_one_system_found_still_places():
    """Lexical-only hits are the reason hybrid search exists — they must survive."""
    fused = reciprocal_rank_fusion([["a", "b"], ["lexical-only"]], limit=5)
    assert "lexical-only" in fused


def test_fusion_respects_the_limit():
    assert len(reciprocal_rank_fusion([[str(i) for i in range(50)]], limit=7)) == 7


def test_fusion_of_a_single_ranking_preserves_its_order():
    assert reciprocal_rank_fusion([["a", "b", "c"]], limit=5) == ["a", "b", "c"]


def test_fusion_of_nothing_is_empty():
    assert reciprocal_rank_fusion([], limit=5) == []
    assert reciprocal_rank_fusion([[], []], limit=5) == []


def test_smaller_k_sharpens_the_advantage_of_rank_one():
    """`k` damps how much the very top positions dominate the fused order."""
    rankings = [["top"], ["second", "top"]]
    assert reciprocal_rank_fusion(rankings, k=1, limit=2)[0] == "top"
