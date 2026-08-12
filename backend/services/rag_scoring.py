"""
Scoring for retrieved history — how relevant a past item is, and how much it mattered.

Every RAG service used to rank retrieved history by embedding proximity alone,
converting Chroma's distance with `1 / (1 + distance)`. Two things were wrong
with that.

The conversion itself: `all-MiniLM-L6-v2` ends in a Normalize module, so every
stored vector is unit length and Chroma's default (squared L2) distance is
exactly `2 - 2*cos`. The real cosine is therefore `1 - distance/2`, and the old
formula squeezed the whole range into [0.2, 1.0]. Measured against the live
model, the sentence "How do I bake sourdough bread at home?" scored 0.316
against "Bitcoin Halving 2024 …" — above the 0.30 threshold three call sites
used to admit a result — while its true cosine is -0.084. The thresholds had
been tuned inside the noise band.

And proximity is only half the question. "Is this text nearby" is not "did this
event matter": nothing accounted for how recent an event was, how far the price
actually moved, whether it concerned the asset being asked about, or what kind
of event it was. Worst of all, a headline's apparent tone was treated as its
outcome — so the precedents with the most to teach, the ones where the market
did the opposite of what the headline implied, were filed as ordinary.

This module is the single place all of that is decided. It is pure: no I/O, no
Chroma, no network, so it can be tested directly.

    score = relevance * importance * surprise_boost

`relevance` multiplies rather than adds, so it acts as a gate — an enormous but
unrelated event cannot climb the list. `importance` is a weighted sum, so one
missing factor (an outcome that could not be measured, say) degrades the score
instead of zeroing it.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from config import settings
from services.rag_bellwethers import is_bellwether, normalize_symbol, same_bloc

# Returned for any factor whose input is unknown. Deliberately mid-range: an
# unmeasurable outcome should neither promote an item nor bury it.
NEUTRAL = 0.5

# Source labels. They select a recency half-life and control which metadata keys
# are meaningful, so they are named once here rather than spelled at call sites.
SOURCE_EVENT = "event"
SOURCE_NEWS = "news"
SOURCE_PRICE = "price"


def floor_for(source: str) -> float:
    """
    The relevance floor for one collection.

    Per-collection because a single value stopped being able to serve them all.
    Measured against qwen3-embedding:0.6b, keeping every on-topic price-history
    hit requires a floor at or below 0.394, while excluding off-topic news
    requires one at or above 0.501 — there is no number that does both. The
    per-collection figures and how they were derived are in `config`.
    """
    if source == SOURCE_EVENT:
        return settings.RAG_MIN_RELEVANCE_EVENTS
    if source == SOURCE_PRICE:
        return settings.RAG_MIN_RELEVANCE_PRICES
    if source == SOURCE_NEWS:
        return settings.RAG_MIN_RELEVANCE_NEWS
    return settings.RAG_MIN_RELEVANCE


BULLISH = "bullish"
BEARISH = "bearish"
NEUTRAL_DIRECTION = "neutral"

_OPPOSITES = {BULLISH: BEARISH, BEARISH: BULLISH}

# Prior importance by kind of event. A rule change or a solvency failure resets
# what the market believes; a scheduled protocol upgrade rarely does, and a
# round-number price milestone is a headline about the past.
#
# Note what is absent: "bullish" / "bearish" / "neutral". Two services store a
# news item's sentiment in the same field events use for their type, so those
# strings do reach this table — and must fall through to the default rather than
# collide with a real class. There is a test for exactly that.
EVENT_CLASS_PRIORS: Dict[str, float] = {
    "regulatory": 1.00,
    "halving": 0.95,
    "macro": 0.90,
    "exchange": 0.90,
    "earnings": 0.85,
    "tariff": 0.85,
    "treasury": 0.75,
    "upgrade": 0.70,
    "adoption": 0.60,
    "price_milestone": 0.45,
}
DEFAULT_CLASS_PRIOR = 0.60

# How much of its weight a precedent keeps when it is not about the asset asked
# about. The spillover row is the point of the bellwether universe: what
# happened to XRP when it was sued is evidence about the next altcoin sued, and
# scoring it as a plain symbol mismatch would throw that away.
SYMBOL_EXACT = 1.00
SYMBOL_SPILLOVER = 0.70
SYMBOL_SAME_BLOC = 0.65
SYMBOL_UNATTRIBUTED = 0.60
SYMBOL_MISMATCH = 0.30

# Moves smaller than this are not a direction, they are noise.
FLAT_PCT = 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# TYPES
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class HistoricalItem:
    """
    One retrieved past item, normalised across the three collections.

    The collections disagree about field names and about which fields exist at
    all — events carry a measured outcome, news carries a sentiment label,
    prices carry neither. `item_from_metadata` does the flattening so scoring
    sees one shape.
    """

    doc_id: str
    source: str
    relevance: float
    date: Optional[datetime] = None
    symbol: Optional[str] = None
    event_type: Optional[str] = None
    magnitude_pct: Optional[float] = None
    apparent_sentiment: Optional[str] = None
    durable_direction: Optional[str] = None
    inverted: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoredItem:
    """A `HistoricalItem` with its score and the parts that produced it."""

    item: HistoricalItem
    relevance: float
    importance: float
    surprise: float
    score: float
    # Recorded as a fact rather than inferred from `surprise`. Reading it back
    # out of the multiplier breaks the moment the boost is configured to 1.0 to
    # disable the promotion: every item would then satisfy `surprise >= boost`
    # and be reported as contradicting its own headline.
    surprised: bool = False
    # Cross-encoder relevance in [0, 1], or None when re-ranking is unavailable.
    #
    # `relevance` above is bi-encoder cosine: the query and the document were
    # embedded separately and never compared directly. This is the score from a
    # model that read both together, which is a different and better-informed
    # judgement of the same thing — but only of *relevance*. Whether a precedent
    # is instructive is what `importance` and `surprise` encode, and no general
    # reranker knows that, so it multiplies the composite rather than replacing it.
    rerank: Optional[float] = None

    @property
    def inverted(self) -> bool:
        """The immediate reaction and the durable outcome disagreed."""
        return self.item.inverted

    @property
    def final_score(self) -> float:
        """The ordering score, including the cross-encoder's opinion if there is one."""
        return self.score if self.rerank is None else self.score * self.rerank


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORS
# ═══════════════════════════════════════════════════════════════════════════════


