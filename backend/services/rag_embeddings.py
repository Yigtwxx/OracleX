"""
The embedding backend for both RAG stores.

Retrieval quality is bounded by the embedding model before any re-ranking gets a
chance to help, and `all-MiniLM-L6-v2` was the binding constraint here: 384
dimensions, English-only, and — measured against this project's own collections
by `scripts/calibrate_rag_relevance.py` — a gap of only ~0.04 between the best
off-topic probe (0.220) and the worst on-topic one (0.260). A floor that narrow
cannot separate "finance but irrelevant" from "finance and relevant", which is
most of the job.

`qwen3-embedding:0.6b` runs through the local Ollama daemon that already serves
the chat model, so it costs no new runtime and no API key. Measured on the same
probes: 0.75 on-topic against 0.36 off-topic. It is also multilingual, which the
old model was not — a Turkish question previously embedded almost at random.

Two things callers must respect:

* **Queries and documents are embedded differently.** Qwen3-Embedding is
  instruction-aware: a query carries a task prefix, a document does not.
  Measured on a Turkish query against a four-document set, the prefix widened
  the gap between the right document and an unrelated one from +0.37 to +0.54.
  Use `embed_query` for questions and `embed_documents` for stored text; using
  one where the other belongs quietly degrades every result.
* **Changing the backend invalidates the stores.** Dimensions differ (1024 vs
  384) and so does the geometry, so vectors from two backends are not
  comparable. `assert_store_compatible` turns that into a clear error at startup
  instead of nonsense rankings at query time.

Vectors come back L2-normalised, which is what lets `rag_scoring` keep reading
Chroma's squared-L2 distance as a cosine (`1 - d/2`). Anything added here must
preserve that.
"""

import logging
from typing import List, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Ollama's batch embedding endpoint. The older /api/embeddings takes one string
# at a time and is not worth the round trips.
_EMBED_PATH = "/api/embed"

# How many texts go in one request. Indexing sends thousands of chunks; one
# request per chunk wastes the daemon's batching, and one request for all of
# them builds a payload large enough to time out.
_BATCH_SIZE = 64

_EMBED_TIMEOUT = 120.0

# The task description Qwen3-Embedding is asked to condition the query on. It
# describes the retrieval job, not the question — it is constant across queries.
_QUERY_TASK = (
    "Given a market question, retrieve historical events, price moves and news "
    "that inform the answer"
)

# Known output widths, used to catch a store built by a different backend before
# it produces silently wrong neighbours.
_DIMENSIONS = {
    "ollama": 1024,  # qwen3-embedding:0.6b
    "minilm": 384,  # all-MiniLM-L6-v2
}

_MINILM_MODEL = "all-MiniLM-L6-v2"

_minilm = None


def backend() -> str:
    """Which embedding backend is configured. `ollama` or `minilm`."""
    configured = (settings.RAG_EMBEDDING_BACKEND or "ollama").strip().lower()
    if configured not in _DIMENSIONS:
        logger.warning("Unknown RAG_EMBEDDING_BACKEND %r — falling back to 'ollama'", configured)
        return "ollama"
    return configured


def model_id() -> str:
    """The model actually doing the embedding, for logs and store fingerprints."""
    return settings.RAG_EMBEDDING_MODEL if backend() == "ollama" else _MINILM_MODEL


def dimension() -> int:
    """Width of the vectors this backend produces."""
    return _DIMENSIONS[backend()]


# ═══════════════════════════════════════════════════════════════════════════════
# BACKENDS
# ═══════════════════════════════════════════════════════════════════════════════


