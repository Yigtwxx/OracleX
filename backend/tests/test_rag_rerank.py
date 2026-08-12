"""
Cross-encoder re-ranking.

No model is loaded here — these cover the wiring around it, which is where the
one destructive bug lived: double-activating an output that was already a
probability. That failure is invisible (nothing errors, scores stay ordered) and
it silently removes the reranker's ability to reorder anything.
"""

import pytest

from services import rag_rerank
from services.rag_rerank import _to_probabilities, rerank


# ── Activation handling ─────────────────────────────────────────────────────


def test_probabilities_pass_through_untouched():
    """
    bge-reranker-v2-m3 has one output label, so sentence-transformers applies a
    sigmoid before we see the values. Applying another maps 0.146 and 0.000063 —
    a 2300x ratio, a decisive verdict — onto 0.536 and 0.500, which reorders
    nothing. Measured values from the real model.
    """
    assert _to_probabilities([0.146, 0.000063]) == pytest.approx([0.146, 0.000063])


def test_raw_logits_are_squashed():
    """A reranker that does not activate its own output must still work."""
    out = _to_probabilities([4.0, -4.0])
    assert out[0] == pytest.approx(0.982, abs=1e-3)
    assert out[1] == pytest.approx(0.018, abs=1e-3)
    assert all(0.0 <= v <= 1.0 for v in out)


def test_the_ordering_survives_either_activation_path():
    for raw in ([0.9, 0.1, 0.5], [6.0, -6.0, 0.0]):
        out = _to_probabilities(raw)
        assert sorted(range(3), key=lambda i: -out[i]) == sorted(range(3), key=lambda i: -raw[i])


def test_boundary_values_are_treated_as_probabilities():
    assert _to_probabilities([0.0, 1.0]) == [0.0, 1.0]


# ── Graceful degradation ────────────────────────────────────────────────────


def test_disabled_reranker_keeps_the_input_order(monkeypatch):
    """
    None means "keep the existing order", never "everything scored zero".

    Retrieval has to keep working when the model is absent — it is a large
    download and an offline deployment must degrade, not fail.
    """
    from config import settings

    monkeypatch.setattr(settings, "RAG_RERANK_MODEL", "")
    candidates = [{"document": "a"}, {"document": "b"}]
    assert rag_rerank.score("q", ["a", "b"]) is None
    assert [c for c, _ in rerank("q", candidates)] == candidates
    assert all(value is None for _, value in rerank("q", candidates))


def test_rerank_orders_by_score(monkeypatch):
    monkeypatch.setattr(rag_rerank, "score", lambda q, docs: [0.1, 0.9, 0.5])
    candidates = [{"document": "low"}, {"document": "high"}, {"document": "mid"}]
    ordered = [c["document"] for c, _ in rerank("q", candidates)]
    assert ordered == ["high", "mid", "low"]


def test_rerank_of_nothing_is_empty():
    assert rerank("q", []) == []


def test_scoring_failure_degrades_to_input_order(monkeypatch):
    """A bad batch must cost the re-ranking, not the whole chat turn."""

    class _Exploding:
        def predict(self, *args, **kwargs):
            raise RuntimeError("CUDA is having a day")

    monkeypatch.setattr(rag_rerank, "_get_model", lambda: _Exploding())
    monkeypatch.setattr(rag_rerank, "enabled", lambda: True)
    assert rag_rerank.score("q", ["a", "b"]) is None


# ── Score composition ───────────────────────────────────────────────────────


def test_final_score_multiplies_composite_by_rerank():
    """
    The cross-encoder corrects relevance; it does not overrule domain weighting.

    `importance` and the surprise boost encode which precedents are instructive —
    that an event whose outcome contradicted its headline teaches more than one
    that went as expected. No general reranker knows that, so its verdict scales
    the composite rather than replacing it.
    """
    from services.rag_scoring import HistoricalItem, ScoredItem

    item = HistoricalItem(doc_id="d", source="event", relevance=0.6)
    base = ScoredItem(item=item, relevance=0.6, importance=0.8, surprise=1.4, score=0.672)

    assert base.final_score == pytest.approx(0.672)

    from dataclasses import replace

    assert replace(base, rerank=0.5).final_score == pytest.approx(0.336)
    assert replace(base, rerank=0.0).final_score == pytest.approx(0.0)