def relevance_from_distance(distance: Optional[float]) -> float:
    """
    Cosine similarity from a Chroma distance, clamped to [0, 1].

    Valid because the embedding model normalises its output: for unit vectors
    the squared L2 distance is `2 - 2*cos`. Negative cosines (genuinely
    unrelated text) clamp to zero, which is the honest answer — they carry no
    information about how unrelated.
    """
    if distance is None:
        return 0.0
    cosine = 1.0 - (float(distance) / 2.0)
    return max(0.0, min(1.0, cosine))


def recency_weight(
    date: Optional[datetime],
    *,
    half_life_days: float,
    now: Optional[datetime] = None,
) -> float:
    """
    Exponential decay on age, floored so old structural precedent survives.

    Without the floor the 2020 halving would decay to nothing, which is wrong:
    it is old *and* it is still the best precedent for a halving question. A
    future-dated item counts as maximally recent.
    """
    if date is None:
        return NEUTRAL
    if half_life_days <= 0:
        return 1.0

    reference = now or datetime.now()
    age_days = (reference - date).total_seconds() / 86400.0
    if age_days <= 0:
        return 1.0

    decayed = 0.5 ** (age_days / half_life_days)
    return max(settings.RAG_RECENCY_FLOOR, decayed)


def magnitude_weight(price_change_pct: Optional[float]) -> float:
    """
    Saturating weight on how far the price actually moved.

    Saturating rather than linear so a once-in-a-decade collapse does not
    outrank everything else by size alone. A move of exactly zero scores zero;
    an *unmeasured* move scores NEUTRAL, because "we could not fetch the
    candles" is not the same claim as "nothing happened".
    """
    if price_change_pct is None:
        return NEUTRAL

    scale = settings.RAG_MAGNITUDE_SCALE_PCT
    if scale <= 0:
        return NEUTRAL
    return 1.0 - math.exp(-abs(float(price_change_pct)) / scale)


def class_weight(event_type: Optional[str]) -> float:
    """Prior importance for a kind of event; unknown kinds get the default."""
    if not event_type:
        return DEFAULT_CLASS_PRIOR
    return EVENT_CLASS_PRIORS.get(str(event_type).strip().lower(), DEFAULT_CLASS_PRIOR)


