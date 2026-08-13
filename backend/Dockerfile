# syntax=docker/dockerfile:1
#
# Oracle-X backend image.
#
# Build from the repository root:
#   docker build -f backend/Dockerfile -t oracle-x-backend .
#
# Python 3.11 matches the CI job (.github/workflows/ci.yml). The code targets
# py39 syntax, so 3.11 is a safe floor with better wheel availability.

# ── Stage 1: build the virtualenv ───────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# torch arrives transitively via sentence-transformers, which on x86_64 pulls
# the CUDA build (~2.5 GB) even though we only ever run on CPU. Installing the
# CPU wheel first pins that resolution. The aarch64 wheels on PyPI are already
# CPU-only, so fall back there if the CPU index has no matching wheel.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    || pip install --no-cache-dir torch

# Both files: requirements.txt is a thin layer over requirements-base.txt and
# pulls it in with `-r`, so copying only the former resolves to nothing.
COPY backend/requirements.txt backend/requirements-base.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Bake the embedding model into the image. rag_service.py and rag_v2_service.py
# load all-MiniLM-L6-v2 without a cache_folder, so without this every container
# start re-downloads ~90 MB from HuggingFace before RAG can serve.
ENV HF_HOME=/opt/hf-cache
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# libgomp1 is required by the torch / onnxruntime native extensions.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/opt/hf-cache \
    # The embedding model is baked in above, so skip the HuggingFace revalidation
    # round-trips on every start. Changing EMBEDDING_MODEL requires a rebuild
    # anyway — that is what re-bakes the cache.
    HF_HUB_OFFLINE=1 \
    PATH="/opt/venv/bin:$PATH"

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/hf-cache /opt/hf-cache

RUN useradd --create-home --uid 1000 appuser

# WORKDIR must be /app with the backend at its root: watchlist_service.py and
# analysis_service.py resolve their data/ paths relative to the process cwd,
# while rag/liquidation services use paths relative to this file. Both only
# agree when the app runs from its own directory.
WORKDIR /app
COPY --chown=appuser:appuser backend/ /app/

# Mount point for the backend-data volume (Chroma stores + runtime JSON).
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4).status == 200 else 1)"

# Single worker only: scheduler_service.py holds a module-level APScheduler and
# websocket_service.py a price-streaming singleton. Extra workers would
# duplicate every scheduled job.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
