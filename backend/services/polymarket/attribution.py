"""
Deleting anything the evidence does not carry.

The model is asked for claims as objects with source ids, not for prose, and
this module is why. Auditing a paragraph sentence by sentence is unreliable when
a local model wrote it — the citations drift, merge, or attach to the wrong
clause. Auditing a list of `{text, sources}` objects is mechanical: a claim
whose ids do not resolve is deleted whole, and nothing is left behind to read
as if it had been checked.

Three failure modes are handled, in order of how often they actually happen:

1. **Invented ids.** A model given eight sources will cite `S12`. The id space
   is known exactly, so this is caught by lookup rather than by judgement.
2. **Claims about the price.** "The market has moved eleven points this week" is
   true and has no URL, because its source is the market. The sentinel
   `"MARKET"` covers it — but it is *verified*, not trusted: every figure in the
   claim must appear verbatim in the rendered facts block. This is the house
   rule "only numbers from the FACTS block" checked in Python instead of asked
   for in prose, and without it the sentinel becomes a hole big enough to drive
   any unsourced number through.
3. **Free prose.** The one free-text field left is the bottom line, and it is
   capped and required to carry inline markers, because a summary is exactly
   where an unsupported sentence hides most comfortably.

What gets deleted is reported rather than silently dropped: `AttributionReport`
rides on the result so a reader can see that the pruning happened, and so the
tests have something to assert against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from models.polymarket import AttributionReport, Claim, SourceRef

#: The one source id that is not a URL. A claim about the market's own price is
#: sourced by the facts block, which is rendered from measurements.
MARKET_SENTINEL = "MARKET"

#: Longest a bottom line may run. Three sentences is enough to state a leaning
#: and its main reason; past that a summary starts restating the claims it is
#: summarising, and each extra sentence is another chance to say something the
#: sources do not.
MAX_BOTTOM_LINE_SENTENCES = 3

#: Fewest surviving claims a verdict needs. A judgement standing on one
#: corroborated claim is not a judgement, and presenting it as one is the
#: failure this pipeline exists to avoid — so the whole synthesis is discarded
#: rather than shown thin.
MIN_KEPT_CLAIMS = 3

#: Any number, with optional currency, separators, decimals or a percent sign.
_FIGURE = re.compile(r"\$?\d[\d,]*\.?\d*%?")

#: Inline citation markers, e.g. "[S3]" or "[S3, S7]".
_MARKER = re.compile(r"\[(S\d+(?:\s*,\s*S\d+)*)\]")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

#: Whitespace left behind once a marker is cut out. Removing "[S1]" from
#: "Rates will fall [S1]." leaves a space in front of the full stop, which is
#: the sort of detail that makes generated text read as generated.
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?])")
_COLLAPSE = re.compile(r"\s{2,}")

#: Punctuation left doubled once a marker between it and the full stop is cut.
#: The model writes "…rather than direct engagement, [S33]." and removing the
#: marker leaves ",." — which is the sort of seam that makes generated prose
#: read as generated.
_DOUBLE_PUNCT = re.compile(r"[,;:]\s*([.!?])")


@dataclass
class EvidenceLedger:
    """The source ids a prompt may cite, and what they resolve to."""

    sources: list[SourceRef] = field(default_factory=list)

    def add(self, ref: SourceRef) -> None:
        self.sources.append(ref)

    @property
    def ids(self) -> set[str]:
        return {s.id for s in self.sources}

    def by_id(self, source_id: str) -> SourceRef | None:
        for source in self.sources:
            if source.id == source_id:
                return source
        return None


def _normalise_figure(text: str) -> str:
    """Compare figures without punctuation noise: "$1,200" and "1200" match."""
    return text.replace(",", "").replace("$", "").rstrip("%").rstrip(".")


def verify_market_claim(text: str, facts_block: str) -> bool:
    """
    True when every figure in a MARKET-sourced claim appears in the facts.

    A claim with no figures at all passes — "the market is thinly traded" is a
    reading of the facts rather than a number lifted from them, and there is
    nothing here to check. The check exists to stop invented quantities, not to
    ban qualitative statements about the order book.
    """
    figures = _FIGURE.findall(text)
    if not figures:
        return True
    haystack = {_normalise_figure(f) for f in _FIGURE.findall(facts_block)}
    return all(_normalise_figure(f) in haystack for f in figures)


def enforce_attribution(
    claims: list[Claim],
    ledger: EvidenceLedger,
    facts_block: str,
) -> tuple[list[Claim], AttributionReport]:
    """
    Drop every claim the evidence does not carry, and say what was dropped.

    Returns the survivors and a report. Callers must treat fewer than
    MIN_KEPT_CLAIMS survivors as a failed synthesis rather than a thin one.
    """
    known = ledger.ids
    kept: list[Claim] = []
    dropped: list[str] = []

    for claim in claims:
        text = (claim.text or "").strip()
        if not text:
            continue

        requested = [s.strip() for s in claim.sources if s and s.strip()]

        if MARKET_SENTINEL in requested:
            if verify_market_claim(text, facts_block):
                kept.append(
                    Claim(
                        text=text,
                        sources=[MARKET_SENTINEL],
                        direction=claim.direction,
                        weight=claim.weight,
                    )
                )
            else:
                dropped.append(
                    f"{text[:80]} — cited the market for a figure the facts do not contain"
                )
            continue

        resolved = [s for s in requested if s in known]
        invented = [s for s in requested if s not in known]

        if not resolved:
            why = (
                f"cited unknown source{'s' if len(invented) > 1 else ''} {', '.join(invented)}"
                if invented
                else "carried no source"
            )
            dropped.append(f"{text[:80]} — {why}")
            continue

        kept.append(
            Claim(
                text=text,
                sources=resolved,
                direction=claim.direction,
                weight=claim.weight,
            )
        )

    report = AttributionReport(
        claims_in=len(claims),
        claims_kept=len(kept),
        dropped=dropped,
    )
    return kept, report


def drop_unsourced_sentences(
    text: str,
    ledger: EvidenceLedger,
    max_sentences: int = MAX_BOTTOM_LINE_SENTENCES,
) -> tuple[str, int]:
    """
    Keep only the sentences that cite a source we actually hold.

    Blunt on purpose. A softer rule — keep the sentence if it *looks*
    supported — is a judgement call, and the whole point of this pass is that
    no judgement is involved. Markers are stripped from the survivors because
    they are scaffolding for this check, not something a reader should see.

    Returns the cleaned text and how many sentences were removed.
    """
    known = ledger.ids
    sentences = [s for s in _SENTENCE_SPLIT.split((text or "").strip()) if s.strip()]

    kept: list[str] = []
    removed = 0
    for sentence in sentences:
        markers = _MARKER.findall(sentence)
        cited = {part.strip() for group in markers for part in group.split(",") if part.strip()}
        if cited and cited & known:
            cleaned = _MARKER.sub("", sentence)
            cleaned = _SPACE_BEFORE_PUNCT.sub(r"\1", cleaned)
            cleaned = _DOUBLE_PUNCT.sub(r"\1", cleaned)
            kept.append(_COLLAPSE.sub(" ", cleaned).strip())
        else:
            removed += 1

    if len(kept) > max_sentences:
        removed += len(kept) - max_sentences
        kept = kept[:max_sentences]

    return " ".join(kept), removed
