"""
What a market is about, decided without asking a model.

The category chooses which wires are read and which queries are issued, so it
sits upstream of the entire evidence base. That is exactly why it is not an LLM
call: a misfire here silently swaps the sources a verdict rests on, and nothing
downstream can detect it — the sweep would report a clean run over the wrong
newspapers. A keyword table gets things wrong too, but it gets them wrong the
same way every time, and `matched_on` says which rule fired.

The second reason is cost. This runs in the stage that has to stay fastest, and
a round trip to a local model to learn that a question containing "Bitcoin" is
about crypto is a poor trade.

Two passes, in order:

1. **Tags.** Gamma publishes curated tag slugs. When one of them is decisive it
   is simply believed — it was set by a human who read the market.
2. **Keywords.** A weighted lexicon, requiring both an absolute score and a
   margin over the runner-up. The margin is what stops "Will the Fed cut before
   the election?" from being classified on a coin flip; without it, a question
   sitting between two categories lands wherever the last keyword fell.

Anything that satisfies neither is `general`, which reads broad wires. Guessing
narrowly is worse than reading widely: a politics market researched off crypto
desks produces a confident answer from irrelevant sources.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from services.polymarket.registry import STRATEGIES, TAG_PRIORITY

#: Absolute floor for a keyword verdict, set equal to the weight of a single
#: decisive term. Market questions are short — "Will Bitcoin reach $150,000?"
#: carries exactly one classifying word and it is conclusive — so a floor that
#: demanded two hits sent most real markets to `general` and read the broad
#: wires for a question the crypto desks had already covered. At 2.0 the
#: unambiguous proper nouns (bitcoin, nba, ceasefire, election) can decide
#: alone, while the merely suggestive ones (vote, match, border, strike) are
#: weighted 1.0-1.5 and still cannot.
MIN_KEYWORD_SCORE = 2.0

#: How far ahead of the runner-up the winner must be. At 1.0 a tie goes to
#: whichever category happens to be declared first, which is not a decision.
MIN_KEYWORD_MARGIN = 1.5

#: Only the head of the description is scanned. Polymarket resolution text runs
#: to several paragraphs of UMA boilerplate that mentions markets, prices and
#: settlement in every market regardless of subject, so reading all of it makes
#: every question look like a macro question.
DESCRIPTION_SCAN_CHARS = 600


# Word-boundary matchers, compiled once per term.
#
# Substring matching was the obvious implementation and it is wrong in a way
# that is easy to miss: "war" is inside "Warner", "toward", "warn" and
# "software", so a market asking whether Warner Bros gets acquired scored two
# points of geopolitics and would have been researched off the wires that cover
# invasions. Every term here is a whole word — multi-word terms like "interest
# rate" and "prime minister" work under \b unchanged.
_TERM_PATTERNS: dict[str, re.Pattern[str]] = {
    term: re.compile(rf"\b{re.escape(term)}\b")
    for strategy in STRATEGIES
    for term, _weight in strategy.keywords
}


@dataclass(frozen=True)
class CategoryVerdict:
    category: str
    confidence: float
    #: Which rules fired, e.g. ("tag:politics",) or ("kw:inflation", "kw:fed").
    matched_on: tuple[str, ...]


def infer_category(
    question: str,
    description: str = "",
    tags: tuple[str, ...] = (),
) -> CategoryVerdict:
    """Classify a market. Never raises; an unreadable market is `general`."""
    slugs = {t.strip().lower() for t in tags if t and t.strip()}
    for slug, category in TAG_PRIORITY:
        if slug in slugs:
            return CategoryVerdict(category, 0.95, (f"tag:{slug}",))

    haystack = f"{question} {description[:DESCRIPTION_SCAN_CHARS]}".lower()

    scored: list[tuple[float, str, tuple[str, ...]]] = []
    for strategy in STRATEGIES:
        if not strategy.keywords:
            continue
        score = 0.0
        hits: list[str] = []
        for term, weight in strategy.keywords:
            if _TERM_PATTERNS[term].search(haystack):
                score += weight
                hits.append(f"kw:{term}")
        if score:
            scored.append((score, strategy.key, tuple(hits)))

    if not scored:
        return CategoryVerdict("general", 0.0, ())

    scored.sort(key=lambda row: row[0], reverse=True)
    best_score, best_key, best_hits = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0

    if best_score < MIN_KEYWORD_SCORE:
        return CategoryVerdict("general", 0.0, ())
    if runner_up and best_score < runner_up * MIN_KEYWORD_MARGIN:
        return CategoryVerdict("general", 0.0, ())

    return CategoryVerdict(best_key, min(0.85, best_score / 6.0), best_hits)


# Leading interrogatives Polymarket phrases nearly every market with. Stripped
# so the subject can be pasted into a search box: "Will X happen by June?" is a
# question to a reader and a bad query to a search engine, which matches the
# words "will" and "by" across the entire web.
_LEAD = re.compile(
    r"^(will|is|are|does|do|did|can|could|would|should|who|what|when|which|how many|how much)\b\s*",
    re.IGNORECASE,
)

# Trailing deadline clauses. The date is carried separately as `end_date`; left
# in the query it pins the search to coverage that happens to repeat the
# deadline, which is rarely the coverage that explains the event.
_TAIL_DEADLINE = re.compile(
    r"\s*\b(by|before|on|in|during|prior to|through)\b\s+"
    r"("
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{0,2},?\s*\d{0,4}"
    r"|\d{4}"
    r"|q[1-4]\s*\d{0,4}"
    r"|the end of[^?]*"
    r"|end of[^?]*"
    r")\s*$",
    re.IGNORECASE,
)

_WHITESPACE = re.compile(r"\s+")


def market_subject(question: str) -> str:
    """
    The noun phrase at the heart of a market question.

    Used verbatim in search queries, which is the whole constraint: the output
    has to read like something a person would type into a search box, not like
    a question. Stripping is conservative — when a pattern does not match, the
    original text is returned rather than mangled, because a slightly wordy
    query still finds the story while an over-trimmed one finds the wrong topic.
    """
    text = (question or "").strip().rstrip("?").strip()
    if not text:
        return ""

    text = _LEAD.sub("", text, count=1)
    # Twice: "…by the end of Q3 2026" leaves "…by the end of" behind on a
    # single pass, and a dangling preposition is worse than the date was.
    for _ in range(2):
        stripped = _TAIL_DEADLINE.sub("", text).strip()
        if stripped == text:
            break
        text = stripped

    text = _WHITESPACE.sub(" ", text).strip(" ,;:-")
    return text or (question or "").strip().rstrip("?")


def resolution_year(end_date: datetime | None) -> str:
    """The year a market resolves in, for query templates. Empty when unknown."""
    return str(end_date.year) if end_date else ""