def symbol_weight(item_symbol: Optional[str], query_symbol: Optional[str]) -> float:
    """
    How much this precedent applies to the asset being asked about.

    A soft weight rather than a hard filter. The previous code filtered on an
    exact symbol match for three hardcoded tickers and let everything else
    through unfiltered — which both dropped useful spillover and admitted
    unrelated assets, depending on which branch you landed in.
    """
    query = normalize_symbol(query_symbol)
    if not query:
        # Nothing to be relevant to; every precedent is equally admissible.
        return SYMBOL_EXACT

    item = normalize_symbol(item_symbol)
    if not item:
        return SYMBOL_UNATTRIBUTED
    if item == query:
        return SYMBOL_EXACT
    if same_bloc(item, query):
        return SYMBOL_SAME_BLOC
    if is_bellwether(item) and not is_bellwether(query):
        return SYMBOL_SPILLOVER
    return SYMBOL_MISMATCH


def direction_from_pct(
    price_change_pct: Optional[float], *, flat_pct: float = FLAT_PCT
) -> Optional[str]:
    """Bullish / bearish / neutral for a percentage move, or None when unknown."""
    if price_change_pct is None:
        return None
    if price_change_pct > flat_pct:
        return BULLISH
    if price_change_pct < -flat_pct:
        return BEARISH
    return NEUTRAL_DIRECTION


def is_surprising(apparent_sentiment: Optional[str], durable_direction: Optional[str]) -> bool:
    """
    Whether the headline's direction and the measured outcome are opposites.

    A direct comparison of the two directions, deliberately not a reading of
    `surprise_boost`'s output: the boost is configurable, and at 1.0 — a
    reasonable way to turn the promotion off — every item would compare equal to
    it and be reported as contradicted.

    "Neutral" is not the opposite of anything. An event that went nowhere did
    not contradict its headline, it merely failed to confirm it.
    """
    apparent = (apparent_sentiment or "").strip().lower()
    durable = (durable_direction or "").strip().lower()
    return bool(apparent and durable and _OPPOSITES.get(apparent) == durable)


def horizons_from_metadata(metadata: Mapping[str, Any]) -> Dict[int, float]:
    """
    The `price_change_<N>d` entries of a metadata row, keyed by day count.

    One parser rather than the same comprehension repeated at every call site.
    A key that looks like a horizon but does not carry a number is skipped
    instead of raising — metadata comes from a store that outlives any one
    version of this code.
    """
    horizons: Dict[int, float] = {}
    for key, value in (metadata or {}).items():
        if not (key.startswith("price_change_") and key.endswith("d")):
            continue
        number = _as_float(value)
        if number is None:
            continue
        try:
            days = int(key[len("price_change_") : -1])
        except ValueError:
            continue
        horizons[days] = number
    return horizons


def longest_horizon(metadata: Mapping[str, Any]) -> Optional[float]:
    """
    The move at the furthest horizon measured — the settled outcome.

    Matches how `rag_outcomes` derives `durable_direction`, so a reported
    average and a reported direction are answering the same question.
    """
    horizons = horizons_from_metadata(metadata)
    return horizons[max(horizons)] if horizons else None


def surprise_boost(
    apparent_sentiment: Optional[str],
    durable_direction: Optional[str],
    inverted: bool = False,
) -> float:
    """
    Reward precedents that contradict their own headline.

    The SEC's suit against Ripple read unambiguously bearish and XRP lost ~73%
    within weeks — then traded far higher while the case was still live. An
    event like that is the only thing that stops a model concluding "lawsuit,
    therefore down"; burying it would defeat the purpose of retrieving history
    at all. So the contradiction is a promotion, not a penalty.

    The smaller boost covers the weaker version: the immediate reaction and the
    durable outcome disagreed, even though the headline's tone was never
    contradicted.
    """
    if is_surprising(apparent_sentiment, durable_direction):
        return settings.RAG_SURPRISE_BOOST
    if inverted:
        return settings.RAG_INVERSION_BOOST
    return 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# SCORING
# ═══════════════════════════════════════════════════════════════════════════════


def half_life_for(source: str) -> float:
    """Recency half-life for a collection, in days."""
    if source == SOURCE_NEWS:
        return settings.RAG_RECENCY_HALF_LIFE_NEWS_DAYS
    if source == SOURCE_PRICE:
        return settings.RAG_RECENCY_HALF_LIFE_PRICES_DAYS
    return settings.RAG_RECENCY_HALF_LIFE_EVENTS_DAYS