def _embed_ollama(texts: List[str]) -> List[List[float]]:
    """Embed via the local Ollama daemon, in batches."""
    vectors: List[List[float]] = []
    url = f"{settings.OLLAMA_BASE_URL}{_EMBED_PATH}"

    with httpx.Client(timeout=_EMBED_TIMEOUT) as client:
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[start : start + _BATCH_SIZE]
            try:
                response = client.post(
                    url,
                    json={
                        "model": settings.RAG_EMBEDDING_MODEL,
                        "input": batch,
                        # Without this Ollama allocates its default window for the
                        # embedding model too, and the KV cache for a 32k context
                        # costs 5.8 GB of unified memory to embed a headline —
                        # more than four times the model itself. Nothing sent here
                        # is long: chunks are capped at RAG_CHUNK_TOKENS and the
                        # rest are headlines and one-line event descriptions.
                        # Measured on an M4 Pro: 5.8 GB at 32k, 1.4 GB at 1k.
                        "options": {"num_ctx": settings.RAG_EMBEDDING_NUM_CTX},
                    },
                )
            except httpx.ConnectError as e:
                raise RuntimeError(
                    f"Ollama is not reachable at {settings.OLLAMA_BASE_URL} — "
                    "is `ollama serve` running?"
                ) from e

            if response.status_code == 404:
                raise RuntimeError(
                    f"Embedding model '{settings.RAG_EMBEDDING_MODEL}' is not "
                    f"installed. Run: ollama pull {settings.RAG_EMBEDDING_MODEL}"
                )
            response.raise_for_status()

            batch_vectors = response.json().get("embeddings")
            if not batch_vectors or len(batch_vectors) != len(batch):
                raise RuntimeError(
                    f"Ollama returned {len(batch_vectors or [])} embeddings for "
                    f"{len(batch)} inputs — refusing to index a misaligned batch"
                )
            vectors.extend(batch_vectors)

    return vectors


def _embed_minilm(texts: List[str]) -> List[List[float]]:
    """The previous backend, kept so RAG_EMBEDDING_BACKEND=minilm still works."""
    global _minilm
    if _minilm is None:
        from sentence_transformers import SentenceTransformer

        from services.rag_device import configure_torch_threads, pick_device

        configure_torch_threads()
        device = pick_device()
        logger.info("Loading %s on %s", _MINILM_MODEL, device)
        _minilm = SentenceTransformer(_MINILM_MODEL, device=device)

    return _minilm.encode(texts, convert_to_numpy=True, normalize_embeddings=True).tolist()


def _embed(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    return _embed_ollama(texts) if backend() == "ollama" else _embed_minilm(texts)


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════


def embed_documents(texts: List[str]) -> List[List[float]]:
    """Embed stored text. No task prefix — documents are indexed as they are."""
    return _embed(texts)


def embed_document(text: str) -> List[float]:
    """Single-document convenience wrapper."""
    return _embed([text])[0]


def embed_query(text: str) -> List[float]:
    """
    Embed a question, conditioned on the retrieval task.

    The prefix is what makes the model rank by "would this document answer the
    question" rather than by surface similarity. On the `minilm` backend there is
    no instruction support, so the prefix would just be noise in the input and is
    skipped.
    """
    if backend() != "ollama":
        return _embed([text])[0]
    return _embed([f"Instruct: {_QUERY_TASK}\nQuery: {text}"])[0]


def warm_up() -> None:
    """
    Load the model before the first real query pays for it.

    Called from the startup path. Failure is logged, not raised: an embedding
    model that will not load should degrade retrieval, not stop the server from
    serving prices.
    """
    try:
        embed_query("warm up")
        logger.info("Embedding backend ready: %s (%s, %d-dim)", backend(), model_id(), dimension())
    except Exception as e:  # noqa: BLE001 — startup must not depend on this
        logger.warning("Embedding warm-up failed (%s): %s", model_id(), e)


def assert_store_compatible(collection, label: str) -> Optional[str]:
    """
    Check that an existing collection was built with the current backend.

    Chroma will happily accept a 1024-dim query against a 384-dim collection's
    neighbours only to fail deep inside the index, or — worse in the cases it
    does not fail — return rankings that mean nothing. Returning the mismatch as
    a message lets the caller decide whether to warn or refuse.
    """
    try:
        if collection.count() == 0:
            return None
        sample = collection.get(limit=1, include=["embeddings"])
        # Chroma returns a numpy array here; `x or []` on one raises rather than
        # falling through, so the emptiness check has to be explicit.
        vectors = sample.get("embeddings")
        if vectors is None or len(vectors) == 0:
            return None
        stored = len(vectors[0])
    except Exception as e:  # noqa: BLE001 — a probe must never break startup
        logger.debug("Could not probe '%s' for embedding width: %s", label, e)
        return None

    if stored != dimension():
        return (
            f"Collection '{label}' holds {stored}-dim vectors but the configured "
            f"embedding backend ({backend()}/{model_id()}) produces {dimension()}-dim "
            "ones. The store must be rebuilt: delete backend/data/rag_v2 (and "
            "backend/data/rag) and POST /api/rag/initialize."
        )
    return None
