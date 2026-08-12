"""
Document chunking for retrieval.

The property that matters is not "pieces of roughly N tokens" — it is that a
retrieved piece still means what it meant inside the document. A chunk cut
mid-sentence embeds as something neither half says, and a body paragraph that
never names its asset cannot be ranked by symbol.
"""

from services.rag_chunking import (
    Chunk,
    chunk_document,
    collapse_by_parent,
    parent_id_for,
    split_text,
)
from services.prompt_budget import estimate_tokens


def _paragraphs(n: int, words: int = 60) -> str:
    return "\n\n".join(" ".join(f"word{i}{j}" for j in range(words)) for i in range(n))


def test_short_text_is_not_split():
    """A headline is already the right size; splitting it scatters one claim."""
    text = "SEC approves spot Bitcoin ETFs after a decade of rejections."
    assert split_text(text) == [text]


def test_empty_text_produces_no_chunks():
    assert split_text("") == []
    assert split_text("   \n\n  ") == []


def test_long_text_is_split_and_every_chunk_respects_the_ceiling():
    chunks = split_text(_paragraphs(40), max_tokens=200, overlap_tokens=40)
    assert len(chunks) > 1
    # The ceiling is what keeps a chunk inside the embedding model's window;
    # a chunk over it is silently truncated by the model, not by us.
    for chunk in chunks:
        assert estimate_tokens(chunk) <= 200 * 1.5


def test_splits_land_on_paragraph_boundaries():
    """Sentences must not be cut in half — a half-sentence embeds as nonsense."""
    text = "\n\n".join(f"Paragraph {i} says something complete." for i in range(60))
    for chunk in split_text(text, max_tokens=120, overlap_tokens=20):
        for line in chunk.split("\n\n"):
            if line.strip():
                assert line.strip().endswith(".")


def test_consecutive_chunks_overlap():
    """
    A claim spanning a paragraph break must survive in at least one chunk.

    Paragraphs here are small relative to the overlap budget — the case where
    carrying a tail is actually possible. See the test below for what happens
    when it is not.
    """
    chunks = split_text(_paragraphs(40, words=8), max_tokens=200, overlap_tokens=80)
    assert len(chunks) >= 2
    first_tail = chunks[0].split("\n\n")[-1]
    assert first_tail in chunks[1]


def test_the_ceiling_wins_when_overlap_cannot_fit():
    """
    Overlap gives way to the size ceiling, never the other way round.

    When every paragraph is larger than the overlap budget there is no tail that
    fits. Carrying one anyway — to guarantee *some* overlap — seeds the next
    chunk with most of a chunk's worth of text and pushes it over the ceiling,
    where the embedding model truncates it without telling anyone.
    """
    chunks = split_text(_paragraphs(40, words=60), max_tokens=200, overlap_tokens=20)
    assert len(chunks) > 1
    for chunk in chunks:
        assert estimate_tokens(chunk) <= 200 * 1.5


def test_zero_overlap_is_honoured():
    chunks = split_text(_paragraphs(40, words=8), max_tokens=200, overlap_tokens=0)
    assert len(chunks) >= 2
    assert chunks[0].split("\n\n")[-1] not in chunks[1]


def test_a_single_oversized_paragraph_is_split_on_sentences():
    """Scraped articles often arrive as one unbroken block."""
    blob = " ".join(f"Sentence number {i} about the market." for i in range(200))
    chunks = split_text(blob, max_tokens=150, overlap_tokens=0)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.strip().endswith(".")


def test_every_chunk_carries_the_headline():
    """
    A body paragraph read alone frequently never names the asset.

    Without the headline the chunk is unattributable, and an unattributable
    chunk cannot be weighted by symbol relevance — it just floats.
    """
    chunks = chunk_document(
        _paragraphs(30),
        parent_id="abc123",
        header="SEC sues Ripple Labs over XRP",
    )
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.text.startswith("SEC sues Ripple Labs over XRP")


def test_chunks_record_their_parent_and_position():
    chunks = chunk_document(_paragraphs(30), parent_id="abc123", header="H")
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert all(c.parent_id == "abc123" for c in chunks)
    assert all(c.metadata["parent_id"] == "abc123" for c in chunks)
    assert chunks[2].id == "abc123:2"


def test_extra_metadata_is_preserved_on_every_chunk():
    chunks = chunk_document(
        _paragraphs(30),
        parent_id="p",
        metadata={"symbol": "BTC", "asset_type": "crypto"},
    )
    assert all(c.metadata["symbol"] == "BTC" for c in chunks)
    assert all(c.metadata["asset_type"] == "crypto" for c in chunks)


def test_parent_id_is_content_derived_and_stable():
    """
    Re-indexing must update a document, not add another copy of it.

    The previous news indexer keyed on the title plus `datetime.now()`, so every
    pass inserted a fresh duplicate of the same article.
    """
    assert parent_id_for("https://example.com/a") == parent_id_for("https://example.com/a")
    assert parent_id_for("https://example.com/a") != parent_id_for("https://example.com/b")


def _hit(parent, label):
    return {"label": label, "metadata": {"parent_id": parent} if parent else {}}


def test_collapse_keeps_only_the_best_chunk_per_document():
    """
    Five chunks of one article read to the model as five sources agreeing.

    They are near-duplicates by construction, so keeping them all manufactures
    false corroboration for whatever that one article claimed.
    """
    hits = [
        _hit("a", "a-best"),
        _hit("a", "a-second"),
        _hit("b", "b-best"),
        _hit("a", "a-third"),
        _hit("c", "c-best"),
    ]
    kept = collapse_by_parent(hits, limit=5)
    assert [h["label"] for h in kept] == ["a-best", "b-best", "c-best"]


def test_collapse_passes_through_unchunked_items():
    """Events and price rows are never chunked and must not be deduplicated."""
    hits = [_hit(None, "event-1"), _hit(None, "event-2"), _hit("a", "chunk")]
    kept = collapse_by_parent(hits, limit=5)
    assert [h["label"] for h in kept] == ["event-1", "event-2", "chunk"]


def test_collapse_respects_the_limit():
    hits = [_hit(str(i), f"doc-{i}") for i in range(10)]
    assert len(collapse_by_parent(hits, limit=3)) == 3


def test_chunk_id_is_unique_per_position():
    chunk = Chunk(text="t", index=7, parent_id="pid", metadata={})
    assert chunk.id == "pid:7"
