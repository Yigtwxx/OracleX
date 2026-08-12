#!/usr/bin/env python3
"""
Re-embed both Chroma stores with the configured embedding backend.

Changing `RAG_EMBEDDING_BACKEND` changes the width and the geometry of every
vector, so a store written by the old model cannot be queried by the new one.
The obvious remedy — delete the stores and re-seed — throws away everything that
cannot be regenerated: the analysed-news collection is built up one analysis at a
time, and `project_docs` was ingested by a tool that is no longer in the tree.

Chroma keeps the original `documents` text alongside the vectors, so nothing has
to be re-fetched. This reads each collection, re-embeds the stored text with the
current backend, and writes it back under the same ids and metadata. Only the
vectors change.

Usage:
    python scripts/reindex_embeddings.py            # report what would change
    python scripts/reindex_embeddings.py --apply    # do it

A timestamped copy of each store is made before the first write. Collections
already at the target width are skipped, so a re-run after a partial failure
resumes rather than redoing the work.
"""

import argparse
import os
import shutil
import sys
import time
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb  # noqa: E402

from services import rag_embeddings  # noqa: E402

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORES = [
    os.path.join(_BACKEND_DIR, "data", "rag"),
    os.path.join(_BACKEND_DIR, "data", "rag_v2"),
]

# Documents per write. Large enough that the embedding daemon batches usefully,
# small enough that a failure does not lose much work.
BATCH = 256


def _width(collection) -> int:
    """Vector width currently stored, or 0 for an empty collection."""
    if collection.count() == 0:
        return 0
    sample = collection.get(limit=1, include=["embeddings"])
    vectors = sample.get("embeddings")
    return len(vectors[0]) if vectors is not None and len(vectors) else 0


def _backup(path: str, stamp: str) -> str:
    destination = f"{path}.bak-{stamp}"
    shutil.copytree(path, destination)
    return destination


def reindex_store(path: str, *, apply: bool, stamp: str) -> bool:
    """Re-embed one store. Returns True if anything needed doing."""
    if not os.path.isdir(path):
        print(f"  {path}: absent, skipping")
        return False

    client = chromadb.PersistentClient(path=path)
    target = rag_embeddings.dimension()
    pending = []

    for descriptor in client.list_collections():
        collection = client.get_collection(descriptor.name)
        count = collection.count()
        width = _width(collection)
        if count == 0:
            print(f"  {descriptor.name}: empty, nothing to do")
            continue
        if width == target:
            print(f"  {descriptor.name}: {count} items already {target}-dim, skipping")
            continue
        print(f"  {descriptor.name}: {count} items at {width}-dim → {target}-dim")
        pending.append(descriptor.name)

    if not pending:
        return False
    if not apply:
        return True

    backup = _backup(path, stamp)
    print(f"  backed up to {backup}")

    for name in pending:
        collection = client.get_collection(name)
        stored = collection.get(include=["documents", "metadatas"])
        ids: List[str] = stored.get("ids") or []
        documents = stored.get("documents") or []
        metadatas = stored.get("metadatas") or []

        # A row whose text was never stored cannot be re-embedded from anything,
        # and keeping it would leave a stale vector behind in a rebuilt
        # collection. Report it rather than dropping it silently.
        usable = [
            (i, d, m)
            for i, d, m in zip(ids, documents, metadatas)
            if isinstance(d, str) and d.strip()
        ]
        if len(usable) != len(ids):
            print(f"    {name}: {len(ids) - len(usable)} rows have no stored text and are dropped")

        # Recreate rather than upsert: the collection's index is built for the
        # old width, and Chroma will not accept a differently-shaped vector into it.
        client.delete_collection(name)
        fresh = client.get_or_create_collection(name=name)

        written = 0
        for start in range(0, len(usable), BATCH):
            chunk = usable[start : start + BATCH]
            texts = [d for _, d, _ in chunk]
            fresh.upsert(
                ids=[i for i, _, _ in chunk],
                embeddings=rag_embeddings.embed_documents(texts),
                metadatas=[m for _, _, m in chunk],
                documents=texts,
            )
            written += len(chunk)
            print(f"    {name}: {written}/{len(usable)}", end="\r", flush=True)
        print(f"    {name}: {written}/{len(usable)} re-embedded")

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="perform the rewrite (default is a dry run)"
    )
    args = parser.parse_args()

    print(
        f"Embedding backend: {rag_embeddings.backend()} / {rag_embeddings.model_id()} "
        f"({rag_embeddings.dimension()}-dim)\n"
    )

    stamp = time.strftime("%Y%m%d-%H%M%S")
    work = False
    for path in STORES:
        print(f"{path}:")
        work = reindex_store(path, apply=args.apply, stamp=stamp) or work
        print()

    if not work:
        print("Nothing to do — every collection already matches the configured backend.")
    elif not args.apply:
        print("Dry run. Re-run with --apply to rewrite.")
    else:
        print(
            "Done. Events and price history can additionally be re-seeded with\n"
            "POST /api/rag/initialize to pick up newly measurable outcomes."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
