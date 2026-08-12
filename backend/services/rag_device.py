"""
Device and thread policy for the local embedding models.

Kept in its own module so the v1 and v2 RAG services share one policy without
either importing the other, and so `torch` is only imported when a model is
actually being loaded — importing it is itself seconds of synchronous work.
"""

import logging
import os

from config import settings

logger = logging.getLogger(__name__)


def pick_device() -> str:
    """
    The device to load embedding models onto: CUDA → MPS → CPU.

    Never hardcoded — the same code runs on an NVIDIA box and on Apple Silicon.
    Silently defaulting to CPU is what made embedding work saturate every core
    on a machine that had an accelerator sitting idle, which starved everything
    else on the host, the frontend dev server included.
    """
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def configure_torch_threads() -> None:
    """
    Cap how many cores torch may take for CPU work.

    Only matters on the CPU fallback, where torch otherwise claims every core:
    the model load and encode then run at full machine width and leave nothing
    for the rest of the host. Half the cores keeps embedding fast while leaving
    the box responsive.

    Safe to call more than once; torch treats the last setting as current.
    """
    import torch

    configured = settings.EMBEDDING_MAX_CPU_THREADS
    threads = configured if configured > 0 else max(1, (os.cpu_count() or 4) // 2)
    torch.set_num_threads(threads)
    logger.info("Embedding torch threads capped at %d", threads)
