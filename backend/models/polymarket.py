"""
Polymarket — the shapes a prediction market and its analysis are served in.

Two distinctions are built into these schemas because collapsing either is how a
prediction-market surface starts telling people things nobody can check.

**A price is a fact about the market, not about the world.** `Outcome.price` is
what somebody was willing to pay, which is evidence of belief and nothing more.
It is never merged into the evidence list and never cited as a source for a
claim about the underlying event; `Claim.sources` carries the sentinel
`"MARKET"` for the one case where a claim is *about* the price, and that case is
verified in Python against the rendered facts block rather than trusted.

**A verdict and a refusal are different shapes, not one shape with empty
fields.** `PolymarketAnalysis` and `PolymarketRefusal` are separate models
discriminated on `status`. A single model with everything optional invites the
frontend to render a verdict-shaped card full of blanks, which reads as a
confident answer that happens to be missing its words — the precise failure this
whole surface is built to avoid. A refusal has to look like a refusal.

The house rule from `models/ownership.py` holds: a figure nobody published is
`None` and renders as "Unknown". Never 0. An outcome priced at 0.0 is a market
saying "certainly not"; an outcome with no price is a market we could not read.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# How much standing a number has.
#   measured  — read directly off a source that published it
#   derived   — computed from measurements by a rule the reader could re-run
#   estimated — an inference; true of the input, uncertain of the conclusion
#
# This rides on the map layers and on anything the UI must badge. It exists
# because the three are visually identical once drawn and only distinguishable
# if the data says which it is.
Provenance = Literal["measured", "derived", "estimated"]

MarketCategory = Literal[
    "politics",
    "geopolitics",
    "macro",
    "crypto",
    "sports",
    "general",
]

# Why no verdict was produced. Each maps to a distinct sentence in the UI,
# because "we found nothing" and "the model was down" are different problems and
# only one of them is worth retrying.
RefusalReason = Literal[
    "no_sources",
    "thin_evidence",
    "single_domain",
    "timeout",
    "market_unavailable",
    "unsourced_output",
    "model_unavailable",
    "ai_disabled",
]


class Outcome(BaseModel):
    """One side of a market. `price` is a probability in [0, 1], not a percent."""

    label: str
    price: float | None = None
    token_id: str | None = None


class MarketSummary(BaseModel):
    """A board row."""

    market_id: str
    slug: str
    question: str
    category: MarketCategory = "general"
    outcomes: list[Outcome] = Field(default_factory=list)
    volume_usd: float | None = None
    liquidity_usd: float | None = None
    end_date: datetime | None = None
    created_at: datetime | None = None
    closed: bool = False
    icon_url: str | None = None
    event_slug: str | None = None


class PricePoint(BaseModel):
    t: datetime
    p: float


class SharpMove(BaseModel):
    """
    A window in which the market changed its mind, or the window it opened in.

    `delta` is in absolute probability points and never a percentage. 0.02 to
    0.04 is a 100% rise and means nothing; 0.45 to 0.62 is the one that had a
    cause. Percentages here would rank noise above news.
    """

    kind: Literal["spike", "creation"]
    started_at: datetime
    ended_at: datetime
    price_from: float | None = None
    price_to: float | None = None
    delta: float | None = None
    outcome_label: str | None = None


class Holder(BaseModel):
    wallet: str
    display_name: str | None = None
    outcome_label: str | None = None
    shares: float | None = None


class MarketFacts(BaseModel):
    """
    Everything about a market that needed no model to establish.

    This is computed without the LLM and served on its own endpoint, which is
    what makes a refusal cheap: the page still shows odds, spread, concentration
    and the move timeline when no verdict can be written.
    """

    market: MarketSummary
    resolution_criteria: str | None = None
    history: list[PricePoint] = Field(default_factory=list)
    moves: list[SharpMove] = Field(default_factory=list)
    holders: list[Holder] = Field(default_factory=list)
    #: Named gaps. A source that could not be read is listed here rather than
    #: silently omitted, so the reader can tell a thin market from a thin fetch.
    unavailable: list[str] = Field(default_factory=list)


class Microstructure(BaseModel):
    """
    What the order book and the holder table say, independent of the news.

    Every field is `None` rather than 0 when unreadable — a market with no
    spread and a market whose book we failed to fetch must not render alike.
    """

    leading_outcome: str | None = None
    leading_price: float | None = None
    #: Change in the leading outcome's price over the last 24h, in points.
    drift_24h: float | None = None
    drift_7d: float | None = None
    spread: float | None = None
    liquidity_usd: float | None = None
    volume_usd: float | None = None
    #: Share of the top-holder table held by the single largest wallet, 0..1.
    top_holder_share: float | None = None
    #: Share held by the top five, 0..1. Read together these say whether the
    #: price is a crowd's view or one wallet's position.
    top5_holder_share: float | None = None
    notes: list[str] = Field(default_factory=list)


class SourceRef(BaseModel):
    """One retrieved document, addressable by `id` from inside a prompt."""

    id: str
    url: str
    domain: str
    title: str = ""
    published_at: datetime | None = None
    #: 1 = allowlisted outlet with a readable body, 2 = one of the two, 3 = a
    #: snippet from an unknown domain. Assigned in Python, never by the model.
    tier: int = 3
    #: How it was found: "search", "news", "feed", "scrape", "rag".
    via: str = "search"
    body_chars: int = 0


class Claim(BaseModel):
    """
    One assertion, with the sources that carry it.

    Objects rather than prose because prose cannot be audited sentence by
    sentence reliably when a local model wrote it, and objects can: a claim
    whose `sources` do not survive `enforce_attribution` is deleted whole.
    """

    text: str
    sources: list[str] = Field(default_factory=list)
    #: Which side of the market this supports, if either.
    direction: Literal["yes", "no", "neutral"] = "neutral"
    weight: Literal["strong", "moderate", "weak"] = "moderate"


class Trigger(BaseModel):
    """The event a sharp move or the market's creation is attributed to."""

    summary: str
    source_id: str
    occurred_at: datetime | None = None
    move_index: int | None = None


