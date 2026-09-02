"""
The equity heatmap: where the money in an index sits, and which way it moved.

Area is market capitalisation and colour is whichever metric the reader picks —
the same division the crypto board makes, and for the same reason: size is the
one quantity that should not change when the reader changes the question.

Two things about this module are deliberate.

**It owns no upstream.** It takes an equity board and a futures board that some
caller already fetched, and returns a shaped board. That is the shape
`positioning_service` has, and it is what keeps the VİOP scrape — the single
most fragile dependency on this realm — out of the import chain of the six
modules that build on `equity_service`. It also means nothing here belongs in
`services/health_registry.py`: no host is contacted.

**Futures are an overlay, never the spine.** VİOP lists single-stock contracts
on roughly forty names, which is under half the XU100. A board sized or scoped
by open interest would be a different, much smaller board wearing this one's
name. Open interest rides along as a per-tile reading that is frequently absent,
and absent is rendered as absent.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from services.bist.equity_service import screen_equities, sector_performance
from services.bist.tradingview_client import EquityRow
from services.bist.viop_service import UnderlyingRoll, ViopContract, roll_by_underlying

# What a listing with no sector from the scanner is grouped under.
#
# Named rather than dropped: `sector_performance` skips an unsectored row
# entirely, which is right for a sector ranking and wrong here — on a heatmap a
# real company would simply vanish, and the board would quietly stop summing to
# the index.
UNCLASSIFIED_SECTOR = "Sınıflandırılmamış"


@dataclass(frozen=True)
class HeatmapTile:
    """One company, as the board draws it."""

    ticker: str
    symbol: str
    name: str
    sector: str
    price: Optional[float]
    change_pct: Optional[float]
    """Daily move, as a fraction."""
    traded_value: Optional[float]
    """Turnover in lira. Raw, not scored — the tile prints a real figure."""
    volume: Optional[float]
    market_cap: Optional[float]
    """The tile's area."""
    indices: tuple[str, ...]
    has_futures: bool
    """Whether VİOP lists any contract on this underlying."""
    contracts: int
    """How many expiries. Zero when there are no futures at all."""
    open_interest: Optional[float]
    open_interest_change: Optional[float]
    open_interest_change_pct: Optional[float]
    """Change against yesterday's position, as a fraction. See `open_interest_change_pct`."""


@dataclass(frozen=True)
class HeatmapSectorGroup:
    """One sector's share of the scoped index and how it moved."""

    sector: str
    count: int
    market_cap: float
    weight: float
    """Share of the scoped index's capitalisation, as a fraction."""
    change_pct: Optional[float]
    advancers: int
    decliners: int


@dataclass(frozen=True)
class HeatmapBoard:
    index: str
    tiles: list[HeatmapTile]
    sectors: list[HeatmapSectorGroup]
    total: int
    """Listings in the scoped index, before `limit`."""
    total_market_cap: float
    futures_covered: int
    """How many drawn tiles carry a futures reading."""
    has_futures_data: bool
    """False when the futures board could not be read at all."""


def open_interest_change_pct(
    open_interest: Optional[float],
    change: Optional[float],
) -> Optional[float]:
    """
    Yesterday's position against today's, as a fraction.

    The relative figure is what gets coloured, and the raw one is what the tile
    prints. Colouring the raw change would make the ramp a second encoding of
    size — a heavily traded bank's daily open-interest swing is five digits and
    a thin name's is three, so every tile but a handful would land in the
    neutral bucket while area already said which names are large.

    None when yesterday's position cannot be recovered or was not positive:
    a position that grew from nothing has no percentage, and inventing one
    (or dividing by zero) would put the loudest colour on the smallest fact.
    """
    if open_interest is None or change is None:
        return None
    previous = open_interest - change
    if previous <= 0:
        return None
    return change / previous


def _tile(row: EquityRow, roll: Optional[UnderlyingRoll]) -> HeatmapTile:
    open_interest = roll.open_interest if roll else None
    change = roll.open_interest_change if roll else None
    return HeatmapTile(
        ticker=row.ticker,
        symbol=row.symbol,
        name=row.name,
        sector=row.sector,
        price=row.price,
        change_pct=row.change_pct,
        traded_value=row.traded_value,
        volume=row.volume,
        market_cap=row.market_cap,
        indices=row.indices,
        has_futures=roll is not None,
        contracts=roll.contracts if roll else 0,
        open_interest=open_interest,
        open_interest_change=change,
        open_interest_change_pct=open_interest_change_pct(open_interest, change),
    )


def build_heatmap(
    equities: list[EquityRow],
    contracts: Optional[list[ViopContract]] = None,
    *,
    index: Optional[str] = None,
    limit: Optional[int] = None,
) -> HeatmapBoard:
    """
    The board for one index, largest company first.

    `limit` truncates the tiles and nothing else. The sector statistics are
    computed over the whole scoped index on purpose: a weight that shifted when
    the reader asked for fewer tiles would be a different number wearing the
    same label, and the difference is invisible on screen.
    """
    scoped = screen_equities(
        equities,
        index=index,
        sort_by="market_cap",
        descending=True,
    )
    # Frozen rows, so a copy rather than an assignment. Done before the sector
    # pass so an unsectored listing lands in a named group instead of being
    # dropped out of the totals it is genuinely part of.
    scoped = [row if row.sector else replace(row, sector=UNCLASSIFIED_SECTOR) for row in scoped]

    stats = sector_performance(scoped)
    sectors = [
        HeatmapSectorGroup(
            sector=stat.sector,
            count=stat.count,
            market_cap=stat.market_cap,
            weight=stat.weight,
            change_pct=stat.change_pct,
            advancers=stat.advancers,
            decliners=stat.decliners,
        )
        for stat in stats
    ]

    rolls = roll_by_underlying(contracts)
    drawn = scoped[:limit] if limit is not None else scoped
    tiles = [_tile(row, rolls.get(row.ticker)) for row in drawn]

    return HeatmapBoard(
        index=(index or "").strip().upper(),
        tiles=tiles,
        sectors=sectors,
        total=len(scoped),
        total_market_cap=sum(
            row.market_cap for row in scoped if row.market_cap and row.market_cap > 0
        ),
        futures_covered=sum(1 for tile in tiles if tile.has_futures),
        # An empty futures board and an unreadable one are the same absence for
        # every tile, but not for the reader: the page says which one it is.
        has_futures_data=contracts is not None,
    )
