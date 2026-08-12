"""
Ownership — the shapes the "who holds what" board and its detail view are served in.

One Position schema covers all five categories. An equity line from a 13F, a BTC
balance read off chain, a cash figure copied out of a 10-Q and a central bank's
gold tonnage differ in `asset_class` and `quantity_unit`, not in shape — so the
allocation bar, the holdings table and the delta maths are written once instead
of five times.

Two distinctions are built into the schema because getting them wrong is how a
board like this starts publishing numbers nobody reported:

`value_basis` — a USD figure is either *reported* (the 13F value column, as
filed) or *marked* (a quantity we multiplied by a price we fetched). Re-pricing
a quarter-old share count against today's quote produces a number no filing
contains and no reader can check. The two are never mixed silently.

`SourceRef` per position — provenance belongs to the line, not to the entity. A
Berkshire card shows 13F equities beside a cash figure typed in by hand out of a
filing; those two cannot wear the same badge.

The house rule from `macro_board_service` holds here and matters more: a figure
nobody published is `None` and renders as "Unknown". Never 0.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["institution", "treasury", "politician", "onchain", "central_bank"]

AssetClass = Literal[
    "equity",
    "crypto",
    "cash",
    "gold",
    "fx_reserve",
    "bond",
    "fund",
    "other",
]

SourceKind = Literal[
    "sec_13f",
    "sec_form4",
    "coingecko_treasury",
    "onchain",
    "central_bank",
    "manual",
]

# Where a USD figure came from.
#   reported — the source published this exact number
#   marked   — we multiplied a reported quantity by a price we fetched
#   unknown  — the quantity is known, the USD value is not, and we will not
#              invent one
ValueBasis = Literal["reported", "marked", "unknown"]

MoveKind = Literal[
    "new",  # 13F: position appears for the first time
    "add",
    "trim",
    "exit",
    "buy",  # Form 4 / insider, transaction codes P and S only
    "sell",
    "transfer_in",  # on-chain; deliberately not called a buy or a sell
    "transfer_out",
    "increase",  # corporate treasury / central bank reserves
    "decrease",
]


class SourceRef(BaseModel):
    """Where one number came from, and when it was true."""

    kind: SourceKind
    # Short human label for the badge: "13F Q3 2025", "on-chain", "IMF IRFCL",
    # "10-K FY2024". Rendered verbatim — the UI never composes this itself, so
    # a period can never be relabelled into something the filing did not say.
    label: str
    # The filing or API page a reader can open to check the number. Required for
    # manual entries: a hand-typed figure without a source is indistinguishable
    # from an invented one.
    url: str | None = None
    # The date the figure describes — quarter end, block time, fiscal year end.
    as_of: date | None = None
    # When we fetched it. Deliberately separate from `as_of`: a Q3 filing pulled
    # today is fresh data about a stale quarter, and the UI has to say so.
    retrieved_at: datetime | None = None
    # Set for hand-maintained rows so the UI can separate them visually.
    manual: bool = False


class Position(BaseModel):
    """One line of one entity's reported holdings."""

    # Stable within an entity, because the snapshot diff is keyed on it. Equity:
    # CUSIP or ticker. Crypto: coin id. Cash: "cash:USD". Gold: "gold".
    key: str
    label: str
    symbol: str | None = None
    asset_class: AssetClass

    quantity: float | None = None
    # "shares", "BTC", "tonnes", "USD" — printed beside the quantity.
    quantity_unit: str | None = None

    value_usd: float | None = None
    value_basis: ValueBasis = "unknown"
    # Only meaningful when value_basis == "marked".
    price_usd: float | None = None
    priced_at: datetime | None = None

    # Share of the entity's total reported value. None when the total is
    # unknown — a weight against an unknown denominator is a fabrication.
    weight_pct: float | None = None

    # Change against the previous observation. None on the first ever capture:
    # "unchanged" and "no baseline yet" are different claims and must not
    # render the same way.
    delta_quantity: float | None = None
    delta_value_usd: float | None = None
    delta_pct: float | None = None

    source: SourceRef
    note: str | None = None


