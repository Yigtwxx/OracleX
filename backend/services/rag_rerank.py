"""
Cross-encoder re-ranking of retrieved candidates.

Search — dense, lexical, or both — compares a query vector against document
vectors that were produced without ever seeing the query. That is what makes it
fast enough to run over a whole collection, and also what makes it approximate:
"what happened after regulators sued a crypto company" and a document about a
tariff ruling land close together because both are "finance, legal, negative".

A cross-encoder reads the query and one document *together* and scores the pair
directly. It is far too slow to run over a collection, which is why it runs last,
over the handful of candidates search has already narrowed to.

This does not replace `rag_scoring`. That module encodes something a general
reranker cannot know: that an event whose durable outcome contradicted its
headline is the most instructive precedent there is. So the cross-encoder decides
*relevance* and `rag_scoring` still applies importance, recency and the surprise
boost on top — see `rank_candidates`.

Disabled by setting `RAG_RERANK_MODEL` to an empty string, in which case
retrieval behaves exactly as it did before this module existed. The model is
loaded lazily on first use: it is a large download, and a deployment that never
retrieves should never pay for it.
"""

import logging
import math
import threading
from typing import List, Optional, Sequence, Tuple

from config import settings

logger = logging.getLogger(__name__)

_model = None
_load_failed = False
_lock = threading.Lock()


def enabled() -> bool:
    return bool((settings.RAG_RERANK_MODEL or "").strip()) and not _load_failed


def _get_model():
    """
    Load the cross-encoder once, on the best available device.

    Guarded by a lock because retrieval runs inside `asyncio.to_thread`: two
    concurrent chat turns would otherwise both see `_model is None` and load a
    multi-gigabyte model twice.
    """
    global _model, _load_failed
    if _model is not None or _load_failed:
        return _model

    with _lock:
        if _model is not None or _load_failed:
            return _model
        try:
            from sentence_transformers import CrossEncoder

            from services.rag_device import configure_torch_threads, pick_device

            configure_torch_threads()
            device = pick_device()
            name = settings.RAG_RERANK_MODEL
            logger.info("Loading cross-encoder reranker %s on %s", name, device)
            _model = CrossEncoder(name, device=device, max_length=512)
            logger.info("Cross-encoder reranker ready")
        except Exception as e:  # noqa: BLE001 — retrieval must survive this
            _load_failed = True
            logger.warning(
                "Cross-encoder reranker unavailable (%s): %s. "
                "Falling back to heuristic ranking only.",
                settings.RAG_RERANK_MODEL,
                e,
            )
    return _model


def _to_probabilities(raw: Sequence[float]) -> List[float]:
    """
    Normalise model output to [0, 1], applying a sigmoid only if one is needed.

    Whether a cross-encoder returns a probability or a raw logit depends on the
    model, and getting it wrong is silently destructive in one direction:
    bge-reranker-v2-m3 has a single output label, so sentence-transformers
    already applies a sigmoid, and squashing it a second time maps 0.146 and
    0.000063 — a 2300x ratio — onto 0.536 and 0.500, a 7% difference that cannot
    reorder anything. Detecting it from the values keeps a differently-configured
    reranker working without a second setting to get wrong.
    """
    values = [float(v) for v in raw]
    if all(0.0 <= v <= 1.0 for v in values):
        return values
    return [
        1.0 / (1.0 + math.exp(-v)) if v >= 0 else math.exp(v) / (1.0 + math.exp(v)) for v in values
    ]


def score(query: str, documents: Sequence[str]) -> Optional[List[float]]:
    """
    Score each document against the query, in [0, 1]. Higher is more relevant.

    Returns None when re-ranking is disabled or the model could not be loaded,
    which the caller must read as "keep the existing order" — not as "everything
    scored zero".
    """
    if not documents or not enabled():
        return None
    model = _get_model()
    if model is None:
        return None

    try:
        raw = model.predict(
            [(query, doc) for doc in documents],
            batch_size=16,
            show_progress_bar=False,
        )
    except Exception as e:  # noqa: BLE001 — a bad batch must not fail the turn
        logger.warning("Cross-encoder scoring failed: %s", e)
        return None

    return _to_probabilities(raw)


def rerank(
    query: str, candidates: Sequence[dict], *, text_key: str = "document"
) -> List[Tuple[dict, Optional[float]]]:
    """
    Order `candidates` by cross-encoder relevance, best first.

    Each result is paired with its score so the caller can combine it with the
    domain signals in `rag_scoring` rather than treating the reranker's opinion
    as final. When re-ranking is unavailable the input order is returned with
    `None` scores, so callers need no separate branch for the disabled case.
    """
    if not candidates:
        return []

    documents = [str(candidate.get(text_key) or "") for candidate in candidates]
    scores = score(query, documents)
    if scores is None:
        return [(candidate, None) for candidate in candidates]

    ranked = sorted(zip(candidates, scores), key=lambda pair: pair[1], reverse=True)
    return [(candidate, value) for candidate, value in ranked]


def warm_up() -> None:
    """Load the model at startup so the first query does not wait for it."""
    if not enabled():
        return
    if _get_model() is not None:
        try:
            score("warm up", ["warm up document"])
        except Exception as e:  # noqa: BLE001
            logger.debug("Reranker warm-up scoring failed: %s", e)