class Origin(BaseModel):
    """Why this market exists, and what moved it since."""

    status: Literal["traced", "undetermined"] = "undetermined"
    opening_rationale: str | None = None
    triggers: list[Trigger] = Field(default_factory=list)


class SweepAttempt(BaseModel):
    """One query or feed that was tried, and what came of it."""

    kind: Literal["search", "news", "feed", "rag", "scrape"]
    target: str
    outcome: Literal["hits", "empty", "error", "timeout"]
    hits: int = 0
    detail: str | None = None


class EvidenceCoverage(BaseModel):
    """
    What the sweep reached, in enough detail to explain a refusal.

    This is the model behind the "no proper analysis could be produced" panel.
    Composed in Python and never written by the model — a model asked to explain
    why it had too little to go on will write a paragraph that sounds like an
    analysis, which is the thing being withheld.
    """

    attempted: list[SweepAttempt] = Field(default_factory=list)
    total_sources: int = 0
    distinct_domains: int = 0
    tier1_sources: int = 0
    body_chars: int = 0
    queries_answered: int = 0
    queries_issued: int = 0
    #: Sources dropped for length before the prompt was built. A body trimmed
    #: out of the prompt is a gap the reader is told about.
    dropped: list[str] = Field(default_factory=list)


class AttributionReport(BaseModel):
    """What the source check deleted, so the pruning is visible to the reader."""

    claims_in: int = 0
    claims_kept: int = 0
    sentences_dropped: int = 0
    dropped: list[str] = Field(default_factory=list)


class PolymarketAnalysis(BaseModel):
    status: Literal["ok", "degraded"]
    market_id: str
    slug: str
    question: str
    category: MarketCategory
    facts: MarketFacts
    microstructure: Microstructure
    origin: Origin
    #: 0..1. Hard-clamped in Python for a degraded run — a thin evidence base
    #: cannot license a confident number no matter what the model returned.
    confidence: float
    leaning: Literal["yes", "no", "unclear"]
    bottom_line: str
    claims_for: list[Claim] = Field(default_factory=list)
    claims_against: list[Claim] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    coverage: EvidenceCoverage
    attribution: AttributionReport
    #: Populated on a degraded run: what was missing, in the reader's words.
    gaps: list[str] = Field(default_factory=list)
    generated_at: datetime


class PolymarketRefusal(BaseModel):
    """
    No verdict, and why — never a hedged guess wearing a verdict's shape.

    `facts` and `microstructure` are still present. Withholding them alongside
    the verdict would turn "we could not judge this" into "this market is
    broken", which is a different and false claim.
    """

    status: Literal["insufficient_evidence"] = "insufficient_evidence"
    market_id: str
    slug: str
    question: str
    category: MarketCategory
    reason_code: RefusalReason
    #: One paragraph naming what was searched and what came back empty.
    explanation: str
    facts: MarketFacts | None = None
    microstructure: Microstructure | None = None
    origin: Origin | None = None
    coverage: EvidenceCoverage
    generated_at: datetime
