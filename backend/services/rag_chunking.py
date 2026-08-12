"""
Splitting long documents into retrievable units.

Until now nothing here was chunked. A news item was indexed as its headline plus
a summary truncated at 2000 characters, and the article body — which
`article_service` already fetches — was passed straight into a prompt and thrown
away. So retrieval could match the headline of a story and never the paragraph
that explained why the price moved, which is the part worth retrieving.

Chunking is done on paragraph boundaries rather than at a fixed character count:
a chunk cut mid-sentence embeds as something neither half means, and a market
paragraph ("funding flipped negative while open interest held") is a self-
contained claim that survives being read alone. Consecutive chunks overlap so a
claim spanning a paragraph break is not lost at the seam.

Token counts come from `prompt_budget.estimate_tokens`, the same estimator the
prompt builder uses, so "512 tokens" means the same thing in both places.
"""

import hashlib
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from config import settings
from services.prompt_budget import estimate_tokens

# Two or more newlines is a paragraph break; a single newline inside a paragraph
# is usually just wrapping and is not a safe split point.
_PARAGRAPH = re.compile(r"\n\s*\n+")

# Fallback split for a "paragraph" that is itself longer than a whole chunk —
# common in scraped articles that arrive as one unbroken block.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    """One indexable piece of a document, and where it came from."""

    text: str
    index: int
    parent_id: str
    # Chroma rejects None in metadata, so absent values are stored as "".
    metadata: Dict[str, str]

    @property
    def id(self) -> str:
        return f"{self.parent_id}:{self.index}"


def _pack(parts: List[str], max_tokens: int, joiner: str) -> List[str]:
    """Greedily pack `parts` into pieces of at most `max_tokens`."""
    pieces: List[str] = []
    current = ""
    for part in parts:
        candidate = f"{current}{joiner}{part}" if current else part
        if current and estimate_tokens(candidate) > max_tokens:
            pieces.append(current)
            current = part
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _split_oversized(block: str, max_tokens: int) -> List[str]:
    """
    Break a single over-long block down to the ceiling, sentences first.

    Sentence boundaries are preferred because a whole sentence is the smallest
    unit that still means something on its own. But they are not guaranteed to
    exist: scraped article text arrives without terminal punctuation often
    enough that relying on them let an over-ceiling chunk through, which the
    embedding model then truncates silently. So anything still too large after
    the sentence pass is packed by words — an ugly split, but a bounded one, and
    a bounded chunk is the thing the caller was promised.
    """
    pieces: List[str] = []
    for piece in _pack(_SENTENCE.split(block), max_tokens, " "):
        if estimate_tokens(piece) <= max_tokens:
            pieces.append(piece)
        else:
            pieces.extend(_pack(piece.split(), max_tokens, " "))
    return pieces


def split_text(
    text: str,
    *,
    max_tokens: Optional[int] = None,
    overlap_tokens: Optional[int] = None,
) -> List[str]:
    """
    Split `text` into chunks of at most `max_tokens`, overlapping by `overlap_tokens`.

    Short text comes back as a single chunk rather than being padded or split —
    most headlines and event descriptions are already the right size, and
    splitting them would only scatter one claim across two vectors.
    """
    max_tokens = max_tokens if max_tokens is not None else settings.RAG_CHUNK_TOKENS
    overlap_tokens = (
        overlap_tokens if overlap_tokens is not None else settings.RAG_CHUNK_OVERLAP_TOKENS
    )

    text = (text or "").strip()
    if not text:
        return []
    if estimate_tokens(text) <= max_tokens:
        return [text]

    blocks: List[str] = []
    for paragraph in _PARAGRAPH.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if estimate_tokens(paragraph) > max_tokens:
            blocks.extend(_split_oversized(paragraph, max_tokens))
        else:
            blocks.append(paragraph)

    chunks: List[str] = []
    current: List[str] = []
    for block in blocks:
        candidate = current + [block]
        if current and estimate_tokens("\n\n".join(candidate)) > max_tokens:
            chunks.append("\n\n".join(current))
            # Carry the tail of the finished chunk into the next one so a claim
            # split across the boundary is still retrievable whole from one side.
            current = _overlap_tail(current, overlap_tokens) + [block]
        else:
            current = candidate
    if current:
        chunks.append("\n\n".join(current))

    return chunks


def _overlap_tail(blocks: List[str], overlap_tokens: int) -> List[str]:
    """
    The trailing blocks of a finished chunk that seed the next one.

    Returns nothing when even the last block alone exceeds the overlap budget.
    Carrying it anyway — which an earlier version did, to guarantee some overlap —
    seeds the next chunk with most of a chunk's worth of text and pushes it past
    the ceiling. The ceiling is a contract with the embedding model; the overlap
    is a nicety, and it is the one that gives way.
    """
    if overlap_tokens <= 0:
        return []
    tail: List[str] = []
    for block in reversed(blocks):
        if estimate_tokens("\n\n".join([block] + tail)) > overlap_tokens:
            break
        tail.insert(0, block)
    return tail


def chunk_document(
    text: str,
    *,
    parent_id: str,
    metadata: Optional[Dict[str, str]] = None,
    header: str = "",
) -> List[Chunk]:
    """
    Chunk one document, tagging every piece with the parent it came from.

    `header` — normally the headline — is prepended to each chunk. A body
    paragraph read alone often does not name the asset it is about, and a chunk
    that cannot be identified is a chunk that cannot be ranked by symbol.

    `parent_id` is what lets retrieval collapse several chunks of one article
    back into a single cited source; without it, five hits from one story look
    like five independent confirmations.
    """
    base = dict(metadata or {})
    chunks: List[Chunk] = []
    for index, piece in enumerate(split_text(text)):
        body = f"{header}\n\n{piece}" if header else piece
        chunks.append(
            Chunk(
                text=body,
                index=index,
                parent_id=parent_id,
                metadata={**base, "parent_id": parent_id, "chunk_index": str(index)},
            )
        )
    return chunks


def parent_id_for(*parts: str) -> str:
    """
    A stable id for a document, so re-indexing updates rather than duplicates.

    Derived from content, not from the clock: the previous news indexer keyed on
    `title` plus `datetime.now()`, which made every pass insert a fresh copy of
    the same article.
    """
    digest = hashlib.md5("::".join(p or "" for p in parts).encode()).hexdigest()
    return digest[:16]


def collapse_by_parent(hits: List[Dict], limit: int) -> List[Dict]:
    """
    Keep the best-scoring chunk per source document, best-ranked first.

    Chunks of the same article are near-duplicates by construction, so without
    this the top of a result list is one story repeated — which reads to the
    model as several independent sources agreeing.

    `hits` must already be in rank order; each is a dict carrying a `metadata`
    mapping. Hits with no `parent_id` (events, price rows — never chunked) are
    passed through untouched.
    """
    seen: set = set()
    kept: List[Dict] = []
    for hit in hits:
        parent = (hit.get("metadata") or {}).get("parent_id")
        if parent:
            if parent in seen:
                continue
            seen.add(parent)
        kept.append(hit)
        if len(kept) >= limit:
            break
    return kept