def score_item(
    item: HistoricalItem,
    *,
    query_symbol: Optional[str] = None,
    now: Optional[datetime] = None,
) -> ScoredItem:
    """Combine the factors into a single ranking score."""
    recency = recency_weight(item.date, half_life_days=half_life_for(item.source), now=now)
    magnitude = magnitude_weight(item.magnitude_pct)
    klass = class_weight(item.event_type)
    symbol = symbol_weight(item.symbol, query_symbol)

    importance = (
        settings.RAG_WEIGHT_RECENCY * recency
        + settings.RAG_WEIGHT_MAGNITUDE * magnitude
        + settings.RAG_WEIGHT_CLASS * klass
        + settings.RAG_WEIGHT_SYMBOL * symbol
    )
    surprise = surprise_boost(item.apparent_sentiment, item.durable_direction, item.inverted)

    return ScoredItem(
        item=item,
        relevance=item.relevance,
        importance=importance,
        surprise=surprise,
        score=item.relevance * importance * surprise,
        surprised=is_surprising(item.apparent_sentiment, item.durable_direction),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CHROMA ADAPTER
# ═══════════════════════════════════════════════════════════════════════════════


def iter_chroma_hits(results: Any) -> Iterator[Tuple[str, Dict[str, Any], float]]:
    """
    Yield `(doc_id, metadata, distance)` from a Chroma query response.

    Chroma returns parallel lists nested one level deep per query embedding, and
    unpacking that by hand was duplicated at twelve call sites — each with its
    own guard against the empty case, and not all of them correct.
    """
    if not results:
        return

    ids = (results.get("ids") or [[]])[0]
    if not ids:
        return

    metadatas = (results.get("metadatas") or [[]])[0] or []
    distances = (results.get("distances") or [[]])[0] or []

    for index, doc_id in enumerate(ids):
        metadata = metadatas[index] if index < len(metadatas) else {}
        distance = distances[index] if index < len(distances) else None
        yield doc_id, dict(metadata or {}), distance


def parse_date(value: Any) -> Optional[datetime]:
    """
    A naive datetime from the several date spellings the collections use.

    Events and price rows store "YYYY-MM-DD"; news stores a full ISO timestamp
    under a different key. Timezone-aware values are flattened to naive because
    everything else in this path — including the stored dates themselves — is
    naive, and mixing the two raises on subtraction.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value

    text = str(value).strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            return None

    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _event_magnitude(metadata: Mapping[str, Any]) -> Optional[float]:
    """
    The largest absolute move an event produced, across every measured horizon.

    Taking the largest rather than one fixed horizon is what keeps a reversal
    legible: XRP's endpoint at 90 days understates a move that ran -73% and then
    far higher, and the drawdown/run-up pair is exactly where that shows up.
    """
    candidates: List[float] = [abs(v) for v in horizons_from_metadata(metadata).values()]
    for key in ("max_drawdown_pct", "max_runup_pct"):
        value = _as_float(metadata.get(key))
        if value is not None:
            candidates.append(abs(value))

    return max(candidates) if candidates else None


def item_from_metadata(
    doc_id: str,
    metadata: Mapping[str, Any],
    distance: Optional[float],
    source: str,
) -> HistoricalItem:
    """
    Flatten one Chroma row into the shape scoring expects.

    Note what is *not* read for a news row: its `sentiment`. That field records
    what the headline appeared to say, which is a claim about tone and not about
    outcome — treating it as an event class is the confusion this whole change
    exists to remove. It is carried through as `apparent_sentiment`, where it
    can be compared against a measured direction instead of standing in for one.
    """
    metadata = metadata or {}

    if source == SOURCE_EVENT:
        date = parse_date(metadata.get("date"))
        event_type = metadata.get("event_type")
        magnitude = _event_magnitude(metadata)
    elif source == SOURCE_NEWS:
        date = parse_date(metadata.get("stored_at") or metadata.get("date"))
        event_type = None
        magnitude = metadata.get("price_change")
        if magnitude is None:
            magnitude = metadata.get("price_change_percent")
    else:
        date = parse_date(metadata.get("date"))
        event_type = None
        magnitude = metadata.get("change_pct")

    apparent = metadata.get("apparent_sentiment") or metadata.get("sentiment")
    durable = metadata.get("durable_direction")
    if durable is None and source != SOURCE_EVENT:
        durable = direction_from_pct(_as_float(magnitude))

    return HistoricalItem(
        doc_id=doc_id,
        source=source,
        relevance=relevance_from_distance(distance),
        date=date,
        symbol=metadata.get("symbol"),
        event_type=event_type,
        magnitude_pct=_as_float(magnitude),
        apparent_sentiment=apparent or None,
        durable_direction=durable or None,
        inverted=bool(metadata.get("inverted", False)),
        metadata=metadata,
    )


def _as_float(value: Any) -> Optional[float]:
    """A float, or None for anything that is not a usable number."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def rank_candidates(
    results: Any,
    *,
    source: str,
    query_symbol: Optional[str] = None,
    k: int = 5,
    min_relevance: Optional[float] = None,
    now: Optional[datetime] = None,
) -> List[ScoredItem]:
    """
    Score a Chroma response, drop the irrelevant, and return the best `k`.

    Callers should over-fetch before calling this — re-ranking can only reorder
    what was retrieved, so asking Chroma for exactly `k` rows means the weights
    never see the candidate that should have won.
    """
    floor = floor_for(source) if min_relevance is None else min_relevance

    scored: List[ScoredItem] = []
    for doc_id, metadata, distance in iter_chroma_hits(results):
        item = item_from_metadata(doc_id, metadata, distance, source)
        if item.relevance < floor:
            continue
        scored.append(score_item(item, query_symbol=query_symbol, now=now))

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:k] if k and k > 0 else scored