class AllocationSlice(BaseModel):
    """
    One segment of the allocation bar — a single holding, not a class.

    Per holding rather than per asset class because a class-wide bar answers a
    question nobody asked of a card: an entity holding 50% ETH, 30% BTC and 20%
    cash draws two segments, and the two coins share one, which is the same
    picture as holding only bitcoin.

    `key`, `label` and `symbol` carry defaults so a board written by an older
    build still validates on read. A cache from yesterday must not 503 the page;
    it renders with class labels until the daily rebuild refills them.
    """

    # The position key, or the pooled-tail sentinel below.
    key: str = ""
    label: str = ""
    symbol: str | None = None
    asset_class: AssetClass
    value_usd: float
    pct: float


# The tail of small holdings, pooled into one segment. Named here because the
# frontend colours this segment differently and must not guess at the string.
POOLED_SLICE_KEY = "__other__"


class Move(BaseModel):
    """A change we can point at a source for."""

    # Deterministic hash of (entity, key, kind, occurred_at, delta). Stable ids
    # are what let the daily job re-process an unchanged quarterly filing for
    # ninety days without publishing the same move ninety times.
    id: str
    entity_id: str
    entity_name: str
    category: Category

    kind: MoveKind
    asset_label: str
    asset_symbol: str | None = None
    asset_class: AssetClass

    quantity_delta: float | None = None
    value_usd_delta: float | None = None
    pct_delta: float | None = None

    # When it happened, or the period it is attributed to.
    occurred_at: date
    # When it became public. For a 13F these are ~45 days apart, and the strip
    # sorts on this one because that is when it was news.
    reported_at: date | None = None

    # Built server-side so the grid strip and the detail list cannot word the
    # same event differently.
    headline: str
    source: SourceRef


class SourceHealth(BaseModel):
    """Per-provider outcome of the last refresh, surfaced under the board."""

    kind: SourceKind
    ok: bool
    entities_covered: int = 0
    as_of: datetime | None = None
    message: str | None = None


class EntitySummary(BaseModel):
    """One grid card."""

    id: str
    name: str
    subtitle: str | None = None
    category: Category
    country: str | None = None
    # The company's own mark, when one identifies it. Filled on the way out of
    # `board` rather than stored with the numbers: it is registry metadata, not
    # something a refresh observed, and pinning it into the snapshot would leave
    # a corrected logo waiting a day behind the next rebuild. None means the
    # card draws a monogram — or, for a politician or a central bank, its flag.
    logo_url: str | None = None

    total_value_usd: float | None = None
    positions_count: int = 0
    allocation: list[AllocationSlice] = Field(default_factory=list)
    # The largest few holdings, so a card says *what* is held and not just how
    # much. The full list is a separate request — a grid of twenty entities
    # carrying every position would move megabytes to render three lines each.
    top_positions: list["Position"] = Field(default_factory=list)

    # The badge on the card: the dominant source's label.
    source_label: str | None = None
    last_move: Move | None = None

    as_of: date | None = None
    # True when the last refresh could not reach this entity's sources and the
    # figures are replayed from the previous run. The card stays on the grid
    # either way — an entity that vanishes during an outage reads as "sold
    # everything", which is a claim we would be making on our own.
    stale: bool = False
    # Human-readable reasons, shown in the detail view rather than on the card.
    issues: list[str] = Field(default_factory=list)
    # False when no source has ever answered for this entity.
    has_data: bool = True
    # What the numbers actually cover, e.g. "US-listed long equity only (13F)".
    # Printed under the allocation bar so a bar that fills to 100% is never read
    # as a complete picture of net worth.
    coverage_note: str | None = None


class EntityDetail(BaseModel):
    """The right-hand pane: one entity, fully expanded."""

    entity: EntitySummary
    positions: list[Position] = Field(default_factory=list)
    moves: list[Move] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    # True when this entity has only ever been observed once: the positions are
    # real, the deltas are not computable yet, and the UI says "baseline"
    # instead of drawing a row of zeroes.
    moves_baseline: bool = False


class OwnershipBoard(BaseModel):
    """The whole grid view in one payload."""

    entities: list[EntitySummary] = Field(default_factory=list)
    latest_moves: list[Move] = Field(default_factory=list)
    category_counts: dict[str, int] = Field(default_factory=dict)
    sources: list[SourceHealth] = Field(default_factory=list)

    as_of: datetime
    last_refresh_at: datetime | None = None
    next_refresh_at: datetime | None = None
    stale: bool = False
