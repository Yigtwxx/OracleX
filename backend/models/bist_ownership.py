"""
Response models for the BIST ownership board.

A parallel set to `models/ownership.py` rather than a reuse of it, and the
split is about currency and evidence, not taste. The global board is USD and
its positions are quarterly portfolio filings; this one is lira and its
positions are *stakes* — a share of one company's capital, disclosed only
once it crosses 5%. Every share here is a **fraction**, as on every other
`/api/bist/*` payload: `0.4912`, never `49.12`.

`value_try` is a marked figure (`stake × market cap`) for a shareholder and a
reported one for a fund, and `value_basis` says which, because the two are not
the same kind of number and a column that mixed them would be wrong for half
its rows.

The house rules are the same as the global board's and are worth restating:
a figure nobody published is `None` and renders as unknown, never as 0; every
position carries its own source; and the board is never handed to a page as an
empty list, because "no data" and "holds nothing" must not look alike.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

HolderCategory = Literal["holding", "state", "foreign", "fund", "other"]

SourceKind = Literal["isyatirim_shareholders", "kap_fund_report"]

ValueBasis = Literal["marked", "reported", "unknown"]

# How a stake changed between two daily snapshots of the shareholder table.
StakeMoveKind = Literal["new", "exit", "add", "trim"]

# Key of the pooled tail slice in an allocation, so the UI can style it apart
# from real holdings without matching on a label.
POOLED_SLICE_KEY = "__other__"

# The KAP filing classes that describe ownership changing hands, in the order
# they matter. The tape is classified by `kap_materiality`; this is the subset
# that becomes a "move" on this board.
OWNERSHIP_EVENTS: tuple[str, ...] = (
    "icsel_islem",
    "satin_alma",
    "pay_alim_teklifi",
    "halka_arz",
    "sermaye",
    "geri_alim",
)


class SourceRef(BaseModel):
    kind: SourceKind
    label: str
    url: str | None = None
    as_of: str | None = None
    """What date the figure describes. For a fund, the report month."""
    retrieved_at: str | None = None
    """When it was fetched. Kept apart from `as_of` on purpose."""


class Position(BaseModel):
    ticker: str
    name: str
    stake_pct: float | None = None
    """Share of the company's capital, as a fraction. `None` when unknown."""
    value_try: float | None = None
    value_basis: ValueBasis = "unknown"
    weight_pct: float | None = None
    """Share of the entity's *known* lira value, as a fraction. `None` when nothing is valued."""
    source: SourceRef
    note: str | None = None
    since: str | None = None
    """Earliest daily snapshot the holder appears in for this company. With
    `at_baseline` true it means "since at least" — the real entry predates
    the first snapshot and is unknown."""
    at_baseline: bool = True
    previous_stake_pct: float | None = None
    """The stake on the previous snapshot, as a fraction. None with one snapshot."""
    delta_pct: float | None = None
    """`stake_pct - previous_stake_pct`, in fraction points. None when unknown."""


class StakeMove(BaseModel):
    """A holder entering, leaving or resizing, as read off two snapshots."""

    id: str
    ticker: str
    company: str
    holder: str
    entity_id: str | None = None
    kind: StakeMoveKind
    stake_before: float | None = None
    stake_after: float | None = None
    delta_pct: float | None = None
    observed_at: str
    """The snapshot day the change was first seen — not the filing date."""


class AllocationSlice(BaseModel):
    key: str
    label: str
    ticker: str | None = None
    value_try: float
    pct: float


class Move(BaseModel):
    id: str
    ticker: str
    company: str
    event: str
    event_label: str
    headline: str
    published_at: str | None = None
    url: str
    score: int | None = None
    band: str


class SourceHealth(BaseModel):
    kind: SourceKind
    ok: bool
    entities_covered: int = 0
    tickers_covered: int = 0
    as_of: str | None = None
    message: str | None = None


class EntitySummary(BaseModel):
    id: str
    name: str
    subtitle: str | None = None
    category: HolderCategory
    total_value_try: float | None = None
    positions_count: int = 0
    allocation: list[AllocationSlice] = Field(default_factory=list)
    top_positions: list[Position] = Field(default_factory=list)
    last_move: Move | None = None
    as_of: str | None = None
    stale: bool = False
    issues: list[str] = Field(default_factory=list)
    has_data: bool = False
    coverage_note: str | None = None


class EntityDetail(BaseModel):
    entity: EntitySummary
    positions: list[Position]
    moves: list[Move]
    stake_moves: list[StakeMove] = Field(default_factory=list)
    sources: list[SourceRef]
    tracking_since: str | None = None
    """The oldest snapshot day. Nothing before it is known."""


class Holder(BaseModel):
    """One row of a company's shareholder table, as İş Yatırım prints it."""

    label: str
    stake_pct: float
    value_try: float | None = None
    entity_id: str | None = None
    tracked: bool = False
    """Whether the row matched a registry entity. Untracked rows are still
    listed — the reader is owed every ≥5% holder, not only the ones we name."""
    since: str | None = None
    at_baseline: bool = True
    previous_stake_pct: float | None = None
    delta_pct: float | None = None


class FundHolder(BaseModel):
    entity_id: str
    name: str
    code: str
    weight_in_fund_pct: float | None = None
    """Share of the fund's equity book, as a fraction."""
    value_try: float | None = None
    stake_pct: float | None = None
    as_of: str | None = None
    url: str | None = None


class AssetOwners(BaseModel):
    ticker: str
    name: str
    market_cap: float | None = None
    free_float_pct: float | None = None
    foreign_ratio_pct: float | None = None
    """Foreign investors' share of the free float, as a fraction, via İş Yatırım."""
    holders: list[Holder] = Field(default_factory=list)
    funds: list[FundHolder] = Field(default_factory=list)
    moves: list[Move] = Field(default_factory=list)
    stake_moves: list[StakeMove] = Field(default_factory=list)
    tracking_since: str | None = None
    as_of: str | None = None
    stale: bool = False
    source_url: str | None = None


class OwnershipBoard(BaseModel):
    entities: list[EntitySummary]
    latest_moves: list[Move] = Field(default_factory=list)
    latest_stake_moves: list[StakeMove] = Field(default_factory=list)
    tracking_since: str | None = None
    category_counts: dict[str, int] = Field(default_factory=dict)
    sources: list[SourceHealth] = Field(default_factory=list)
    universe: str = "XU100"
    tickers_covered: int = 0
    tickers_total: int = 0
    as_of: str | None = None
    last_refresh_at: str | None = None
    stale: bool = False