def candidate_pool_size(k: int, collection_count: int) -> int:
    """How many rows to ask Chroma for so re-ranking has something to work with."""
    if collection_count <= 0:
        return 0
    return max(1, min(k * settings.RAG_CANDIDATE_MULTIPLIER, collection_count))


# ═══════════════════════════════════════════════════════════════════════════════
# WEIGHTED AGGREGATION
# ═══════════════════════════════════════════════════════════════════════════════


def _clean_pairs(values: Sequence[Any], weights: Sequence[Any]) -> List[Tuple[float, float]]:
    """Value/weight pairs with the unusable ones removed."""
    pairs: List[Tuple[float, float]] = []
    for value, weight in zip(values, weights):
        number = _as_float(value)
        w = _as_float(weight)
        if number is None or w is None or w <= 0:
            continue
        pairs.append((number, w))
    return pairs


def weighted_mean(values: Sequence[Any], weights: Sequence[Any]) -> Optional[float]:
    """
    Weighted average, or None when nothing usable was supplied.

    Replaces the plain `sum(x) / len(x)` the aggregations used, which let a
    barely-related decade-old item count as much as a strong recent one.
    """
    pairs = _clean_pairs(values, weights)
    if not pairs:
        return None
    total_weight = sum(w for _, w in pairs)
    if total_weight <= 0:
        return None
    return sum(v * w for v, w in pairs) / total_weight


def weighted_vote(labels: Sequence[Any], weights: Sequence[Any]) -> Optional[Tuple[str, float]]:
    """
    The heaviest label and its share of the total weight.

    Replaces `Counter(...).most_common(1)`, where three weak matches outvoted
    one strong one.
    """
    tallies: Dict[str, float] = {}
    total = 0.0
    for label, weight in zip(labels, weights):
        if not label:
            continue
        w = _as_float(weight)
        if w is None or w <= 0:
            continue
        key = str(label).strip().lower()
        if not key:
            continue
        tallies[key] = tallies.get(key, 0.0) + w
        total += w

    if not tallies or total <= 0:
        return None

    winner = max(tallies.items(), key=lambda pair: pair[1])
    return winner[0], winner[1] / total


def weighted_percentile_range(
    values: Sequence[Any],
    weights: Sequence[Any],
    low: float = 0.1,
    high: float = 0.9,
) -> Optional[Tuple[float, float]]:
    """
    Weighted percentile band.

    Used instead of raw min/max: over five samples the extremes are whichever
    two outliers happened to be retrieved, and reporting them as the range of
    plausible outcomes overstates what the history supports.
    """
    pairs = _clean_pairs(values, weights)
    if not pairs:
        return None

    pairs.sort(key=lambda pair: pair[0])
    total = sum(w for _, w in pairs)
    if total <= 0:
        return None

    def pick(fraction: float) -> float:
        target = total * max(0.0, min(1.0, fraction))
        seen = 0.0
        for value, weight in pairs:
            seen += weight
            if seen >= target:
                return value
        return pairs[-1][0]

    return pick(low), pick(high)
